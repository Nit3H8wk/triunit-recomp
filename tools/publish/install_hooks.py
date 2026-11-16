#!/usr/bin/env python3
"""Install (or remove) the pre-commit hook that runs tools/publish/audit.py --staged.

The hook goes into the repository's own hooks directory, found with
`git rev-parse --git-path hooks`; git configuration is never changed.
Re-running is safe. A pre-commit hook that this script did not write is left
alone unless --force is given (it is then kept as pre-commit.foreign).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

MARKER = "# triunit-publish-audit hook v1 (tools/publish/install_hooks.py)"
HOOK = """#!/bin/sh
%s
# Blocks commits whose staged content fails the publication audit.
top=$(git rev-parse --show-toplevel) || exit 1
for py in python3 python py; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c "import sys; sys.exit(sys.version_info < (3, 8))" >/dev/null 2>&1; then
        exec "$py" "$top/tools/publish/audit.py" --staged
    fi
done
echo "pre-commit: Python 3.8+ not found; cannot run tools/publish/audit.py" >&2
exit 1
""" % MARKER


def hooks_dir(repo):
    out = subprocess.run(["git", "-C", str(repo), "rev-parse", "--git-path", "hooks"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit("install_hooks: not a git repository: %s" % repo)
    path = Path(out.stdout.strip())
    return path if path.is_absolute() else Path(repo) / path


def ours(path):
    try:
        return MARKER in path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default=".", help="repository (default: current directory)")
    ap.add_argument("--uninstall", action="store_true", help="remove the hook written by this script")
    ap.add_argument("--force", action="store_true", help="replace a foreign pre-commit hook")
    a = ap.parse_args(argv)
    hook = hooks_dir(a.repo) / "pre-commit"

    if a.uninstall:
        if not hook.exists():
            print("install_hooks: no pre-commit hook at %s" % hook)
            return 0
        if not ours(hook):
            print("install_hooks: %s was not written by this script; left untouched" % hook, file=sys.stderr)
            return 1
        hook.unlink()
        print("install_hooks: removed %s" % hook)
        return 0

    if hook.exists() and not ours(hook):
        if not a.force:
            print("install_hooks: %s exists and is not ours; use --force to replace it" % hook, file=sys.stderr)
            return 1
        backup = hook.with_name("pre-commit.foreign")
        os.replace(hook, backup)
        print("install_hooks: kept the previous hook as %s" % backup)
    if hook.exists() and hook.read_text(encoding="utf-8", errors="replace") == HOOK:
        print("install_hooks: already installed at %s" % hook)
        return 0
    hook.parent.mkdir(parents=True, exist_ok=True)
    with open(hook, "w", encoding="utf-8", newline="\n") as f:
        f.write(HOOK)
    hook.chmod(0o755)
    print("install_hooks: installed %s" % hook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
