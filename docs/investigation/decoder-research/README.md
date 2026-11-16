# Decoder research sources

This folder holds the third-party reference sources that the project's tools read or compile, and a small offline
disassembler harness. It holds no program bytes, no disassembly listings and no data derived from any ROM.

- `upstream/`: unmodified copies of MAME source files (pinned commit `4f9dcc832cc0089de2451696320f671e87da79f4`),
  BSD-3-Clause, with the original notices and authors kept (`upstream/LICENSE-BSD-3-Clause.txt`). `sources.json`,
  `adsp-sources.json`, `field-sources.json` and `graphics-sources.json` record each file's SHA-256 and purpose. See
  also `docs/third_party/mame/README.md`.
- `shim/emu.h`: the minimal header that lets `upstream/34010dsm.cpp` compile on its own.
- `disassemble.cpp`: a command-line wrapper around the upstream TMS34010 disassembler. It prints text for bytes the
  user supplies; nothing it prints is stored in the repository.
- `build_probe.py` and `build.json`: how the wrapper was built (paths relative to the repository root). The setup
  builds its own copy with `tools/setup/decoder.py`; `build.json` is the reference record of that build.

Output of these tools is local to the user's machine and stays out of Git (enforced by
`tools/publish/audit.py`).
