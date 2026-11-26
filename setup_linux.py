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


def prepare_roms(rom_dir, rom_status):
    """Extract and rename ROM files from MAME zips to what each binary expects.
    
    MK1 needs: <roms>/mk1/mks-u3.rom, mks-u12.rom, mks-u13.rom (256KB each)
    MK2 needs: <roms>/su2.l1 through su7.l1 (512KB each) + u2.l1
    MK3 needs: MAME-named files directly (l1_mortal_kombat_3_u*.u*)
    
    Returns dict of game -> prepared directory path.
    """
    import zipfile
    prep_dir = rom_dir / '.triunit-prep'
    result = {}

    # --- MK1: extract ALL files from mk.zip (binary scans for 512KB program ROMs by SHA1) ---
    mk1_dir = prep_dir / 'mk1'
    mk1_dir.mkdir(parents=True, exist_ok=True)
    mk1_zip = rom_dir / 'mk.zip'
    if not mk1_zip.exists():
        mk1_zip = rom_dir / 'mk1' / 'mk.zip'
    if mk1_zip.exists():
        try:
            with zipfile.ZipFile(mk1_zip) as z:
                for name in z.namelist():
                    if not name.startswith('TORRENTZIPPED'):
                        (mk1_dir / name).write_bytes(z.read(name))
            # Also create the expected short names for audio ROMs
            audio_map = {
                'sl1_mortal_kombat_u3_sound_rom.u3': 'mks-u3.rom',
                'sl1_mortal_kombat_u12_sound_rom.u12': 'mks-u12.rom',
                'sl1_mortal_kombat_u13_sound_rom.u13': 'mks-u13.rom',
            }
            with zipfile.ZipFile(mk1_zip) as z:
                for src, dst in audio_map.items():
                    if src in z.namelist() and not (mk1_dir / dst).exists():
                        (mk1_dir / dst).write_bytes(z.read(src))
            log(f"  MK1: extracted {len(list(mk1_dir.iterdir()))} files from mk.zip")
            # Binary reads <roms>/mk1/mks-u*.rom and recursively scans <roms> for
            # 512 KiB program lanes — so the --roms root must be the PARENT of mk1/.
            result['mk1'] = prep_dir
        except Exception as e:
            log(f"  MK1 extract error: {e}")

    # --- MK2: extract program + graphics ROMs from mk2.zip ---
    mk2_dir = prep_dir / 'mk2'
    mk2_dir.mkdir(parents=True, exist_ok=True)
    mk2_zip = rom_dir / 'mk2.zip'
    if not mk2_zip.exists():
        mk2_zip = rom_dir / 'mk2' / 'mk2.zip'
    if mk2_zip.exists():
        # MK2 L3.1 expects specific short names:
        # Program: uj12.l31, ug12.l31 (512KB)
        # Graphics: ug14-vid, uj14-vid, etc. (1MB each)
        # DCS data: su2.l1 through su7.l1 (512KB each)
        mk2_mapping = {
            'l3.1_mortal_kombat_ii_game_rom_ug12.ug12': 'ug12.l31',
            'l3.1_mortal_kombat_ii_game_rom_uj12.uj12': 'uj12.l31',
            'l1_mortal_kombat_ii_game_rom_ug14.ug14': 'ug14-vid',
            'l1_mortal_kombat_ii_game_rom_uj14.uj14': 'uj14-vid',
            'l1_mortal_kombat_ii_game_rom_ug16.ug16': 'ug16-vid',
            'l1_mortal_kombat_ii_game_rom_uj16.uj16': 'uj16-vid',
            'l1_mortal_kombat_ii_game_rom_ug17.ug17': 'ug17-vid',
            'l1_mortal_kombat_ii_game_rom_uj17.uj17': 'uj17-vid',
            'l1_mortal_kombat_ii_game_rom_ug19.ug19': 'ug19-vid',
            'l1_mortal_kombat_ii_game_rom_uj19.uj19': 'uj19-vid',
            'l1_mortal_kombat_ii_game_rom_ug20.ug20': 'ug20-vid',
            'l1_mortal_kombat_ii_game_rom_uj20.uj20': 'uj20-vid',
            'l1_mortal_kombat_ii_game_rom_ug22.ug22': 'ug22-vid',
            'l1_mortal_kombat_ii_game_rom_uj22.uj22': 'uj22-vid',
        }
        # DCS data ROMs (su2-su7)
        for n in range(2, 8):
            mk2_mapping[f'l1_mortal_kombat_ii_sound_rom_u{n}.u{n}'] = f'su{n}.l1'
        
        try:
            with zipfile.ZipFile(mk2_zip) as z:
                names = set(z.namelist())
                for src, dst in mk2_mapping.items():
                    if src in names:
                        (mk2_dir / dst).write_bytes(z.read(src))
                log(f"  MK2: extracted {len(list(mk2_dir.iterdir()))} files from mk2.zip")
            result['mk2'] = mk2_dir
        except Exception as e:
            log(f"  MK2 extract error: {e}")

    # --- MK3: extract all files (already MAME-named) ---
    mk3_dir = prep_dir / 'mk3'
    mk3_dir.mkdir(parents=True, exist_ok=True)
    mk3_zip = rom_dir / 'mk3.zip'
    if not mk3_zip.exists():
        mk3_zip = rom_dir / 'mk3' / 'mk3.zip'
    if not mk3_zip.exists():
        # Try mk3r10, mk3r21, umk3 as fallbacks
        for alt in ['mk3r10.zip', 'mk3r21.zip', 'umk3.zip']:
            if (rom_dir / alt).exists():
                mk3_zip = rom_dir / alt
                break
    if mk3_zip.exists():
        try:
            with zipfile.ZipFile(mk3_zip) as z:
                for name in z.namelist():
                    if not name.startswith('TORRENTZIPPED'):
                        data = z.read(name)
                        (mk3_dir / name).write_bytes(data)
            log(f"  MK3: extracted {mk3_zip.name} -> mk3/ ({len(list(mk3_dir.iterdir()))} files)")
            result['mk3'] = mk3_dir
            # gfx.txt uses CWD-relative paths (roms/mk3/<file>). Regenerate it with
            # absolute paths into the prepared dir so the launcher's CWD doesn't matter.
            gfx_src = BASE / 'gfx.txt'
            if gfx_src.exists():
                lines = []
                for line in gfx_src.read_text().splitlines():
                    parts = line.split()
                    if len(parts) == 3 and parts[2].startswith('roms/mk3/'):
                        abs_path = mk3_dir / parts[2][len('roms/mk3/'):]
                        lines.append(f"{parts[0]} {parts[1]} {abs_path}")
                    elif line.strip():
                        lines.append(line)
                (prep_dir / 'gfx-abs.txt').write_text('\n'.join(lines) + '\n')
                log("  MK3: generated gfx-abs.txt (absolute paths)")
        except Exception as e:
            log(f"  MK3 extract error: {e}")

    return result


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
    # MK1: mk5-native-audio --roms <root> + visual-stage boot-flow args
    #      (cabinet snapshot: all inputs released, DSW 0xFEFF, product IRQ/raster epoch)
    # MK2: mk2-native /path/to/roms --window
    # MK3: mk3 /path/to/roms factory-seed.bin gfx.txt --window
    if game == 'mk1':
        args = [str(exe), '--roms', str(rom_dir),
                '--stage', 'visual',
                '--irq-pending', '0x400',
                '--raster-next-line', '1',
                '--raster-quanta', '6325',
                '--body-sound-status-byte', '128',
                '--dsw-word', '65279',
                '--boot-dsw-word', '65279',
                '--task-dsw-word', '65279',
                '--body-dsw-word', '65279',
                '--main-dsw-word', '65279',
                '--irq-in01', '0xffffffff',
                '--irq-in2-dsw', '4278190079',
                '--body-irq-in01', '0xffffffff',
                '--body-irq-in2-dsw', '4278190079',
                '--active-irq-in01', '0xffffffff',
                '--active-irq-in2-dsw', '4278190079']
    elif game == 'mk2':
        args = [str(exe), str(rom_dir), '--window']
    else:  # mk3
        # mk3 /path/to/roms /abs/factory-seed.bin /abs/gfx.txt --window
        # Absolute paths only: the binary opens these relative to its CWD, and
        # Recomplauncher's environment must not be able to break that.
        gfx_list = rom_dir.parent / 'gfx-abs.txt' if (rom_dir.parent / 'gfx-abs.txt').exists() else BASE / 'gfx.txt'
        seed = BASE / 'factory-seed.bin'
        args = [str(exe), str(rom_dir), str(seed), str(gfx_list), '--window']

    log(f"Launching {game}: {' '.join(args)}")
    print(f"\n  → Launching {info['label']}...")

    # Pre-flight: data files the game opens by path must exist before launch.
    if game == 'mk3':
        for f in (args[2], args[3]):
            if not Path(f).exists():
                log(f"  WARNING: missing expected MK3 file: {f}")

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

    # Prepare ROM files (extract from zips, rename to what binaries expect)
    print("\n  Preparing ROM files...")
    prep = prepare_roms(rom_dir, rom_status)
    for g, d in prep.items():
        print(f"  ✓ {g.upper()} ROMs ready")

    # tkinter menu when no TTY (Recomplauncher), CLI menu in terminal
    if sys.stdin.isatty():
        game_menu_cli(rom_dir, rom_status)
    else:
        selected, resolved_rom_dir = game_menu_tkinter(rom_dir, rom_status)
        if selected:
            # Use prepared ROM directory if available
            game_rom_dir = prep.get(selected, resolved_rom_dir or rom_dir)
            run_game(selected, game_rom_dir)

    return 0


if __name__ == '__main__':
    sys.exit(main())
