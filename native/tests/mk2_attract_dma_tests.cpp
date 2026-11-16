#include "../mk2/mk2_executor.hpp"
#include "../mk2/mk2_valid_cmos_boot.hpp"
#include "../mk2/mk2_valid_cmos_draw.hpp"
#include "../mk2/mk2_live_limits.hpp"
#include "mk5_program.hpp"
#include <fstream>
#include <iostream>
#include <memory>

int main(int argc,char** argv) { try {
    if(argc!=3)throw std::runtime_error("Authenticated ROM directory and factory CMOS required");
    const auto program=mk2::LoadProgram(argv[1]);
    const std::array<uint8_t,4> writer={0x87,0x09,0xf8,0x02};
    if(!std::equal(writer.begin(),writer.end(),program.bytes.begin()+(0xff805240u-0xff800000u)/8))
        throw std::runtime_error("Original MMTM writer bytes differ");
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    {
        auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
        auto out=std::make_unique<mk2::BootContinuation>();
        out->ready.next_pc=0xff805240;
        mk2::BootOps o(program,*machine,*out);
        bool rejected=false;
        try { o.Write16(0x01a80010,0x9008); }
        catch(const std::runtime_error& error) {
            rejected=std::string(error.what())=="MK2 DMA start outside qualified loaded drawing context";
        }
        if(!rejected || !out->bus.empty() || machine->DmaDeadlineSubticks() ||
           machine->LastMainCycles() || out->ready.board.dma_command)
            throw std::runtime_error("Cold attract writer must reject without scheduling or video mutation");
    }
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    machine->dsp.SetTraceObservation(false);
    std::ifstream file(argv[2],std::ios::binary);
    const std::vector<uint8_t> image{std::istreambuf_iterator<char>(file),{}};
    if(Sha256(image)!="f401005e9be6b161ba3becb3cc20b8fd72359e3234652af3b5c2fbbce0d06e1f")
        throw std::runtime_error("Factory CMOS identity differs");
    mk2::GeneratedBoot generated(program,*machine,&image,0xfc7d); // generated closure from reset to delivery
    auto out=std::make_unique<mk2::ValidCmosContinuation>(mk2::DeliverAs<mk2::ValidCmosContinuation>(generated));
    auto& s=out->ready;
    s.board.SetHostInputProvider([](uint64_t){return 0xffffffffu;},s.cycles*16);
    machine->AdmitValidCmosLiveHost(s.board,mk2::live_detail::ChunkDeadline(s.cycles,s.cycles+2000000));
    if(!machine->FirstFightAdmitted())throw std::runtime_error("Real prefix did not admit the live drawing domain");
    // Synthetic component operands at the writer PC; the scheduler stays at its real admitted boundary. Kept from the
    // hardware: A7 = end of the DMA register block, A6 = unscaled steps (0x100/0x100), A12 high = command 0x9008 and the
    // field bits of ST. Synthetic: flags, palette/colour (A8), 9x7 size (A9), position (A10) and source (A11).
    s.next_pc=0xff805240;s.status=0xd0200030;
    s.a[6]=0x01000100;s.a[7]=0x01a800c0;s.a[8]=0x02c70000;
    s.a[9]=0x00070009;s.a[10]=0x003a0051;s.a[11]=0x0213c4a0;s.a[12]=0x90080000;
    constexpr unsigned pixels=9*7;
    const auto original=s.a;const auto cycle=s.cycles;const auto completions=machine->DmaCompletions();
    out->bus.clear();out->observe_history=true;
    mk2::BootOps o(program,*machine,*out);
    o.Mmtm(0x02f8,0xff805260,false,7);
    auto expected=original;expected[7]=0x01a80000;
    if(s.a!=expected || s.next_pc!=0xff805260 || s.status!=0xd0200030 ||
       s.cycles!=cycle+26 || machine->LastMainCycles()!=s.cycles || out->bus.size()!=12 ||
       machine->DmaCompletions()!=completions ||
       machine->DmaDeadlineSubticks()!=(cycle+22)*160+uint64_t(pixels)*41)
        throw std::runtime_error("Attract MMTM must start its pixel timer at the sixth write, cycle+22, not at instruction entry");
    const std::array<uint32_t,12> addresses={0x01a800a0,0x01a800b0,0x01a80080,0x01a80090,
        0x01a80060,0x01a80070,0x01a80040,0x01a80050,0x01a80020,0x01a80030,0x01a80000,0x01a80010};
    std::array<uint16_t,12> values{};
    for(unsigned n=0;n<6;++n) {
        values[2*n]=uint16_t(original[6+n+(n>0)]);values[2*n+1]=uint16_t(original[6+n+(n>0)]>>16);
    }
    for(unsigned n=0;n<12;++n) {
        const auto& lane=out->bus[n];
        if(lane.kind!='w' || lane.pc!=0xff805240 || lane.cycle!=cycle ||
           lane.address_bit!=addresses[n] || lane.value!=values[n])
            throw std::runtime_error("Attract MMTM physical DMA write order differs from Original");
    }
    for(unsigned elapsed : {26u,33u,40u}) {
        if(s.cycles!=cycle+elapsed || bool(o.Read16(0x01a80010)&0x8000)!=(elapsed<40))
            throw std::runtime_error("Attract MMTM busy polling differs from its actual write time");
        if(elapsed<40) { o.Load(s.a[6],o.ReadField(0x01a80010,0),0xff805200,5);o.Finish(0xff8051d0,2); }
    }
    if(machine->DmaCompletions()!=completions+1 || machine->DmaDeadlineSubticks())
        throw std::runtime_error("Attract MMTM delayed completion was lost");
    std::cout<<"attract DMA component: cold rejection, real live admission, 12 ordered lanes, 26 cycles, sixth-write timer and busy polling PASS\n";
    return 0;
} catch(const std::exception& error) { std::cerr<<error.what()<<'\n';return 1; } }
