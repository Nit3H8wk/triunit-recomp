#pragma once
#include "mk5_machine.hpp"
#include "mk5_fighter_bicubic.hpp"
#include "mk5_training.hpp"
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
    // across/down: the presented frame's physical aspect (4:3; a widescreen frame is wider and shows no TV frame).
    explicit Mk5Window(bool immediate_headroom=false,unsigned across=4,unsigned down=3);~Mk5Window();
    Mk5Window(const Mk5Window&)=delete;
    Mk5Window& operator=(const Mk5Window&)=delete;
    bool Pump();
    enum class StateRequest {Save,Load};
    // F5 saves and F7 loads; the requests wait here until the game loop reaches a state boundary.
    std::vector<StateRequest> TakeStateRequests();
    BootDiInputs Inputs(BootDiInputs base)const;
    // Run-ahead (launcher CONTROLS, MK1_CONTROLS): the loop presents the frame after the current one, run speculatively.
    bool RunAhead()const;
    // Training mode (launcher CONTROLS): Present draws the input history and the boxes it is given over the image.
    bool Training()const;
    void Present(const std::vector<uint32_t>& pixels,unsigned width,unsigned height,
                 const std::vector<uint32_t>& backdrop={},
                 const mk5presentation::FighterFrame& fighters={},
                 const std::vector<mk5training::Box>& boxes={});
    void Frontier(uint32_t pc);
    uint64_t frames()const;uint64_t input_events()const;
    bool GraphicsValidationEnabled()const;
    std::string presentation_json()const;
};
