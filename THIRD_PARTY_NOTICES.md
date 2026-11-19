# Third-party notices

TriUnit Recomp is licensed under the BSD 3-Clause License (see `LICENSE`).
The components below come from other authors and keep their own licenses.
Each entry was checked against the file headers and license files in this
tree. No game file of any kind is included (see `DISCLAIMER.md`).

## Distributed in this repository

### MAME — TMS34010 disassembler

- Files: `docs/investigation/decoder-research/upstream/34010dsm.cpp`,
  `docs/investigation/decoder-research/upstream/34010dsm.h` (unmodified).
- Origin: https://github.com/mamedev/mame, commit
  `4f9dcc832cc0089de2451696320f671e87da79f4`, path
  `src/devices/cpu/tms34010/`. URL, size and SHA-256 of each file are pinned in
  `docs/investigation/decoder-research/sources.json`; `tools/setup/decoder.py`
  refuses to build when a file differs from its pin.
- Use: compiled on the user's machine by `tools/setup/decoder.py` into the
  offline decoder used by the setup. It is not linked into the launcher or the
  game executable.
- License: BSD-3-Clause. File header: `license:BSD-3-Clause`,
  `copyright-holders:Zsolt Vasvari`. Notice: `docs/third_party/mame/README.md`.
- Local adapter: `docs/investigation/decoder-research/shim/emu.h` and
  `disassemble.cpp` are project code (BSD-3-Clause, this project) that supply
  byte reads and text output to the unmodified disassembler.

### MAME — reference sources read by the tools

- Files: `docs/investigation/decoder-research/upstream/` (CPU cores, ADSP-2100,
  DAC/sound/scheduler headers) and `docs/investigation/sources/` (board drivers
  and devices), unmodified.
- Origin: MAME commit `4f9dcc832cc0089de2451696320f671e87da79f4` (`machine.cpp`
  from tag `mame0280`); pins in the JSON files of `decoder-research/`.
- Use: the MK3 generator reads the TMS34010 opcode table, MK2 tests compile the
  DAC headers and read driver code as behavioural contracts. Not linked into the
  launcher or a game.
- License: BSD-3-Clause, each file's own header. Notice:
  `docs/investigation/decoder-research/upstream/LICENSE-BSD-3-Clause.txt`,
  `docs/third_party/mame/README.md`.

### MAME — adapted code and behavioural references

Some hardware models are adaptations of MAME code or were written against MAME
behaviour as a reference. Files that state a MAME origin in their header:

| File | MAME source | Copyright holders (from MAME headers) |
|------|-------------|----------------------------------------|
| `native/audio/williams_resampler.hpp` | `src/emu/resampler.cpp`, tag `mame0280` | Olivier Galibert |
| `native/audio/oki6295.cpp` | OKI ADPCM / OKIM6295 reference | Andrew Gardner, Aaron Giles; Mirko Buffoni, Aaron Giles |
| `native/include/mk5_protection.hpp` | driver file `midtunit_m.cpp` (device protocol), commit `4f9dcc8` | Alex Pasadyn, Zsolt Vasvari, Ernesto Corvi, Aaron Giles |
| `tools/mk2/generate_adsp.py`, `tools/mk3/generate_adsp.py` (ADSP-2105 semantics) | `src/devices/cpu/adsp2100/adsp2100.cpp`, `2100ops.hxx` | Aaron Giles |

License: BSD-3-Clause. Notice: `native/audio/LICENSE.txt` (copied for
packaging as `native/runtime/LICENSE-audio.txt`) and
`docs/third_party/mame/README.md`.

### ymfm (YM2151 / OPM emulation)

- Files: `native/audio/ymfm/` (`ymfm.h`, `ymfm_fm.h`, `ymfm_fm.ipp`,
  `ymfm_opm.cpp`, `ymfm_opm.h`, `ymfm_ssg.cpp`, `ymfm_ssg.h`).
- Origin: ymfm by Aaron Giles, https://github.com/aaronsgiles/ymfm. The
  upstream commit was not recorded when the files were imported.
