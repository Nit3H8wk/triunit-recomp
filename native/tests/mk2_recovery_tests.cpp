#define wmain Mk2DiagnosticMain
#include "../mk2/mk2_native_check.cpp"
#include "../mk2/mk2_factory_seed.hpp"
#undef wmain

int wmain(int argc,wchar_t** argv) {
    if(argc<3 || std::wstring(argv[2])!=L"--smoke")return Mk2DiagnosticMain(argc,argv);
    try {
        const uint64_t end=argc>3 ? std::stoull(argv[3]) : 100000000;
        const bool controls=argc>4 && std::wstring(argv[4])==L"controls";
        const std::filesystem::path output=argc>5?argv[5]:L"";
        const uint64_t request=argc>6?std::stoull(argv[6]):2000000;
        if(!request || request>mk2::live_detail::kRequestCycles)
            throw std::runtime_error("Recovery request exceeds the unchanged live limit");
        const auto program=mk2::LoadProgram(argv[1]);const auto rom=mk2::LoadDcsDataRoms(argv[1]);
        const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
        auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
        machine->dsp.SetTraceObservation(false);
        mk2::Scanout scanout;uint64_t samples=0;float peak=0;
        machine->dsp.SetDacObserver([&](uint64_t,const float* pcm,size_t count){
            samples+=count;for(size_t n=0;n<count;++n)peak=std::max(peak,std::abs(pcm[n]));
        });
        machine->SetScanlineObserver([&](const auto& edge,const auto& video){scanout.Line(edge,video);});
        const auto image=[]{
            std::ifstream stream(mk2::FactorySeedPath(),std::ios::binary);
            return std::vector<uint8_t>(std::istreambuf_iterator<char>(stream),{});
        }();
        if(Sha256(image)!="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f")
            throw std::runtime_error("Recovery factory CMOS identity differs");
        mk2::GeneratedBoot generated(program,*machine,&image,0xfc7d); // generated closure from reset to delivery
        const auto draw=mk2::DeliverAs<mk2::ValidCmosContinuation>(generated);
        auto provider=[=](uint64_t tick){
            uint32_t mask=0;
            if(controls) {
                if((tick>=200000000 && tick<240000000) || (tick>=280000000 && tick<320000000))mask|=0x10000;
                if(tick>=400000000 && tick<440000000)mask|=0x40000;
                if(tick>=700000000 && tick<740000000)mask|=0x10;
            }
            return 0xffffffffu^mask;
        };
        auto current=mk2::RunValidLiveHost(program,draw,*machine,provider,std::min(end,draw.ready.cycles+request));
        const auto save_frame=[&] {
            if(output.empty())return;
            std::ofstream frame(output/"last-frame.ppm",std::ios::binary);
            frame<<"P6\n"<<scanout.width()<<' '<<scanout.height()<<"\n255\n";
            for(auto rgb:scanout.pixels()) {
                const char bytes[]={char(rgb>>16),char(rgb>>8),char(rgb)};
                frame.write(bytes,3);
            }
            if(!frame)throw std::runtime_error("Recovery small frame write failed");
        };
        while(current.State().ready.cycles<end) {
            const auto& s=current.State().ready;
            save_frame();
            std::cerr<<"progress PC="<<std::hex<<s.next_pc<<std::dec<<" cycles="<<s.cycles<<" frames="<<scanout.frames()<<'\n';
            current=mk2::ResumeValidLiveHost(program,std::move(current),*machine,std::min(end,s.cycles+request));
        }
        save_frame();
        const auto& s=current.State().ready;
        if(!output.empty()) {
            const auto words=[&](const char* name,const auto& values) {
                std::ofstream file(output/name,std::ios::binary);
                for(const auto value:values) {
                    const char bytes[]={char(value),char(value>>8)};file.write(bytes,2);
                }
                if(!file)throw std::runtime_error("Recovery state write failed");
            };
            words("cmos.bin",s.cmos);words("ram.bin",current.State().main_ram);
            words("palette.bin",current.State().video.palette_ram);
            words("vram.bin",current.State().video.vram);words("io.bin",s.board.io);
            words("dma.bin",current.State().video.DmaRegisters(s.board));
        }
        std::cout<<"{\"passed\":true,\"gameplay_qualified\":false,\"cycles\":"<<s.cycles
                 <<",\"pc\":"<<s.next_pc<<",\"frames\":"<<scanout.frames()
                 <<",\"DAC_samples\":"<<samples<<",\"DAC_peak\":"<<peak<<",\"cpu34\":["<<s.next_pc<<','<<s.status<<','<<s.cycles;
        for(auto v:s.a)std::cout<<','<<v;
        for(unsigned n=0;n<15;++n)std::cout<<','<<s.b[n];
        std::cout<<"]}\n";
        return 0;
    }catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}
}
