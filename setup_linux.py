#!/usr/bin/env python3
"""TriUnit Recomp Linux launcher — MK1, MK2, MK3.

Works inside Recomplauncher (no TTY: tkinter game menu, ROM path from arg)
and standalone (kdialog/zenity/tkinter for ROM folder, CLI or tkinter menu).
"""
import os
import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.resolve()
CONFIG_DIR = Path.home() / '.config' / 'triunit-recomp'
CONFIG_FILE = CONFIG_DIR / 'roms.path'

ALL_ROMS = {
    'mk.zip':     'Mortal Kombat (1994)',
    'mk2.zip':    'Mortal Kombat 2 (1994)',
    'mk3.zip':    'Mortal Kombat 3 (1995)',
    'mk3r21.zip': 'Mortal Kombat 3 R2.1',
    'umk3.zip':   'Ultimate Mortal Kombat 3',
}

GAME_INFO = {
    'mk1': {'label': 'Mortal Kombat (1994)', 'exe': 'mk5-native-audio', 'roms': ['mk.zip']},
    'mk2': {'label': 'Mortal Kombat 2 (1994)', 'exe': 'mk2-native', 'roms': ['mk2.zip']},
    'mk3': {'label': 'Mortal Kombat 3 (1995)', 'exe': 'mk3', 'roms': ['mk3.zip']},
}


def show_rom_requirements():
    print("\n" + "=" * 60)
    print("  ROM FILES REQUIRED")
    print("=" * 60)
    print()
    print("  You need MAME-style ROM files for Mortal Kombat games.")
    print("  These are NOT bundled — you must provide them yourself.")
    print()
    print("  Required:")
    for name, desc in ALL_ROMS.items():
        print(f"    • {name:20s} {desc}")
    print()


