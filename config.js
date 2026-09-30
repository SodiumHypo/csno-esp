// Runtime config — mirrors offsets.json (single source of truth).
// Research on the Android CS:GO-style port "CSNO" (com.ledi.csno, by 乐迪).
// NOTE: netvars are struct offsets (arch-independent). rva_seeds are THIS build only;
// every script resolves module bases at runtime and validates/falls back to signatures.

const CONFIG = {
  modules: {
    client: 'libkm_client_panorama_client.so',
    engine: 'libkm_engine_client.so',
  },

  // --- struct offsets (this build, from RecvProp*/RecvTable::Construct disasm) ---
  structs: {
    RecvTable: { props: 0x00, nProps: 0x08, name: 0x18, size: 0x28 },
    RecvProp: {
      size: 0x60,
      varName: 0x00,   // char*
      type: 0x08,      // int (DataTable=6, Int=7 in this build's enum)
      flags: 0x0C,
      proxyFn: 0x30,
      dataTableProxyFn: 0x38,
      dataTable: 0x40, // RecvTable* (DataTable props)
      offset: 0x48,    // int — THE netvar offset
    },
  },

  // --- RVA seeds (this km_ build; validate before trust) ---
  rva: {
    client: {
      s_pLocalPlayer: 0x1617F40,          // C_BasePlayer*[slots], local = slot 0
      s_EntityList: 0x16432A0,            // CClientEntityList singleton
      engine_iface: 0x1639C08,            // IEngineClient* engine
      DT_CSPlayer_RecvTable: 0x1F6B160,
      fn_GetClientEntity: 0xA889D8,       // (this=s_EntityList, i)
      fn_GetLocalPlayerIndex: 0xA83EC8,
      fn_ScreenTransform: 0xBC0768,       // bool (Vector const& in, Vector& out)
    },
    engine: {
      g_EngineRenderer: 0xBA2220,         // CRender*
      render_viewMatrixOff: 0xA4,         // VMatrix @ CRender+0xA4 (view<2)
      render_viewStride: 0x220,
    },
  },

  // --- entity list (EMPIRICALLY CONFIRMED in-match 2026-09-30 via vptr scan) ---
  entityList: {
    // CClientEntityList object @ s_EntityList: vptr@+0x00, int@+0x10 (~count).
    // Entry[i] = DIRECT C_BaseEntity* at obj + entryBase + stride*i — NO wrapper,
    // NO vcall (the Phase-1 disasm reading was off by 0x20). Entry layout:
    // +0x00 entity*, +0x08 serial, +0x10/+0x18 intrusive list links.
    // entry[0] = local player; players follow at 1..N (bot match: 10 total).
    entryBase: 0x28,
    stride: 0x20,
    maxScan: 128,
  },

  // --- ESP-critical netvars (validated statically; re-verify vs runtime RecvTable) ---
  netvars: {
    m_iTeamNum: 0x12C,
    m_bSpotted: 0xECD,     // K3 fallback: networked spotted flag (DT_BaseEntity) — remote dormancy signal
    m_vecOrigin: 0x170,
    m_vecViewOffset: 0x140,
    m_vecVelocity: 0x14C,
    m_iHealth: 0x138,
    m_fFlags: 0x13C,
    m_lifeState: 0x297,
    m_nTickBase: 0x3C50,   // K3: local-player-only (DT_LocalPlayerExclusive) — NOT a remote dormancy signal
    m_iFOV: 0x39A8,
    m_hActiveWeapon: 0x3638,
    m_iAccount: 0xBC38,
    m_ArmorValue: 0xBC4C,
    m_angEyeAngles: 0xBC50,
    m_bHasHelmet: 0xBC40,
    m_bHasDefuser: 0xBC5C,
    m_bIsScoped: 0x41F6,
    m_flFlashDuration: 0xACF0,
  },

  // --- signatures (ADRP/ADD immediates wildcarded; decode at match) ---
  sigs: {
    client: {
      // C_BasePlayer::GetLocalPlayer: sxtw x8,w0; cmn w0,#1; adrp x9; add x9; csel; ldr x0,[x9,x8,lsl#3]; ret
      GetLocalPlayer: '08 7C 40 93 1F 04 00 31 89 60 ?? ?? 29 ?? ?? 91 E8 03 88 9A 20 79 68 F8 C0 03 5F D6',
      // CClientEntityList::GetClientEntity formula
      GetClientEntity: '01 01 F8 37 E8 03 01 2A 08 14 08 8B 00 05 40 F9 80 00 00 B4 08 00 40 F9 01 1D 40 F9 20 00 1F D6',
    },
    engine: {
      // CEngineClient::WorldToScreenMatrix: adrp x8; add x8,#0x220; ldr x0,[x8]; ldr x8,[x0]; ldr x1,[x8,#0x70]; br x1
      WorldToScreenMatrix: 'A8 29 ?? ?? 08 ?? ?? 91 00 01 40 F9 08 00 40 F9 01 39 40 F9 20 00 1F D6',
    },
  },
};

