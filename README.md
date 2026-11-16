# TriUnit Recomp

TriUnit Recomp is a set of tools that turns the program of a 1990s arcade
board into native C++ for Windows. It covers three board families built on the
TMS34010 graphics processor (Y-Unit, T-Unit and Wolf Unit), with their sound
hardware (ADSP-2105 DCS, 6809 sound board, YM2151, OKI ADPCM).

The repository contains only tools: decoders, generators, hardware models and
a launcher. It contains no game files. The game's C++ is generated on your
machine, from ROM files you own, by a static recompilation done locally from
your ROM.

## Compatibility

| Game | Revision | Board | Setup | ROM manifest |
|------|----------|-------|-------|--------------|
| Mortal Kombat II | L3.1 | T-Unit | supported | `tools/mk2/roms-l31.json` |
| Mortal Kombat 3 | 2.1 | Wolf Unit | supported | `tools/mk3/roms-21.json` |
| Mortal Kombat | 5.0 | T-Unit (ADPCM sound) | supported | `tools/mk1/roms-l1.json` |
| Ultimate Mortal Kombat 3 | — | Wolf Unit | not supported | — |

Each manifest lists the file names the setup accepts with their size, CRC32,
SHA-1 and SHA-256. Only files that match the manifest exactly are accepted.
The digests that the generated output must reproduce are in
`tools/acceptance/manifest.json` and `tools/acceptance/generated.json`.

## Requirements

- Windows with a DirectX 12 GPU.
- MSYS2 with the MinGW-w64 g++ compiler at `C:/msys64/mingw64/bin/g++.exe`
  (validated version: 16.1.0).
- Python 3.

The toolchain and Python are not bundled; the setup uses the ones installed on
your machine.

## Build a game

```powershell
python tools/setup/setup.py --game mk1 --roms <folder with your own ROM files>
python tools/setup/setup.py --game mk2 --roms <folder with your own ROM files>
python tools/setup/setup.py --game mk3 --roms <folder with your own ROM files>
```

The setup:

1. verifies every file of the supported revision by name, size and checksums
   (including SHA-256) against the manifest;
2. links or copies the verified files into `roms/<game>/`;
3. compiles the TMS34010 decoder from its BSD-3-Clause sources
   (`tools/setup/decoder.py`) into `generated/tools/`;
4. generates the game's C++ into `generated/<game>/<sha256>/`, where `<sha256>`
   identifies the program image;
5. compares the generated output with the acceptance digests;
6. compiles the game executable into the same folder.

`--no-compile` stops after step 5. The receipt `setup.json` in the output
folder keeps only identities, digests, counts and timings. `roms/` and
`generated/` are ignored by Git.

## Launcher

Build it with `python tools/launcher/build.py` (writes `triunit.exe` at the
project root). Its start screen has a ROM-folder button that runs the setup for
every supported game, shows the setup state of each cabinet and the legal
notice. `triunit.exe` only offers games whose setup has finished (a record in
`generated/<game>/<sha256>/setup.json`), and accepts a game executable only by
the SHA-256 that record holds. All launcher art is drawn in code. Each game has
two modes:

- **Arcade Original**: the board's audio exactly as the arcade produces it, with
  the arcade image (video filters stay optional). This mode never reads
  `custom_audio/`.
- **Remastered**: presentation options on top of the same game: video filters
  (scaling, CRT presets, ScaleFX, CAS sharpening, SMAA, bilateral filter), a
  bezel drawn in code, and optional music supplied by you.

Game rules, timing, voices and effects are the same in both modes.

## Your own music (`custom_audio/`)

Remastered can play music files that you provide; nothing is included. Put them
in `custom_audio/<game>/` (see `custom_audio/<game>/README_AUDIO.txt`):

- WAV, PCM 16-bit, 48000 Hz, mono or stereo;
- one file per neutral slot, named `music-NN.wav`;
- optional `slots.json` for cuts, loops and gain;
- a slot that is missing or cannot be read falls back to the arcade's original
  music from your ROM.

The launcher menu can play `custom_audio/launcher/menu.wav`; without it the
menu is silent.

## Method

The setup reads your ROM, decodes the program and emits C++ for it with the
project's generators. Hardware is modelled in the project's own C++. Nothing
generated is distributed: generated code stays in `generated/` on your machine,
and releases never contain generated code.

## Tests

```powershell
python tools/quality/run.py fast
```

`fast` needs no GPU or installed game, but several of its cases read your ROM
files and the setup output: run the setup of the three games first. Scope and other suites:
`docs/CPP_QUALITY.md`.

## Legal notice

TriUnit Recomp is an independent project, not affiliated with or endorsed by
the owners of the games. It includes no game files. You need your own legally
obtained ROM files. Read [DISCLAIMER.md](DISCLAIMER.md).

## License

BSD 3-Clause, see [LICENSE](LICENSE). Third-party components and their
licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions:
[CONTRIBUTING.md](CONTRIBUTING.md). Security and rights notices:
[SECURITY.md](SECURITY.md).
