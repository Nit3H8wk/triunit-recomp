#include "../mk2/mk2_executor.hpp"
#include "../audio/williams_resampler.hpp"
#include "../mk2/mk2_audio.hpp"
#include <fstream>
#include <cstring>
#include <iostream>
#include <memory>

namespace {
mk2::BootContinuation run(const mk2::Program& program,mk2::DcsBootMachine& machine) {
    mk2::GeneratedBoot generated(program,machine,nullptr,0xfc7d); // generated closure from reset to delivery
    return std::move(generated.Deliver());
}
}
int main(int argc,char** argv) {try {
    if (argc!=3) throw std::runtime_error("expected MK2 ROM directory and transient PCM path");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    auto observed=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    auto plain=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    mk5audio::WilliamsResampler resampler(31250);
    std::vector<float> source,output;
    std::vector<int16_t> pcm16;
    mk2::DcsAudio audio([&](const int16_t* data,size_t count) {pcm16.insert(pcm16.end(),data,data+count);});
    observed->dsp.SetDacObserver([&](uint64_t first,const float* samples,size_t count) {
        if (first!=source.size()) throw std::runtime_error("cold DAC timeline discontinuity");
        audio.Feed(first,samples,count);
        for (size_t n=0;n<count;++n) {
            source.push_back(samples[n]);resampler.Push(samples[n]);
            while (output.size()*31250<=uint64_t(source.size()-1)*48000)
                output.push_back(resampler.Sample(output.size()));
        }
    });
    const auto a=std::make_unique<mk2::BootContinuation>(run(program,*observed));
    const auto b=std::make_unique<mk2::BootContinuation>(run(program,*plain));
    if (a->ready.next_pc!=0xff80dd30 || a->ready.cycles!=1261260 ||
        a->ready.a!=b->ready.a || a->ready.b!=b->ready.b || a->ready.next_pc!=b->ready.next_pc ||
        a->ready.cycles!=b->ready.cycles || a->ready.status!=b->ready.status ||
        a->main_ram!=b->main_ram || a->video.vram!=b->video.vram || a->video.palette_ram!=b->video.palette_ram ||
        observed->dsp.Registers()!=plain->dsp.Registers() || observed->dsp.trace!=plain->dsp.trace ||
        observed->dsp.pm!=plain->dsp.pm || observed->dsp.dm!=plain->dsp.dm ||
        observed->dsp.external_pm!=plain->dsp.external_pm || observed->dsp.control!=plain->dsp.control ||
        observed->dsp.DeviceState()!=plain->dsp.DeviceState() || observed->dsp.sport_pcm!=plain->dsp.sport_pcm ||
        observed->dsp.sport_transfers!=plain->dsp.sport_transfers)
        throw std::runtime_error("cold observer changed CPU34, complete DSP76 trace, memory or SPORT state");
    if (output.size()<9601 || source.size()<6251 || pcm16.size()!=output.size() ||
        audio.SourceSamples()!=source.size() || audio.OutputSamples()!=output.size())
        throw std::runtime_error("cold stream did not include the complete first 200 ms");
    auto untraced=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    untraced->dsp.SetTraceObservation(false);
    mk5audio::WilliamsResampler untraced_resampler(31250);
    std::vector<float> untraced_source,untraced_output;
    std::vector<int16_t> untraced_pcm;
    mk2::DcsAudio untraced_audio([&](const int16_t* data,size_t count) {untraced_pcm.insert(untraced_pcm.end(),data,data+count);});
    untraced->dsp.SetDacObserver([&](uint64_t first,const float* samples,size_t count) {
        if (first!=untraced_source.size()) throw std::runtime_error("untraced PCM discontinuity");
        untraced_audio.Feed(first,samples,count);
        for (size_t n=0;n<count;++n) {
            untraced_source.push_back(samples[n]);untraced_resampler.Push(samples[n]);
            while (untraced_output.size()*31250<=uint64_t(untraced_source.size()-1)*48000)
                untraced_output.push_back(untraced_resampler.Sample(untraced_output.size()));
        }
    });
    const auto c=std::make_unique<mk2::BootContinuation>(run(program,*untraced));
    if (!untraced->dsp.trace.empty() || untraced->dsp.InstructionCount()!=1998125 ||
        untraced->dsp.InstructionCount()!=plain->dsp.InstructionCount() ||
        c->ready.next_pc!=b->ready.next_pc || c->ready.cycles!=b->ready.cycles || c->ready.status!=b->ready.status ||
        c->ready.instructions!=b->ready.instructions || c->ready.a!=b->ready.a || c->ready.b!=b->ready.b ||
        c->ready.board.io!=b->ready.board.io || c->ready.board.display_address!=b->ready.board.display_address ||
        c->main_ram!=b->main_ram || c->video.vram!=b->video.vram || c->video.palette_ram!=b->video.palette_ram ||
        untraced->dsp.Registers()!=plain->dsp.Registers() || untraced->dsp.DeviceState()!=plain->dsp.DeviceState() ||
        untraced->dsp.pm!=plain->dsp.pm || untraced->dsp.dm!=plain->dsp.dm ||
        untraced->dsp.external_pm!=plain->dsp.external_pm || untraced->dsp.control!=plain->dsp.control ||
        untraced->dsp.DacBuffer(2880)!=plain->dsp.DacBuffer(2880) || untraced_pcm!=pcm16 ||
        untraced_source.size()!=source.size() || untraced_output.size()!=output.size() ||
        std::memcmp(untraced_source.data(),source.data(),source.size()*sizeof(float)) ||
        std::memcmp(untraced_output.data(),output.data(),output.size()*sizeof(float)))
        throw std::runtime_error("omitting DSP register history changed CPU, DSP, memory or complete PCM");
    std::ofstream pcm(argv[2],std::ios::binary);
    pcm.write(reinterpret_cast<const char*>(output.data()),9601*sizeof(float));
    pcm.write(reinterpret_cast<const char*>(source.data()),6251*sizeof(float));
    pcm.write(reinterpret_cast<const char*>(pcm16.data()),9601*sizeof(int16_t));
    if (!pcm) throw std::runtime_error("transient PCM write failed");
    std::cout<<"{\"output_float32_samples\":9601,\"rate\":48000,\"source_samples\":"<<source.size()
             <<",\"dsp76_rows_compared\":"<<observed->dsp.trace.size()<<",\"observer_state_equal\":true,\"untraced_state_and_pcm_equal\":true,\"cpu34\":["
             <<a->ready.next_pc<<','<<a->ready.status<<','<<a->ready.cycles;
    for (const auto value:a->ready.a) std::cout<<','<<value;
    for (const auto value:a->ready.b) std::cout<<','<<value;
    std::cout<<"]}\n";
}catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}}
