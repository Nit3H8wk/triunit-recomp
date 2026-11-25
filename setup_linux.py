#!/usr/bin/env python3
"""Interactive Linux launcher for TriUnit Recomp — MK1, MK2, MK3."""
import subprocess
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

# ── ROM requirements ──────────────────────────────────────────────────────

MK_ROMS = {
    'mk.zip':   'Mortal Kombat (1994) — 1MB',
    'mk2.zip':  'Mortal Kombat 2 (1994) — 1MB',
}

MK3_ROMS = {
    'mk3.zip':     'Mortal Kombat 3 (1995) — 1MB',
    'mk3r21.zip':  'Mortal Kombat 3 R2.1 — 1MB',
    'umk3.zip':    'Ultimate Mortal Kombat 3 — 1MB',
}

ALL_ROMS = {**MK_ROMS, **MK3_ROMS}

REQUIRED = ['mk.zip', 'mk2.zip', 'mk3.zip']
OPTIONAL = ['mk3r21.zip', 'umk3.zip', 'umk3.zip']


def show_rom_requirements():
    """Display what ROM files are needed and where to get them."""
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
    print("  Tips:")
    print("    • Use MAME set names: 'mk', 'mk2', 'mk3', 'mk3r21', 'umk3'")
    print("    • ROMs go in a single directory — structure doesn't matter")
    print("    • The launcher will verify which files are present")
    print()


def get_rom_directory():
    """Prompt user to select ROM directory using native file chooser."""
    # Try KDE kdialog first (best for KDE/Plasma)
    try:
        result = subprocess.run(
            ['kdialog', '--getexistingdir', '--title=Select ROM Directory'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try GNOME zenity (works on GNOME, KDE, XFCE, etc.)
    try:
        result = subprocess.run(
            ['zenity', '--file-selection', '--title=Select ROM Directory', '--directory'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try KDE Dolphin (if launched as file picker)
    try:
        result = subprocess.run(
            ['dolphin', '--select', '~'],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, 'QT_QPA_PLATFORM': 'xcb'}
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try Thunar (XFCE)
    try:
        result = subprocess.run(
            ['thunar', '--select', '~'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try PCManFM (LXDE/LXQt)
    try:
        result = subprocess.run(
            ['pcmanfm', '--desktop-profile', '--select', '~'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try Nemo (Cinnamon)
    try:
        result = subprocess.run(
            ['nemo', '--select', '~'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Try tkinter (works on most DEs with X11/Wayland)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.call('tk', 'scaling', 1.5)  # Better HiDPI support
        d = filedialog.askdirectory(title="Select ROM Directory")
        root.destroy()
        if d: return Path(d)
    except ImportError:
        pass

    # CLI fallback
    print("GUI file browser not available.")
    print("\nEnter path to ROM directory (or Ctrl+C to cancel):")
    return Path(input("> ").strip())


def verify_roms(rom_dir):
    """Check which ROMs are present and show results."""
    mk = list(MK_ROMS.keys())
    mk3 = [r for r in MK3_ROMS if r not in mk]

    print(f"\nChecking ROMs in {rom_dir}...")
    found_mk = []
    found_mk3 = []

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
        'mk1': ROOT / 'build' / 'native' / 'mk1-native' / 'product' / 'mk5-native-audio',
        'mk2': ROOT / 'build' / 'native' / 'mk2-native' / 'product' / 'mk2-native',
        'mk3': ROOT / 'build' / 'native' / 'mk3-native' / 'product' / 'mk3',
    }
    exe = game_paths.get(game)
    if not exe or not exe.exists():
        print(f"  ✗ {game} not yet ported to Linux.")
        return False

    product = exe.parent
    args = [str(exe), str(rom_dir), 'factory-seed.bin', 'gfx.txt', '--window']

    print(f"\n  → Launching {game.upper()} from {product}...")
    result = subprocess.run(args, cwd=product)
    return result.returncode == 0


_rom_dir = None


def launcher_menu():
    """Menu to run MK1, MK2, or MK3."""
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
        choice = input("  Select option: ").strip()
        if choice == '5': break
        elif choice == '4':
            _rom_dir = get_rom_directory()
            print(f"  ROM directory set to: {_rom_dir}")
            continue
        game = games.get(choice)
        if not game:
            print("  Invalid option")
            continue

        if not _rom_dir:
            _rom_dir = get_rom_directory()

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

    _rom_dir = get_rom_directory()
    if not Path(_rom_dir).exists():
        print(f"\nError: Directory {_rom_dir} does not exist")
        return 1

    found_mk, found_mk3 = verify_roms(Path(_rom_dir))
    if not found_mk:
        print("\n  Required ROMs missing. Please provide at least mk.zip and mk2.zip.")
        return 1

    launcher_menu()


main()
