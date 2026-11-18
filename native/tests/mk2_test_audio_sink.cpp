// Test-only silent PCM sink: every pushed frame counts as submitted and completed. No Windows audio device.
#include "mk5_audio_output.hpp"
#include <stdexcept>
namespace mk5audio {
struct WaveOutSink::Impl { unsigned channels; uint64_t frames=0; };
WaveOutSink::WaveOutSink(unsigned channels,WaveOutPacket):impl(std::make_unique<Impl>(Impl{channels})){
    if(channels!=1 && channels!=2)throw std::invalid_argument("PCM channels must be 1 or 2");
}
WaveOutSink::~WaveOutSink()=default;
void WaveOutSink::Push(const int16_t*,size_t count){
    if(count%impl->channels)throw std::invalid_argument("PCM push splits a frame");
    impl->frames+=count/impl->channels;
}
void WaveOutSink::Drain(){}
uint64_t WaveOutSink::Submitted()const{return impl->frames;}
uint64_t WaveOutSink::Completed()const{return impl->frames;}
uint64_t WaveOutSink::Underruns()const{return 0;}
unsigned WaveOutSink::QueueCapacityMs()const{return 0;}
unsigned WaveOutSink::StartupReserveMs()const{return 0;}
uint64_t WaveOutSink::MaxProducerGapMs()const{return 0;}
}
