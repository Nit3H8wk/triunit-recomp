#!/usr/bin/env python3
"""Interactive Linux launcher for TriUnit Recomp — MK1, MK2, MK3."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def get_rom_directory():
    """Prompt user to select ROM directory with GUI fallback."""
    for cmd in (['zenity', '--file-selection', '--title=Select ROM Directory', '--directory'],
                ['kdialog', '--getexistingdir', '--title=Select ROM Directory']):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and result.stdout.strip():
                return Path(result.stdout.strip())
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        d = filedialog.askdirectory(title="Select ROM Directory")
        root.destroy()
        if d: return Path(d)
    except ImportError:
        pass

    print("GUI not available. Enter path to ROM directory:"); return Path(input("> ").strip())

def verify_roms(rom_dir):
    """Check which ROMs are present."""
    mk  = ['mk.zip', 'mk2.zip']
    mk3 = ['mk3.zip', 'mk3r21.zip', 'umk3.zip']
    print(f"\nChecking ROMs in {rom_dir}...")
    found = []
    for rom in mk + mk3:
        if (rom_dir / rom).exists():
            print(f"  ✓ Found: {rom}"); found.append(rom)
        else:
            print(f"  ✗ Missing: {rom}")
    return found

def run_game(game, rom_dir):
    """Run a game binary with the user's ROM directory."""
    game_paths = {
        'mk1': ROOT / 'build' / 'native' / 'mk1-native' / 'product' / 'mk5-native-audio',
        'mk2': ROOT / 'build' / 'native' / 'mk2-native' / 'product' / 'mk2-native',
        'mk3': ROOT / 'build' / 'native' / 'mk3-native' / 'product' / 'mk3',
    }
    exe = game_paths.get(game)
    if not exe or not exe.exists():
        print(f"  ✗ {game} not yet built for Linux.")
        return False

    product = exe.parent
    args = [str(exe), str(rom_dir), 'factory-seed.bin', 'gfx.txt', '--window']

    print(f"\n  → Launching {game.upper()} from {product}...")
    result = subprocess.run(args, cwd=product)
    return result.returncode == 0

_rom_dir = None

def launcher_menu():
    """Menu to run MK1, MK2, or MK3."""
    print("\n=== TriUnit Recomp Launcher ===")
    print("1. Run MK1")
    print("2. Run MK2")
    print("3. Run MK3")
    print("4. Exit")

    games = {'1': 'mk1', '2': 'mk2', '3': 'mk3'}

    while True:
        choice = input("\nSelect option: ").strip()
        if choice == '4': break
        game = games.get(choice)
        if not game:
            print("  Invalid option")
            continue

        global _rom_dir
        if not _rom_dir:
            _rom_dir = get_rom_directory()

        if not Path(_rom_dir).exists():
            print(f"  Error: {_rom_dir} does not exist")
            continue

        roms = verify_roms(Path(_rom_dir))
        if not roms:
            print("  No ROMs found. Please provide valid ROM files.")
            continue

        run_game(game, Path(_rom_dir))

def main():
    global _rom_dir
    print("=== TriUnit Recomp Linux Launcher ===\n")

    _rom_dir = get_rom_directory()
    if not Path(_rom_dir).exists():
        print(f"Error: Directory {_rom_dir} does not exist"); return 1

    roms = verify_roms(Path(_rom_dir))
    if not roms:
        print("No ROMs found. Please provide valid ROM files."); return 1

    launcher_menu()

main()
