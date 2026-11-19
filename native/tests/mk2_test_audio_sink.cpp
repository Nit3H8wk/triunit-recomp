// Test-only silent PCM sink: every pushed frame counts as submitted and completed. No Windows audio device.
#include "mk5_audio_output.hpp"
#include <cstdio>
#include <cstdlib>
#include <stdexcept>
namespace mk5audio {
struct WaveOutSink::Impl { unsigned channels; uint64_t frames=0,hash=0xcbf29ce484222325ull; };
WaveOutSink::WaveOutSink(unsigned channels,WaveOutPacket):impl(std::make_unique<Impl>(Impl{channels})){
    if(channels!=1 && channels!=2)throw std::invalid_argument("PCM channels must be 1 or 2");
}
WaveOutSink::~WaveOutSink()=default;
// MK2_TEST_PCM_HASHES: the FNV-1a of the PCM pushed so far, printed every 4800 frames (run-ahead tests).
void WaveOutSink::Push(const int16_t* samples,size_t count){
    if(count%impl->channels)throw std::invalid_argument("PCM push splits a frame");
    if(!std::getenv("MK2_TEST_PCM_HASHES")){impl->frames+=count/impl->channels;return;}
    for(size_t n=0;n<count;++n){
        impl->hash=(impl->hash^uint16_t(samples[n]))*0x100000001b3ull;
        if((n+1)%impl->channels==0 && ++impl->frames%4800==0)
            std::printf("{\"pcm\":\"%016llx\",\"at\":%llu}\n",(unsigned long long)impl->hash,(unsigned long long)impl->frames);
    }
}
void WaveOutSink::Drain(){}
uint64_t WaveOutSink::Submitted()const{return impl->frames;}
uint64_t WaveOutSink::Completed()const{return impl->frames;}
uint64_t WaveOutSink::Underruns()const{return 0;}
unsigned WaveOutSink::QueueCapacityMs()const{return 0;}
unsigned WaveOutSink::StartupReserveMs()const{return 0;}
uint64_t WaveOutSink::MaxProducerGapMs()const{return 0;}
}
