#pragma once
// platform_hal.h — OS / I/O / Input / Audio abstraction for TriUnit Recomp.
// Decouples the core TMS34010 CPU/game logic from Win32 so an SDL3 backend can
// run on Linux. On Windows these map to the existing Win32 implementations;
// on Linux they are satisfied by POSIX/SDL3 stubs (Phase 1) and real SDL3
// (Phase 2).
#include <cstdint>
#include <string>
#include <vector>
#include <filesystem>

namespace triunit::hal {

// --- Filesystem & Paths -----------------------------------------------------
// Abstract path separators and "owned" checks (symlink/junction guards).
std::string to_native_path(const std::filesystem::path& p);
bool is_symlink_or_junction(const std::filesystem::path& p);

// --- Timing -----------------------------------------------------------------
// Replace CreateWaitableTimerExW / SetWaitableTimer with a portable timer.
struct TimerHandle { int id = -1; };
TimerHandle create_timer();
void destroy_timer(TimerHandle t);
void arm_timer(TimerHandle t, int64_t ticks, int64_t frequency); // 100ns units
bool wait_timer(TimerHandle t, uint32_t timeout_ms);

// --- Process Management -----------------------------------------------------
// Replace Windows Job Objects with POSIX process groups.
struct Process { int pid = -1; };
Process spawn(const std::vector<std::string>& args, const std::filesystem::path& cwd);
void kill_process_group(Process p); // kill(-pgid, SIGKILL)
int wait_process(Process p, uint32_t timeout_ms);

// --- Input (Gamepad + HID) --------------------------------------------------
// Replace XInput (mk5_gamepad.hpp) and Raw Input (mk5_hid.hpp).
struct GamepadState { bool connected = false; uint16_t buttons = 0; float lx = 0, ly = 0, rx = 0, ry = 0; };
std::vector<GamepadState> poll_gamepads(); // SDL3 game controller API
void vibrate_gamepad(int index, uint16_t left, uint16_t right);

struct HidEvent { int device_id = 0; uint8_t type = 0; uint8_t code = 0; bool pressed = false; };
std::vector<HidEvent> poll_hid_events(); // SDL3 HIDAPI or evdev

// --- Audio Output -----------------------------------------------------------
// Replace winmm (mk5_audio_output.cpp) and XAudio2 (launcher_music.hpp).
struct AudioDevice { 
    struct Impl; Impl* impl = nullptr; 
    int id = -1; 
    ~AudioDevice() { delete impl; } 
    AudioDevice() = default; 
    AudioDevice(AudioDevice&& other) noexcept : impl(other.impl), id(other.id) { other.impl = nullptr; other.id = -1; }
    AudioDevice& operator=(AudioDevice&& other) noexcept { if (this != &other) { delete impl; impl = other.impl; id = other.id; other.impl = nullptr; other.id = -1; } return *this; }
    AudioDevice(const AudioDevice&) = delete; 
    AudioDevice& operator=(const AudioDevice&) = delete; 
};
AudioDevice open_audio_device(uint32_t sample_rate, int channels); // 48kHz mono/stereo
void submit_audio(AudioDevice d, const int16_t* pcm, size_t frames);
void close_audio(AudioDevice d);

// --- Unicode / Strings ------------------------------------------------------
// Replace -municode / wchar_t* Win32 APIs with UTF-8 internally.
std::wstring to_wide(const std::string& utf8);
std::string from_wide(const std::wstring& ws);

} // namespace triunit::hal
