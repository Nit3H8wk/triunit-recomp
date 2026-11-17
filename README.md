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

- Windows 10 or 11, 64-bit, with a DirectX 12 GPU.
- MSYS2 with the MinGW-w64 g++ compiler at `C:/msys64/mingw64/bin/g++.exe`
  (validated version: 16.1.0; another version is reported as not validated).
- Python 3.12 or later on `PATH` (`python` or the `py` launcher; validated with
  3.13.2). The setup uses only the standard library.

The toolchain and Python are not bundled; the setup uses the ones installed on
your machine. The app shows what it found on its Overview page.

## Quick start

1. Double-click `TriUnit Setup.cmd`. It builds the app (`triunit.exe`) when it
   is missing or older than its sources, then opens it. A release already
   contains `triunit.exe`.
2. **Legal**: read the notice and confirm that you own the original board / ROM
   files and obtained them legally. Verify and Build stay disabled until then.
3. **ROM Setup**: choose the folder with the ROM files of each game (or one
   folder for all) and press **Verify**. Every file is checked against the
   manifest; the report lists each file with its result.
4. **Build**: press **Build** (or **Build all**). The page shows the current
   step, the compiled units, the elapsed time and the time of the last run, and
   ends with *Ready to play* or with the step that failed and its log.
5. **Play**: choose a cabinet, switch between Arcade Original and Remastered,
   and press **PLAY**.

Nothing is downloaded. Everything the setup writes stays on your machine
(`roms/`, `generated/`, `build/`, `logs/`, all ignored by Git).

## The app (`triunit.exe`)

One window, drawn entirely in code (no image files), with keyboard, mouse and
XInput controller navigation (PgUp / PgDn or LB / RB change pages):

| Page | What it does |
|------|--------------|
| Overview | The six setup steps, one card per game (revision, board, ROM folder, manifest and the digests it pins, Build), requirements found on this machine, output and receipt locations, launcher modes and custom audio. |
| ROM Setup | ROM folder per game, Verify, and the per-file verification report. |
| Build | One game at a time: progress, Cancel (ends the whole build), Open log (`logs/setup-<game>.log`), Open folder, Play. |
| Play | The cabinets, the selected game and edition, PLAY. |
| Settings | Video, Audio, Display, Launcher, Adjustments and Utilities of the selected game and of the app. |
| Legal | The legal notice, the ROM ownership confirmation and links to `DISCLAIMER.md`, `THIRD_PARTY_NOTICES.md` and `LICENSE`. |

The app runs `tools/setup/setup.py` with the Python found on `PATH`, one game at
a time, and offers a game only when its setup finished on this machine.

## Build a game from the command line

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
6. compiles the game executable into the same folder;
7. installs the launcher package of the game from that executable
   (`build/native/…/product`, local and ignored by Git); the player's saved
   profile is kept.

`--no-compile` stops after step 5. The receipt `setup.json` in the output
folder keeps only identities, digests, counts and timings. `roms/` and
`generated/` are ignored by Git.

Other options:

- `--verify-only` checks every ROM file on its own (missing, size, CRC32,
  SHA-1, SHA-256) and the program image, and writes nothing;
- `--requirements` (no `--game`) reports 64-bit Windows, the Python version and
  the g++ version found against the validated one;
- `--progress <file>` keeps a small JSON file at the current step, with the
  compiled-unit count during compilation; the launcher reads it.

## Launcher modes

`python tools/launcher/build.py` builds the app by hand (`--if-stale` skips an
up-to-date build). `triunit.exe` only offers games whose setup has finished (a
record in `generated/<game>/<sha256>/setup.json`), and accepts a game
executable only by the SHA-256 that record holds. Each game has two modes:

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
`docs/CPP_QUALITY.md`. Launcher internals: `docs/LAUNCHER_ARCHITECTURE.md`.

## Legal notice

TriUnit Recomp is an independent project, not affiliated with or endorsed by
the owners of the games. It includes no game files. You need your own legally
obtained ROM files. Read [DISCLAIMER.md](DISCLAIMER.md).

## License

BSD 3-Clause, see [LICENSE](LICENSE). Third-party components and their
licenses: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Contributions:
[CONTRIBUTING.md](CONTRIBUTING.md). Security and rights notices:
[SECURITY.md](SECURITY.md).
