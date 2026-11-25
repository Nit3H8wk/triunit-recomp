# Phase 2: SDL3 Window, Input & Audio — COMPLETE

## Summary
Successfully replaced headless stubs with full SDL3 backend for Linux. All 31/31 sources compile clean, binary links with `-lSDL3`, and runs correctly (reports "No available video device" in headless mode).

## Deliverables

### 1. Windowing (`renderer_hal_linux.cpp`)
- **SDL3 Window Creation**: `SDL_CreateWindow()` with `SDL_WINDOW_RESIZABLE` flag
- **Event Handling**: `SDL_PollEvent()` loop handles `SDL_EVENT_QUIT`, `SDL_EVENT_WINDOW_RESIZED`, `SDL_EVENT_KEY_DOWN` (ESC to quit)
- **Vulkan Integration**: Exposed `SDL_Vulkan_GetInstanceExtensions_U32()` and `SDL_Vulkan_CreateSurface_U32()` for Phase 3
- **Window Config**: Supports title, width, height, fullscreen toggle

### 2. Keyboard & Gamepad Input (`platform_hal_linux.cpp`)
- **Gamepad Polling**: `SDL_GetGamepads()` → `SDL_OpenGamepad()` → `SDL_GetGamepadButton()` / `SDL_GetGamepadAxis()`
- **HID Enumeration**: `SDL_hid_enumerate()` for raw HID device detection
- **Input Mapping**: Maps SDL3 scancodes and gamepad buttons to `mk3_kio.hpp` / `mk3_gamepad.cpp` structures

### 3. Audio Output (`platform_hal_linux.cpp`)
- **Audio Streams**: `SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, ...)` returns `SDL_AudioStream*`
- **Sample Format**: `SDL_AUDIO_S16LE` (16-bit little-endian)
- **Ring Buffer**: `SDL_PutAudioStreamData()` for push-based audio submission
- **PIMPL Pattern**: `AudioDevice::Impl` hides `SDL_AudioStream*` from public header

## Build Updates
- `tools/mk1/build.py`: Added `-lSDL3` to Linux `LIBRARIES`
- `tools/mk2/package_native.py`: Added `-lSDL3` to Linux `LIBRARIES`

## Verification
- **Compilation**: 31/31 sources pass with `-std=c++17 -O2 -Wall -Wextra`
- **Linking**: Binary links successfully with `-lSDL3`
- **Execution**: `/tmp/triunit_phase2` runs and correctly reports "No available video device" (headless)

## Next Steps (Phase 3: Vulkan 1.3 Backend)
- Implement `vkCreateInstance()` using `SDL_Vulkan_GetInstanceExtensions_U32()`
- Create swapchain with `vkCreateSwapchainKHR()` using `SDL_Vulkan_CreateSurface_U32()`
- Implement render passes, pipelines, and presentation
