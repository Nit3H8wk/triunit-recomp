# TriUnit Recomp — Linux Porting Plan (Win32/D3D12 → SDL3/Vulkan 1.3)

Static recompilation of TMS34010 arcade boards (MK1/MK2/MK3) into native C++.
This plan decouples the core game/CPU logic from Win32 and D3D12 so an
SDL3 + Vulkan 1.3 backend can run on Linux without touching the generated
game code or the hardware models.

---

## 1. Windows Header Inventory

Files that include `<windows.h>`, `<d3d12.h>`, `<dxgi*.h>`, `<xinput.h>` or
audio-related Win32 headers (`<mmsystem.h>` / XAudio2). No file includes
`<wasapi.h>` directly — audio is done via **XAudio2** and **winmm**.

### Core runtime (`native/src/`)
| File | Headers | What it uses them for |
|------|---------|----------------------|
| `native/src/mk5_window.cpp` | `<windows.h>`, `<d3d12.h>`, `<dxgi1_6.h>`, `<d3dcompiler.h>`, `<wincodec.h>`, `<wrl/client.h>` | Win32 window (`CreateWindowExW`), D3D12 device/swapchain, DXGI flip-model presentation, HDR metadata, waitable timers (`CreateWaitableTimerExW`), PNG bezel loading (WinCodec) |
| `native/src/mk5_audio_output.cpp` | `<windows.h>`, `<mmsystem.h>` | winmm audio output / timing |
| `native/src/mk5_program.cpp` | `<windows.h>` | Path/file helpers, process identity |
| `native/src/mk5_scanout.cpp` | `<windows.h>` | Timing / synchronization primitives |
| `native/src/mk5_boot_flow_cli.cpp` | `<windows.h>` | CLI boot flow, file I/O |

### Shared includes (`native/include/`)
| File | Headers | Purpose |
|------|---------|---------|
| `native/include/mk5_gamepad.hpp` | `<windows.h>`, `<xinput.h>` | XInput polling via `LoadLibraryExW("xinput1_4.dll"/"xinput9_1_0.dll")` + `XInputGetState` |
| `native/include/mk5_hid.hpp` | `<windows.h>` | Raw Input (`RegisterRawInputDevices`, `GetRawInputData`) for arcade sticks |
| `native/include/mk5_scalefx.hpp` | `<windows.h>`, `<d3d12.h>` | ScaleFX D3D12 pipeline, `D3DCompile` of embedded HLSL |

### Launcher (`native/launcher/`)
| File | Headers | Purpose |
|------|---------|---------|
| `native/launcher/launcher_main.cpp` | `<windows.h>` (via others) | Win32 window, `PlaySoundW` (winmm), XInput navigation |
| `native/launcher/launcher_renderer.hpp/.cpp` | `<windows.h>`, `<d3d12.h>`, `<dxgi1_4.h>` | D3D12 UI renderer, embedded HLSL via `D3DCompile` |
| `native/launcher/launcher_backend.hpp/.cpp` | `<windows.h>` | Process management (Job Objects), setup queue, file prefs |
| `native/launcher/launcher_music.hpp` | `<windows.h>` | **XAudio2** (`XAudio2Create`, `IXAudio2SourceVoice`) menu music |

### Game-specific (`native/mk2/`, `native/mk3/`)
| File | Headers | Purpose |
|------|---------|---------|
| `native/mk2/mk2_native_check.cpp` | `<windows.h>` | Native package check, file digests |
| `native/mk2/mk2_profile.cpp` | `<windows.h>` | CMOS profile file I/O |
| `native/mk3/mk3_host.cpp` | `<windows.h>` | MK3 host glue, paths |

### Tests (`native/tests/`) — all include `<windows.h>`
`cmos_file_tests.cpp`, `cmos_rename_retry_tests.cpp`, `mk2_profile_tests.cpp`,
`mk5_audio_lifetime_tests.cpp`, `mk5_audio_queue_contract.cpp`,
`mk5_game_volume_sink_tests.cpp`, `mk5_scalefx_window_tests.cpp`,
`mk5_stereo_output_tests.cpp`

### Tools (`tools/`)
| File | Headers | Purpose |
|------|---------|---------|
| `tools/mk1/product/presentation_contract.cpp` | `<windows.h>`, `<dxgi.h>` | Presentation contract test |

**Summary:** The Win32 surface is concentrated in **windowing, input, audio
output and file paths**. The TMS34010 CPU, ADSP-2105, 6809, CMOS and scanout
logic in `native/mk2/`, `native/mk3/` and the generated `.inc` drivers are
mostly pure C++ (they talk to the host through the `mk5_*` interfaces).

