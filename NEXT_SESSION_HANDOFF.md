# Next Session Handoff — Phase 4: Host-Side Memory Reading

**You are starting v2. v1 (Frida) is finished, tagged `v1.0-frida`, and frozen —
it exists now only as the validation oracle for your work.**

## 1. The goal

Read the game's memory **from the Windows host** — from outside, by reading the
memory of the emulator process — and completely abandon Frida in the data path.
Deliverable: same `getEspFrame` JSON, produced with **zero in-guest
components** (no frida-server, no agent, no root, no ports).

Full plan with gated steps and hypotheses H1/H2:
[docs/phase4-hostmem.md](docs/phase4-hostmem.md). Do not re-derive Phases 1–3;
they are settled ([docs/README.md](docs/README.md) → per-phase records).

## 2. Known host-side facts (start here)

| Item | Value |
|------|-------|
| Target process | `dnplayer.exe` (LDPlayer 14, one per emulator instance; x86_64) |
| Where guest RAM lives | inside dnplayer's address space — expect a few huge private RW regions (QEMU allocation); **verify, don't assume** (H1) |
| Where the arm64 lib images live | file-backed `libkm_*.so` mappings of the *guest's* linker — visible as host memory carrying the raw arm64 bytes (guest `.text` is `r--p` there) |
| Guest VAs to expect | Frida-observed bases look like `0x4000_xxxx_xxxx` — these are guest-side VAs; the host address is `guestVA + delta` (delta ❓ unknown, possibly per-region) |
| Read formulas to port | [docs/offsets-reference.md](docs/offsets-reference.md): `local = *(client+0x1617F40)`; `entity(i) = *(client+0x16432A0+0x28+0x20*i)`; matrix = 16 f32 at `**(engine+0xBA2220)+0xA4`; netvars `0x138/0x12C/0x170/0x140`; W2S in `esp_loop.js project()` — port verbatim |
| Anchor signatures | the 4 wildcarded ADRP/ADD patterns in offsets-reference § Signatures — designed to be found by byte-scan; that's exactly how you locate module bases in host memory (Q1) |
| Reusable render layer | `esp_overlay.py` **as-is**: window creation, transparent + click-through, `find_emulator_client_rect()` geometry tracking, `keep_on_top()` re-assertion, `draw_frame()`, ✕-ESP pill pattern in `esp_auto.py` |
| Parity oracle | run `python frida_run.py verify_bases.js` / v1 supervisor alongside v2 and diff frames (see docs/migration-guide.md port order) |
| Working v1 end-to-end | `start_esp.bat` (needs local `config.json` with tool paths — never committed; template in `config.example.json`) |

## 3. Open research questions (your actual work)

1. **Stable base locating on the host (Q1):** scan candidate regions
   (`VirtualQueryEx`/psutil prefilter: private, RW, large) for the anchor
   signatures; decode ADRP+ADD (port `config.js:adrpAddTarget` to Python) to
   recover the *guest* global address → cross-match against v1's reported
   guest VA → derive the delta. Uniqueness required; two matches = abort.
2. **Is the NtDll layer necessary (Q2)?** Default to
   `kernel32!ReadProcessMemory` (ctypes / pymem). Only escalate to a direct
   `NtReadVirtualMemory` syscall stub if you *measure* user-mode hook
   interference — there is none expected in this lab. Don't pre-engineer it.
3. **Re-location after emulator restart (Q3):** pid-change watch (mirror
   `esp_auto.py`'s game-pid loop) → invalidate delta → rescan anchors. Budget:
   rescan must stay out of the frame loop (one-shot per rebase event).
4. Delta constancy across RAM blocks (Q6), cross-process read throughput (Q5),
   multi-instance disambiguation (Q4) — see phase4 doc table.

## 4. Hard constraints

- **Python + JS only.** No IDA/Ghidra/Binary-Ninja/Hopper. Static needs (if any)
  go through pyelftools/capstone tooling already proven in Phase 1.
- Never bulk-scan per frame (v1 lesson: GB-scale scan = 48 s freeze; on the host
  the same mistake = UI stutter and wasted hours). Anchor once, then ~130 reads.
- Read-only. No writes to guest or emulator memory, ever.
- Don't edit v1 files (`esp_loop.js`, `offsets.json`, overlay logic) — parity
  requires the spec to stay still. New code goes in new files
  (`host_reader.py`, `esp_frame_v2.py`, `parity_check.py`).
- No local absolute paths / usernames in anything committed; SO binaries never
  committed (`.gitignore` enforces).

## 5. First commands for the new session

```bash
# orient: read these, in this order
docs/README.md  docs/architecture.md  docs/offsets-reference.md
docs/phase4-hostmem.md  docs/migration-guide.md
# live ground truth (game + emulator running, frida-server-x64 on device):
python frida_run.py verify_bases.js        # guest-VA bases + seed/sig validation
# host reconnaissance (Phase 4 step 1–2):
python -c "import psutil;[print(p.pid,p.name()) for p in psutil.process_iter() if 'dnplayer' in p.name().lower()]"
```

Definition of done for the phase: parity gate (≥1000 identical frames) +
footprint audit clean (guest `ps`/maps/TracerPid/ports show nothing).
