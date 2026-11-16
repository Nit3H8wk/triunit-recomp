// Real sink with a fault-injectable WinMM boundary. Actual Win32 event handles.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <mmsystem.h>
#include <iostream>
#include <stdexcept>

namespace {
int devices = 0, headers = 0, prepare_index = 0, fail_prepare = -1;
bool fail_open = false, fail_pause = false;
void need(bool value, const char* why) { if (!value) throw std::runtime_error(why); }
MMRESULT open_device(LPHWAVEOUT out, UINT_PTR, LPCWAVEFORMATEX, DWORD_PTR, DWORD_PTR, DWORD) {
    if (fail_open) return MMSYSERR_ERROR;
    *out = reinterpret_cast<HWAVEOUT>(1); ++devices; return 0;
}
MMRESULT pause_device(HWAVEOUT) { return fail_pause ? MMSYSERR_ERROR : 0; }
MMRESULT prepare(HWAVEOUT, LPWAVEHDR, UINT) {
    if (prepare_index++ == fail_prepare) return MMSYSERR_ERROR;
    ++headers; return 0;
}
MMRESULT unprepare(HWAVEOUT, LPWAVEHDR, UINT) { --headers; return 0; }
MMRESULT close_device(HWAVEOUT) { --devices; return 0; }
MMRESULT reset_device(HWAVEOUT) { return 0; }
MMRESULT write_device(HWAVEOUT, LPWAVEHDR, UINT) {
    throw std::runtime_error("lifetime fixture must not submit a full audio packet");
}
MMRESULT restart_device(HWAVEOUT) {
    throw std::runtime_error("lifetime fixture must not start playback");
}
DWORD handles() {
    DWORD count = 0;
    need(GetProcessHandleCount(GetCurrentProcess(), &count) != 0, "handle measurement");
    return count;
}
}
#define waveOutOpen open_device
#define waveOutPause pause_device
#define waveOutPrepareHeader prepare
#define waveOutUnprepareHeader unprepare
#define waveOutClose close_device
#define waveOutReset reset_device
#define waveOutWrite write_device
#define waveOutRestart restart_device
#include "../src/mk5_audio_output.cpp"

int main() {
    try {
        _putenv_s("MK1_AUDIO_LATENCY", "safe");
        { mk5audio::WaveOutSink warmup; } // Lazy OS/runtime initialization before baseline.
        const auto baseline = handles();
        unsigned checks = 0;
        for (unsigned cycle = 0; cycle < 200; ++cycle) {
            for (int failure = -3; failure < 8; ++failure) {
                prepare_index = 0; fail_open = failure == -3; fail_pause = failure == -2;
                fail_prepare = failure >= 0 ? failure : -1;
                bool threw = false;
                try {
                    mk5audio::WaveOutSink sink;
                    need(devices == 1 && headers == 8, "complete construction owns all resources");
                    // Unwinding a live sink with a buffered tail must release its resources.
                    int16_t tail[4]{}; sink.Push(tail, 4);
                    throw std::logic_error("test unwind");
                } catch (const std::logic_error&) {
                    need(failure == -1, "only successful construction reaches unwind");
                } catch (const std::runtime_error&) { threw = true; }
                need(threw == (failure != -1), "injected constructor failure reported");
                need(devices == 0 && headers == 0, "partial/full construction releases WinMM resources");
                need(handles() == baseline, "event handles return to baseline after each cycle");
                ++checks;
            }
        }
        std::cout << "PASS " << checks << " audio lifetimes: open/pause/8 prepare failures, unwind, WinMM and event handles\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "FAIL " << error.what() << '\n';
        return 1;
    }
}