---

## 2. Build & Setup Scripts — g++ Invocation and Hardcoded Windows Paths

### Entry point
- **`TriUnit Setup.cmd`** — batch script. Finds `python`/`py -3` on PATH, runs
  `python tools\launcher\build.py --if-stale`, then `start "" "%~dp0triunit.exe"`.
  Hardcoded reference: `C:\msys64\mingw64\bin\g++.exe` (error message only).

### Compiler discovery (the single source of truth)
- **`tools/quality/run.py`**:
  - `DEFAULT_CC = Path("C:/msys64/mingw64/bin/g++.exe")`
  - `ASAN_CC = Path("C:/msys64/clang64/bin/clang++.exe")`
  - `command()` runs g++ via `subprocess.Popen` with a **Windows Job Object**
    (`ProcessJob`, `CREATE_SUSPENDED`) to own and kill descendant compiler
    processes. This is Windows-only (`ctypes.WinDLL("kernel32")`).

### Parallel build engine
- **`tools/quality/cpp_build.py`**:
  - Compiles each source separately (`g++ ... -c src.cpp -o N.o`), heaviest
    first, gated by a memory gate using `GlobalMemoryStatusEx` (`ctypes.windll`).
  - Links all objects in one final `g++` call.
  - Optional pinned **ccache** (`build/toolchain/ccache-4.14.2/ccache.exe`,
    Windows binary downloaded from GitHub).
  - `route()` only recognizes the project's simple GCC form and requires the
    output to end in `.exe`.

### Launcher build
- **`tools/launcher/build.py`**:
  - `NAME='triunit.exe'`
  - Command: `[cc, '-std=c++17','-O2','-s','-Wall','-Wextra','-Werror','-static','-municode','-mwindows', <sources>, -l<libs>..., '-Wl,--no-insert-timestamp','-o',output]`
  - Libraries: `d3d12 dxgi d3dcompiler dxguid windowscodecs ole32 uuid gdi32 user32 shell32 xinput9_1_0`

### Game builds (MK1 / MK2 / MK3)
All games are built from **generated C++** (`generated/<game>/<sha256>/`) plus
the shared host in `native/src/`.

| Game | Script | Output exe | Key flags / libs |
|------|--------|-----------|------------------|
| **MK1** | `tools/mk1/build.py` | `mk5-native-audio.exe` | `-std=c++17 -O2 -DUNICODE -D_UNICODE -Wall -Wextra -Werror -pthread -municode`; libs: `-static -lbcrypt -luser32 -lgdi32 -lwinmm -ld3d12 -ldxgi -ld3dcompiler -ldxguid -lwindowscodecs -lole32 -luuid -s -Wl,--no-insert-timestamp` |
| **MK2** | `tools/mk2/package_native.py` | `mk2-native.exe` (+ `triunit.exe`) | `-std=c++17 -O1 -Wall -Wextra -Werror -pthread -municode`; libs: `bcrypt user32 gdi32 winmm d3d12 dxgi d3dcompiler dxguid windowscodecs ole32 uuid` |
| **MK3** | `tools/mk3/preview.py` / `setup_mk3()` in `setup.py` | `mk3.exe` | FLAGS from `tools/mk3/generate.py`: `-std=c++17 -O2 -Wall -Wextra -Werror -static -municode`; libs same as MK2 |

### Setup orchestrator
- **`tools/setup/setup.py`** — 8-step pipeline: verify → stage → decoder →
  generate → accept → compile → seed → install.
  - Uses `q.DEFAULT_CC` for all compilation.
  - `VALIDATED_CC='16.1.0'`; `requirements()` checks `sys.platform=='win32'`.
  - Calls `cpp_build.build()` or `q.command([q.DEFAULT_CC, ...])` directly.

### Decoder build
- **`tools/setup/decoder.py`** — compiles the TMS34010 decoder (MAME sources)
  into `generated/tools/tms34010-decoder-<key>.exe` using `DEFAULT_CC`.

### Shared backend args
- **`tools/launcher_backend_build.py`**:
  - Returns `-I native/include -I native/mk2` + sources (`mk2_profile.cpp`,
    `mk2_program.cpp`, `launcher_operator.cpp`, `mk5_program.cpp`) + libs:
    `-lbcrypt -lwinmm -lmfreadwrite -lmfplat -lmfuuid -lxaudio2_9`

