#pragma once
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
namespace mk5audio {
using AudioConsumer=std::function<void(const int16_t*,size_t)>;
void SetGameAudioConsumer(AudioConsumer);
enum class WaveOutPacket : unsigned { Ms10=10, Ms20=20 };
class WaveOutSink {
 struct Impl;std::unique_ptr<Impl> impl;
public:
 explicit WaveOutSink(unsigned channels=1,WaveOutPacket packet=WaveOutPacket::Ms20);~WaveOutSink();
 WaveOutSink(const WaveOutSink&)=delete;WaveOutSink& operator=(const WaveOutSink&)=delete;
 void Push(const int16_t*,size_t);void Drain();
 uint64_t Submitted()const;uint64_t Completed()const;
 uint64_t Underruns()const;
 unsigned QueueCapacityMs()const;unsigned StartupReserveMs()const;
 uint64_t MaxProducerGapMs()const;
};
}
