# Launcher architecture

`triunit.exe` is the setup, the launcher and the settings of TriUnit Recomp in
one Win32 window. It holds no game code: it runs the setup on the user's ROM
files, then starts the game executables that setup built on this machine.

## Files

| File | Role |
|------|------|
| `native/launcher/launcher_main.cpp` | Window, pages, input (mouse, keyboard, XInput), drawing. |
| `native/launcher/launcher_renderer.{hpp,cpp}` | D3D12 renderer of the launcher: quads, triangles, lines, rounded rectangles (signed distance), effects, text from a GDI glyph atlas, captures. |
| `native/launcher/launcher_backend.{hpp,cpp}` | Preferences, setup queue, game availability, game processes and shutdown. |
| `native/launcher/launcher_setup.hpp` | Reads the setup records `generated/<game>/<sha256>/setup.json`. |
| `native/launcher/launcher_legal.hpp` | The only launcher file that names the games: compatibility list (title, revision, board, manifest) and the legal notice. |
| `tools/launcher/build.py` | Builds `triunit.exe` at the project root (`--if-stale` skips an up-to-date build). |
| `TriUnit Setup.cmd` | Double-click entry: finds Python, builds the app when needed, opens it. |

All art is drawn in code; the launcher reads no image file
(`native/tests/launcher_art_tests.cpp` checks it).

## Pages

`App::page` selects Overview, ROM Setup, Build, Play or Legal; `App::settings`
shows the Settings panel over any page. The interactive elements of Overview,
ROM Setup, Build and Legal come from one function, `App::pageButtons()`, used for
drawing, hit-testing and keyboard / controller focus, so the three never
disagree. Play (the cabinets) and Settings keep their control ids, which the UI
contract tests drive (`launcher_selection_tests.cpp`,
`launcher_operator_ui_tests.cpp`).

`triunit.exe --ui-capture <png> [overview|roms|build|play|legal]` and
`--settings-capture <png>` draw one deterministic frame for layout checks.

## Setup queue

`Backend::queueSetup(game, verifyOnly)` runs `tools/setup/setup.py` one game at a
time:

1. The first job is `setup.py --requirements`, run with `python.exe`, then
   `py.exe -3`, looked up on `PATH` only (never in the launcher or working
   folder). The first interpreter that answers is kept.
2. Each game runs `setup.py -I ... --game <id> --roms <folder> --progress
   logs/setup-<game>.progress.json` (`--verify-only` for Verify), with its
   output in `logs/setup-<game>.log`.
3. Each run is in a kill-on-close Job Object: Cancel, or closing the launcher,
   ends the whole process tree (compiler included).
4. The progress file (step, state, elapsed seconds, compiled units, verify
   report) is read every 250 ms with `FILE_SHARE_DELETE`, so `setup.py` can
   replace it atomically meanwhile.
5. The time estimate is the setup time of the last finished record.

Verify and Build require the ROM ownership confirmation of the Legal page
(`acknowledged=1` in `build/native/launcher-profile/setup.cfg`, with the ROM
folder of each game). A game cannot start while a setup runs.

## From setup to Play

The setup ends with `install` (`tools/setup/install.py`): the launcher package of
the game from the executable just built (MK1
`build/native/manual-temporary-8-20261025/product`, MK2
`build/native/mk2-native-v1/product`, MK3 `build/native/mk3-native/product`).
The player's profile in each package is kept. The launcher offers a game only
when its setup record exists, and for MK2 and MK3 only when the package
executable has the SHA-256 of that record. A built game without its package is
shown as *Built* / *INSTALL PENDING*.

## Tests

- `native/tests/setup_queue_tests.cpp`: the queue against a stub `setup.py`
  (requirements, verify report, failure, Cancel of the process tree, saved
  folders and confirmation).
- `tools/setup/test_setup.py`: `--verify-only`, `--progress`, `--requirements`
  and the MK3 reinstall.
- `native/tests/launcher_art_tests.cpp`, `launcher_selection_tests.cpp`,
  `launcher_operator_ui_tests.cpp`: drawing, legal footer, navigation, cabinet
  selection and settings.

All of them run in `python tools/quality/run.py fast`.