### Hardcoded Windows paths (all must become configurable / cross-platform)
| Path / Token | Where | Issue |
|--------------|-------|-------|
| `C:/msys64/mingw64/bin/g++.exe` | `tools/quality/run.py`, `tools/mk1/product/build.py`, `check*.py`, `launcher_flow_contract.py` | Hardcoded MSYS2 location |
| `C:/msys64/clang64/bin/clang++.exe` | `tools/quality/run.py` | ASan compiler |
| `C:/msys64/usr/bin/pacman.exe` | `tools/quality/setup_asan.py` | Package manager |
| `.exe` | Everywhere (`triunit.exe`, `mk5-native-audio.exe`, `mk2-native.exe`, `mk3.exe`, `ccache.exe`, decoder exes) | Windows executable suffix |
| `-municode`, `-mwindows` | All build scripts | MinGW-specific flags (Unicode entry point, GUI subsystem) |
| `-lbcrypt`, `-luser32`, `-lgdi32`, `-lwinmm`, `-ld3d12`, `-ldxgi`, `-ld3dcompiler`, `-ldxguid`, `-lwindowscodecs`, `-lole32`, `-luuid`, `-lshell32`, `-lxinput9_1_0`, `-lmfreadwrite`, `-lmfplat`, `-lmfuuid`, `-lxaudio2_9` | All build scripts | Windows-only libraries |
| `powershell.exe` | `tools/mk1/product/build.py` | Compiles `LogStore.cs` via PowerShell/Add-Type |
| `session.ps1` | `tools/mk1/product/` | PowerShell session template |
| `TriUnit Setup.cmd` | Root | Batch entry point |
| `-Wl,--no-insert-timestamp` | All builds | PE timestamp stripping (works on Linux ELF too, but different semantics) |

**Porting action:** Replace `DEFAULT_CC` with an environment variable
(`TRIUNIT_CC`) or `shutil.which("g++")`. Drop `-municode`/`-mwindows` on Linux.
Replace Windows libs with SDL3/Vulkan libs (`-lSDL3 -lvulkan`). Replace Job
Objects with POSIX process groups (`kill(-pgid)`).

---

## 3. Shader Storage, Compilation and Runtime Loading

### Storage: embedded HLSL in C++ raw string literals
Shaders are **not** separate `.hlsl` files on disk. They are `constexpr char[]`
raw strings compiled into the executable:

| File | Namespace / Symbol | Content |
|------|-------------------|---------|
| `native/include/mk5_crt_shader.hpp` | `mk5crt::shader` | CRT/scanline/BVM/CAS/bilateral pass. Uses `static const int crtMode=MK5_CRT_MODE,sample_mode=MK5_SAMPLE_MODE;` — specialized at compile time via `-D` defines |
| `native/include/mk5_scalefx_shader.hpp` | `mk5sfx::shader` | ScaleFX 5-pass edge reconstruction (adapted from libretro Cg) |
| `native/include/mk5_smaa_shader.hpp` | `mk5smaa::shader` | SMAA 1x (iryoku/smaa), with LUTs embedded as `constexpr unsigned[]` from `mk5_smaa_upstream/AreaTex.h` / `SearchTex.h` |
| `native/launcher/launcher_renderer.cpp` | local `shader` string | Launcher UI layers ("launcher_layers.hlsl") |

### Compilation: runtime `D3DCompile()` → DXIL blobs
All shaders are compiled **at runtime** (not pre-compiled to `.dxil`):

- `native/src/mk5_window.cpp`:
  - `D3DCompile(source, size, nullptr, shader_defines, nullptr, "vs", "vs_5_0", D3DCOMPILE_OPTIMIZATION_LEVEL3, ...)` for the CRT vertex shader.
  - `D3DCompile(..., "ps", "ps_5_0", ...)` for the fragment shader, with `shader_defines` injecting the active preset (`MK5_CRT_MODE`, `MK5_SAMPLE_MODE`).
- `native/include/mk5_scalefx.hpp`:
  - Compiles `vs` once, then loops `pass=0..4` compiling `ps0`..`ps4`.
- `native/include/mk5_smaa.hpp`:
  - Compiles SMAA entry points (`area`, `search`, `blending`) with explicit sampler registers.
- `native/launcher/launcher_renderer.cpp`:
  - `D3DCompile(shader, ..., "launcher_layers.hlsl", ..., entry, model, ...)` for each UI pass.

### Loading: D3D12 pipeline state
The resulting `ID3DBlob` (DXIL) is fed into `CreateGraphicsPipelineState` with a
root signature and blend/sampler descriptors. There is **no shader cache on
disk** — every launch recompiles from the embedded HLSL.

