# Migration Guide — v1 (Frida) → v2 (host reader)

What carries over, what gets replaced, and how to prove equivalence. The
architecture seam (4 logical layers, see
[architecture.md](architecture.md)) means **only layer 2 changes**; layers 1,
3, 4 are reused verbatim.

## File-by-file disposition

| v1 file | Fate | Why |
|---------|------|-----|
| `offsets.json` | **keep, unchanged** | pure data — netvars, formulas, sigs are backend-agnostic |
| `config.js` | keep as **data + algorithm spec** | `adrpAddTarget` logic must be re-implemented in Python against host bytes; netvar/entity constants port directly |
| `esp_loop.js` | **freeze — it is the spec** | port `getEspFrame` 1:1 to Python (sketch below); keep running it as the v2 oracle |
| `frida_run.py` | keep | the oracle harness for parity testing (phase4 step 4) |
| `verify_bases.js` | keep | guest-side ground truth when re-establishing the delta after restarts |
| `verify_recvtable.js` | keep | regression check after game updates (netvars drift) |
| `verify_esp_core.js` | keep | A/B reference for frame parity by eye |
| `esp_overlay.py` | **keep, unchanged** | renderer only consumes the frame JSON + window geometry; no frida types cross the seam |
| `esp_auto.py` | adapt (~30 lines) | drop frida-server management + frida attach; add dnplayer discovery/re-anchor; supervision cadence, topmost, pill, worker-thread pattern all stay |
| `start_esp.bat` | simplify later | frida push/start stages go away; keep the config.json path pattern and the `ping`-delay/CRLF rules |

## The Reader abstraction (v2 core interface)

All addresses below are **guest virtual addresses** — the same numbers v1
computed from `module.base + rva`. The GuestReader's job is exactly and only
`guestVA → bytes`:

```python
class GuestReader:            # host_reader.py — ctypes ReadProcessMemory based
    def open(pid: int) -> None
    def scan_anchor(self, sig: str, perms="r") -> int | None   # guest-VA match
    def read_ptr (self, gva: int) -> int | None
    def read_i32 (self, gva: int) -> int | None
    def read_f32s(self, gva: int, n: int) -> list[float] | None
    def close(self) -> None
```

`esp_frame_v2.py` — direct port of `esp_loop.js getEspFrame`:

| esp_loop.js step | v2 equivalent |
|------------------|---------------|
| `resolveModule(name)` | anchor scan in host memory (Q1) → `delta`; `base_of(name) = guest_base_observed` |
| `client.base.add(rva).readPointer()` | `reader.read_ptr(client_gva + rva)` |
| `p.add(off).readS32()/readFloat()` | `reader.read_i32 / read_f32s` |
| `project(px,py,pz)` float math | copy verbatim (pure math — keep the `wc < 0.05` clip) |
| `EYE_Z_FALLBACK = 60.0`, K2 filter, entry walk `0x28 + 0x20*i` | copy verbatim — **do not "improve"; parity first** |
| `rpc.exports = {getEspFrame}` | plain function call; same JSON dict out |

## Port order that keeps v1 working throughout

1. Build `GuestReader` + anchor scan → print guest-VA bases; diff against
   `verify_bases.js` output on the same running game. (v1 untouched.)
2. Port `getEspFrame`; run **both** backends on one match and diff the JSON
   frame-by-frame (`parity_check.py`, ≥1000 frames, gate: exact on ints,
   ±1 px on projected floats).
3. Only after the gate: switch `esp_auto.py`'s frame source. v1 stays one
   `git revert` away.

## What must NOT be ported

- Any Frida type or concept (`NativePointer`, ranges iteration, agent lifecycle)
  beyond the seam. The frame JSON is the only crossing.
- The GB-scan pattern: on host the equivalent mistake is scanning *all* of
  dnplayer's regions per frame — anchoring happens **once per rebase event**
  (startup / delta-validation failure), never in the frame loop.
- v1's error strings may be reused verbatim (they surface in the overlay status
  line and the supervisor logs treat them as opaque).

## Known migration risks ❓

| Risk | Mitigation |
|------|------------|
| Delta not constant across guest RAM blocks (Q6) | multiple anchors (lib region + heap probes); per-block delta table inside GuestReader |
| Anchor sig false-positives in host copies of memory (JIT caches under Houdini contain translated x86 code, **not** the arm64 pattern — expected clean) | require uniqueness: abort if a sig matches twice; re-verify ADRP+ADD decode equals the seed RVA relationship |
| dnplayer restarts silently | pid watch (same role as game-pid watch in v1 supervisor) → full re-anchor |
| Cross-process read cost (Q5) | page-chunked reads + slice; measure at step 2 of phase4 plan |
