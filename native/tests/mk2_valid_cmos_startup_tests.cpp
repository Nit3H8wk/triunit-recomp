#include "../mk2/mk2_valid_cmos_continuation.hpp"
#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_valid_cmos_startup.hpp"
#include "../mk2/mk2_cmos_image.hpp"
#include "../mk2/mk2_valid_cmos_draw.hpp"
#include "mk5_operator_settings.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>

int main(int argc,char** argv) {try {
    mk2::ResetTrace selectors;selectors.cmos.resize(8192);selectors.cmos[0x82f]=2;
    for(unsigned credits:{0,1,2,255}){
        selectors.cmos[0x10e]=uint16_t(0xab00|credits);
        if(mk2::OperatorStartupProfile(selectors)!=(credits?credits<2?2u:3u:0u))
            throw std::runtime_error("saved-credit selector differs from original unsigned byte/price");
    }
    selectors.cmos[0x82c]=1;
    if(mk2::OperatorStartupProfile(selectors)!=2)throw std::runtime_error("price bytes are not big endian");
    selectors.cmos[0x84b]=1;
    if(mk2::OperatorStartupProfile(selectors)!=1)throw std::runtime_error("Free Play must precede credit comparison");
    bool invalid_profile=false;try{mk2::OperatorProfileIndex(0xfc7d,4);}catch(const std::runtime_error&){invalid_profile=true;}
    if(!invalid_profile)throw std::runtime_error("unknown startup profile accepted");
    if(argc!=3 && argc!=4)throw std::runtime_error("ROM directory and seed required");
    const auto program=mk2::LoadProgram(argv[1]);const auto data=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({data.begin(),data.begin()+0x1000});
    std::ifstream stream(argv[2],std::ios::binary);
    const std::vector<uint8_t> seed{std::istreambuf_iterator<char>(stream),{}};
    auto run=[&](const std::vector<uint8_t>& image,uint16_t dsw=0xfc7d) {try {
        auto machine=std::make_unique<mk2::DcsBootMachine>(boot,data);machine->dsp.SetTraceObservation(false);
        // Generated closure from reset; the former startup and dispatcher stage ends are checked on the way.
        mk2::GeneratedBoot generated(program,*machine,&image,dsw);
        const auto& s=generated.State().ready;
        const auto profile=mk2::OperatorStartupProfile(s);
        generated.RunTo(0xff8114d0,mk2::OperatorCycle(dsw,mk2::OperatorBoundary::Irq,profile));
        if(!mk2::ValidCmosStartupBoundary(s,2))throw std::runtime_error("first RETI context differs");
        const auto irq_instructions=s.instructions;
        generated.RunTo(0xff811710,mk2::OperatorCycle(dsw,mk2::OperatorBoundary::Startup,profile));
        const auto startup_instructions=s.instructions;
        const auto& end=generated.RunToBoundary(mk2::BootEvent::admit_draw);
        const unsigned disabled=unsigned(!(dsw&0x4000))+unsigned(!(dsw&0x8000));
        if(!mk2::ValidCmosStartupBoundary(end.ready,5)||startup_instructions-irq_instructions!=1313+5*disabled||
           end.ready.instructions-startup_instructions!=mk2::OperatorDispatcherInstructions(dsw,mk2::OperatorStartupProfile(end.ready))||
           !end.bus.empty()||!end.points.empty())
            throw std::runtime_error("finite startup endpoint or observation-free instruction count differs");
        const auto draw=mk2::DeliverAs<mk2::ValidCmosContinuation>(generated);
        if(!mk2::ValidCmosDrawBoundary(draw.ready))throw std::runtime_error("operator first-draw CPU differs");
        if(draw.main_ram.at((0x01061a50-0x01000000)/16)!=unsigned(!(dsw&0x8000)) ||
           draw.main_ram.at((0x01061a60-0x01000000)/16)!=unsigned(!(dsw&0x4000)))
            throw std::runtime_error("original ROM blood/violence flags differ from physical DIP");
        auto inputs=draw.ready.board;
        inputs.SetHostInputProvider([](uint64_t){return 0xffffffffu;},draw.ready.cycles*16);
        machine->AdmitValidCmosHost(inputs);
        if(!machine->ValidCmosHostAdmitted())throw std::runtime_error("operator first draw was not admitted for real host input");
        return mk2::EncodeCmosImage(draw.ready.cmos);
    }catch(const std::exception& e){throw std::runtime_error(std::string(e.what())+"; difficulty="+std::to_string(mkoperator::ReadParameter(image,14))+" preset="+std::to_string(mkoperator::ReadParameter(image,1))+" freeplay="+std::to_string(mkoperator::ReadParameter(image,18))+" dsw="+std::to_string(dsw));}};
    if(argc==4){
        std::ifstream used_stream(argv[3],std::ios::binary);
        const std::vector<uint8_t> used{std::istreambuf_iterator<char>(used_stream),{}};
        if(Sha256(used)!="29e846cc9e1b10d02851e35251ec25e3bee91748c2468177c9c439d1d6697012")
            throw std::runtime_error("saved-credit regression CMOS identity differs");
        for(uint8_t credits:{1,2,10,99})for(uint16_t dsw:{0xfc7d,0xbc7d,0x7c7d,0x3c7d}){
            auto image=used;image[540]=credits;image[554]=uint8_t(255-credits);
            run(image,dsw);
        }
        std::cout<<"PASS exact saved-credit startup, four credit counts and four DIP combinations\n";return 0;
    }
    const auto first=run(seed),second=run(first);
    for(uint16_t dsw:{uint16_t(0xbc7d),uint16_t(0x7c7d),uint16_t(0x3c7d)})run(seed,dsw);
    for(unsigned difficulty=1;difficulty<=5;++difficulty) {
        auto adjusted=seed;adjusted.at(0x1076)=uint8_t(difficulty);
        unsigned sum=0;for(unsigned n=0;n<168;++n)sum+=adjusted.at(0x1000+2*n);
        const auto checksum=uint16_t(~sum);
        adjusted.at(0x1150)=uint8_t(checksum>>8);adjusted.at(0x1152)=uint8_t(checksum);
        const auto persisted=run(adjusted);
        if(persisted.at(0x1076)!=difficulty)throw std::runtime_error("difficulty lost in native startup");
    }
    const uint16_t switches[]={0xfc7d,0xbc7d,0x7c7d,0x3c7d};
    auto preserve=[&](const std::vector<uint8_t>& adjusted,uint16_t dsw){
        const auto persisted=run(adjusted,dsw);auto expected=adjusted;
        for(size_t n=0;n<expected.size();++n)if(first[n]!=seed[n])expected[n]=first[n];
        if(persisted!=expected)throw std::runtime_error("native operator boot changed bytes outside original guest audits");
    };
    for(unsigned preset=1;preset<=58;++preset){
        auto adjusted=seed;mkoperator::ApplyMk2Coinage(adjusted,program.bytes,preset,false);
        preserve(adjusted,switches[preset%4]);
    }
    for(auto dsw:switches){
        auto adjusted=seed;mkoperator::ApplyMk2Coinage(adjusted,program.bytes,1,true);preserve(adjusted,dsw);
    }
    auto ranking=seed;ranking.at(0x1800)^=1;mkoperator::ResetMk2HighScores(ranking,program.bytes);
    preserve(ranking,0xfc7d);
    const auto words=mk2::DecodeCmosImage(first);auto expected=words;
    if(words[0xf3]!=1)throw std::runtime_error("first real guest boot audit differs");
    expected[0xf0]=expected[0xf1]=expected[0xf2]=0;expected[0xf3]=2;expected[0xf4]=255;expected[0xf5]=253;
    if(second!=mk2::EncodeCmosImage(expected))throw std::runtime_error("second exact-image boot lost CMOS words or guest audit");
    std::cout<<"PASS: operator startup/draw/host admission, 58 pricing presets, Free Play, five difficulties, four DIP pairs, exact CMOS, guest audit 1->2 and ROM flags\n";
    return 0;
}catch(const std::exception& error){std::cerr<<error.what()<<'\n';return 1;}}
