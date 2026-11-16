# native/

Hand-written C++ of TriUnit Recomp: hardware semantics and presentation, never game routines.

- `include/`, `src/`: TMS34010 board models, video presenter (`mk5_window.cpp`, CRT/ScaleFX/SMAA/CAS filters, bezel
  drawn in code), T-Unit sound board, audio output and timing.
- `mk2/`, `mk3/`: board, DMA, DCS (ADSP-2105) and runtime support for the games whose C++ the setup generates into
  `generated/<game>/<sha256>/` from the user's ROM (`tools/setup/setup.py`).
- `audio/`: shared audio devices (ymfm, OKI ADPCM, resampler, host gain) and the user music slot loader
  (`custom_audio.hpp`, see `custom_audio/<game>/README_AUDIO.txt`).
- `launcher/`: the `triunit.exe` launcher (`python tools/launcher/build.py`), drawn in code; game names and the legal
  notice only in `launcher_legal.hpp`.
- `runtime/`: license texts shipped with builds and the music slot tables.
- `tests/`: hardware and launcher tests run by `python tools/quality/run.py fast` (no ROM needed for most cases).

Remastered music comes only from the user's `custom_audio/` folder; a missing or unreadable slot plays the arcade's
original music. The Arcade Original edition never reads that folder.
