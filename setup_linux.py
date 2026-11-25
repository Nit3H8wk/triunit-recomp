#!/usr/bin/env python3
"""Interactive Linux setup and launcher for TriUnit Recomp."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def get_rom_directory():
    """Prompt user to select ROM directory with GUI fallback."""
    # Try zenity first
    try:
        result = subprocess.run(
            ['zenity', '--file-selection', '--title=Select ROM Directory', '--directory'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Try kdialog
    try:
        result = subprocess.run(
            ['kdialog', '--getexistingdir', '--title=Select ROM Directory'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    
    # Try tkinter
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        dir_path = filedialog.askdirectory(title="Select ROM Directory")
        root.destroy()
        if dir_path:
            return Path(dir_path)
    except ImportError:
        pass
    
    # CLI fallback
    print("GUI not available. Enter path to ROM directory:")
    return Path(input("> ").strip())

def verify_roms(rom_dir):
    """Check which ROMs are present."""
    required = ['mk.zip', 'mk2.zip']
    optional = ['mk3.zip', 'mk3r21.zip', 'umk3.zip']
    
    print(f"\nChecking ROMs in {rom_dir}...")
    found = []
    for rom in required + optional:
        if (rom_dir / rom).exists():
            print(f"  ✓ Found: {rom}")
            found.append(rom)
        else:
            print(f"  ✗ Missing: {rom}")
    
    return found

def run_generator():
    """Run the asset generator to build .inc files."""
    print("\nRunning asset generator...")
    result = subprocess.run([sys.executable, str(ROOT / 'tools/mk3/generate.py')], cwd=ROOT)
    return result.returncode == 0

def compile_shaders():
    """Compile SPIR-V shaders."""
    print("\nCompiling shaders...")
    result = subprocess.run(['bash', str(ROOT / 'build/shaders/compile_spirv.sh')], cwd=ROOT)
    return result.returncode == 0

def build_binaries():
    """Build the native Linux binaries."""
    print("\nBuilding binaries...")
    for game in ['mk1', 'mk2', 'mk3']:
        script = ROOT / f'tools/{game}/build.py' if game != 'mk3' else ROOT / 'tools/mk3/generate.py'
        if script.exists():
            result = subprocess.run([sys.executable, str(script)], cwd=ROOT)
            if result.returncode == 0:
                print(f"  ✓ Built {game}")
            else:
                print(f"  ✗ Failed to build {game}")
    return True

def launcher_menu():
    """Simple menu to run built games."""
    while True:
        print("\n=== TriUnit Recomp Launcher ===")
        print("1. Run MK1")
        print("2. Run MK2")
        print("3. Run MK3")
        print("4. Exit")
        
        choice = input("Select option: ").strip()
        
        if choice == '1':
            subprocess.run([str(ROOT / 'bin/mk1')], cwd=ROOT)
        elif choice == '2':
            subprocess.run([str(ROOT / 'bin/mk2')], cwd=ROOT)
        elif choice == '3':
            subprocess.run([str(ROOT / 'bin/mk3')], cwd=ROOT)
        elif choice == '4':
            break
        else:
            print("Invalid option")

def main():
    print("=== TriUnit Recomp Linux Setup ===\n")
    
    # Step 1: Get ROM directory
    rom_dir = get_rom_directory()
    if not rom_dir.exists():
        print(f"Error: Directory {rom_dir} does not exist")
        return 1
    
    # Step 2: Verify ROMs
    roms = verify_roms(rom_dir)
    if not roms:
        print("No ROMs found. Please provide valid ROM files.")
        return 1
    
    # Step 3: Run generator
    if not run_generator():
        print("Asset generation failed")
        return 1
    
    # Step 4: Compile shaders
    if not compile_shaders():
        print("Shader compilation failed")
        return 1
    
    # Step 5: Build binaries
    build_binaries()
    
    # Step 6: Launch menu
    launcher_menu()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
