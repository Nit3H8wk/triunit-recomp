# Contributing

Contributions are welcome under the BSD 3-Clause License (`LICENSE`). Read
`DISCLAIMER.md` first: the project contains tools only, never game material.

## Never submit

- ROM files, or any part of them (bytes, hex or base64 dumps, extracted data).
- Game assets: graphics, sound, music, screen captures, videos, scans of
  manuals, cabinets or artwork.
- Game routines translated or transcribed by hand, and disassembly listings of
  a game.
- Generated code (anything the setup writes under `generated/`).
- Memory dumps, CMOS/NVRAM seeds or other captured game state.
- Leaked, confidential or proprietary material of any kind.
- Links to, or instructions for obtaining, any of the above.

## How coverage is added

All new game coverage enters through the generator, which runs on the user's
machine from the user's own ROM. Contributions change the decoders, generators,
hardware models, fact tables (addresses, control-flow edges, partitions,
hashes, sizes, file names), the launcher or the tests, never the game code.

## Origin statement

Every pull request must state the origin of its content, for example:

- "I wrote this myself."
- "It comes from <source, URL and version> under <license>."

Third-party code must have a license compatible with BSD-3-Clause and must be
added to `THIRD_PARTY_NOTICES.md` in the same pull request.

## Checks

Before opening a pull request, run:

```powershell
python tools/publish/audit.py
python tools/quality/run.py fast
```

Both must pass. `python tools/publish/install_hooks.py` installs a pre-commit
hook that runs the audit on every commit.

## Commit messages

Use Conventional Commits, for example `fix(mk3): ...`, `feat(setup): ...`,
`docs: ...`.
