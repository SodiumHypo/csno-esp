# Phase 1 — Static Analysis (✅ complete)

Goal: extract every offset, structure and RVA needed for ESP **without a
debugger**, from the pulled arm64 binaries, using only a scripted Python
toolchain (pyelftools + capstone). Output feeds `offsets.json`.

## Inputs

```bash
# locate the game's native lib dir on the device (path hash varies per install):
adb shell pm path com.ledi.csno          # → .../lib/arm64/libkm_*.so
# pull the two core libraries (NEVER commit .so files to this repo):
adb pull <install-dir>/lib/arm64/libkm_client_panorama_client.so
adb pull <install-dir>/lib/arm64/libkm_engine_client.so
```

## Binary profile ✅

| Check | Result |
|-------|--------|
| Format | ELF64, EM_AARCH64 (arm64) |
| Packer / obfuscation | **None** — clean NDK r27 build |
| Symbols | **Not stripped**: 185,376 symbols |
| RecvTable metadata | Present: full `DT_*` / `m_*` string set (`strings`-able) |

Because symbols and RTTI-ish strings survived the build, most extraction is
symbol-guided disassembly rather than blind pattern hunting.

## Toolchain (Python-only, headless)

The host needs no binutils/IDA — everything is driven through Python:

| Tool | Role |
|------|------|
| pyelftools | Sections, symbols, relocations; `so_image.py` wraps it into a **relocation-aware** reader (VA ↔ file offset, resolved `R_AARCH64_*` adrp pairs) |
| capstone | ARM64 disassembly of named functions (`Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)`) |
| keystone | (available) assembling probe patterns — not needed so far |
| plain Python | parsing netvar dumps, ADRP+ADD decoding, JSON config generation |

Core ADRP+ADD decode (mirrored at runtime in `config.js:adrpAddTarget`):

```python
page = (addr & ~0xFFF) + sign_extend(imm21(adrp_word)) * 0x1000
target = page + imm12(add_word)
```

## Method 1 — netvar extraction (RecvTable constructors)

Source Engine registers each class's `RecvProp[]` via a
`ClientClassInit<DT_CSPlayer>`-style constructor at load time. We disassembled
those constructors and recovered this build's **structure layout** first:

| Struct | Layout facts (this build, 64-bit) |
|--------|-----------------------------------|
| `RecvProp` | size **0x60**; `m_VarName@0x00`, `m_Type@0x08`, `m_Flags@0x0C`, `m_pDataTable@0x40`, **`m_Offset@0x48`** |
| `RecvTable` | size **0x28**; `props@0x00`, `nProps@0x08`, `name@0x18` |

Then: walk the `DT_CSPlayer` table statically (`props@0x1F6B228`, 110 direct
props, recursion through `m_pDataTable`) →
[`reference/netvars_DT_CSPlayer.txt`](reference/netvars_DT_CSPlayer.txt)
(355 netvars, format `name 0xoffset RecvPropType [DT_table]`).

**Key finding 🔧:** every baseline CS:GO offset is shifted **+0x38** in this
rebuild — e.g. `m_iHealth` 0x100→**0x138**, `m_iTeamNum` 0xF4→**0x12C**,
`m_vecOrigin` 0x138→**0x170**. Do not trust upstream CS:GO offset tables
against this build; use [offsets-reference.md](offsets-reference.md).

## Method 2 — global pointer RVAs (symbol-guided disasm)

| Target | Derivation |
|--------|------------|
| `s_pLocalPlayer` (client +0x1617F40) | `C_BasePlayer::GetLocalPlayer` body: `sxtw/cmn/adrp x9/add/csel/ldr x0,[x9,x8,lsl#3]` → the ADRP+ADD pair decodes to the global; the `lsl #3` proves it's a pointer array with slot 0 = local |
| `s_EntityList` (client +0x16432A0) | `CClientEntityList::GetClientEntity` references the singleton; array layout read from the same body (**wrapper+vcall reading later corrected by Phase 2 — off by 0x20, see phase2 K1**) |
| View matrix (engine +0xBA2220 → `CRender+0xA4`) | `CEngineClient::WorldToScreenMatrix` = `adrp x8/add x8,#0x220; ldr x0,[x8]; …br x1` → `g_EngineRenderer`; the vcall target loads the VMatrix at `CRender+0xA4` |

## Method 3 — rebuild-survivable signatures

ADRP/ADD **immediates are wildcarded (`??`)** so patterns match across
rebuilds; the target address is *decoded from the matched instruction*, not
embedded in the pattern. Three sigs shipped (client `GetLocalPlayer`,
client `GetClientEntity`, engine `WorldToScreenMatrix`) — byte strings live in
[offsets-reference.md § Signatures](offsets-reference.md).

## Outputs & verification status

- `offsets.json` — machine-readable config (single source of truth; mirrored by
  `config.js` for the agent).
- `docs/reference/netvars_DT_CSPlayer.txt` — static netvar dump.
- Every value was re-verified at runtime in Phase 2:
  **18/18 ESP-critical netvars matched, 0 mismatches**
  ([phase2-dynamic.md](phase2-dynamic.md)); full runtime dump (1972 netvars,
  all tables) in [`reference/runtime_netvars_all_tables.txt`](reference/runtime_netvars_all_tables.txt).

## Recalibration after a game update 🔧

1. Re-pull the two `.so` files.
2. Re-run the constructor walk (tooling: `so_image.py` + capstone disasm of the
   `ClientClassInit` symbols, which persist as long as the build stays
   unstripped) → refresh netvars.
3. Re-decode the three ADRP+ADD sites via the wildcarded sigs → refresh RVA
   seeds. If a sig stops matching, re-derive from the symbol first.
4. Field offsets stay valid across x86⇄arm64; only the RVAs move.
