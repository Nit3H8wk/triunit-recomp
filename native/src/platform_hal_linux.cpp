// platform_hal_linux.cpp — SDL3 backend for Phase 2.
// Implements gamepad input, HID events, and audio output using SDL3.
#include "platform_hal.h"
#include <SDL3/SDL.h>
#include <SDL3/SDL_hidapi.h>
#include <unistd.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <signal.h>
#include <cstring>
#include <mutex>

namespace triunit::hal {

// --- Filesystem & Paths -----------------------------------------------------
std::string to_native_path(const std::filesystem::path& p) { return p.string(); }
bool is_symlink_or_junction(const std::filesystem::path& p) {
    struct stat st{};
    return lstat(p.c_str(), &st) == 0 && S_ISLNK(st.st_mode);
}

// --- Timing -----------------------------------------------------------------
TimerHandle create_timer() { return TimerHandle{0}; }
void destroy_timer(TimerHandle) {}
void arm_timer(TimerHandle, int64_t, int64_t) {}
bool wait_timer(TimerHandle, uint32_t timeout_ms) {
    if (timeout_ms) usleep(timeout_ms * 1000);
    return true;
}

// --- Process Management -----------------------------------------------------
Process spawn(const std::vector<std::string>& args, const std::filesystem::path&) {
    Process p;
    if (!args.empty()) {
        pid_t pid = fork();
        if (pid == 0) {
            setsid(); // new process group
            std::vector<const char*> argv;
            for (const auto& arg : args) argv.push_back(arg.c_str());
            argv.push_back(nullptr);
            execvp(argv[0], const_cast<char**>(argv.data()));
            _exit(127);
        } else if (pid > 0) {
            p.pid = pid;
        }
    }
    return p;
}
void kill_process_group(Process p) {
    if (p.pid > 0) kill(-p.pid, SIGKILL);
}
int wait_process(Process p, uint32_t) {
    int status = 0;
    if (p.pid > 0) waitpid(p.pid, &status, 0);
    return status;
}

// --- Input (Gamepad + HID) --------------------------------------------------
static bool sdl_initialized = false;
static std::mutex sdl_mutex;

static void ensure_sdl() {
    std::lock_guard<std::mutex> lock(sdl_mutex);
    if (!sdl_initialized) {
        SDL_Init(SDL_INIT_GAMEPAD | SDL_INIT_AUDIO);
        SDL_hid_init();
        sdl_initialized = true;
    }
}

std::vector<GamepadState> poll_gamepads() {
    ensure_sdl();
    std::vector<GamepadState> states;
    int count = 0;
    SDL_JoystickID* gamepads = SDL_GetGamepads(&count);
    if (!gamepads) return states;
    
    for (int i = 0; i < count; ++i) {
        GamepadState state;
        state.connected = true;
        
        SDL_Gamepad* gp = SDL_OpenGamepad(gamepads[i]);
        if (gp) {
            uint16_t buttons = 0;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_SOUTH)) buttons |= 0x0001; // A
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_EAST))  buttons |= 0x0002; // B
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_WEST))  buttons |= 0x0004; // X
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_NORTH)) buttons |= 0x0008; // Y
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_BACK))   buttons |= 0x0010; // LB
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_GUIDE))  buttons |= 0x0020; // Start
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_START))  buttons |= 0x0040; // RB
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_LEFT_STICK))  buttons |= 0x0100;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_RIGHT_STICK)) buttons |= 0x0200;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_DPAD_UP))    buttons |= 0x1000;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_DPAD_DOWN))  buttons |= 0x2000;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_DPAD_LEFT))  buttons |= 0x4000;
            if (SDL_GetGamepadButton(gp, SDL_GAMEPAD_BUTTON_DPAD_RIGHT)) buttons |= 0x8000;
            
            state.buttons = buttons;
            
            Sint16 lx = SDL_GetGamepadAxis(gp, SDL_GAMEPAD_AXIS_LEFTX);
            Sint16 ly = SDL_GetGamepadAxis(gp, SDL_GAMEPAD_AXIS_LEFTY);
            Sint16 rx = SDL_GetGamepadAxis(gp, SDL_GAMEPAD_AXIS_RIGHTX);
            Sint16 ry = SDL_GetGamepadAxis(gp, SDL_GAMEPAD_AXIS_RIGHTY);
            state.lx = lx / 32768.0f;
            state.ly = ly / 32768.0f;
            state.rx = rx / 32768.0f;
            state.ry = ry / 32768.0f;
            
            SDL_CloseGamepad(gp);
        }
        states.push_back(state);
    }
    SDL_free(gamepads);
    return states;
}

void vibrate_gamepad(int index, uint16_t left, uint16_t right) {
    ensure_sdl();
    int count = 0;
    SDL_JoystickID* gamepads = SDL_GetGamepads(&count);
    if (!gamepads || index < 0 || index >= count) {
        if (gamepads) SDL_free(gamepads);
        return;
    }
    SDL_Gamepad* gp = SDL_OpenGamepad(gamepads[index]);
    if (gp) {
        // SDL3 haptic API: use SDL_HapticRunEffect if available
        SDL_CloseGamepad(gp);
    }
    SDL_free(gamepads);
}

std::vector<HidEvent> poll_hid_events() {
    ensure_sdl();
    std::vector<HidEvent> events;
    SDL_hid_device_info* devs = SDL_hid_enumerate(0, 0);
    if (devs) {
        for (auto* dev = devs; dev; dev = dev->next) {
            HidEvent ev;
            ev.device_id = dev->vendor_id << 16 | dev->product_id;
            events.push_back(ev);
        }
        SDL_hid_free_enumeration(devs);
    }
    return events;
}

// --- Audio Output -----------------------------------------------------------
struct AudioDevice::Impl {
    SDL_AudioStream* stream = nullptr;
    uint32_t sample_rate = 48000;
    int channels = 1;
};

AudioDevice open_audio_device(uint32_t sample_rate, int channels) {
    ensure_sdl();
    AudioDevice dev;
    dev.impl = new AudioDevice::Impl();
    dev.impl->sample_rate = sample_rate;
    dev.impl->channels = channels;
    
    SDL_AudioSpec spec{};
    spec.freq = sample_rate;
    spec.format = SDL_AUDIO_S16LE;
    spec.channels = channels;
    
    dev.impl->stream = SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, nullptr, nullptr);
    return dev;
}

void submit_audio(AudioDevice d, const int16_t* pcm, size_t frames) {
    if (!d.impl || !d.impl->stream) return;
    SDL_PutAudioStreamData(d.impl->stream, pcm, frames * sizeof(int16_t) * d.impl->channels);
}

void close_audio(AudioDevice d) {
    if (d.impl) {
        if (d.impl->stream) SDL_DestroyAudioStream(d.impl->stream);
        delete d.impl;
        d.impl = nullptr;
    }
}

// --- Unicode / Strings ------------------------------------------------------
std::wstring to_wide(const std::string& utf8) { return std::wstring(utf8.begin(), utf8.end()); }
std::string from_wide(const std::wstring& ws) { return std::string(ws.begin(), ws.end()); }

} // namespace triunit::hal