### Porting to Vulkan 1.3
- **Option A (fast):** Convert HLSL → SPIR-V at build time using `glslc` or
  DXC, store `.spv` blobs in the binary (replace `constexpr char[]` with
  `constexpr unsigned int[]` SPIR-V). Use `glslc -D MK5_CRT_MODE=N` to bake in
  the preset defines.
- **Option B (runtime):** Keep HLSL strings, compile at runtime with DXC or a
  Vulkan shader compiler library. Not recommended — adds a heavy dependency.
- **Recommended:** Pre-compile all shader variants (CRT presets × sample modes)
  to SPIR-V during the Linux build step (`tools/shaders/build_spirv.py`), and
  load them via `vkCreateShaderModule`.

---

## 4. Clean Boundary Interface: `platform_hal.h` + `renderer_hal.h`

The goal is to move every Win32/D3D12 call behind two headers so the core
TMS34010 CPU, ADSP, CMOS and game logic compile unchanged on Linux.

### `platform_hal.h` — OS / I/O / Input / Audio abstraction
Replace direct Win32 calls with these interfaces:

```cpp
// platform_hal.h
#pragma once
#include <cstdint>
#include <string>
#include <vector>
#include <filesystem>

namespace triunit::hal {

// --- Filesystem & Paths ---
// Replace std::filesystem (already portable) but abstract path separators and
// "owned" checks (symlink/junction guards in tools/setup/paths.py).
std::string to_native_path(const std::filesystem::path& p);
bool is_symlink_or_junction(const std::filesystem::path& p);

// --- Timing ---
// Replace CreateWaitableTimerExW / SetWaitableTimer (mk5_window.cpp) with a
// portable high-resolution timer.
struct TimerHandle;
TimerHandle create_timer();
void arm_timer(TimerHandle t, int64_t ticks, int64_t frequency); // 100ns units
bool wait_timer(TimerHandle t, uint32_t timeout_ms);

// --- Process Management ---
// Replace Windows Job Objects (tools/quality/run.py ProcessJob, launcher_backend)
// with POSIX process groups.
struct Process;
Process spawn(const std::vector<std::string>& args, const std::filesystem::path& cwd);
void kill_process_group(Process p); // kill(-pgid, SIGKILL)
int wait_process(Process p, uint32_t timeout_ms);

// --- Input (Gamepad + HID) ---
// Replace XInput (mk5_gamepad.hpp) and Raw Input (mk5_hid.hpp).
struct GamepadState { bool connected; uint16_t buttons; float lx, ly, rx, ry; };
std::vector<GamepadState> poll_gamepads(); // SDL3 game controller API
void vibrate_gamepad(int index, uint16_t left, uint16_t right);

struct HidEvent { int device_id; uint8_t type; uint8_t code; bool pressed; };
std::vector<HidEvent> poll_hid_events();  // SDL3 HIDAPI or evdev

// --- Audio Output ---
// Replace winmm (mk5_audio_output.cpp) and XAudio2 (launcher_music.hpp).
struct AudioDevice;
AudioDevice open_audio_device(uint32_t sample_rate, int channels); // 48kHz mono/stereo
void submit_audio(AudioDevice d, const int16_t* pcm, size_t frames);
void close_audio(AudioDevice d);

// --- Unicode / Strings ---
// Replace -municode / wchar_t* Win32 APIs with UTF-8 internally.
std::wstring to_wide(const std::string& utf8);
std::string from_wide(const std::wstring& ws);

} // namespace triunit::hal
```

### `renderer_hal.h` — Graphics / Presentation abstraction
Replace D3D12/DXGI with a Vulkan 1.3 backend:

```cpp
// renderer_hal.h
#pragma once
#include "platform_hal.h"
#include <cstdint>
#include <vector>

namespace triunit::gfx {

struct WindowConfig {
    const char* title;
    int width, height;
    bool fullscreen;
    bool vsync;
    bool vrr; // G-Sync / FreeSync
};

struct TextureConfig {
    int width, height;
    bool srgb;
    bool is_depth;
};

struct RenderPassDesc {
    const void* spirv;      // SPIR-V binary (replaces ID3DBlob DXIL)
    size_t spirv_size;
    const char* entry_point;
    int bind_count;         // number of bound textures
};

class Renderer {
public:
    static Renderer create(const WindowConfig& cfg);
    ~Renderer();

    // Surface / Swapchain
    void resize(int width, int height);
    void present(); // vkQueuePresentKHR with VRR support

    // Resources
    uint32_t create_texture(const TextureConfig& cfg);
    void destroy_texture(uint32_t tex);
    void upload_texture(uint32_t tex, const uint8_t* data, size_t size);

    // Pipeline / Shaders
    uint32_t create_pipeline(const RenderPassDesc& desc);
    void destroy_pipeline(uint32_t pipe);

    // Frame rendering
    void begin_frame();
    void bind_pipeline(uint32_t pipe);
    void bind_texture(int slot, uint32_t tex);
    void set_uniforms(const float* data, size_t floats);
    void draw_fullscreen_quad();
    void end_frame();

    // HDR / Color
    void set_hdr_metadata(float paper_white, float peak_nits);
    void set_srgb_output(bool enabled);

    // Window integration (SDL3)
    void set_window(void* sdl_window); // SDL_Window*
    bool should_close() const;
};

} // namespace triunit::gfx
```

