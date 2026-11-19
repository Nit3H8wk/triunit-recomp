#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <filesystem>
#include <string>
#include <vector>
namespace mk2::state {struct Writer;struct Reader;}
namespace mk5audio {
struct Cpu6809State {
 uint16_t pc=0,s=0,u=0,x=0,y=0; uint8_t a=0,b=0,dp=0,cc=0x50;
 uint64_t cycles=0,instructions=0,irq_entries=0,firq_entries=0;
};
struct AudioEvent {uint64_t cycle;uint16_t pc,address;uint8_t value,bank;bool write;};
struct AudioCommand {uint64_t requested_quanta,effective_cycle;uint16_t value;};
class WilliamsAudio {
 struct Impl;std::unique_ptr<Impl> impl;
 // Save states (mk5_audio.cpp): the 6809, its RAM, the YM2151, OKI, DAC, latches, schedulers and the host
 // resamplers and music mix. ROMs and the user's tracks stay with the live object.
 friend void Fields(mk2::state::Writer&,WilliamsAudio&);
 friend void Fields(mk2::state::Reader&,WilliamsAudio&);
public:
 WilliamsAudio(std::vector<uint8_t> u3,std::vector<uint8_t> u12,std::vector<uint8_t> u13);
 ~WilliamsAudio();
 WilliamsAudio(const WilliamsAudio&)=delete;WilliamsAudio& operator=(const WilliamsAudio&)=delete;
 void AdvanceTo(uint64_t quanta10ns);
 void TmsWrite(uint64_t quanta10ns,uint16_t value);
 // Main-CPU instruction ordering. Direct board fixtures keep using TmsWrite.
 void AdvanceMainTo(uint64_t quanta10ns);
 void TmsInstructionWrite(uint64_t quanta10ns,uint16_t value);
 const Cpu6809State& Cpu()const;
 const std::array<uint8_t,8192>& Ram()const;
 const std::array<uint8_t,43>& HiddenRam()const;
 const std::vector<AudioEvent>& Events()const;
 const std::vector<AudioCommand>& Commands()const;
 const std::vector<int16_t>& Pcm()const;
 // Optional host-only output; canonical Pcm(), CPU and board events stay original.
 void EnableRemasteredMusic(const std::filesystem::path& directory);
 const std::vector<int16_t>& PresentationPcm()const;
 std::string RemasteredDiagnostics()const;
 // Empty in the Original edition; the loaded tracks' identity in the Remastered one.
 std::string MusicFingerprint()const;
 // Caller must consume/compare these diagnostic records before discarding.
 // This never resets the audio CPU, RAM, chips, clocks, bank or interrupt lines.
 void DiscardDiagnostics();
 uint8_t Bank()const;uint8_t Talkback()const;
 std::string Frontier()const;
};
}
