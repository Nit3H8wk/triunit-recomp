#pragma once
#include "mk5_machine.hpp"
#include "mk5_fighter_bicubic.hpp"
#include <array>
#include <memory>
#include <string>
#include <vector>

// Keys are Windows virtual-key codes. Unmapped ports and DSW keep the explicit
// host sample; a released key leaves its electrical input high.
BootDiInputs Mk5KeyboardInputs(const std::array<bool,256>& keys,BootDiInputs base);
class Mk5Window {
    struct Impl;std::unique_ptr<Impl> impl;
public:
    explicit Mk5Window(bool immediate_headroom=false);~Mk5Window();
    Mk5Window(const Mk5Window&)=delete;
    Mk5Window& operator=(const Mk5Window&)=delete;
    bool Pump();
    enum class StateRequest {Save,Load};
    // F5 saves and F7 loads; the requests wait here until the game loop reaches a state boundary.
    std::vector<StateRequest> TakeStateRequests();
    BootDiInputs Inputs(BootDiInputs base)const;
    void Present(const std::vector<uint32_t>& pixels,unsigned width,unsigned height,
                 const std::vector<uint32_t>& backdrop={},
                 const mk5presentation::FighterFrame& fighters={});
    void Frontier(uint32_t pc);
    uint64_t frames()const;uint64_t input_events()const;
    bool GraphicsValidationEnabled()const;
    std::string presentation_json()const;
};