### Migration Map: Current File → HAL Call

| Current Win32/D3D12 Usage | File | HAL Replacement |
|---------------------------|------|-----------------|
| `CreateWindowExW`, `WM_APP`, message loop | `mk5_window.cpp` | `Renderer::create(WindowConfig)` + SDL3 event pump |
| `CreateWaitableTimerExW`, `SetWaitableTimer` | `mk5_window.cpp` | `hal::create_timer()`, `hal::arm_timer()` |
| `D3DCompile` (HLSL → DXIL) | `mk5_window.cpp`, `mk5_scalefx.hpp`, `mk5_smaa.hpp` | Pre-compiled SPIR-V + `Renderer::create_pipeline()` |
| `IDXGISwapChain`, flip-model present | `mk5_window.cpp` | `Renderer::present()` (Vulkan swapchain) |
| `XInputGetState` via DLL load | `mk5_gamepad.hpp` | `hal::poll_gamepads()` (SDL3) |
| `RegisterRawInputDevices`, `GetRawInputData` | `mk5_hid.hpp` | `hal::poll_hid_events()` (SDL3 HIDAPI) |
| winmm audio (`mmsystem.h`) | `mk5_audio_output.cpp` | `hal::open_audio_device()`, `hal::submit_audio()` |
| XAudio2 (`XAudio2Create`) | `launcher_music.hpp` | Same as above |
| `PlaySoundW` | `launcher_main.cpp` | `hal::submit_audio()` or SDL3 audio |
| WinCodec PNG loading | `mk5_window.cpp` | SDL3 image loading or stb_image |
| Job Objects (process kill) | `launcher_backend.cpp`, `tools/quality/run.py` | `hal::kill_process_group()` |
| `bcrypt` SHA-256 | Multiple | OpenSSL or a pure-C++ SHA-256 (already have `q.sha` in Python; need C++ equivalent) |

### Implementation Strategy (Phased)

**Phase 1: Extract HAL interfaces**
- Create `native/include/platform_hal.h` and `native/include/renderer_hal.h`.
- Add `#ifdef _WIN32` wrappers around existing Win32 code so it still builds on Windows.

**Phase 2: Linux backend (`native/linux/`)**
- `platform_hal_linux.cpp`: Implement with SDL3, POSIX timers (`clock_nanosleep`), process groups, SDL3 audio.
- `renderer_hal_vulkan.cpp`: Implement with Vulkan 1.3 + SDL3 window surface.

**Phase 3: Replace direct calls**
- Rewrite `mk5_window.cpp` to use `Renderer` instead of D3D12.
- Rewrite `mk5_gamepad.hpp` / `mk5_hid.hpp` to use `hal::poll_*`.
- Rewrite `mk5_audio_output.cpp` to use `hal::AudioDevice`.

**Phase 4: Build system**
- Create `CMakeLists.txt` (or a portable `build_linux.sh`) that finds SDL3 and Vulkan via `pkg-config` or CMake packages.
- Replace `tools/quality/run.py` `DEFAULT_CC` with `TRIUNIT_CC` env var.
- Pre-compile shaders to SPIR-V in a build step (`glslc`).

**Phase 5: Test on Linux**
- Run `python tools/quality/run.py fast` with the Linux backend.
- Verify MK1/MK2/MK3 boot, scanout, audio and save states.

---

## Appendix: Key Files to Modify First

1. `native/src/mk5_window.cpp` — largest Win32/D3D12 surface.
2. `native/include/mk5_gamepad.hpp`, `mk5_hid.hpp` — input.
3. `native/src/mk5_audio_output.cpp` — audio.
4. `native/launcher/*` — launcher UI (can be deferred; games work standalone).
5. `tools/quality/run.py`, `cpp_build.py` — build system portability.
