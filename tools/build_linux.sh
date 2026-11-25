#!/bin/bash
# Build all 3 TriUnit Recomp games for native Linux (x86_64)
# Requires: g++, SDL3 dev, Vulkan dev
set -e
cd "$(dirname "$0")/.."

OUT="build/native/linux-product"
mkdir -p "$OUT/bin"

echo "=== Building MK1 (mk5-native-audio) ==="
g++ -std=c++17 -O2 -Wall -Wextra -Wno-error -Wno-unused-parameter -Wno-missing-field-initializers -pthread \
  -Inative/include -Inative/audio -Igenerated \
  native/src/mk5_task_body.cpp \
  native/src/mk5_main_loop.cpp \
  native/src/mk5_live_video.cpp \
  native/src/mk5_audio.cpp \
  native/src/mk5_audio_link.cpp \
  native/audio/oki6295.cpp \
  native/audio/ymfm/ymfm_opm.cpp \
  native/src/mk5_boot_flow_cli.cpp \
  native/src/mk5_irq.cpp \
  native/src/mk5_program.cpp \
  native/src/mk5_scanout.cpp \
  native/src/mk5_window_linux.cpp \
  native/src/mk5_diagnostics.cpp \
  native/src/probe_audio_main.cpp \
  native/src/mk5_audio_output.cpp \
  native/src/mk5_remastered_music.cpp \
  native/src/linux_main_wrapper.cpp \
  -lSDL3 -lvulkan \
  -o "$OUT/bin/mk5-native-audio"

echo "=== Building MK2 (mk2-native) ==="
g++ -std=c++17 -O1 -Wall -Wextra -Wno-error -Wno-unused-parameter -Wno-missing-field-initializers -pthread \
  -Inative/include -Igenerated \
  native/mk2/mk2_task_batch.cpp \
  native/mk2/mk2_program.cpp \
  native/mk2/mk2_dcs.cpp \
  native/mk2/mk2_adsp.cpp \
  native/src/mk5_program.cpp \
  native/mk2/mk2_executor.cpp \
  native/mk2/mk2_profile.cpp \
  native/mk2/mk2_native_check.cpp \
  native/mk2/mk2_music.cpp \
  native/src/mk5_window_linux.cpp \
  native/src/mk5_audio_output.cpp \
  native/src/linux_main_wrapper.cpp \
  -lSDL3 -lvulkan \
  -o "$OUT/bin/mk2-native"

echo "=== Building MK3 (mk3) ==="
python3 tools/mk3/preview.py --frames 1 2>/dev/null || true
# MK3 is built via its own pipeline; if already built, copy it
if [ -f "build/native/mk3-native/product/mk3" ]; then
  cp build/native/mk3-native/product/mk3 "$OUT/bin/"
else
  echo "MK3: run 'python3 tools/mk3/preview.py --window' first to build, or use existing binary"
fi

# Copy supporting files
cp build/native/mk3-native/product/factory-seed.bin "$OUT/bin/" 2>/dev/null || true
cp build/native/mk3-native/product/gfx.txt "$OUT/bin/" 2>/dev/null || true
cp build/native/mk3-native/product/package.ini "$OUT/bin/" 2>/dev/null || true

# Copy launcher
cp setup_linux.py "$OUT/bin/launcher"
chmod +x "$OUT/bin/"*

echo ""
echo "=== Done ==="
ls -lh "$OUT/bin/"
echo ""
echo "Package as tarball:"
echo "  cd $OUT && tar czf TriUnitRecomp-v0.11.0-Linux-x64.tar.gz ."
