# Technical Documentation

Engineering docs for the CSNO-ESP project. The user-facing quickstart lives in
the [root README](../README.md); this directory explains *how it works, what was
proven, and what comes next*.

Status legend used throughout:

| Mark | Meaning |
|------|---------|
| ✅ | Resolved & verified (empirical evidence on record) |
| 🔧 | Build-specific value — valid for this game build, must be recalibrated after an update |
| ❓ | Open / to be explored (not speculative content — just not yet tested) |

## Reading order

| Doc | Contents | Status |
|-----|----------|--------|
| [architecture.md](architecture.md) | System topology, the 4-layer design, component responsibilities | ✅ |
| [phase1-static.md](phase1-static.md) | Static extraction of netvars/RVAs from the arm64 `.so` files (Python toolchain) | ✅ done |
| [phase2-dynamic.md](phase2-dynamic.md) | On-device Frida verification: Houdini environment facts, K1–K4 unknowns resolved | ✅ done |
| [phase3-frida-esp.md](phase3-frida-esp.md) | The shipped reference implementation (in-process Frida RPC + PC overlay) | ✅ frozen at `v1.0-frida` |
| [phase4-hostmem.md](phase4-hostmem.md) | Next phase: reading guest memory from the Windows host, no Frida in the guest | ❓ planned |
| [migration-guide.md](migration-guide.md) | What carries over from v1 (Frida) to v2 (host reader), file by file | ❓ planned |
| [offsets-reference.md](offsets-reference.md) | **Authoritative table** of every offset, RVA, formula and its validation state | ✅ current |
| [reference/](reference/) | Raw data dumps: `netvars_DT_CSPlayer.txt` (355 static netvars), `runtime_netvars_all_tables.txt` (1972 runtime netvars, all RecvTables) | ✅ |

## Two approaches — comparison

Both approaches consume the same data model (entity formula, netvars, view
matrix — see [offsets-reference.md](offsets-reference.md)). They differ only in
*where the reads execute*.

| | **v1 — Frida in-process (shipped, `v1.0-frida`)** | **v2 — host-side memory read (planned, Phase 4)** |
|---|---|---|
| Read engine | Frida agent running **inside** the game process (`Memory.readPointer` via RPC) | Windows host reads `dnplayer.exe` memory (`ReadProcessMemory` / `NtReadVirtualMemory`) |
| Guest footprint | High: frida-server daemon, injected agent (anonymous exec regions in `/proc/<pid>/maps`), `TracerPid` during attach, port 27042 | None at the guest level — all activity happens outside the Android VM |
| Setup | adb push + start frida-server, root on the emulator | OpenProcess on host (same user, no root needed on guest) |
| Dev speed | Fast (JS in agent, live iteration) | Slower first pass: must solve guest-VA → host-VA translation |
| Hard problem | none left — solved | ❓ locating a stable module base anchor in host address space; delta stability across emulator restarts |
| Detectability (anti-cheat context) | Detectable by any guest-side integrity check | Invisible to guest-level checks; still visible from host (process handles) |
| Verdict | ✅ complete; **reference implementation for an authorized R&D lab only — NOT a long-term covert solution** | ❓ the actual research goal of the next phase |

## Selection advice

- Reproducing the result today in the lab → use **v1** as-is (tag `v1.0-frida`).
- Testing a realistic stealth threat model, or anything long-running → **v2**
  is the only sanctioned direction; v1 exists to validate v2 (it doubles as the
  oracle — same frame data, independent read path).
- v1's agent code (`esp_loop.js`) is frozen on purpose: it is the behavioral
  spec for the v2 reader. Port it, don't evolve it.

## Tooling constraints (project-wide rule)

All future work uses **Python and JavaScript (Node.js)** only.
Static analysis: pyelftools, capstone, keystone, angr, yara-python, lief
(optionally r2pipe against radare2 as a *headless data source*). Dynamic:
frida-tools. Host memory: pymem / ctypes `NtReadVirtualMemory` / pywin32;
Node: ffi-napi / koffi. Overlay: PyQt5/PySide6 or tkinter (shipped), optionally
electron. Allowed CLI helpers are data sources called from Python only:
`adb`, `readelf`, `objdump`, `strings`, `nm`.
No IDA Pro / Ghidra / Binary Ninja / Hopper GUI workflows — every value in this
repo was and must remain extractable by the scripted pipeline.
