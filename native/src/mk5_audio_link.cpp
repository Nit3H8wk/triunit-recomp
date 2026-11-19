#include "mk5_audio_link.hpp"
#include "mk5_audio.hpp"
#include "mk5_audio_output.hpp"
#include <stdexcept>
namespace mk5audio {
namespace {thread_local WilliamsAudio* active=nullptr;thread_local AudioConsumer consumer;thread_local size_t consumed=0;thread_local AudioDiagnosticCounts discarded;thread_local bool speculative=false;
void publish(){if(consumer && active){const auto& pcm=active->Pcm();if(pcm.size()>consumed){const auto& stereo=active->PresentationPcm();if(speculative){}else if(!stereo.empty()){if(stereo.size()!=pcm.size()*2)throw std::logic_error("presentation PCM alignment");consumer(stereo.data()+consumed*2,(pcm.size()-consumed)*2);}else consumer(pcm.data()+consumed,pcm.size()-consumed);consumed=pcm.size();}}}}
void SetGameAudioSpeculative(bool on){speculative=on;}
namespace {
void sync_active(uint64_t cycles){if(active){if(cycles>UINT64_MAX/16)throw std::overflow_error("TMS audio time");active->AdvanceMainTo(cycles*16);publish();if(!active->Frontier().empty())throw std::runtime_error("original audio frontier "+active->Frontier());}}
void write_active(uint64_t cycles,uint16_t value){if(active){if(cycles>UINT64_MAX/16)throw std::overflow_error("TMS audio time");active->TmsInstructionWrite(cycles*16,value);publish();}}
}
GameAudioScope::GameAudioScope(WilliamsAudio& a):board(&a){if(active || detail::hooks.sync || detail::hooks.write)throw std::logic_error("audio scope already bound to a live history");active=board;discarded={};detail::hooks={sync_active,write_active};}
GameAudioScope::~GameAudioScope(){if(active==board){detail::hooks={};active=nullptr;consumer={};consumed=0;}}
void SetGameAudioConsumer(AudioConsumer c){if(!active || consumer || !c)throw std::logic_error("PCM consumer requires an exclusive new audio scope");consumer=std::move(c);detail::hooks.output_clock=true;consumed=0;publish();}
AudioDiagnosticCounts GameAudioDiagnosticCounts(){if(!active)throw std::logic_error("audio diagnostics require an active scope");return {discarded.commands+active->Commands().size(),discarded.events+active->Events().size(),discarded.samples+active->Pcm().size()};}
bool TrimGameAudioDiagnostics(){
 if(!active || !consumer)return false;
 publish();
 if(consumed!=active->Pcm().size())throw std::logic_error("unpublished PCM cannot be discarded");
 if(!speculative){discarded.commands+=active->Commands().size();discarded.events+=active->Events().size();discarded.samples+=active->Pcm().size();}
 active->DiscardDiagnostics();consumed=0;return true;
}
}
