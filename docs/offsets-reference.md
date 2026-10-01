# Offsets Reference — authoritative table

Single source of truth for every number used by the code. Machine-readable
canonical copy: [`offsets.json`](../offsets.json) (agent mirror:
[`config.js`](../config.js)). This page adds **portability class** and
**validation status** per item.

Game build analyzed: `com.ledi.csno` km_ rebuild, 2026-09-30.

## Portability classes

| Class | Meaning | Examples below |
|-------|---------|----------------|
| **P** portable | arch-independent (x86_64-Houdini ⇄ native arm64 ⇄ host-side reads); only a *game update* invalidates | netvars, struct field offsets, entity formula constants |
| **B** build-specific | valid only for this `.so` build | RVA seeds, signature anchors, RecvProp size |
| **S** session-specific | re-resolve every process start | module bases (guest VA), guest→host delta (v2) |
| **U** universal | engine math, always true | W2S projection formula |

Validation status: ✅ runtime-verified in-match · ✅s static-extracted (verified
against live RecvTable 18/18) · ❓ untested.

## Modules

| Key | File | Provides |
|-----|------|----------|
| `client` | `libkm_client_panorama_client.so` | entity list, local player, RecvTables, ScreenTransform |
| `engine` | `libkm_engine_client.so` | `g_EngineRenderer` → view matrix |

## Entity list 🔧P/B · ✅ runtime-confirmed 2026-09-30

```
entity(i) = *(clientBase + 0x16432A0 + 0x28 + 0x20*i)      # DIRECT C_BaseEntity*
```

> The Phase-1 disassembly suggested a wrapper→vcall layer; live enumeration
> proved it wrong by 0x20 (K1). There is **no wrapper and no vcall** — entries
> hold the entity pointer directly. Do not "fix" this back.

| Fact | Value | Class |
|------|-------|-------|
| Singleton RVA (`s_EntityList`, `CClientEntityList`, obj size 0x600d8) | client + `0x16432A0` | B |
| Entry array base / stride | `+0x28` / `0x20` | P/B |
| Entry layout | `+0x00` entity\*, `+0x08` serial, `+0x10/+0x18` intrusive links | P/B |
| Index 0 | **local player** | P |
| Player range | 0..N (bot match: 10 at 0–9), unused slots null | P |
| Indices 64+ | world entities (weapons/props), `team==0` | P |
| Player filter | `hp > 0 && m_iTeamNum != 0` | P |
| Scan bound | 128 entries max (`maxScan`) | perf guard |
| Dormancy | `m_bDormant` **not networked**; `m_nTickBase` local-only → use `m_bSpotted` (0xECD) or origin-staleness | P (K3) |
| Perf rule | never bulk-scan in loop (3.1 GB scan froze game 48 s under Houdini) | — |

## Global RVA seeds (this build) 🔧B · resolution = runtime, class S

| Module | Name | RVA | Kind / formula |
|--------|------|-----|----------------|
| client | `s_pLocalPlayer` | `0x1617F40` | `localPlayer = *(base + rva)` — C_BasePlayer\* storage, slot 0 (array of `MAX_SPLITSCREEN`, `lsl #3` stride) |
| client | `s_EntityList` | `0x16432A0` | see entity-list box |
| client | `engine_iface` | `0x1639C08` | `IEngineClient*` (`matrix = vcall(engine→vtbl+0x128)`) — **not used by v1 read path** (kept for reference) |
| client | `DT_CSPlayer_RecvTable` | `0x1F6B160` | RecvTable; props array @ `0x1F6B228`, 110 props |
| client | `fn_GetClientEntity` | `0xA889D8` | CClientEntityList::GetClientEntity(int) |
| client | `fn_GetLocalPlayerIndex` | `0xA83EC8` | int GetLocalPlayerIndex() |
| client | `fn_ScreenTransform` | `0xBC0768` | `bool ScreenTransform(Vector const&, Vector&)`, out = clip space [−1,1] |
| engine | `g_EngineRenderer` | `0xBA2220` | `CRender*` global |
| engine | `fn_WorldToScreenMatrix` | `0x66D054` | `CEngineClient::WorldToScreenMatrix() → VMatrix*` |

