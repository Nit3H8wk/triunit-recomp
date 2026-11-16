// Research-only compatibility surface for MAME's unchanged BSD-3-Clause decoder.
// This supplies byte reads and text output; it does not execute a CPU.
#pragma once
#include <cstdint>
#include <cstdio>
#include <ostream>
#include <stdexcept>
#include <string>
#include <vector>
using u8=uint8_t;
using u16=uint16_t;
using u32=uint32_t;
using offs_t=uint32_t;
namespace util {
template<class... A> void stream_format(std::ostream& out,const char* fmt,A... args) {
    int n=std::snprintf(nullptr,0,fmt,args...);
    if(n<0) throw std::runtime_error("format failure");
    std::vector<char> buf(static_cast<size_t>(n)+1);
    std::snprintf(buf.data(),buf.size(),fmt,args...);
    out.write(buf.data(),n);
}
class disasm_interface {
public:
    static constexpr u32 SUPPORTED=0x80000000u;
    static constexpr u32 STEP_OUT=0x40000000u;
    static constexpr u32 STEP_OVER=0x20000000u;
    static constexpr u32 STEP_COND=0x10000000u;
    class data_buffer {
    public:
        virtual ~data_buffer()=default;
        virtual u16 r16(offs_t pc) const=0;
        virtual u32 r32(offs_t pc) const=0;
    };
    virtual ~disasm_interface()=default;
    virtual u32 opcode_alignment() const=0;
    virtual offs_t disassemble(std::ostream&,offs_t,const data_buffer&,const data_buffer&)=0;
};
}
