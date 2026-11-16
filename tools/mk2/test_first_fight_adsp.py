"""Execute newly observed DSP division, absolute value and S-condition words."""
import os,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as quality


class FirstFightAdspTests(unittest.TestCase):
    def test_new_trap_site_preserves_vector_stack_lanes_and_rejects_other_scopes(self):
        source=r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <iostream>
#include <memory>
int main() {try {
    for(uint32_t pc:{0xff8044f0u,0xff804940u,0xff805470u}) {
        mk2::Program program;program.bytes.resize(0x100000);
        program.bytes[0xffff8]=0xd0;program.bytes[0xffff9]=0x45;
        program.bytes[0xffffa]=0x80;program.bytes[0xffffb]=0xff;
        auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        machine->link.HostWrite(0x01d01020,0);machine->link.Synchronize();
        auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);auto& s=out->ready;
        machine->main_horizon_=machine->dsp.main_horizon_=s.board.main_horizon_=
            pc==0xff8044f0?5077311:pc==0xff804940?100091930:118028828;
        s.next_pc=pc;s.a[15]=0x010000c0;s.status=0x30;s.board.io[8]=0x2000;
        mk2::BootOps o(program,*machine,*out);o.TrapOne(0xff8045d0,pc+16);
        if(s.next_pc!=0xff8045d0 || s.status!=0x10 || s.a[15]!=0x01000080 ||
           s.cycles!=16 || s.instructions!=1 || out->bus.size()!=6) return 1;
        const std::array<uint32_t,6> addresses{0x010000a0,0x010000b0,0x01000080,0x01000090,0xffffffc0,0xffffffd0};
        const std::array<uint16_t,6> values{uint16_t(pc+16),0xff80,0x30,0,0x45d0,0xff80};
        for(unsigned n=0;n<6;++n) {
            const auto& row=out->bus[n];
            if(row.pc!=pc || row.address_bit!=addresses[n] || row.value!=values[n] ||
               row.cycle || row.kind!=(n<4?'w':'r')) return 2;
        }
    }
    for(unsigned which=0;which<6;++which) {
        mk2::Program program;program.bytes.resize(0x100000);
        program.bytes[0xffff8]=0xd0;program.bytes[0xffff9]=0x45;
        program.bytes[0xffffa]=0x80;program.bytes[0xffffb]=0xff;
        auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        auto out=std::make_unique<mk2::BootContinuation>();out->main_ram.resize(262144);auto& s=out->ready;
        machine->main_horizon_=machine->dsp.main_horizon_=s.board.main_horizon_=which==0?6087360:100091930;
        s.next_pc=which==1?0xff804930:0xff804940;s.a[15]=which==4?0x01000030:0x010000c0;s.status=0x30;
        if(which==5)program.bytes[0xffff8]^=1;
        mk2::BootOps o(program,*machine,*out);const auto before=out->main_ram;const auto sp=s.a[15];
        bool rejected=false;try{o.TrapOne(which==2?0xff804950:0xff8045d0,which==3?0xff804960:0xff804950);}
        catch(const std::runtime_error&){rejected=true;}
        if(!rejected || out->main_ram!=before || !out->bus.empty() || s.a[15]!=sp || s.status!=0x30 || s.cycles) return 3;
    }
}catch(const std::exception& error){std::cerr<<error.what();return 99;}}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'trap.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'trap.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),cpp,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_first_fight_dma_accepts_authenticated_writers_only_in_its_admitted_scope(self):
        # Catches the stale single-writer guard without broadening earlier endpoints.
        source=r'''
#include "native/mk2/mk2_boot_ops.hpp"
#include <iostream>
#include <memory>
int main() {try {
    for(uint64_t horizon:{100091930ull,101005964ull,104090574ull,110030700ull,118028828ull,126026668ull,134024907ull,150023965ull})
    for(uint16_t command:{0xe588,0xe088,0xe188,0xe792})
    for(uint32_t pc:{0xff801590u,0xff801600u,0xff804630u}) {
        mk2::Program program;program.graphics.resize(0xc00000);
        auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        auto out=std::make_unique<mk2::BootContinuation>();auto& s=out->ready;
        machine->main_horizon_=machine->dsp.main_horizon_=s.board.main_horizon_=horizon;
        machine->last_main_=s.cycles=86875706;s.next_pc=pc;
        s.board.io[18]=2;out->video.dma_registers[6]=2;out->video.dma_registers[7]=3;
        out->video.dma_registers[13]=511;out->video.dma_registers[17]=511;
        mk2::BootOps o(program,*machine,*out);o.Write16(0x01a80010,command);
        if(s.board.dma_command!=command || (s.board.io[18]&2) ||
           machine->DmaDeadlineSubticks()!=86875706ull*160+6*41 || !o.dma_line_event_ ||
           out->bus.size()!=1 || out->bus[0].pc!=pc || out->bus[0].value!=command ||
           out->bus[0].address_bit!=0x01a80010 || out->bus[0].cycle!=86875706 ||
           out->bus[0].kind!='w') return 1;
    }
    for(const auto& item:std::array<std::array<uint64_t,3>,5>{{
            {100091930,0xff801580,86875706},{30060282,0xff801590,86875706},
            {5077311,0xff801600,4000000},{3658091,0xff801590,1259252},
            {100091930,0xff801590,86875707}}}) {
        mk2::Program program;program.graphics.resize(0xc00000);
        auto machine=std::make_unique<mk2::DcsBootMachine>(std::vector<uint32_t>(376));
        auto out=std::make_unique<mk2::BootContinuation>();auto& s=out->ready;
        machine->main_horizon_=machine->dsp.main_horizon_=s.board.main_horizon_=item[0];
        s.next_pc=uint32_t(item[1]);s.cycles=item[2];machine->last_main_=item[2]-(item[2]==86875707);
        s.board.io[18]=2;const auto before=out->video.vram;
        mk2::BootOps o(program,*machine,*out);bool rejected=false;
        try{o.Write16(0x01a80010,0xe588);}catch(const std::runtime_error&){rejected=true;}
        if(!rejected || s.board.dma_command || s.board.io[18]!=2 ||
           machine->DmaDeadlineSubticks() || out->video.vram!=before || !out->bus.empty()) return 2;
    }
}catch(const std::exception& error){std::cerr<<error.what();return 99;}}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'writers.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'writers.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),cpp,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_fight_dm_pointer_and_register_arithmetic_shift_execute_real_words(self):
        source=r'''