⚠️ `NativeFunction` calls into these `fn_*` are impossible under Houdini
(x86_64 agent); they exist for native-arm64 hardware validation (❓ deferred).

## View matrix ✅ runtime-confirmed (K4)

```
R = *(engineBase + 0xBA2220)            # CRender*
viewMatrix = 16 × f32 at (R + 0xA4)     # row-major VMatrix, primary view
per-view stride = 0x220                 # R + 0xA4 + 0x220*viewIndex
```
Class P/B (struct offsets) + S (R, re-read every frame — cheap, survives
CRender reallocation).

## World-to-Screen ✅ · class **U** (from `esp_loop.js project()`)

```python
wc = M[12]*x + M[13]*y + M[14]*z + M[15]
if wc < 0.05: behind_near_plane
sx = (M[0]*x + M[1]*y + M[2]*z + M[3]) / wc * 0.5 + 0.5          # → [0,1]
sy = 0.5 - (M[4]*x + M[5]*y + M[6]*z + M[7]) / wc * 0.5          # → [0,1], y down
# multiply by guest render w,h; overlay maps that space to the window client rect
```
Head point uses `z + eye`; eye = `m_vecViewOffset.z` (local player only —
K3), fallback constant `60.0` for remotes.

## Netvars — ESP-critical set 🔧P · ✅s (18/18 matched at runtime)

All **P-class**: identical on Houdini-x86 and native arm64; only a game rebuild
changes them. (Baseline CS:GO values are wrong here: uniform **+0x38** shift.)

| Netvar | Offset | Source table | Type | Note |
|--------|--------|--------------|------|------|
| `m_iTeamNum` | `0x12C` | DT_BaseEntity | int | team filter: 0 = not a player |
| `m_iHealth` | `0x138` | DT_BasePlayer | int | |
| `m_fFlags` | `0x13C` | DT_BasePlayer | int | FL_ONGROUND etc. |
| `m_vecOrigin` | `0x170` | DT_BaseEntity / CSLocal+NonLocal | vec3 | feet position |
| `m_vecViewOffset` | `0x140` | DT_LocalPlayerExclusive | vec3 | **stale for remotes** (K3) |
| `m_vecVelocity` | `0x14C` | DT_LocalPlayerExclusive | vec3 | local-only |
| `m_lifeState` | `0x297` | DT_BasePlayer | int | |
| `m_bSpotted` | `0xECD` | DT_BaseEntity | bool | K3 dormancy fallback |
| `m_bSpottedByMask` | `0xF10` | DT_BaseEntity | int[2] | per-player seen mask |
| `m_hActiveWeapon` | `0x3638` | DT_BaseCombatCharacter | ehandle | |
| `m_viewPunchAngle` | `0x3768` | DT_Local | vec3 | aim-noise research (v2 candidate) |
| `m_aimPunchAngle` | `0x3774` | DT_Local | vec3 | ″ |
| `m_iFOV` | `0x39A8` | DT_BasePlayer | int | |
| `m_bIsScoped` | `0x41F6` | DT_CSPlayer | bool | |
| `m_bIsWalking` | `0x41F7` | DT_CSPlayer | bool | |
| `m_bGunGameImmunity` | `0x4214` | DT_CSPlayer | bool | |
| `m_nTickBase` | `0x3C50` | DT_LocalPlayerExclusive | int | **local-only — not a dormancy signal** |
| `m_iShotsFired` | `0xAC80` | DT_CSLocalPlayerExclusive | int | local-only |
| `m_nSurvivalTeam` | `0xACB0` | DT_CSPlayer | int | |
| `m_flFlashMaxAlpha` | `0xACEC` | DT_CSPlayer | float | |
| `m_flFlashDuration` | `0xACF0` | DT_CSPlayer | float | |
| `m_iAccount` | `0xBC38` | DT_CSPlayer | int | |
| `m_bHasHelmet` | `0xBC40` | DT_CSPlayer | bool | |
| `m_iClass` | `0xBC48` | DT_CSPlayer | int | |
| `m_ArmorValue` | `0xBC4C` | DT_CSPlayer | int | |
| `m_angEyeAngles` | `0xBC50` | DT_CSPlayer | vec3 | yaw/pitch (rotation/trigger research) |
| `m_bHasDefuser` | `0xBC5C` | DT_CSPlayer | bool | |

