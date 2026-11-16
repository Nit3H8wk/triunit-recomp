#pragma once
#include "mk5_program.hpp"
#include <array>
#include <stdexcept>

namespace mkoperator {
enum class Game { Mk1, Mk2 };
inline void RequireImage(const std::vector<uint8_t>& image){
    if(image.size()!=16384)throw std::runtime_error("Operator CMOS must contain exactly 16384 bytes");
}
inline size_t ParameterOffset(const std::vector<uint8_t>& image,unsigned index,size_t base){
    RequireImage(image);
    if(index>=42 || (base&1) || base>image.size()-336)throw std::runtime_error("Operator CMOS parameter outside adjustment bank");
    return base+size_t(index)*8;
}
// The arcade stores a big-endian dword in the low bytes of four 16-bit CMOS words.
inline uint32_t ReadParameter(const std::vector<uint8_t>& image,unsigned index,size_t base=0x1000){
    const auto at=ParameterOffset(image,index,base);
    uint32_t result=0;for(unsigned i=0;i<4;++i)result=(result<<8)|image[at+i*2];return result;
}
inline void WriteParameter(std::vector<uint8_t>& image,unsigned index,uint32_t value,size_t base=0x1000){
    const auto at=ParameterOffset(image,index,base);
    for(unsigned i=0;i<4;++i)image[at+i*2]=uint8_t(value>>(24-i*8));
}
inline void UpdateSettingsChecksum(std::vector<uint8_t>& image,size_t base=0x1000,size_t count=168,size_t checksumOffset=0x1150){
    RequireImage(image);
    if(!count || (base&1) || (checksumOffset&1) || count>image.size()/2 || base>image.size()-count*2 || checksumOffset>image.size()-3)
        throw std::runtime_error("Operator CMOS checksum outside image");
    uint32_t sum=0;for(size_t i=0;i<count;++i)sum+=image[base+i*2];
    const auto checksum=uint16_t(~sum);image[checksumOffset]=uint8_t(checksum>>8);image[checksumOffset+2]=uint8_t(checksum);
}
inline bool SettingsChecksumValid(const std::vector<uint8_t>& image){
    RequireImage(image);uint32_t sum=0;for(size_t i=0;i<168;++i)sum+=image[0x1000+i*2];
    return uint16_t(~sum)==uint16_t((unsigned(image[0x1150])<<8)|image[0x1152]);
}
inline void RequireProgram(const std::vector<uint8_t>& program,Game game){
    const auto* expected=game==Game::Mk1?kMk5ProgramSha256:
        game==Game::Mk2?"45b3285496db555efaf4a3608a4f59845dd47a82e4a0593607e0592f47b36f23":nullptr;
    if(!expected || program.size()!=1048576 || Sha256(program)!=expected)
        throw std::runtime_error("Operator adjustment ROM identity differs");
}
inline uint32_t ProgramField(const std::vector<uint8_t>& program,size_t at,unsigned count){
    if(!count || count>4 || at>program.size() || count>program.size()-at)throw std::runtime_error("Operator ROM field outside program");
    uint32_t value=0;for(unsigned i=0;i<count;++i)value|=uint32_t(program[at+i])<<(i*8);return value;
}
inline size_t CoinageOffset(Game game,unsigned preset){
    if(preset<1 || preset>58)throw std::runtime_error("Operator coinage preset outside 1..58");
    return ((game==Game::Mk1?0xfffaeed0u:0xffc14c50u)-0xff800000u)/8+size_t(preset-1)*56;
}
inline std::string CoinageLabel(Game game,const std::vector<uint8_t>& program,unsigned preset){
    RequireProgram(program,game);const auto pointer=ProgramField(program,CoinageOffset(game,preset)+42,4);
    if(pointer<0xff800000u || (pointer&7))throw std::runtime_error("Operator coinage label pointer invalid");
    size_t at=(pointer-0xff800000u)/8;std::string label;
    for(unsigned i=0;i<64;++i){
        if(at>=program.size())throw std::runtime_error("Operator coinage label outside ROM");
        const auto c=program[at++];if(!c)return label;
        // The authenticated pricing labels abbreviate FRANCE with dictionary token 80h.
        if(c==0x80){label+="FRANCE";continue;}
        if(c<32 || c>126)throw std::runtime_error("Operator coinage label is not plain text");
        label+=char(c);
    }
    throw std::runtime_error("Operator coinage label exceeds limit");
}
inline void ApplyCoinage(std::vector<uint8_t>& image,const std::vector<uint8_t>& program,Game game,unsigned preset,bool freeplay){
    RequireImage(image);RequireProgram(program,game);const auto at=CoinageOffset(game,preset);
    constexpr std::array<unsigned,11> parameters{2,3,4,5,6,7,8,11,12,9,10};
    WriteParameter(image,1,preset);
    for(unsigned i=0;i<parameters.size();++i){
        const auto word=uint16_t(ProgramField(program,at+i*2,2));
        const auto signedValue=(word&0x8000)?uint32_t(word)|0xffff0000u:uint32_t(word);
        WriteParameter(image,parameters[i],signedValue);
    }
    WriteParameter(image,18,freeplay?1:0);WriteParameter(image,21,1);UpdateSettingsChecksum(image);
}
inline void ResetHighScores(std::vector<uint8_t>& image,const std::vector<uint8_t>& program,Game game){
    RequireImage(image);RequireProgram(program,game);
    const size_t table=((game==Game::Mk1?0xffdf14c0u:0xffa28730u)-0xff800000u)/8;
    // Both authenticated factory tables are already ordered by descending streak;
    // the original insertion routine preserves that order for tied streaks.
    uint32_t sum=0;
    for(unsigned record=0;record<15;++record){
        const size_t src=table+record*12,dst=0x1800+record*18;
        for(unsigned letter=0;letter<3;++letter){
            const auto value=uint8_t(ProgramField(program,src+letter*2,2)-0x41u);
            image[dst+letter*2]=value;sum+=value;
        }
        for(unsigned i=0;i<6;++i){const auto value=program[src+6+i];image[dst+6+i*2]=value;sum+=value;}
    }
    image[0x190e]=uint8_t(sum);image[0x1910]=uint8_t(sum>>8);
}
inline void ApplyMk1Coinage(std::vector<uint8_t>& image,const std::vector<uint8_t>& program,unsigned preset,bool freeplay){ApplyCoinage(image,program,Game::Mk1,preset,freeplay);}
inline void ResetMk1HighScores(std::vector<uint8_t>& image,const std::vector<uint8_t>& program){ResetHighScores(image,program,Game::Mk1);}
inline void ApplyMk2Coinage(std::vector<uint8_t>& image,const std::vector<uint8_t>& program,unsigned preset,bool freeplay){ApplyCoinage(image,program,Game::Mk2,preset,freeplay);}
inline void ResetMk2HighScores(std::vector<uint8_t>& image,const std::vector<uint8_t>& program){ResetHighScores(image,program,Game::Mk2);}
}