#include "mk2_adsp.hpp"
#include <iostream>
#include <memory>
int main() {try {
    mk2::DcsLink link;
    auto holder=std::make_unique<mk2::AdspBoot>(std::vector<uint32_t>(376),link);
    auto& d=*holder;d.rebooted_=true;d.imask=0;
    d.external_pm[0x1c7]=0x879ff0;d.external_pm[0x1de]=0x0e370f;
    for(unsigned value:{0u,0x3fffu,0x4000u,0xffffu}) {
        d.pc=0x9c7;d.dm[0x1ff]=uint16_t(value);d.i[0]=0x1234;
        auto expected=d.Registers();const auto device=d.DeviceState();
        expected[0]=0x9c8;++expected[1];expected[16]=value&0x3fff;
        const auto before=d.AccessCount();d.Step();
        if(d.Registers()!=expected || d.DeviceState()!=device || d.AccessCount()!=before+1) return 1;
        const auto& access=d.accesses.back();
        if(access.pc!=0x9c7 || access.address!=0x39ff || access.value!=value ||
           access.cycle!=expected[1]-1 || access.space!='r') return 2;
        d.DiscardObservedTrace();
    }
    unsigned cases=0;
    for(int count:{-128,-33,-32,-31,-16,-1,0,1,15,16,31,32,127})
    for(unsigned value=0;value<65536;++value) {
        d.pc=0x9de;d.sr0=0xa55a;d.sr1=uint16_t(value);d.se=uint16_t(count);d.astat=0xd7;
        const int64_t source=int16_t(value);
        int64_t signed_result;
        if(count>=32)signed_result=0;
        else if(count>=0)signed_result=source*(int64_t(1)<<count);
        else if(count<=-32)signed_result=source<0?-1:0;
        else {const auto divisor=int64_t(1)<<-count;signed_result=source>=0?source/divisor:-((-source+divisor-1)/divisor);}
        const auto result=uint32_t(signed_result);
        auto expected=d.Registers();const auto device=d.DeviceState();const auto accesses=d.AccessCount();
        expected[0]=0x9df;++expected[1];expected[55]=uint16_t(result);expected[56]=uint16_t(result>>16);
        d.Step();
        if(d.Registers()!=expected || d.DeviceState()!=device || d.AccessCount()!=accesses) return 3;
        d.DiscardObservedTrace();++cases;
    }
    for(uint16_t pc:{uint16_t(0x9c7),uint16_t(0x9de)}) {
        d.pc=pc;d.external_pm[pc&0x7ff]^=1;
        const auto state=d.Registers(),device=d.DeviceState();const auto count=d.InstructionCount(),accesses=d.AccessCount();
        bool rejected=false;try {d.Step();}catch(const std::runtime_error&) {rejected=true;}
        if(!rejected || d.Registers()!=state || d.DeviceState()!=device || d.InstructionCount()!=count || d.AccessCount()!=accesses) return 4;
        d.external_pm[pc&0x7ff]^=1;
    }
    std::cout<<cases<<" arithmetic shift cases;4physical load cases;2opcode rejection controls\n";
}catch(const std::exception& error) {std::cerr<<error.what();return 99;}}
'''

        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'fight-shift.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'fight-shift.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(quality.ROOT/'native/mk2'),'-I'+str(quality.ROOT/'native/include'),cpp,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    @unittest.skipUnless((quality.ROOT/'roms/mk2/su2.l1').is_file(),'requires authenticated MK2 U2 ROM')
    def test_suspended_prefix_trace_preserves_execution_events_and_complete_resumed_rows(self):
        # Catches skipped execution, stale access PCs, lost reboot counts and partial resumed rows.
        source=r'''