Full field set: [`reference/netvars_DT_CSPlayer.txt`](reference/netvars_DT_CSPlayer.txt)
(355 static netvars, DT_CSPlayer incl. nested tables) and
[`reference/runtime_netvars_all_tables.txt`](reference/runtime_netvars_all_tables.txt)
(1972 netvars, every live RecvTable, dumped from the process — authoritative
over the static file if they ever disagree after an update).

## RecvTable / RecvProp structure layouts 🔧P/B

| Struct | size | Field | Offset |
|--------|------|-------|--------|
| `RecvTable` | `0x28` | `props` / `nProps` / `name` | `0x00` / `0x08` / `0x18` |
| `RecvProp` | `0x60` | `varName`(char\*) / `type`(int) / `flags` / `proxyFn` / `dtProxyFn` / **`dataTable`** / **`offset`** | `0x00` / `0x08` / `0x0C` / `0x30` / `0x38` / `0x40` / `0x48` |

Type enum in this build: `DataTable=6`, `Int=7` (verify on update).

## Signatures (rebuild-survivable; ADRP/ADD immediates wildcarded) 🔧B-anchors

| Name | Module | Pattern | Anchor RVA | Decode |
|------|--------|---------|-----------|--------|
| `GetLocalPlayer` | client | `08 7C 40 93 1F 04 00 31 89 60 ?? ?? 29 ?? ?? 91 E8 03 88 9A 20 79 68 F8 C0 03 5F D6` | `0xA07054` | ADRP@+8 / ADD@+12 → `s_pLocalPlayer` |
| `GetClientEntity` | client | `01 01 F8 37 E8 03 01 2A 08 14 08 8B 00 05 40 F9 80 00 00 B4 08 00 40 F9 01 1D 40 F9 20 00 1F D6` | `0xA889D8` | formula constants (`+0x20` scale, ptr @ `+8`) — note K1 corrected the *interpretation* |
| `WorldToScreenMatrix` | engine | `A8 29 ?? ?? 08 ?? ?? 91 00 01 40 F9 08 00 40 F9 01 39 40 F9 20 00 1F D6` | `0x66D054` | ADRP@+0 / ADD `#0x220`@+4 → `g_EngineRenderer` |
| `ScreenTransform_client` | client | `08 7D 47 F9 08 01 40 F9` | inside `0xBC0768` | GOT slot `+0xEF8` → engine iface; `vtbl+0x128` = WorldToScreenMatrix |

**Houdini scan note:** match these against `r--` ranges (raw arm64 bytes are
mapped read-only; `r-x`-only scanning finds nothing). Same rules become the
host-side anchor set for v2 (phase4 Q1).

## v2 (host reader) — session values ❓

| Item | Status |
|------|--------|
| dnplayer pid discovery | ❓ phase4 step 1 |
| guest→host delta (per RAM block) | ❓ H1/Q6 |
| host anchor scan of the sigs above | ❓ H2/Q1 |
| re-anchor policy on restart | ❓ Q3 |

## Recalibration matrix (what to redo when)

| Event | Redo | Tool |
|-------|------|------|
| Game update | RVA seeds (B) — sigs may survive; if symbols moved, full Phase-1 re-run | `verify_bases.js`, then Phase-1 pipeline |
| Netvar mismatch after update | RecvTable re-walk | `verify_recvtable.js` (runtime) > static extractor |
| Emulator image / LDPlayer update | v1: nothing. v2: delta + anchors | `verify_bases.js`, host scan |
| New emulator instance / restart | v1: automatic (supervisor). v2: re-anchor loop | built into supervisor |
| Native arm64 device | module resolution switches to Frida Module API automatically; re-validate `fn_*` via NativeFunction (❓ first time ever tested) | v1 scripts run unmodified (config.js handles both) |
