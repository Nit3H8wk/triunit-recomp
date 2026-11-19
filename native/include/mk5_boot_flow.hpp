#pragma once

// MK1 product command line: power-on, first task, main loop and the window.
namespace mk5audio {class WilliamsAudio;class HostGain;}
// The live sound board and host gain, for F5/F7 save states in the window (null: no save states).
struct Mk5StateHost {mk5audio::WilliamsAudio* audio=nullptr;mk5audio::HostGain* gain=nullptr;};
int Mk5BootFlowCli(int argc,wchar_t** argv,bool remastered=false,Mk5StateHost host={});
