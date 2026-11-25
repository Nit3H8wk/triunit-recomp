#!/usr/bin/env python3
"""CLI-only Linux launcher for TriUnit Recomp — MK1, MK2, MK3.

Sandbox-safe: no GUI file dialogs (compatible with Recomplauncher/WebKit).
ROM directory is set via:
  1. Command-line argument:   ./run.sh /path/to/roms
  2. Config file:             ~/.config/triunit-recomp/roms.path
  3. CLI prompt (last resort)
"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).parent.resolve()
CONFIG_DIR = Path.home() / '.config' / 'triunit-recomp'
CONFIG_FILE = CONFIG_DIR / 'roms.path'

# ── ROM requirements ──────────────────────────────────────────────────────

MK_ROMS = {
    'mk.zip':   'Mortal Kombat (1994)',
    'mk2.zip':  'Mortal Kombat 2 (1994)',
}

MK3_ROMS = {
    'mk3.zip':     'Mortal Kombat 3 (1995)',
    'mk3r21.zip':  'Mortal Kombat 3 R2.1',
    'umk3.zip':    'Ultimate Mortal Kombat 3',
}

ALL_ROMS = {**MK_ROMS, **MK3_ROMS}


def show_rom_requirements():
    """Display what ROM files are needed."""
    print("\n" + "=" * 60)
    print("  ROM FILES REQUIRED")
    print("=" * 60)
    print()
    print("  You need MAME-style ROM files for Mortal Kombat games.")
    print("  These are NOT bundled — you must provide them yourself.")
    print()
    print("  Required:")
    for name, desc in MK_ROMS.items():
        print(f"    • {name:20s} {desc}")
    for name, desc in MK3_ROMS.items():
        if name not in MK_ROMS:
            print(f"    • {name:20s} {desc}")
    print()
    print("  Optional (enhanced features):")
    for name in ['mk3r21.zip', 'umk3.zip']:
        print(f"    • {name:20s} {MK3_ROMS[name]}")
    print()
    print("  How to set your ROM directory:")
    print(f"    1. Pass as argument:     ./run.sh /path/to/roms")
    print(f"    2. Create config file:   echo '/path/to/roms' > {CONFIG_FILE}")
    print()


def get_rom_directory(argv):
    """Resolve ROM directory from arg, config, or prompt. No GUI calls."""
    # 1. Command-line argument
    if len(argv) > 1 and argv[1]:
        p = Path(argv[1]).expanduser()
        if p.is_dir():
            return p
        print(f"  Warning: {p} is not a directory, falling through...")

    # 2. Config file
    if CONFIG_FILE.exists():
        content = CONFIG_FILE.read_text().strip()
        if content:
            p = Path(content).expanduser()
            if p.is_dir():
                return p
            print(f"  Warning: config points to {p} which doesn't exist, falling through...")

    # 3. CLI prompt (no GUI)
    print("No ROM directory set.")
    print(f"  Create a config file:  echo '/path/to/roms' > {CONFIG_FILE}")
    print()
    print("  Or enter path now:")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not raw:
        return None
    p = Path(raw).expanduser()
    # Save to config for next time
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(str(p))
        print(f"  Saved to {CONFIG_FILE}")
    except OSError:
        pass
    return p


def verify_roms(rom_dir):
    """Check which ROMs are present and show results."""
    mk = list(MK_ROMS.keys())
    mk3 = [r for r in MK3_ROMS if r not in mk]

    print(f"\nChecking ROMs in {rom_dir}...")
    found_mk, found_mk3 = [], []

    for rom in mk:
        if (rom_dir / rom).exists():
            print(f"  ✓ Found: {rom}")
            found_mk.append(rom)
        else:
            print(f"  ✗ Missing: {rom}  ({MK_ROMS[rom]})")

    print()

    for rom in mk3:
        if (rom_dir / rom).exists():
            print(f"  ✓ Found: {rom}")
            found_mk3.append(rom)
        else:
            print(f"  ✗ Missing: {rom}  ({MK3_ROMS[rom]})")

    return found_mk, found_mk3


def run_game(game, rom_dir):
    """Run a game binary with the user's ROM directory."""
    game_paths = {
        'mk1': BASE / 'mk5-native-audio',
        'mk2': BASE / 'mk2-native',
        'mk3': BASE / 'mk3',
    }
    exe = game_paths.get(game)
    if not exe or not exe.exists():
        print(f"  ✗ {game} not yet ported to Linux.")
        return False

    args = [str(exe), str(rom_dir), 'factory-seed.bin', 'gfx.txt', '--window']
    print(f"\n  → Launching {game.upper()} from {BASE}...")
    result = subprocess_run(args, cwd=BASE)
    return result.returncode == 0


def subprocess_run(args, cwd=None):
    """Thin wrapper so we can stub in tests if needed."""
    import subprocess
    return subprocess.run(args, cwd=cwd)


_rom_dir = None


def launcher_menu():
    """Menu to run MK1, MK2, or MK3. CLI-only, no GUI."""
    global _rom_dir
    print("\n" + "=" * 40)
    print("  TriUnit Recomp Launcher")
    print("=" * 40)
    print()
    print("  1.  Run MK1 (Mortal Kombat)")
    print("  2.  Run MK2 (Mortal Kombat 2)")
    print("  3.  Run MK3 (Mortal Kombat 3)")
    print("  4.  Change ROM directory")
    print("  5.  Exit")
    print()

    games = {'1': 'mk1', '2': 'mk2', '3': 'mk3'}

    while True:
        try:
            choice = input("  Select option: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if choice == '5' or not choice:
            break
        elif choice == '4':
            p = get_rom_directory([])
            if p:
                _rom_dir = p
                print(f"  ROM directory set to: {_rom_dir}")
            continue

        game = games.get(choice)
        if not game:
            print("  Invalid option")
            continue

        if not _rom_dir:
            p = get_rom_directory([])
            if not p:
                break
            _rom_dir = p

        if not Path(_rom_dir).exists():
            print(f"  Error: {_rom_dir} does not exist")
            continue

        found_mk, found_mk3 = verify_roms(Path(_rom_dir))
        if not found_mk:
            print("\n  Required ROMs missing. Please provide at least mk.zip and mk2.zip.")
            continue
        if game == 'mk3' and not found_mk3:
            print("\n  MK3 requires at least mk3.zip. Please add it to your ROM directory.")
            continue

        run_game(game, Path(_rom_dir))


def main():
    global _rom_dir
    print("=== TriUnit Recomp Linux Launcher ===\n")
    show_rom_requirements()

    _rom_dir = get_rom_directory(sys.argv)
    if not _rom_dir:
        print("\n  No ROM directory provided. Exiting.")
        return 1

    if not Path(_rom_dir).exists():
        print(f"\nError: Directory {_rom_dir} does not exist")
        return 1

    found_mk, found_mk3 = verify_roms(Path(_rom_dir))
    if not found_mk:
        print("\n  Required ROMs missing. Please provide at least mk.zip and mk2.zip.")
        return 1

    launcher_menu()
    return 0


if __name__ == '__main__':
    sys.exit(main())