#include "native/mk2/mk2_adsp.hpp"
#include <iostream>
#include <memory>
#include <tuple>
void check(bool ok,const char* message) {if(!ok) throw std::runtime_error(message);}
void same(const mk2::AdspBoot& a,const mk2::AdspBoot& b,
          const mk2::DcsLink& x,const mk2::DcsLink& y) {
    check(a.Registers()==b.Registers() && a.DeviceState()==b.DeviceState(),"76 registers/devices");
    check(a.InstructionCount()==b.InstructionCount() && a.pm==b.pm && a.dm==b.dm &&
          a.external_pm==b.external_pm && a.control==b.control,"count and complete memories");
    check(a.pc_stack_==b.pc_stack_ && a.counters_==b.counters_,"physical stacks");
    for(unsigned n=0;n<4;++n) check(a.loops_[n].start==b.loops_[n].start &&
                                 a.loops_[n].end==b.loops_[n].end,"loop frames");
    check(std::tie(a.interrupt_.pc,a.interrupt_.mstat,a.interrupt_.imask,a.interrupt_.astat)==
          std::tie(b.interrupt_.pc,b.interrupt_.mstat,b.interrupt_.imask,b.interrupt_.astat),"IRQ2 frame");
    check(std::tie(a.rebooted_,a.reset_pending_,a.boot_reloads,a.ifc,a.sport_enabled,
          a.sport_irq1_asserted,a.sport_irq1_latched,a.sport_timer_cancelled,a.sport_dma_position,
          a.dac_write_sample_,a.dac_last_ticks_,a.dac_bufin_,a.dac_bufout_,a.instruction_ticks_)==
          std::tie(b.rebooted_,b.reset_pending_,b.boot_reloads,b.ifc,b.sport_enabled,
          b.sport_irq1_asserted,b.sport_irq1_latched,b.sport_timer_cancelled,b.sport_dma_position,
          b.dac_write_sample_,b.dac_last_ticks_,b.dac_bufin_,b.dac_bufout_,b.instruction_ticks_),"device clocks/flags");
    check(a.reboot_events==b.reboot_events && a.serial_events==b.serial_events &&
          a.sport_transfers==b.sport_transfers && a.sport_pcm==b.sport_pcm &&
          a.sport_dma_positions==b.sport_dma_positions && a.sport_irq1_events==b.sport_irq1_events &&
          a.dac_buffer_==b.dac_buffer_,"complete device observations");
    check(a.accesses.size()==b.accesses.size(),"access count");
    for(size_t n=0;n<a.accesses.size();++n) {
        const auto& p=a.accesses[n];const auto& q=b.accesses[n];
        check(std::tie(p.pc,p.address,p.value,p.cycle,p.space)==
              std::tie(q.pc,q.address,q.value,q.cycle,q.space),"complete access including source PC");
    }
    check(std::tie(x.control_,x.input_,x.output_,x.pending_output_,x.reset_,x.irq2_)==
          std::tie(y.control_,y.input_,y.output_,y.pending_output_,y.reset_,y.irq2_),"link latches");
    check(x.pending_.size()==y.pending_.size(),"link queue count");
    for(size_t n=0;n<x.pending_.size();++n)
        check(x.pending_[n].kind==y.pending_[n].kind && x.pending_[n].value==y.pending_[n].value,"link queue");
}
int main(int argc,char** argv) {try {
    check(argc==2,"ROM argument");const auto rom=mk2::LoadDcsRom(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    mk2::DcsLink x,y;
    auto ap=std::make_unique<mk2::AdspBoot>(boot,x,rom),bp=std::make_unique<mk2::AdspBoot>(boot,y,rom);
    auto& a=*ap;auto& b=*bp;
    for(unsigned n=0;n<2;++n) {a.Step();b.Step();}
    b.SetTraceObservation(false);
    // Keep the old rows to detect accidental use of trace.back() for a new access.
    bool command=false;
    for(unsigned n=0;n<20000;++n) {
        if(!command && a.pc==0x44 && a.imask==0x20) {
            x.HostWrite(0x01d01030,0xff02);y.HostWrite(0x01d01030,0xff02);
            x.Synchronize();y.Synchronize();command=true;
        }
        a.DiscardObservedTrace();a.SetInstructionTicks(n*10);b.SetInstructionTicks(n*10);
        a.Step();b.Step();
        check(a.ApplyPendingReset()==b.ApplyPendingReset(),"same pending reset");
        same(a,b,x,y);check(b.trace.size()==2,"no hidden prefix rows");
    }
    check(command && !a.reboot_events.empty(),"real boot/IRQ/software reboot reached");
    check(a.InstructionCount()==20002,"all real prefix instructions counted");
    b.DiscardObservedTrace();b.SetTraceObservation(true);a.DiscardObservedTrace();
    for(unsigned n=0;n<200;++n) {
        a.Step();b.Step();check(a.trace==b.trace && b.trace.back().size()==76,"integral resumed rows");
        check(a.ApplyPendingReset()==b.ApplyPendingReset(),"resumed reset");same(a,b,x,y);
    }
    // Exercise SPORT and all seven access-source consumers with trace disabled.
    for(auto* d:{&a,&b}) {
        d->DiscardObservedTrace();d->imask=0;d->mstat=0;d->loop_sp=d->cntr_sp=0;
        d->rebooted_=false;d->pm[0x38]=0x5000a5;d->pm[0x39]=0x5800a2;
        d->pm[0x23]=0x93fff8;d->pm[0x31]=0x979fb4;d->pm[0x45]=0x839fca;d->pm[0x3b]=0x700080;
        d->l.fill(0);d->m.fill(0);d->i[5]=0x20;d->i[4]=0x18;d->si=0x10;
    }
    b.SetTraceObservation(false);
    for(uint16_t pc:{uint16_t(0x38),uint16_t(0x39),uint16_t(0x23),uint16_t(0x31),uint16_t(0x45),uint16_t(0x3b)}) {
        a.pc=b.pc=pc;if(pc==0x3b)a.i[4]=b.i[4]=0x3400;
        a.Step();b.Step();same(a,b,x,y);
        check(a.accesses.back().pc==pc,"literal physical access source");
    }
    for(auto* d:{&a,&b}) {
        d->rebooted_=true;d->pc=0x829;d->external_pm[0x29]=0x0d0cb0;
        d->control[31]=0x800;d->control[15]=0xe82;d->i[7]=0x400;d->l[7]=480;d->m[5]=1;
    }
    a.Step();b.Step();same(a,b,x,y);check(a.serial_events.back()[0]==0x829,"SPORT source");
    for(auto* d:{&a,&b}) {d->imask=0x20;d->SportTransfer(1000000);}
    same(a,b,x,y);
    for(auto* d:{&a,&b})d->SportTransfer(1768000);
    same(a,b,x,y);check(a.sport_irq1_asserted,"real masked SPORT IRQ1");
    a.ClearSportIrq1(1768010);b.ClearSportIrq1(1768010);same(a,b,x,y);
    for(bool observed:{false,true}) {
        b.SetTraceObservation(observed);b.pc=0x829;b.external_pm[0x29]^=1;
        const auto state=b.Registers(),device=b.DeviceState();const auto count=b.InstructionCount(),rows=b.trace.size();
        bool rejected=false;try{b.Step();}catch(const std::runtime_error&){rejected=true;}
        check(rejected && b.Registers()==state && b.DeviceState()==device &&
              b.InstructionCount()==count && b.trace.size()==rows,"changed opcode rejects without a row/count");
        b.external_pm[0x29]^=1;
    }
    std::cout<<"20002 real prefix steps; full states/memories/events; resumed DSP76; seven access PCs; SPORT IRQ1; opcode rejection\n";
}catch(const std::exception& error){std::cerr<<error.what();return 99;}}
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'observation.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'observation.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),cpp,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe,quality.ROOT/'roms/mk2/su2.l1'],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])

    def test_division_q_flag_absolute_saturation_and_sign_condition_execute_actual_words(self):
        # Independent integer evaluation of the pinned DIVS/DIVQ switch cases.
        rows=[]
        for ax in (0,1,0x7fff,0x8000,0xffff):
            for af in (0,1,0x7fff,0x8000,0xffff):
                for ay in (0,0xffff):
                    flags=0xdf
                    temp=ax^af
                    qflags=(flags&~0x20)|((temp>>10)&0x20)
                    qaf=((af<<1)|(ay>>15))&0xffff
                    qay=((ay<<1)|(temp>>15))&0xffff
                    first=(qaf,qay,qflags)
                    for _ in range(16):
                        value=qaf+ax if qflags&0x20 else qaf-ax
                        temp=value^ax
                        qflags=(qflags&~0x20)|((temp>>10)&0x20)
                        qaf=((value<<1)|(qay>>15))&0xffff
                        qay=((qay<<1)|((~temp>>15)&1))&0xffff
                    rows.append((ax,af,ay,flags,*first,qaf,qay,qflags))
        source=r'''
#include "native/mk2/mk2_adsp.hpp"
#include <iostream>
#include <memory>
int main() { try {
    mk2::DcsLink link;
    auto holder=std::make_unique<mk2::AdspBoot>(std::vector<uint32_t>(376),link);
    auto& dsp=*holder;dsp.rebooted_=true;dsp.imask=0;
    dsp.pm[0x2dc]=0x23e60f;dsp.pm[0x2de]=0x061000;dsp.pm[0x2e1]=0x071000;dsp.pm[0x2e3]=0x233a0a;
    struct Case {uint16_t ax,af,ay,flags,first_af,first_ay,first_flags,last_af,last_ay,last_flags;};
    const Case cases[]={
'''+''.join('{'+','.join(hex(v) for v in row)+'},\n' for row in rows)+r'''};
    for(const auto& item:cases) {
        dsp.pc=0x2de;dsp.ax0=item.ax;dsp.af=item.af;dsp.ay0=item.ay;dsp.astat=uint8_t(item.flags);
        auto expected=dsp.Registers();const auto device=dsp.DeviceState();
        expected[0]=0x2df;++expected[1];expected[6]=item.first_flags;expected[42]=item.first_ay;expected[44]=item.first_af;
        dsp.Step();
        if(dsp.Registers()!=expected || dsp.DeviceState()!=device || !dsp.accesses.empty()) return 1;
        dsp.DiscardObservedTrace();
        for(unsigned n=0;n<16;++n) {dsp.pc=0x2e1;dsp.Step();dsp.DiscardObservedTrace();}
        if(dsp.af!=item.last_af || dsp.ay0!=item.last_ay || dsp.astat!=item.last_flags || dsp.ax0!=item.ax) return 2;
    }
    // Exhaust all16-bit ABS inputs for normal, sticky-V and saturation modes.
    for(unsigned mode:{0u,4u,8u,12u})for(unsigned value=0;value<65536;++value) {
        dsp.pc=0x2dc;dsp.mstat=uint8_t(mode);dsp.sr0=uint16_t(value);dsp.astat=0xff;
        auto expected=dsp.Registers();const auto device=dsp.DeviceState();
        const uint16_t raw=value&0x8000?uint16_t(0u-value):uint16_t(value);
        uint8_t flags=uint8_t((0xffu&((mode&4)?0xf4u:0xf0u))&~0x10u);
        if(!value)flags|=1;
        if(value==0x8000)flags|=6;
        if(value&0x8000)flags|=0x10;
        expected[0]=0x2dd;++expected[1];expected[6]=flags;
        expected[2]=(mode&8)&&(flags&4)?0x7fff:raw;
        dsp.Step();
        if(dsp.Registers()!=expected || dsp.DeviceState()!=device || !dsp.accesses.empty()) return 3;
        dsp.DiscardObservedTrace();
    }
    for(unsigned flags:{0xe2u,0xf0u}) {
        dsp.pc=0x2e3;dsp.mstat=0;dsp.ar=3;dsp.astat=uint8_t(flags);
        auto expected=dsp.Registers();expected[0]=0x2e4;++expected[1];
        if(flags&0x10) {expected[2]=0xfffd;expected[6]=0xf2;}
        dsp.Step();
        if(dsp.Registers()!=expected || !dsp.accesses.empty()) return 4;
        dsp.DiscardObservedTrace();
    }
    dsp.pc=0x2de;dsp.pm[0x2de]=0x061001;
    const auto before=dsp.Registers();const auto count=dsp.InstructionCount();bool rejected=false;
    try {dsp.Step();} catch(const std::runtime_error&){rejected=true;}
    if(!rejected || dsp.Registers()!=before || dsp.InstructionCount()!=count || !dsp.accesses.empty()) return 5;
} catch(const std::exception& error) {std::cerr<<error.what();return 99;} }
'''
        with quality.scratch_tree() as (scratch,cleanup):
            cpp=scratch/'fight-adsp.cpp';cpp.write_text(source,encoding='utf-8');exe=scratch/'fight-adsp.exe'
            cc=quality.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ.get('PATH','')}
            build=quality.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-fno-access-control',
                '-I'+str(quality.ROOT),'-I'+str(quality.ROOT/'native/include'),cpp,
                quality.ROOT/'native/mk2/mk2_adsp.cpp',quality.ROOT/'native/mk2/mk2_dcs.cpp',
                quality.ROOT/'native/src/mk5_program.cpp','-lbcrypt','-o',exe],scratch,env=env)
            self.assertTrue(build['passed'],build['stdout'])
            result=quality.command([exe],scratch,env=env)
            self.assertTrue(result['passed'],result['stdout'])
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
