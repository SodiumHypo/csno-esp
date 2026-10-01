# Phase 4 — Host-Side Memory Reading (❓ planned — this is a shell, not results)

**Goal:** obtain the same `getEspFrame` data by reading the emulator process
(`dnplayer.exe`) **from the Windows host, with zero in-guest components** —
completely abandoning Frida in the read path.

> Everything below marked ❓ is *open work*, deliberately not yet tested.
> Everything referenced from Phases 1–3 is ✅ settled (see
> [offsets-reference.md](offsets-reference.md)).

## Why

| Trace | v1 (Frida) | v2 (host reader) |
|-------|-----------|------------------|
| process in guest `ps` | frida-server | none |
| `/proc/<pid>/maps` anomalies | injected agent regions | none |
| `TracerPid` | ≠0 during attach | 0 |
| guest network listener | :27042 | none |
| root requirement | yes | no |
| host-visible activity | adb + frida | one process handle on dnplayer |

v2 is invisible to *guest-level* integrity checks — the point of this phase is
to measure the game/anti-cheat surface under a realistic threat model.

## Working model (hypotheses to confirm ❓)

LDPlayer is QEMU-based: the **entire guest RAM lives inside `dnplayer.exe`'s
host address space**. Guest virtual addresses as observed by v1 (e.g. module
bases like `0x4000_27c0_0000`) are in-process views of that host memory.

- **H1 ❓:** within one guest RAM region, `hostVA = guestVA + delta` with a
  single constant delta (typical QEMU flat mapping). Must be verified, not
  assumed — QEMU may split guest RAM into multiple blocks each with its own
  delta.
- **H2 ❓:** the wildcarded signatures from offsets-reference can be found by
  scanning dnplayer's committed+readable private regions, giving the module
  base → solving anchoring **without any guest cooperation**.
- The v1 agent's own base addresses double as ground truth while both run
  concurrently (they can — v1 attach + host OpenProcess are independent).

## What ports over unchanged

Every read formula from [offsets-reference.md](offsets-reference.md) — entity
formula, netvar offsets, matrix chain, W2S math — expressed against a
`GuestReader` abstraction in [migration-guide.md](migration-guide.md).
The draw layer (`esp_overlay.py` window/geometry/topmost logic) is reused
**verbatim**; only the frame source changes.

## Open questions (the actual research agenda)

| # | Question | Notes / candidates |
|---|----------|--------------------|
| Q1 ❓ | Stable host-side locating of the arm64 lib images inside dnplayer | Anchor = H2 signature scan (`GetLocalPlayer` / `WorldToScreenMatrix` sigs, wildcarded immediates survive). Fallback anchors: unique guest strings ("DT_CSPlayer", module path strings). Region prefilter via `VirtualQueryEx` (MEM_PRIVATE, PAGE_READWRITE, size-ranked) to keep scans ms-scale |
| Q2 ❓ | Is a plain `ReadProcessMemory` handle sufficient, or does something hook user32/kernel32 read paths in this stack? | Default: `kernel32!ReadProcessMemory` via ctypes/pymem. Only escalate to **direct `NtReadVirtualMemory` syscall stub** (bypassing any user-mode inline hooks) if a measured interference exists — currently none expected (no anti-cheat in this lab build). Do not pre-optimize for it |
| Q3 ❓ | Re-location after emulator restart / dnplayer restart | On pid change (or delta validation failure) → rescan. Keep v1's `verify_bases.js` as the guest-side oracle for the fresh delta |
| Q4 ❓ | Multi-instance: which dnplayer is which emulator | Correlate by window title (`ldconsole` lists indexes) / pid; TODO |
| Q5 ❓ | Cross-process read throughput | ~130 small reads × 30 Hz across the boundary — if RPC-like latency dominates, batch with one 4 KiB chunked `ReadProcessMemory` per page touched and slice in host Python. Measure, then decide |
| Q6 ❓ | Guest→host delta constancy beyond the lib region | Entity/matrix data live in *heap* regions (different VAs than the mapped `.so`). If H1 fails for heap, resolve per-region deltas by scanning for recognizable structures (entity list array of heap pointers) — TBD in first experiment |

## Planned steps (gate = the reason each step exists)

1. ❓ **Process discovery** — enumerate `dnplayer.exe`, acquire
   `OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION)`; gate:
   reads of a known page succeed.
2. ❓ **Region map dump** (psutil `memory_maps` / `VirtualQueryEx` walk) —
   characterize the big private RW regions; gate: a region ≥ guest RAM size found.
3. ❓ **Anchor scan** — signatures from offsets-reference across candidate
   regions; gate: unique match, decoded ADRP+ADD target == v1-reported
   guest-VA of the same global → **delta established**.
4. ❓ **Parity test (main gate)** — run v1 (frida) and the v2 reader on the same
   match; diff `getEspFrame` JSON field-by-field for ≥ 1000 frames; gate: 100 %
   equal (± projection rounding).
5. ❓ **Overlay swap** — point `esp_auto.py`'s frame source at the v2 reader;
   gate: identical UX, no adb/frida processes running.
6. ❓ **Lifecycle test** — kill/restart emulator and game; gate: auto re-anchor
   within seconds (Q3 policy proven).
7. ❓ **Footprint audit** — guest-side `ps`, `/proc/<pid>/maps`, `TracerPid`,
   netstat: gate: clean (this is the phase's *definition of done*).

## Stack constraints (project rule)

Python + JS only: `ctypes` (kernel32/ntdll), `pymem`, `pywin32`, `psutil`;
Node alternative: `koffi`/`ffi-napi`. GUI unchanged (tkinter) or PyQt5/PySide6
if it ever needs more. No IDA/Ghidra-class tooling — the anchor math reuses the
same capstone pipeline from Phase 1.

## Deliverable

`host_reader.py` (GuestReader impl) + `esp_frame_v2.py` (ported
`getEspFrame`) + `parity_check.py` (diffs v1 vs v2). Until step 4 passes, v1
remains the only working implementation.
