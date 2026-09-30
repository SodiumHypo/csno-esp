// Phase 3 — ESP frame provider (persistent RPC script).
// Attach, then poll rpc.getEspFrame(width, height) at ~30 Hz from the host.
// Per frame: 1 pointer + 16 floats (matrix) + 128 entry pointers + ~8 reads
// per player. No scans, no native calls (Houdini-safe; identical on arm64).
const { CONFIG, resolveModule } = require('./config.js');

// m_vecViewOffset lives in DT_LocalPlayerExclusive (K3 lesson: local-only
// networking) — stale for remote players. Fallback to the CS standing eye
// height when the read is implausible.
const EYE_Z_FALLBACK = 60.0;

const EL = CONFIG.entityList;
const NV = CONFIG.netvars;

let client = null, engine = null, list = null, rendererGlobal = null;

const rdPtr = (p) => { try { const v = p.readPointer(); return v.isNull() ? null : v; } catch (e) { return null; } };
const rdI32 = (p, off) => { try { return p.add(off).readS32(); } catch (e) { return null; } };
const rdF32 = (p, off) => { try { return p.add(off).readFloat(); } catch (e) { return null; } };

function init() {
  // Resolve into locals first — a partial resolution must not leave the module
  // refs half-set (the game may still be loading its libs).
  const c = resolveModule(CONFIG.modules.client);
  const e = resolveModule(CONFIG.modules.engine);
  if (!c || !e) throw new Error('libkm modules not resolved yet');
  client = c;
  engine = e;
  list = client.base.add(CONFIG.rva.client.s_EntityList);
  rendererGlobal = engine.base.add(CONFIG.rva.engine.g_EngineRenderer);
}

function getEspFrame(w, h) {
  if (!client) {
    try {
      init();
    } catch (e) {
      // Game still loading (Houdini maps not up yet) — retry on the next poll,
      // no exception: the supervisor would otherwise force a needless re-attach.
      return { ok: false, players: [], localTeam: -1, error: 'modules loading: ' + e.message };
    }
  }
  const out = { ok: false, players: [], localTeam: -1, error: '' };

  const local = rdPtr(client.base.add(CONFIG.rva.client.s_pLocalPlayer));
  if (!local) { out.error = 'no local player (in match?)'; return out; }

  // View matrix: re-read the renderer pointer + 16 floats each frame (cheap,
  // immune to CRender reallocation).
  const R = rdPtr(rendererGlobal);
  if (!R) { out.error = 'renderer null'; return out; }
  const M = [];
  for (let i = 0; i < 16; i++) M.push(R.add(CONFIG.rva.engine.render_viewMatrixOff + i * 4).readFloat());
  if (M.some(f => !isFinite(f))) { out.error = 'matrix not ready'; return out; }

  const project = (px, py, pz) => {
    const wc = M[12] * px + M[13] * py + M[14] * pz + M[15];
    if (wc < 0.05) return null;            // behind / at near plane
    return {
      x: (M[0] * px + M[1] * py + M[2] * pz + M[3]) / wc * 0.5 + 0.5,  // -> [0,1]
      y: 0.5 - (M[4] * px + M[5] * py + M[6] * pz + M[7]) / wc * 0.5,  // -> [0,1], y down
    };
  };

  const localTeam = rdI32(local, NV.m_iTeamNum);
  out.localTeam = localTeam === null ? -1 : localTeam;

  for (let i = 0; i < EL.maxScan; i++) {
    const ent = rdPtr(list.add(EL.entryBase + EL.stride * i));
    if (!ent) continue;
    // K2 filter: players have hp>0 and a real team; world entities (indices 64+)
    // carry team=0 / hp=0.
    const team = rdI32(ent, NV.m_iTeamNum), hp = rdI32(ent, NV.m_iHealth);
    if (team === null || hp === null || hp <= 0 || team === 0) continue;

    const x = rdF32(ent, NV.m_vecOrigin), y = rdF32(ent, NV.m_vecOrigin + 4), z = rdF32(ent, NV.m_vecOrigin + 8);
    if (x === null || y === null || z === null) continue;

    let eyeZ = rdF32(ent, NV.m_vecViewOffset + 8);
    if (eyeZ === null || eyeZ < 10 || eyeZ > 100) eyeZ = EYE_Z_FALLBACK;

    const feet = project(x, y, z);
    const head = project(x, y, z + eyeZ);
    if (!feet || !head) continue;

    out.players.push({
      i: i,
      local: ent.equals(local) ? 1 : 0,
      team: team,
      hp: hp,
      spotted: rdI32(ent, NV.m_bSpotted) ? 1 : 0,
      fx: Math.round(feet.x * w), fy: Math.round(feet.y * h),
      hx: Math.round(head.x * w), hy: Math.round(head.y * h),
    });
  }

  out.ok = true;
  return out;
}

rpc.exports = { getEspFrame: getEspFrame };
console.log('[esp] frame provider ready — poll rpc.getEspFrame(w, h)');
