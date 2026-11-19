#pragma once
#include <array>
#include <cstddef>
#include <cstdint>

// Fixed MK T-unit protection stream. Device protocol/table derived from the
// authenticated docs/investigation/sources/midtunit_m.cpp, BSD-3-Clause,
// copyright Alex Pasadyn, Zsolt Vasvari, Ernesto Corvi, Aaron Giles.
// The runner owns this device for the entire live CPU/RAM continuation.
class Mk5Protection {
    inline static constexpr std::array<uint8_t,57> sequence{
        0x13,0x27,0x0f,0x1f,0x3e,0x3d,0x3b,0x37,
        0x2e,0x1c,0x38,0x31,0x22,0x05,0x0a,0x15,
        0x2b,0x16,0x2d,0x1a,0x34,0x28,0x10,0x21,
        0x03,0x06,0x0c,0x19,0x32,0x24,0x09,0x13,
        0x27,0x0f,0x1f,0x3e,0x3d,0x3b,0x37,0x2e,
        0x1c,0x38,0x31,0x22,0x05,0x0a,0x15,0x2b,
        0x16,0x2d,0x1a,0x34,0x28,0x10,0x21,0x03,0xff
    };
    size_t index=0;
    template<class A> friend void Fields(A& a,Mk5Protection& p){a(p.index);}
public:
    void Write(uint16_t data){
        const uint8_t first=uint8_t((data>>9)&63);
        index=0;
        for(size_t i=0;i<sequence.size();++i)if(sequence[i]==first){index=i;break;}
    }
    uint16_t Read(){
        if(index>=sequence.size())index=0;
        return uint16_t(uint16_t(sequence[index++])<<9);
    }
};
