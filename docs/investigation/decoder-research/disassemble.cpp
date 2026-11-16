// Offline research harness, not game/runtime implementation.
#include "emu.h"
#include "34010dsm.h"
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <sstream>
#include <string_view>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

class RomBuffer final:public util::disasm_interface::data_buffer {
    std::vector<uint8_t> data;
    uint32_t base;
public:
    explicit RomBuffer(std::istream& in,uint32_t origin):base(origin) {
        data.assign(std::istreambuf_iterator<char>(in),{});
    }
    RomBuffer(const char* path,uint32_t origin):base(origin) {
        std::ifstream in(path,std::ios::binary);
        if(!in) throw std::runtime_error("cannot open input image");
        data.assign(std::istreambuf_iterator<char>(in),{});
    }
    uint16_t r16(offs_t pc)const override {
        uint64_t offset=uint32_t(pc-base)/8;
        if(pc<base || (pc&15) || offset+1>=data.size())
            throw std::out_of_range("unaligned or outside ROM read");
        return uint16_t(data[offset])|uint16_t(data[offset+1])<<8;
    }
    uint32_t r32(offs_t pc)const override {return uint32_t(r16(pc))|uint32_t(r16(pc+16))<<16;}
};

int main(int argc,char** argv) {
    try {
        const bool aligned=argc==2 && std::string_view(argv[1])=="--aligned-stdin";
        if(!aligned && argc!=5) throw std::runtime_error("usage: decoder --aligned-stdin | image base_bit_address start_bit_address instruction_count");
        std::ios::sync_with_stdio(false);
#ifdef _WIN32
        if(aligned && _setmode(_fileno(stdin),_O_BINARY)==-1) throw std::runtime_error("cannot open binary input pipe");
#endif
        uint32_t base=aligned?0xff800000u:std::stoul(argv[2],nullptr,0);
        uint32_t pc=aligned?base:std::stoul(argv[3],nullptr,0);
        size_t count=aligned?0x80000:std::stoul(argv[4],nullptr,0);
        if(count>1000000) throw std::runtime_error("instruction count exceeds research limit");
        RomBuffer data=aligned?RomBuffer(std::cin,base):RomBuffer(argv[1],base);
        tms34010_disassembler decoder(false);
        for(size_t i=0;i<count;++i) {
            std::ostringstream text;
            uint32_t result;
            try {
                result=decoder.disassemble(text,pc,data,data);
            } catch(const std::out_of_range&) {
                if(!aligned || pc<0xffffffc0u) throw;
                std::cout<<std::hex<<pc<<"\t0000\t00000000\t"<<data.r16(pc)<<"\t\n";
                pc+=16;
                continue;
            }
            const uint32_t bits=result&0xffffu;
            if(!bits || bits%16) throw std::runtime_error("invalid decoded length");
            std::cout<<std::hex<<std::setfill('0')<<std::setw(8)<<pc<<'\t'
                <<std::setw(4)<<bits<<'\t'<<std::setw(8)<<(result&0xffff0000u)<<'\t';
            for(uint32_t j=0;j<bits;j+=16) std::cout<<std::setw(4)<<data.r16(pc+j)<<' ';
            std::cout<<'\t'<<text.str()<<'\n';
            pc+=aligned?16:bits;
        }
        return 0;
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