// AArch64 ADRP+ADD decoder: addr = NativePointer of the ADRP instruction.
// Returns NativePointer(page + imm12). All page arithmetic via NativePointer
// (JS bitwise ops are 32-bit and would truncate 64-bit module addresses).
function adrpAddTarget(addr) {
  const adrp = addr.readU32();
  const add = addr.add(4).readU32();
  if (((adrp >>> 24) & 0x9F) !== 0x90) throw new Error('not ADRP');
  if (((add >>> 24) & 0xFF) !== 0x91) throw new Error('not ADD-imm');
  const immlo = (adrp >>> 29) & 3;
  const immhi = (adrp >>> 5) & 0x7FFFF;
  let imm = immhi * 4 + immlo;              // 21-bit, in 4K units
  if (imm >= (1 << 20)) imm -= (1 << 21);   // sign-extend
  const page = addr.and(ptr('0xfffffffffffff000')).add(imm * 0x1000);
  const imm12 = (add >>> 10) & 0xFFF;
  return page.add(imm12);
}

// Signature scan over a module's readable regions. Houdini-shim modules carry
// their ranges directly (from /proc maps); native Modules resolve via the API.
// 'r--' matches every readable range (minimum-permission semantics), hence dedupe.
// Under Houdini the original arm64 .text is mapped r--p (translation happens in
// separate JIT caches), so scanning only r-x would find nothing.
function scanSig(module, pattern) {
  const ranges = module.ranges
    ? module.ranges
    : module.enumerateRanges('r-x').concat(module.enumerateRanges('r--'));
  const scanned = new Set();
  for (const r of ranges) {
    const key = r.base.toString();
    if (scanned.has(key)) continue;
    scanned.add(key);
    const results = Memory.scanSync(r.base, r.size, pattern);
    if (results.length > 0) return results[0].address;
  }
  return null;
}

// Houdini-loaded arm64 modules are invisible to frida's Module API (that list only
// covers the native x86_64 linker namespace). Resolve them from /proc-derived
// ranges by file path instead. Native arm64 devices take the normal path.
// Returns {name, base, size, ranges} or null.
function resolveModule(name) {
  const native = Process.findModuleByName(name);
  if (native) return native;
  let base = null, end = null;
  const ranges = [];
  for (const r of Process.enumerateRanges('r--')) {
    if (!r.file || r.file.path.indexOf(name) < 0) continue;
    ranges.push(r);
    if (base === null || r.base.compare(base) < 0) base = r.base;
    const e = r.base.add(r.size);
    if (end === null || e.compare(end) > 0) end = e;
  }
  if (base === null) return null;
  return { name: name, base: base, size: end.sub(base).toInt32(), ranges: ranges };
}

if (typeof module !== 'undefined' && typeof module.exports !== 'undefined') {
  module.exports = { CONFIG, adrpAddTarget, scanSig, resolveModule };
}