- Local changes (save states): `save_restore` also keeps the noise LFO waveform, the
  operator caches and the engine's prepare bookkeeping, and no longer invalidates the
  caches after a restore. Marked `TriUnit:` in `ymfm_opm.cpp` and `ymfm_fm.ipp`.
- License: BSD-3-Clause, Copyright (c) 2021, Aaron Giles.
  Text: `native/audio/ymfm/LICENSE` (identical copy for packaging:
  `native/runtime/LICENSE-ymfm.txt`).

### AMD FidelityFX CAS (contrast adaptive sharpening)

- File: `native/include/mk5_crt_shader.hpp` (the CAS kernel inside the
  embedded HLSL; the rest of that shader is project code).
- Origin: https://github.com/GPUOpen-Effects/FidelityFX-CAS, commit `d70012e`,
  file `ffx-cas/ffx_cas.h`, version 1.0.1. Adapted.
- License: MIT. Copyright (c) 2017-2019 Advanced Micro Devices, Inc.
  Text: header of `native/include/mk5_crt_shader.hpp` and
  `native/runtime/LICENSE-video.txt`.

### SMAA (enhanced subpixel morphological antialiasing)

- Files: `native/include/mk5_smaa_upstream/SMAA.hlsl.h`, `AreaTex.h`,
  `SearchTex.h` (upstream sources wrapped as C++ string/array literals), used by
  `native/include/mk5_smaa_shader.hpp` and `mk5_smaa.hpp`.
- Origin: https://github.com/iryoku/smaa, commit
  `71c806a838bdd7d517df19192a20f0c61b3ca29d`.
- License: MIT-style (the SMAA license; it does not require the notice in
  binary distributions). Copyright (C) 2013 Jorge Jimenez, Jose I. Echevarria,
  Belen Masia, Fernando Navarro, Diego Gutierrez. Text: header of each file in
  `native/include/mk5_smaa_upstream/`.

### ScaleFX

- File: `native/include/mk5_scalefx_shader.hpp` (HLSL/DX12 adaptation of the
  five Cg passes); `native/include/mk5_scalefx.hpp` is project code that runs
  them.
- Origin: ScaleFX by Sp00kyFox,
  https://github.com/libretro/common-shaders/tree/663f706cee753f0290d5c14af7a47cc69b266e91/scalefx/shaders.
- License: MIT. Copyright (c) 2016 Sp00kyFox. Text: header of
  `native/include/mk5_scalefx_shader.hpp`.

## Project code that looks third-party but is not

- CRT presets and shader (`native/include/mk5_crt.hpp`,
  `mk5_crt_shader.hpp` outside the CAS kernel, `mk5_video_presets.hpp`): project
  code. `docs/CRT_SETUP.md` names CRT Guest Advanced only as an architectural
  reference; no code from it is incorporated.
- Bezel (`native/include/mk5_bezel.hpp`), bicubic scaling
  (`mk5_stage_bicubic.hpp`, `mk5_fighter_bicubic.hpp`) and the bilateral filter:
  project code, drawn or computed in code without image assets.

## Referenced, not distributed

- MAME files that no project tool reads or compiles (copies formerly kept in
  `tools/audio_reference_20261024/resampler_upstream/`), BSD-3-Clause: removed,
  listed by former path, size and SHA-256 in `docs/third_party/mame/sources.json`.

## Toolchain and Python

Not embedded. The setup uses the compiler and Python already installed on the
user's machine: MSYS2 MinGW-w64 g++ (validated version 16.1.0, expected at
`C:/msys64/mingw64/bin/g++.exe`) and Python 3. Their licenses apply to those
installations. Executables built with `-static` include the GCC runtime
libraries (GPL with the GCC Runtime Library Exception) and the MinGW-w64
runtime and winpthreads (permissive licenses); a published binary of the
launcher or setup must carry those notices. Embedding a fixed toolchain and
an embeddable Python is planned; when it happens their notices will be added
here.
