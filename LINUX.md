# TriUnit Recomp — Linux Setup Guide

## Requirements

### Arch Linux
```bash
sudo pacman -S sdl3 vulkan-devel shaderc python g++
```

### Ubuntu/Debian
```bash
sudo apt update
sudo apt install libsdl3-dev libvulkan-dev shaderc python3 g++
```

## Quick Start

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd triunit-recomp
   ```

2. **Run the interactive setup**
   ```bash
   python3 setup_linux.py
   ```
   
   The script will:
   - Prompt you to select your ROM directory (with GUI folder dialog if available)
   - Verify which ROMs are present (`mk.zip`, `mk2.zip`, `mk3.zip`/`mk3r21.zip`)
   - Run the asset generator to build `.inc` files locally
   - Compile SPIR-V shaders
   - Build the native Linux binaries into `bin/`

3. **Launch a game**
   
   The setup script provides a launcher menu. Alternatively, run the binaries directly:
   ```bash
   ./bin/mk1
   ./bin/mk2
   ./bin/mk3
   ```

## Manual Build (Advanced)

If you prefer to build manually:

```bash
# Generate assets from ROMs
python3 tools/mk3/generate.py

# Compile shaders
bash build/shaders/compile_spirv.sh

# Build binaries
python3 tools/mk1/build.py
python3 tools/mk2/package_native.py
python3 tools/mk3/generate.py
```

## Troubleshooting

### "No available video device"
This error occurs in headless environments. Ensure you have a display server running (X11 or Wayland).

### "Failed to create Vulkan instance"
Verify that Vulkan drivers are installed:
```bash
vulkaninfo --summary
```

### ROM Authentication Failed
Ensure your ROMs match the expected revisions:
- MK1: `mk.zip` (any recent revision)
- MK2: `mk2.zip` (any recent revision)  
- MK3: `mk3r21.zip` (**revision 21 required**)

**Note**: MAME 0.289 non-merged sets contain r10 ROMs, which are NOT compatible with the generator. You need actual r21 ROMs for MK3.

## Notes

- **No Emulator**: This is a static recompilation, not an emulator. The game logic is compiled directly to native code.
- **ROMs Required**: You must provide your own legally obtained ROM files. They are not included in the repository.
- **Generated Files**: All `.inc` files and `.spv` shaders are generated locally and excluded from version control via `.gitignore`.
