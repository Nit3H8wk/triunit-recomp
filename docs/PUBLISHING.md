# Publishing

This repository is prepared and audited locally. Creating the GitHub repository
and the first `push` need the maintainer's own account and are done by hand.

## Before the first push

1. Work from a fresh clone of the local repository, never from a folder that
   holds `roms/`, `generated/`, `build/` or `custom_audio/` files.
2. Commit only with the public identity: the GitHub `noreply` address of the
   account that pushes (Settings > Emails > "Keep my email addresses private"
   and "Block command line pushes that expose my email"):

   ```powershell
   git config user.name "TriUnit Recomp contributors"
   git config user.email "<id>+<login>@users.noreply.github.com"
   ```

   If a commit was made with another address, rewrite it before pushing:
   `git rebase --root --exec "git commit --amend --no-edit --reset-author"`.
3. Check the history:

   ```powershell
   python tools/publish/audit.py --all-objects
   git log --format="%an <%ae>%n%cn <%ce>" | sort -u
   ```

   The audit must report 0 findings and the log must show only the `noreply`
   identity.
4. Install the commit hook in every clone used for work:
   `python tools/publish/install_hooks.py`.

## First push

1. Create an empty **private** repository `triunit-recomp` (no README, licence
   or `.gitignore` from GitHub).
2. Enable private vulnerability reporting (Settings > Security), the channel
   `SECURITY.md` names.
3. Push `main`, wait for the `publication-audit` workflow to pass and review
   the tree on GitHub: no ROM, generated C++, CMOS seed, capture, music or art
   file, and no game mark outside `native/launcher/launcher_legal.hpp`,
   `README.md`, `DISCLAIMER.md` and `THIRD_PARTY_NOTICES.md`.
4. Only then make the repository public.

## Releases

A release contains only the setup, the launcher and the tools. It never
contains generated code, a game executable, a CMOS seed, ROM data, captures or
music. The game's C++ is always generated and compiled on the user's machine
by `tools/setup/setup.py`.

The toolchain is not bundled: the setup records the identity (version and
SHA-256) of the MSYS2 g++ 16.1.0 that validated the routes. Bundling another
compiler requires revalidating every route first.

## Rights notices

1. A notice arrives through the private channel in `SECURITY.md`.
2. The same day, remove the item from `main` (a normal commit) and say so in
   the advisory. If the item is in an older commit and the notice requires it,
   rewrite the history and force-push, then ask GitHub support to purge cached
   views.
3. Review the notice and answer in the advisory with the outcome.

## Outside the scope of this repository

A formal trademark search (USPTO, INPI) for the name and a lawyer's opinion
are recommended before the repository is made public.
