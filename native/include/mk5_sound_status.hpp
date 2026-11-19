#pragma once
#include <cstdint>
// T-unit ADPCM interface from the pinned midtunit_m.cpp, not a physical
// ready/busy measurement. Each upper-word command owns 128 low status reads.
class Mk5SoundStatus {
    unsigned pending=0;
    template<class A> friend void Fields(A& a,Mk5SoundStatus& s){a(s.pending);}
public:
    void Command(){pending=128;}
    uint8_t Read(){if(pending){--pending;return 0;}return 0xff;}
};
