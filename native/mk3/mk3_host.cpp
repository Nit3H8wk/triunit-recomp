#include "mk3_host.hpp"
#define WIN32_LEAN_AND_MEAN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#include "mk5_gamepad.hpp"
#include "mk5_hid.hpp"
#include "mk5_window.hpp"
#include <cstdio>
#include <cwchar>
#include <filesystem>
#include <stdexcept>

namespace mk3host {
namespace {
namespace fs = std::filesystem;
HWND Window() {
    static HWND cached = nullptr;
    if (cached && IsWindow(cached)) return cached;
    cached = nullptr;
    EnumWindows([](HWND h, LPARAM out) -> BOOL {
        DWORD pid = 0;
        wchar_t name[64]{};
        GetWindowThreadProcessId(h, &pid);
        if (pid == GetCurrentProcessId() && GetClassNameW(h, name, 64) && std::wcscmp(name, L"Mk5TemporalScanout") == 0) {
            *reinterpret_cast<HWND*>(out) = h;
            return FALSE;
        }
        return TRUE;
    }, reinterpret_cast<LPARAM>(&cached));
    return cached;
}
// The shared word of Mk5KeyboardInputs / mk5pad::map (MK2 layout: IN0 in bits 0-15, MK2 IN1 in 16-31) -> Wolf-Unit ports.
Ports FromShared(uint32_t shared) {
    return {uint16_t((shared & 0x7f7f) | 0x8080),                                       // joysticks, HP, Block, HK
            uint16_t(((shared >> 28) & 3) | ((shared >> 21) & 0x30) | 0xffcc),          // P1 LP/LK, P2 LP/LK
            uint16_t(((shared >> 16) & 0x27) | 0xffd8)};                                 // coins 1-2, starts
}
struct Extra { unsigned key; bool in2; uint16_t mask; };
constexpr Extra kExtra[] = {{'T', true, 0x0008}, {VK_F2, true, 0x0010}, {'9', true, 0x0040}, {'7', true, 0x0080}, {'8', true, 0x0100},
    {VK_OEM_MINUS, true, 0x0800}, {VK_OEM_PLUS, true, 0x1000}, {VK_BACK, true, 0x8000}};

// Held actions (mk5controls) -> Wolf-Unit ports. Run is MK3's own (IN1), so it never doubles as Block here.
Ports Held(const std::array<uint32_t, 2>& held, const std::array<bool, 256>& keys) {
    Ports out = FromShared(mk5controls::shared(held[0], held[1], 0xffffffffu, false));
    if (held[0] >> mk5controls::Run & 1) out.in1 &= ~0x0004;
    if (held[1] >> mk5controls::Run & 1) out.in1 &= ~0x0040;
    for (const auto& e : kExtra) if (keys[e.key]) (e.in2 ? out.in2 : out.in1) &= uint16_t(~e.mask);
    return out;
}
uint32_t PadHeld(const mk5controls::Config& c, unsigned player, const Pad& p) {
    XINPUT_GAMEPAD g{};
    g.wButtons = p.buttons; g.bLeftTrigger = p.left_trigger; g.bRightTrigger = p.right_trigger; g.sThumbLX = p.lx; g.sThumbLY = p.ly;
    return mk5controls::from_pad(c, player, mk5pad::buttons(g), mk5pad::directions(g));
}
}

Ports Map(const std::array<bool, 256>& keys, const Pad* p1, const Pad* p2) {
    const mk5controls::Config c;   // the original layout
    std::array<uint32_t, 2> held{{mk5controls::from_keys(c, 0, keys), mk5controls::from_keys(c, 1, keys)}};
    if (p1) held[0] |= PadHeld(c, 0, *p1);
    if (p2) held[1] |= PadHeld(c, 1, *p2);
    return Held(held, keys);
}

std::string InputMapJson() {
    std::string out = "{\"keys\":[";
    char row[96];
    for (unsigned vk = 1; vk < 256; ++vk) {
        std::array<bool, 256> keys{};
        keys[vk] = true;
        const Ports p = Map(keys, nullptr, nullptr);
        if (p.in0 == 0xffff && p.in1 == 0xffff && p.in2 == 0xffff) continue;
        std::snprintf(row, sizeof row, "%s[%u,%u,%u,%u]", out.back() == '[' ? "" : ",", vk, p.in0, p.in1, p.in2);
        out += row;
    }
    struct Control { const char* name; Pad pad; };
    const Control controls[] = {{"dpad_up", {XINPUT_GAMEPAD_DPAD_UP}}, {"dpad_down", {XINPUT_GAMEPAD_DPAD_DOWN}},
        {"dpad_left", {XINPUT_GAMEPAD_DPAD_LEFT}}, {"dpad_right", {XINPUT_GAMEPAD_DPAD_RIGHT}},
        {"stick_up", {0, 0, 0, 0, 32767}}, {"stick_down", {0, 0, 0, 0, -32768}}, {"stick_left", {0, 0, 0, -32768, 0}},
        {"stick_right", {0, 0, 0, 32767, 0}}, {"a", {XINPUT_GAMEPAD_A}}, {"b", {XINPUT_GAMEPAD_B}}, {"x", {XINPUT_GAMEPAD_X}},
        {"y", {XINPUT_GAMEPAD_Y}}, {"lb", {XINPUT_GAMEPAD_LEFT_SHOULDER}}, {"rb", {XINPUT_GAMEPAD_RIGHT_SHOULDER}},
        {"lt", {0, 255, 0}}, {"rt", {0, 0, 255}}, {"back", {XINPUT_GAMEPAD_BACK}}, {"start", {XINPUT_GAMEPAD_START}},
        {"ls", {XINPUT_GAMEPAD_LEFT_THUMB}}, {"rs", {XINPUT_GAMEPAD_RIGHT_THUMB}}};
    out += "],\"pads\":[";
    const Pad idle{};
    for (unsigned player = 0; player < 2; ++player)
        for (const auto& c : controls) {
            const Ports p = player ? Map({}, &idle, &c.pad) : Map({}, &c.pad, &idle);
            std::snprintf(row, sizeof row, "%s[%u,\"%s\",%u,%u,%u]", out.back() == '[' ? "" : ",", player + 1, c.name, p.in0, p.in1, p.in2);
            out += row;
        }
    const Ports rest = Map({}, &idle, &idle);
    std::snprintf(row, sizeof row, "],\"rest\":[%u,%u,%u]}", rest.in0, rest.in1, rest.in2);
    return out + row;
}

struct Input::Impl {
    mk5pad::Devices devices; mk5pad::Ports slots; unsigned pads = 0;
    mk5controls::Config controls; std::array<mk5controls::Socd, 2> socd{};
};
Input::Input() : impl(std::make_unique<Impl>()) {
    // MK1_CONTROLS: the launcher's player controls; absent: the original layout.
    std::string text(4096, ' ');
    text.resize(GetEnvironmentVariableA("MK1_CONTROLS", text.data(), DWORD(text.size())));
    if (!text.empty() && (text.size() >= 4096 || !mk5controls::parse(text, impl->controls))) throw std::runtime_error("MK1_CONTROLS is invalid");
}
Input::~Input() = default;
unsigned Input::pads() const { return impl->pads; }
Ports Input::Poll() {
    std::array<bool, 256> keys{};
    const auto& c = impl->controls;
    std::array<uint32_t, 2> held{};
    impl->pads = 0;
    const HWND h = Window();
    if (h && GetForegroundWindow() == h) {
        for (int vk = 1; vk < 256; ++vk) keys[size_t(vk)] = (GetAsyncKeyState(vk) & 0x8000) != 0;
        held = {mk5controls::from_keys(c, 0, keys), mk5controls::from_keys(c, 1, keys)};
        impl->devices.poll();
        impl->slots.update(impl->devices.connected);
        // Players without an XInput pad take the Raw Input (HID) controllers in arrival order.
        const auto hid = mk5hid::shared().pads();
        size_t next = 0;
        for (unsigned p = 0; p < 2; ++p) {
            const int slot = impl->slots.slots[p];
            if (slot >= 0 && impl->devices.connected[unsigned(slot)]) {
                const auto& g = impl->devices.states[unsigned(slot)].Gamepad;
                held[p] |= mk5controls::from_pad(c, p, mk5pad::buttons(g), mk5pad::directions(g));
                ++impl->pads;
            } else if (next < hid.size()) {
                held[p] |= mk5controls::from_pad(c, p, hid[next].buttons, hid[next].directions);
                ++next;
                ++impl->pads;
            }
        }
    }
    for (unsigned p = 0; p < 2; ++p) held[p] = mk5controls::clean(held[p], c.socd, impl->socd[p]);
    return Held(held, keys);
}

namespace {
constexpr size_t kCmosBytes = 0xc000;
void Unlinked(const fs::path& path) {
    for (fs::path c = fs::absolute(path);; c = c.parent_path()) {
        const DWORD a = GetFileAttributesW(c.c_str());
        if (a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_REPARSE_POINT)) throw std::runtime_error("MK3 CMOS profile: linked path " + c.u8string());
        if (c == c.parent_path()) return;
    }
}
}
CmosProfile::CmosProfile(const std::wstring& directory) : dir_(fs::absolute(directory).wstring()), lock_(INVALID_HANDLE_VALUE) {
    Unlinked(dir_);
    fs::create_directories(dir_);
    Unlinked(dir_);
    // Exclusive and removed on close (also when the process dies): a second session on the same profile fails closed.
    lock_ = CreateFileW((fs::path(dir_) / L".cmos.lock").c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                        FILE_ATTRIBUTE_NORMAL | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
    if (lock_ == INVALID_HANDLE_VALUE) throw std::runtime_error("MK3 CMOS profile is in use (.cmos.lock exists)");
}
CmosProfile::~CmosProfile() { if (lock_ != INVALID_HANDLE_VALUE) CloseHandle(lock_); }
std::vector<uint8_t> CmosProfile::Load(const std::vector<uint8_t>& seed, bool& from_profile) const {
    const fs::path file = fs::path(dir_) / L"cmos.bin";
    from_profile = GetFileAttributesW(file.c_str()) != INVALID_FILE_ATTRIBUTES;
    if (!from_profile) return seed;
    Unlinked(file);
    HANDLE h = CreateFileW(file.c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, nullptr);
    std::vector<uint8_t> image(kCmosBytes + 1);
    DWORD read = 0;
    const bool ok = h != INVALID_HANDLE_VALUE && ReadFile(h, image.data(), DWORD(image.size()), &read, nullptr);
    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    if (!ok || read != kCmosBytes) throw std::runtime_error("MK3 CMOS profile image must be exactly 49152 bytes (never repaired)");
    image.resize(kCmosBytes);
    return image;
}
void CmosProfile::Save(const std::vector<uint16_t>& words) const {
    if (words.size() * 2 != kCmosBytes) throw std::runtime_error("MK3 CMOS save requires 24576 words");
    std::vector<uint8_t> image(kCmosBytes);
    for (size_t i = 0; i < words.size(); ++i) { image[2 * i] = uint8_t(words[i]); image[2 * i + 1] = uint8_t(words[i] >> 8); }
    const fs::path file = fs::path(dir_) / L"cmos.bin", pending = fs::path(dir_) / (L".cmos-pending-" + std::to_wstring(GetCurrentProcessId()));
    Unlinked(file);
    HANDLE h = CreateFileW(pending.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW, FILE_FLAG_WRITE_THROUGH, nullptr);
    DWORD written = 0;
    const bool ok = h != INVALID_HANDLE_VALUE && WriteFile(h, image.data(), DWORD(image.size()), &written, nullptr) &&
                    written == image.size() && FlushFileBuffers(h);
    if (h != INVALID_HANDLE_VALUE) CloseHandle(h);
    if (!ok || !MoveFileExW(pending.c_str(), file.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        if (h != INVALID_HANDLE_VALUE) DeleteFileW(pending.c_str());
        throw std::runtime_error("MK3 CMOS profile save failed");
    }
}

void SetTitle(const std::wstring& title) { if (HWND h = Window()) SetWindowTextW(h, title.c_str()); }

std::wstring Widen(const std::string& text) {
    const int n = MultiByteToWideChar(CP_UTF8, 0, text.data(), int(text.size()), nullptr, 0);
    std::wstring out(size_t(n > 0 ? n : 0), L'\0');
    if (n > 0) MultiByteToWideChar(CP_UTF8, 0, text.data(), int(text.size()), out.data(), n);
    return out;
}

std::string Narrow(const std::wstring& text) {
    const int n = WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), nullptr, 0, nullptr, nullptr);
    std::string out(size_t(n > 0 ? n : 0), char());
    if (n > 0) WideCharToMultiByte(CP_UTF8, 0, text.data(), int(text.size()), out.data(), n, nullptr, nullptr);
    return out;
}
}