def get_rom_directory_gui():
    """Open a native file browser to pick the ROM directory."""
    # KDE (kdialog — native KDE directory picker)
    try:
        result = subprocess.run(
            ['kdialog', '--getexistingdirectory', str(Path.home()),
             '--title', 'Select ROM Directory'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            p = Path(result.stdout.strip())
            if p.is_dir():
                return p
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # GNOME (zenity)
    try:
        result = subprocess.run(
            ['zenity', '--file-selection', '--directory',
             '--title=Select ROM Directory'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0 and result.stdout.strip():
            p = Path(result.stdout.strip())
            if p.is_dir():
                return p
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # tkinter (universal fallback)
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        p = filedialog.askdirectory(title='Select ROM Directory')
        root.destroy()
        if p:
            return Path(p)
    except Exception:
        pass

    return None


def get_rom_directory(argv):
    """Resolve ROM directory: arg > config > native GUI > CLI prompt."""
    # 1. Command-line argument (Recomplauncher passes {input:roms})
    if len(argv) > 1 and argv[1]:
        p = Path(argv[1]).expanduser()
        if p.is_dir():
            return p
        print(f"  Warning: {p} is not a directory")

    # 2. Config file
    if CONFIG_FILE.exists():
        content = CONFIG_FILE.read_text().strip()
        if content:
            p = Path(content).expanduser()
            if p.is_dir():
                return p

    # 3. Native GUI file browser (KDE kdialog, GNOME zenity, tkinter)
    p = get_rom_directory_gui()
    if p:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(str(p))
        except OSError:
            pass
        return p

    # 4. CLI prompt (only if we have a TTY)
    if sys.stdin.isatty():
        print("No ROM directory set.")
        print(f"  Create a config file:  echo '/path/to/roms' > {CONFIG_FILE}")
        print()
        raw = input("> ").strip()
        if raw:
            p = Path(raw).expanduser()
            try:
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                CONFIG_FILE.write_text(str(p))
            except OSError:
                pass
            return p

    return None


def verify_roms(rom_dir):
    """Check which ROMs are present (top-level or in game subfolders)."""
    print(f"\n  Checking ROMs in {rom_dir}:")
    found = {}
    for game_id, info in GAME_INFO.items():
        # Check top-level and game-specific subfolder
        search_dirs = [rom_dir, rom_dir / game_id]
        missing = []
        resolved_dir = None
        for rom in info['roms']:
            found_path = None
            for d in search_dirs:
                if (d / rom).exists():
                    found_path = d / rom
                    if resolved_dir is None:
                        resolved_dir = d
                    break
            if found_path:
                print(f"    ✓ {rom}")
            else:
                print(f"    ✗ Missing: {rom}  ({ALL_ROMS.get(rom, '')})")
                missing.append(rom)
        found[game_id] = (len(missing) == 0, resolved_dir or rom_dir)
    return found


def run_game(game, rom_dir):
    """Run a game binary with the correct arguments for each game."""
    info = GAME_INFO[game]
    exe = BASE / info['exe']
    if not exe.exists():
        msg = f"{info['exe']} not found — {game.upper()} not yet ported to Linux."
        print(f"  ✗ {msg}")
        log(msg)
        show_error(msg)
        return False

    # Each game has different argument formats:
    # MK1: mk5-native-audio --roms /path/to/roms
    # MK2: mk2-native /path/to/roms --window
    # MK3: mk3 /path/to/roms factory-seed.bin gfx.txt --window
    if game == 'mk1':
        args = [str(exe), '--roms', str(rom_dir)]
    elif game == 'mk2':
        args = [str(exe), str(rom_dir), '--window']
    else:  # mk3
        args = [str(exe), str(rom_dir), 'factory-seed.bin', 'gfx.txt', '--window']

    log(f"Launching {game}: {' '.join(args)}")
    print(f"\n  → Launching {info['label']}...")

    try:
        result = subprocess.run(args, cwd=BASE, capture_output=True, text=True)
        log(f"  exit={result.returncode}")
        if result.stdout:
            log(f"  stdout: {result.stdout[:500]}")
        if result.stderr:
            log(f"  stderr: {result.stderr[:500]}")

        if result.returncode != 0:
            err = (result.stderr or result.stdout or '').strip() or f'exit code {result.returncode}'
            show_error(f"{info['label']} failed:\n\n{err}\n\nROM dir: {rom_dir}")
            return False
    except Exception as e:
        log(f"  exception: {e}")
        show_error(f"Failed to launch {info['label']}:\n{e}")
        return False

    return True


def show_error(msg):
    """Show an error dialog (tkinter) — visible even in Recomplauncher."""
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showerror("TriUnit Recomp", msg)
        root.destroy()
    except Exception:
        pass  # Last resort: just print (might be invisible)


def game_menu_tkinter(rom_dir, rom_status):
    """tkinter game selection — works without TTY (Recomplauncher)."""
    import tkinter as tk

    root = tk.Tk()
    root.title("TriUnit Recomp — Select Game")
    root.geometry("440x340")
    root.resizable(False, False)

    tk.Label(root, text="TriUnit Recomp", font=("Arial", 16, "bold")).pack(pady=(20, 5))
    tk.Label(root, text=f"ROMs: {rom_dir}", font=("Arial", 9), fg="gray").pack()
    tk.Frame(root, height=10).pack()

    selected = None
    selected_rom_dir = None

    def choose(game_id):
        nonlocal selected, selected_rom_dir
        selected = game_id
        _, selected_rom_dir = rom_status.get(game_id, (False, rom_dir))
        root.destroy()

    for game_id, info in GAME_INFO.items():
        available, resolved_rom_dir = rom_status.get(game_id, (False, rom_dir))
        status = "ready" if available else "no ROM"
        btn_text = f"{info['label']}  [{status}]"
        btn = tk.Button(
            root, text=btn_text, font=("Arial", 11), width=38,
            state="normal" if available else "disabled",
            command=lambda g=game_id: choose(g)
        )
        btn.pack(pady=5, padx=20)

    tk.Button(root, text="Cancel", font=("Arial", 10), command=root.destroy).pack(pady=(15, 5))
    root.mainloop()
    return selected, selected_rom_dir


def game_menu_cli(rom_dir, rom_status):
    """CLI game menu — for standalone terminal use."""
    print("\n" + "=" * 40)
    print("  TriUnit Recomp Launcher")
    print("=" * 40)
    print()
    print("  1.  Mortal Kombat (1994)")
    print("  2.  Mortal Kombat 2 (1994)")
    print("  3.  Mortal Kombat 3 (1995)")
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
                rom_dir = p
                print(f"  ROM directory: {rom_dir}")
                rom_status = verify_roms(rom_dir)
            continue

        game = games.get(choice)
        if not game:
            print("  Invalid option")
            continue
        run_game(game, rom_dir)


def log(msg):
    """Write to a visible log file (stdout is invisible in Recomplauncher)."""
    try:
        log_file = BASE / 'launcher.log'
        with open(log_file, 'a') as f:
            from datetime import datetime
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except OSError:
        pass


def main():
    print("=== TriUnit Recomp Linux Launcher ===\n")
    log(f"argv={sys.argv}")
    show_rom_requirements()

    rom_dir = get_rom_directory(sys.argv)
    if not rom_dir:
        print("\n  No ROM directory available. Exiting.")
        print(f"  Set it with: echo '/path/to/roms' > {CONFIG_FILE}")
        return 1

    print(f"\n  ROM directory: {rom_dir}")
    log(f"rom_dir={rom_dir}")
    rom_status = verify_roms(rom_dir)
    for g, (ok, d) in rom_status.items():
        log(f"  {g}: ready={ok} dir={d}")

    if not any(v[0] for v in rom_status.values()):
        print("\n  No supported ROMs found. Exiting.")
        return 1

    # tkinter menu when no TTY (Recomplauncher), CLI menu in terminal
    if sys.stdin.isatty():
        game_menu_cli(rom_dir, rom_status)
    else:
        selected, resolved_rom_dir = game_menu_tkinter(rom_dir, rom_status)
        if selected:
            run_game(selected, resolved_rom_dir or rom_dir)

    return 0


if __name__ == '__main__':
    sys.exit(main())
