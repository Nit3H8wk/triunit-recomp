#include "../mk2/mk2_task_batch.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_audio.hpp"
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>

int main(int argc,char** argv) {try {
    const bool first_fight=argc==4 && std::strcmp(argv[3],"first-fight")==0;
    if(argc!=3 && !first_fight) throw std::runtime_error("expected ROM directory and exclusive transient PCM path [first-fight]");
    const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    machine->dsp.SetTraceObservation(false);
    std::vector<float> source,speaker;
    std::vector<int16_t> pcm;
    mk5audio::WilliamsResampler resampler(31250);
    mk2::DcsAudio audio([&](const int16_t* data,size_t count) {pcm.insert(pcm.end(),data,data+count);});
    machine->dsp.SetDacObserver([&](uint64_t first,const float* samples,size_t count) {
        if(first!=source.size()) throw std::runtime_error("continuation DAC gap or overlap");
        audio.Feed(first,samples,count);
        for(size_t n=0;n<count;++n) {
            source.push_back(samples[n]);resampler.Push(samples[n]);
            while(speaker.size()*31250<=uint64_t(source.size()-1)*48000)
                speaker.push_back(resampler.Sample(speaker.size()));
        }
    });
    mk2::GeneratedBoot generated(program,*machine,nullptr,0xfc7d); // generated closure from reset to delivery
    const auto& draw=generated.Deliver();
    const auto result=mk2::RunTranslatedContinuation(program,draw,*machine,
        first_fight ? int(mk2::kFirstFightWindowCount)-1 : -1);
    const auto blocks=result.ready.cycles*16/2000000;
    if(source.size()!=blocks*625+1 || speaker.size()!=blocks*960+1 || pcm.size()!=speaker.size() ||
        audio.SourceSamples()!=source.size() || audio.OutputSamples()!=speaker.size() ||
        !machine->dsp.trace.empty() || !result.cpu_trace.empty() || !result.bus.empty())
        throw std::runtime_error("continuation PCM cardinality or unobserved history differs");
    std::ofstream output(argv[2],std::ios::binary);
    output.write(reinterpret_cast<const char*>(speaker.data()),speaker.size()*sizeof(float));
    output.write(reinterpret_cast<const char*>(source.data()),source.size()*sizeof(float));
    output.write(reinterpret_cast<const char*>(pcm.data()),pcm.size()*sizeof(int16_t));
    output.close();if(!output) throw std::runtime_error("continuation PCM write/close failed");
    const auto& s=result.ready;
    std::cout<<"{\"source_samples\":"<<source.size()<<",\"speaker_samples\":"<<speaker.size()<<",\"cpu34\":["
             <<s.next_pc<<','<<s.status<<','<<s.cycles;
    for(const auto value:s.a) std::cout<<','<<value;
    for(const auto value:s.b) std::cout<<','<<value;
    std::cout<<"]}\n";
}catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;}}
