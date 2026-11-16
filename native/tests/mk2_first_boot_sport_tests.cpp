#include "../mk2/mk2_adsp.hpp"
#include "../mk2/mk2_board.hpp"
#include "../mk2/mk2_dcs.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value,const char* why) { if(!value) throw std::runtime_error(why); }
template<class F> void rejected(F&& operation) {
    bool failed=false;try { operation(); } catch(const std::runtime_error&) { failed=true; }
    check(failed,"unsupported first-boot context accepted");
}
void configure(mk2::AdspBoot& dsp) {
    dsp.pc=0x8a;dsp.imask=0x24;dsp.mstat=0x10;dsp.control[31]=0xc10;dsp.control[15]=0xe82;
    dsp.i[7]=0x3800;dsp.l[7]=480;dsp.m[5]=1;dsp.main_horizon_=6607529;
    for(unsigned n=0;n<480;++n) dsp.dm[n]=uint16_t(n*257u);
    for(auto& value:dsp.external_pm) value=0xabcdef;
    dsp.SportTransmit(0);
}
}
int main(int argc,char** argv) { try {
    // The IRQ1 vector guard compares PM 0x10 with the user's U2 (argv[1]); the boot page supplies it.
    check(argc==2,"expected the authenticated U2 ROM path");
    const auto u2=mk2::LoadDcsRom(argv[1]);
    const std::vector<uint32_t> image=mk2::DecodeDcsBoot({u2.begin(),u2.begin()+0x1000});
    mk2::DcsLink link;mk2::AdspBoot dsp(image,link,u2);configure(dsp);
    check(dsp.sport_enabled&&dsp.sport_base==0x3800&&dsp.i[7]==0x3800,"first-boot SPORT start");
    dsp.SportTransfer(25807840);
    check(dsp.sport_pcm.size()==240&&dsp.i[7]==0x38f0&&!dsp.sport_irq1_asserted,"first half DMA");
    dsp.SportTransfer(26575840);
    check(dsp.sport_pcm.size()==480&&dsp.i[7]==0x3800&&dsp.sport_irq1_asserted&&dsp.sport_irq1_latched,"wrapped DMA IRQ1 pulse");
    for(unsigned n=0;n<480;++n) check(dsp.sport_pcm[n]==int16_t(uint16_t(n*257u)),"first boot DMA must read internal DM");
    check(dsp.accesses.empty(),"device DMA must not invent CPU memory lanes");
    dsp.pc_sp=2;dsp.loop_sp=2;dsp.cntr_sp=2;dsp.sstat=0x10;dsp.astat=0xa5;
    dsp.EnterIrq1();
    check(dsp.pc==0x10&&dsp.imask==0&&dsp.pc_sp==3&&dsp.stat_sp==1&&!dsp.sport_irq1_latched&&dsp.sport_irq1_asserted,"IRQ1 vector/status/latch");
    dsp.ClearSportIrq1(26575850);
    check(!dsp.sport_irq1_asserted&&!dsp.sport_irq1_latched,"accepted IRQ1 pulse clears after ten ticks");
    dsp.ReturnIrq();
    check(dsp.pc==0x8a&&dsp.imask==0x24&&dsp.mstat==0x10&&dsp.astat==0xa5&&dsp.pc_sp==2&&dsp.stat_sp==0&&dsp.loop_sp==2&&dsp.cntr_sp==2,"IRQ1 return preserves active loop stacks");
    for(unsigned n=2;n<63;++n) {
        dsp.SportTransfer(25807840+uint64_t(n)*768000);
        if(dsp.sport_irq1_asserted) {dsp.EnterIrq1();dsp.ClearSportIrq1(25807850+uint64_t(n)*768000);dsp.ReturnIrq();}
    }
    check(dsp.sport_transfers.size()==63,"first boot transfers within measured horizon");
    {
        mk2::DcsLink other;mk2::AdspBoot unsupported(image,other,u2);configure(unsupported);
        unsupported.pm[0x10]^=1;unsupported.sport_irq1_asserted=unsupported.sport_irq1_latched=true;
        const auto before=unsupported.Registers();rejected([&]{unsupported.EnterIrq1();});
        check(unsupported.Registers()==before,"changed IRQ vector must reject before register mutation");
        unsupported.pm[0x10]^=1;unsupported.icntl=2;rejected([&]{unsupported.EnterIrq1();});
    }
    {
        mk2::DcsBootMachine machine(image);mk2::BoardBootControls board;
        rejected([&]{machine.AdmitValidCmosDelay(board);});
        check(machine.main_horizon_==3658091&&machine.dsp.main_horizon_==3658091&&board.main_horizon_==3658091,"invalid delay admission must not widen horizons");
        machine.last_main_=311971;machine.scanline_events_=board.scanline_events=775;
        board.input_events.push_back({0,0,0,0});rejected([&]{machine.AdmitValidCmosDelay(board);});
        check(machine.main_horizon_==3658091,"scripted input invalidates clean delay admission");
        board.input_events.clear();machine.AdmitValidCmosDelay(board);
        check(machine.main_horizon_==6607529&&machine.dsp.main_horizon_==6607529&&board.main_horizon_==6607529,"all clean-delay horizons must advance together");
        check(machine.LastMainCycles()==311971&&machine.ScanlineEvents()==775,"delay admission cannot advance guest clocks");
        rejected([&]{machine.AdmitValidCmosDelay(board);});
    }
    std::cout<<"PASS: first-boot DM SPORT, IRQ1 pulse/vector/return and unsupported contexts\n";
    return 0;
} catch(const std::exception& error) {std::cerr<<error.what()<<'\n';return 1;} }
