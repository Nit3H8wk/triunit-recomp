#include "../mk2/mk2_adsp.hpp"
#include "../mk2/mk2_dcs.hpp"
#include "../include/mk5_program.hpp"
#include "../mk2/mk2_oracle_digest.hpp"
#include <array>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
// Fixed DSP words come from the user's authenticated U2 (argv[1]); none is stored in this file.
std::vector<uint8_t> u2;
uint32_t U2Word(size_t offset) {
    return (uint32_t(u2.at(offset)) << 16) | (uint32_t(u2.at(offset + 1)) << 8) | u2.at(offset + 2);
}
// Second-boot firmware: bank-one page for internal PM, external PM from U2 0x2000.
uint32_t Firmware(uint16_t pc) { return U2Word(pc < 0x400 ? 0x1000 + size_t(pc) * 4 : 0x2000 + size_t(pc - 0x800) * 4); }
void step(mk2::AdspBoot& dsp, uint16_t pc) {
    const uint32_t opcode = Firmware(pc);
    dsp.pc = pc;
    if (pc < 0x400) dsp.pm.at(pc) = opcode;
    else dsp.external_pm.at(pc - 0x800) = opcode;
    const auto cycle = dsp.cycles;
    dsp.Step();
    check(dsp.cycles == cycle + 1, "each fixed DSP instruction consumes one original cycle");
}
// Synthetic DCS resume blocks; the table between the markers is compared with MAME 0.280 stepping the same start state by
// tools/mk2/dcs_resume_witnesses.py --check (only SHA-256 of what MAME reached is kept). irq2: MAME raised IRQ2 after
// that step (0: none).
struct ResumeBlock {
    uint16_t pc; unsigned steps; std::array<uint16_t,16> stack; std::array<uint64_t,76> start;
    std::array<const char*,8> rows; const char* write_lanes; unsigned writes; unsigned irq2;
};
// SHA-256 (mk2_oracle_digest.hpp order) of the local General Test timeline read by --service; the words stay local.
constexpr char k_service_timeline_sha256[]="a937398f943c08d650bdcfd8ec6407f21ab87ad3165c8b9086918f19ff9e1aeb";
// IRQ2 block: idle loop words, the vector and the first vector target (read from U2 by the test).
constexpr std::array<uint16_t,5> k_irq2_code{0x004,0x130,0x131,0x132,0x394};
// BEGIN dcs_resume_witnesses
// Synthetic DCS resume blocks, compared with MAME 0.280 (:dcs:dcs) by python tools/mk2/dcs_resume_witnesses.py --check.
// start: synthetic DSP76; rows: SHA-256 of the DSP76 MAME reached after each step (oracle_digest order);
// writes: SHA-256 of the data-write lanes (PC, address, value, cycle offset); irq2: IRQ2 raised after that
// step (0: none).
constexpr ResumeBlock k_wrap{0x358,6,{0x1a1,0x2b7,0x3c5},
    {856,1000003,60318,34810,68,12220,170,85,24,0,0,3,0,0,0,0,14508,14554,14718,14336,14528,14710,14610,14396,0,16381,16381,16382,16382,2,16382,0,0,0,0,0,0,0,0,0,22192,62518,49826,57916,45252,20066,23846,14680,51000,58894,46602,244,8972,26,14,42224,50208,8628,44722,52566,40168,15784,3422,11322,48132,37116,45162,32862,8576,144,4310,41218,92,4,11906,6},
    {"60d5a5aafe67dcf518c61511eb7d807b53946649a47dcf51c6710a42906cc7dd","0d0f6c5930498d09ea4adda28a009b6e962ec9ca145bd0abbfc90889040861fa","373687f332927b42d1dc14fb2bb5a1e525a9057eb8576ff2ff14e683e88c84c3","4bd45dd4c5171b947ded7ed447e6c2db77c4ba7419b51bf907f2eebdf985856b","27904eccc7f8b0df4998517bc5e8e21753b71c2f31c8c3639a9adbe39322688d","964cc090e40dda92764171284073f05b27cbec1d2bd98e1d8e67e951e805f4b8"},
    "73ec3323f741314a3c75d3485295b238c6789d0abf52fb87b808ad4c4ead32aa",2,0};
constexpr ResumeBlock k_clear{0x246,8,{0x1a1,0x31d},
    {582,2000005,160,55114,54,4140,244,84,24,0,0,2,0,0,0,0,14796,14404,14694,14778,14456,14552,14658,14494,1,16382,0,16381,2,16383,1,3,0,0,0,0,0,0,0,0,184,504,402,430,148,460,398,226,384,240,250,70,2012,132,22,35514,25224,16932,34876,57118,51026,7824,28896,14602,36982,63212,52788,5830,28266,24,45464,63858,78,20,37100,55534},
    {"7013f49bb3f740169766283bb0a7a21966c4f78fc6ab0c896827ac8f6c5d0b5f","e77645a5a9a3b92c69c800afb063e36ae9dadc521e193335966cbe2211855d4a","f776d0f360ae2f9be137ec725e6f5da6b8a804c54aa60113ef6db6020adc9727","4df4c2d2d119d0aad49e7aab40e1280a7911d07f2982e9b28ec69569fba51f42","d4834bc0a9ae151832279bccfef4de46b987420605b7c2abbfb268beeec8c2a0","83d57c0aca78d60518f3c6a0b126f4b2805749944bdceaddb168115873926ecc","072863c3e481bd0a8279b40864fba6eea2883d637e0c0167595792c92dd0ba60","d8cccaf05ea68ed915fb5fcf46c49e90a9a6f64acefd3b3ee14e7398ecdf12d8"},
    "8f6f2664252f96554d59ec78517d2f289c93982fe8c5613bd3a234982c8abfa5",2,0};
constexpr ResumeBlock k_irq2{0x130,7,{},
    {304,208263833,43722,63318,180,12316,150,85,24,32,0,0,0,0,0,0,14412,14358,14570,14608,14592,14546,14814,14412,3,16383,16381,3,2,16383,1,1,0,0,0,0,0,0,0,0,38304,58450,14375,8540,28660,32478,52626,64584,2904,23098,26918,36,59244,134,10,21776,33872,25124,29102,49474,53528,8392,20618,24726,45172,49244,61526,16538,20640,192,53554,57710,188,20,37566,49970},
    {"cfedc1f839a41aa3eb60e1dbeded537eb8d732426b9c02a7def88ac13826888d","70016ed0d8642e3e9fa795ab84e90bf34c555705ca511d4b6dbf761e283b44d6","59af2fa5f55a031e343eaae84807b04b38fa9036b22d819a7f1eaf8bc7d83b01","5fa7b34015f8977316f3bc9f8ea645456405c5821dd51ee9437dcefd98fd7c5a","c28be8c37d8e8fcad668d7e658adf6166c8c47f2ad4d0910e6c960aaa179c883","363bb07d63bf1a55389b0df5fce76175545b8ffe7ef7603da79d1e937b6ff533","53711b7eca262d5c003c2c76bd03a4d347a3f31d0e9944dfd2bd9431a3def453"},
    "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",0,5};
// END dcs_resume_witnesses
uint16_t Signed(uint64_t value,unsigned bits) {
    const uint64_t sign=uint64_t(1)<<(bits-1),low=value&((sign<<1)-1);
    return uint16_t((low^sign)-sign);
}
// Inverse of AdspBoot::Registers(); MR2/SE/SB/M are sign-extended as the MAME state import does.
void Load(mk2::AdspBoot& d,const ResumeBlock& block) {
    const auto& s=block.start;
    d.pc=uint16_t(s[0]);d.cycles=s[1];d.ar=uint16_t(s[2]);d.si=uint16_t(s[3]);d.px=uint8_t(s[4]);d.cntr=uint16_t(s[5]);
    d.astat=uint8_t(s[6]);d.sstat=uint8_t(s[7]);d.mstat=uint8_t(s[8]);d.imask=uint16_t(s[9]);d.icntl=uint16_t(s[10]);
    d.pc_sp=uint8_t(s[11]);d.cntr_sp=uint8_t(s[12]);d.loop_sp=uint8_t(s[13]);d.stat_sp=uint8_t(s[14]);
    check(s[15]==0,"synthetic blocks start with IRQ2 clear");
    for(unsigned n=0;n<8;++n){d.i[n]=uint16_t(s[16+n]);d.m[n]=int16_t(Signed(s[24+n],14));d.l[n]=uint16_t(s[32+n]);}
    d.ax0=uint16_t(s[40]);d.ax1=uint16_t(s[41]);d.ay0=uint16_t(s[42]);d.ay1=uint16_t(s[43]);d.af=uint16_t(s[44]);
    d.mx0=uint16_t(s[45]);d.mx1=uint16_t(s[46]);d.my0=uint16_t(s[47]);d.my1=uint16_t(s[48]);d.mr0=uint16_t(s[49]);
    d.mr1=uint16_t(s[50]);d.mr2=Signed(s[51],8);d.mf=uint16_t(s[52]);d.se=Signed(s[53],8);d.sb=Signed(s[54],5);
    d.sr0=uint16_t(s[55]);d.sr1=uint16_t(s[56]);
    auto& a=d.alternate_;
    a.ax0=uint16_t(s[57]);a.ax1=uint16_t(s[58]);a.ay0=uint16_t(s[59]);a.ay1=uint16_t(s[60]);a.ar=uint16_t(s[61]);
    a.af=uint16_t(s[62]);a.mx0=uint16_t(s[63]);a.mx1=uint16_t(s[64]);a.my0=uint16_t(s[65]);a.my1=uint16_t(s[66]);
    a.mr0=uint16_t(s[67]);a.mr1=uint16_t(s[68]);a.mr2=Signed(s[69],8);a.mf=uint16_t(s[70]);a.si=uint16_t(s[71]);
    a.se=Signed(s[72],8);a.sb=Signed(s[73],5);a.sr0=uint16_t(s[74]);a.sr1=uint16_t(s[75]);
    d.pc_stack_=block.stack;
}
}
int main(int argc, char** argv) {
    try {
        check(argc == 2 || (argc == 4 && std::string(argv[2]) == "--service"),
              "expected the MK2 ROM directory and optional --service <local General Test timeline>");
        const auto rom = mk2::LoadDcsDataRoms(argv[1]);
        u2.assign(rom.begin(), rom.begin() + 0x80000);
        const auto boot = mk2::DecodeDcsBoot({rom.begin(), rom.begin() + 0x1000});
        mk2::DcsLink link;
        mk2::AdspBoot dsp(std::vector<uint32_t>(376), link);
        dsp.rebooted_ = true;
        {
            mk2::DcsLink missing_link;
            mk2::AdspBoot missing(std::vector<uint32_t>(376),missing_link);
            missing.rebooted_=true;missing.pc=0x1fff;missing.external_pm.back()=0x123456;
            const auto before=missing.Registers();const auto trace=missing.trace.size();
            bool rejected=false;
            try {missing.Step();}catch(const std::runtime_error& error) {
                rejected=std::string(error.what())=="ADSP untranslated PC 8191; opcode 1193046";
            }
            check(rejected && missing.Registers()==before && missing.trace.size()==trace &&
                  missing.external_pm.back()==0x123456,"missing DSP entry reports actual PM word without executing or mutating CPU");
        }
        {
            // Actual late PM words; component vectors cover both clamp paths without changing game state.
            // {PC, next PC, AR, AR written}; the opcode is the U2 word at PC.
            const std::array<std::array<uint32_t,4>,6> cases{{
                {0xa93,0xa94,0x1fff,1},{0xa94,0xa99,0,0},
                {0xa98,0xa99,0xe001,1},{0xaac,0xaad,0x1fff,1},
                {0xaad,0xab2,0,0},{0xab1,0xab2,0xe001,1}}};
            for(const auto& item:cases)for(uint16_t input:{0u,1u,0x1fffu,0x2000u,0x7fffu,0x8000u,0xe000u,0xe001u,0xffffu}) {
                mk2::DcsLink clamp_link;mk2::AdspBoot clamp(std::vector<uint32_t>(376),clamp_link);
                clamp.rebooted_=true;clamp.SetTraceObservation(false);
                clamp.pc=uint16_t(item[0]);clamp.external_pm[item[0]-0x800]=Firmware(uint16_t(item[0]));
                clamp.ar=input;clamp.ay0=0x1fff;clamp.af=1;clamp.astat=0x28;clamp.mstat=0x18;
                const auto memory=clamp.dm;const auto internal=clamp.pm;const auto external=clamp.external_pm;
                auto expected=clamp.Registers();expected[0]=item[1];++expected[1];
                if(item[3])expected[2]=item[2];
                const auto instructions=clamp.InstructionCount();clamp.Step();
                check(clamp.Registers()==expected && clamp.InstructionCount()==instructions+1 &&
                      clamp.dm==memory && clamp.pm==internal && clamp.external_pm==external && clamp.accesses.empty(),
                      "sound clamp changes only encoded PC/AR and one DSP cycle; all banks/flags/memory retained");
                clamp.pc=uint16_t(item[0]);clamp.external_pm[item[0]-0x800]^=0x10;
                const auto before=clamp.Registers();bool rejected=false;
                try {clamp.Step();}catch(const std::runtime_error&){rejected=true;}
                check(rejected && clamp.Registers()==before && clamp.InstructionCount()==instructions+1,
                      "altered clamp opcode rejects before execution");
            }
        }
        {
            mk2::DcsLink palette_link;
            mk2::AdspBoot palette_dsp(std::vector<uint32_t>(376), palette_link);
            palette_dsp.rebooted_ = true;
            for (uint16_t original : {uint16_t(0), uint16_t(1)}) {
                palette_dsp.mstat = 0; palette_dsp.astat = 0; palette_dsp.ay0 = original; palette_dsp.sr0 = 0x1234;
                const auto accesses = palette_dsp.accesses.size();
                step(palette_dsp, 0x99c);
                check(palette_dsp.ar == uint16_t(original - 1) && palette_dsp.ay0 == 0x1234 &&
                      palette_dsp.astat == (original ? 1 : 0x0a) && palette_dsp.accesses.size() == accesses,
                      "palette-wait parallel decrement uses original AY0 before moving SR0 and retains exact flags");
            }
            step(palette_dsp, 0x99e);
            check(palette_dsp.pc == 0x9a2 && palette_dsp.pc_sp == 0,
                  "palette-wait fixed jump reaches original continuation without a call frame");
        }
        // wrap (0x358, through its RETS) and clear (0x246, through its CALL): synthetic start states stepped in MAME
        // 0.280 (tools/mk2/dcs_resume_witnesses.py); the include keeps the start and the SHA-256 of what MAME reached.
        auto resume=[&](const ResumeBlock& block,mk2::AdspBoot& dsp,mk2::DcsLink& block_link,const char* name) {
            dsp.rebooted_=true;
            for(unsigned n=0;n<dsp.pm.size();++n)dsp.pm[n]=(n*1337u+0x55555u)&0xffffff;
            for(unsigned n=0;n<dsp.external_pm.size();++n)dsp.external_pm[n]=(n*293u+0xabcdefu)&0xffffff;
            for(unsigned n=0;n<dsp.dm.size();++n)dsp.dm[n]=uint16_t(n*29u^0xa55au);
            for(unsigned n=0;n<block.steps;++n)dsp.pm[block.pc+n]=Firmware(uint16_t(block.pc+n));
            Load(dsp,block);
            check(dsp.Registers()==std::vector<uint64_t>(block.start.begin(),block.start.end()),"synthetic DSP76 start loads exactly");
            const auto pm=dsp.pm;const auto control=dsp.control;const auto stack=dsp.pc_stack_;
            const auto link=block_link.ExecutionState();auto expected_dm=dsp.dm;auto expected_external=dsp.external_pm;
            for(unsigned n=0;n<block.steps;++n){
                dsp.pc=uint16_t(block.pc+n);dsp.pm[dsp.pc]^=1;const auto registers=dsp.Registers();
                bool rejected=false;try{dsp.Step();}catch(const std::runtime_error&){rejected=true;}
                check(rejected && dsp.Registers()==registers && dsp.InstructionCount()==0 && dsp.accesses.empty() &&
                    dsp.dm==expected_dm && dsp.external_pm==expected_external && dsp.control==control &&
                    dsp.pc_stack_==stack && block_link.ExecutionState()==link && dsp.trace.empty(),
                    "every block PC rejects a changed opcode before CPU, bus or memory mutation");
                dsp.pm[dsp.pc]^=1;
            }
            dsp.pc=block.pc;
            std::vector<uint64_t> lanes;
            for(unsigned n=0;n<block.steps;++n){
                const auto accesses=dsp.accesses.size();
                dsp.Step();
                for(size_t a=accesses;a<dsp.accesses.size();++a) {
                    const auto& lane=dsp.accesses[a];
                    if(lane.space!='d')continue;
                    lanes.insert(lanes.end(),{lane.pc,lane.address,lane.value,lane.cycle-block.start[1]});
                    if(lane.address>=0x3800 && lane.address<0x3a00)expected_dm[lane.address-0x3800]=uint16_t(lane.value);
                    else if(lane.address<0x2000){auto& word=expected_external[lane.address&0x7ff];word=(uint32_t(lane.value)<<8)|(word&0xff);}
                    else throw std::runtime_error(std::string(name)+": write outside the seeded memories");
                }
                check(mk2::WordsDigest(dsp.Registers())==block.rows[n] && dsp.InstructionCount()==n+1 &&
                    dsp.pm==pm && dsp.dm==expected_dm && dsp.external_pm==expected_external && dsp.control==control &&
                    block_link.ExecutionState()==link,(std::string(name)+": DSP76 or complete memories differ from MAME").c_str());
            }
            check(lanes.size()==4*block.writes && mk2::WordsDigest(lanes)==block.write_lanes,
                (std::string(name)+": data-write lanes or clocks differ from MAME").c_str());
        };
        {
            mk2::DcsLink wrap_link;mk2::AdspBoot wrap(std::vector<uint32_t>(376),wrap_link);
            resume(k_wrap,wrap,wrap_link,"wrap");
            check(wrap.pc==k_wrap.stack[2] && wrap.pc_sp==2 && wrap.pc_stack_==k_wrap.stack,"wrap RETS pops its return PC");

            for(const auto& value:std::array<std::array<uint16_t,3>,3>{{{0,1,0xf0},{0x7fff,0x7fff,0xf6},{0xffff,0,0xf9}}}){
                wrap.ay0=value[0];wrap.astat=0xf5;step(wrap, 0x35a);
                check(wrap.ay0==value[0] && wrap.ar==value[1] && wrap.astat==value[2],
                    "wrap increment preserves AY0 and flags from the raw result before saturation");
            }
        }
        {
            mk2::DcsLink clear_link;mk2::AdspBoot clear(std::vector<uint32_t>(376),clear_link);
            resume(k_clear,clear,clear_link,"clear");
            auto stack=k_clear.stack;stack[2]=uint16_t(k_clear.pc+k_clear.steps);
            check(clear.pc_sp==3 && clear.pc_stack_==stack,"clear CALL pushes its return PC");
            clear.mr0=0x7fff;clear.ay0=0x388;clear.astat=0;
            step(clear, 0x247);
            check(clear.af==0x8387 && clear.mr0==0x7fff,"AF keeps unsaturated sixteen-bit result");
            step(clear, 0x248);
            check(clear.ar==0x386 && (clear.astat&15)==8,"AR uses original MR0 and the new unsaturated AF");
        }

        // IRQ2 dispatch across the scanline inside MOVE @1D01030: input precedes that timer. The DSP side is the
        // synthetic idle-loop block k_irq2 stepped in MAME 0.280 (five idle instructions, IRQ2 raised, vector to 0x395);
        // the board replay checks that the host write and the scanline timer bring the DSP to exactly that dispatch.
        uint8_t irq2_astat=0;
        {
            mk2::DcsLink irq_link;mk2::AdspBoot irq(boot,irq_link,rom);
            irq.rebooted_=irq.live_host_domain_=true;irq.live_instruction_ceiling_=100;irq.SetTraceObservation(false);
            for(unsigned n=0;n<irq.pm.size();++n)irq.pm[n]=(n*1337u+0x55555u)&0xffffff;
            for(unsigned n=0;n<irq.external_pm.size();++n)irq.external_pm[n]=(n*293u+0xabcdefu)&0xffffff;
            for(unsigned n=0;n<irq.dm.size();++n)irq.dm[n]=uint16_t(n*29u^0xa55au);
            for(const auto pc:k_irq2_code)irq.pm[pc]=Firmware(pc);
            Load(irq,k_irq2);
            check(irq.Registers()==std::vector<uint64_t>(k_irq2.start.begin(),k_irq2.start.end()),"synthetic IRQ2 start loads exactly");
            const auto pm=irq.pm;const auto dm=irq.dm;const auto external=irq.external_pm;const auto control=irq.control;
            const auto stack=irq.pc_stack_;const auto link=irq_link.ExecutionState();
            for(const auto pc:k_irq2_code){
                irq.pc=pc;irq.pm[pc]^=1;const auto registers=irq.Registers();
                bool rejected=false;try{irq.Step();}catch(const std::runtime_error&){rejected=true;}
                check(rejected && irq.Registers()==registers && irq.InstructionCount()==0 && irq.accesses.empty() &&
                    irq.dm==dm && irq.external_pm==external && irq.control==control && irq.pc_stack_==stack &&
                    irq_link.ExecutionState()==link,"every IRQ2 block PC rejects a changed opcode before CPU, bus or memory mutation");
                irq.pm[pc]^=1;
            }
            irq.pc=k_irq2.pc;
            for(unsigned n=0;n<k_irq2.steps;++n){
                if(n==k_irq2.irq2){
                    irq2_astat=irq.astat;
                    irq_link.HostWrite(0x01d01030,0xff5a);irq_link.Synchronize();
                    check(irq_link.Irq2Asserted() && irq_link.Control()==0x400,"synthetic host write raises level IRQ2");
                }
                irq.Step();
                check(mk2::WordsDigest(irq.Registers())==k_irq2.rows[n] && irq.InstructionCount()==n+1 && irq.pm==pm &&
                    irq.dm==dm && irq.external_pm==external && irq.control==control && irq.accesses.empty(),
                    "irq2: DSP76 or complete memories differ from MAME");
            }
            auto expected_stack=stack;expected_stack[0]=0x132;
            check(irq.pc_stack_==expected_stack && irq.interrupt_.pc==0x132 && irq.interrupt_.mstat==k_irq2.start[8] &&
                irq.interrupt_.imask==k_irq2.start[9] && irq.interrupt_.astat==irq2_astat,
                "irq2: IRQ2 return PC or pushed status differs from the dispatch state");
        }
        {
            auto replay=[&](bool write,bool crossing,bool timer_cap=false){
                mk2::DcsBootMachine m(boot,rom);auto& d=m.dsp;
                m.live_host_domain_=d.live_host_domain_=true;m.main_horizon_=d.main_horizon_=137000000;
                d.live_instruction_ceiling_=100;d.rebooted_=true;
                Load(d,k_irq2);
                const uint64_t start=k_irq2.start[1];
                // Scheduler clocks of the replay: the DSP is five instructions before the old quantum target and seven
                // before the scanline timer.
                m.dsp_ticks_=2191953980ull;
                m.target_ticks_=2191954030ull;
                m.main_limit_=136997126ull;
                m.last_main_=136997125ull;
                m.boost_expiry_ticks_=2191953972ull;
                m.sport_deadline_ticks_=2192180920ull;
                m.sport_irq1_clear_ticks_=0ull;
                m.next_scanline_ticks_=2191954050ull;
                m.next_sound_ticks_=2192000000ull;
                m.scanline_events_=346539ull;
                m.sliced_=1ull;
                m.dma_deadline_subticks_=21919790432ull;
                m.dma_completions_=118526ull;
                if(!crossing)m.next_scanline_ticks_+=6325;
                if(timer_cap)m.target_ticks_=2191954100ull;
                d.pm.fill(0xffffff);
                for(const auto pc:k_irq2_code)d.pm[pc]=Firmware(pc);
                for(unsigned n=0;n<d.pc_stack_.size();++n)d.pc_stack_[n]=uint16_t(0x700+n);
                const auto stack=d.pc_stack_;const auto pm=d.pm;const auto dm=d.dm;const auto external=d.external_pm;const auto control=d.control;
                m.MainInstruction(timer_cap?136997130:136997128,write,0xff5a);
                check(d.pm==pm && d.dm==dm && d.external_pm==external && d.control==control,
                    "host-write timer ordering changes unrelated DSP memories");
                if(timer_cap){
                    // Synthetic limit control: both the opcode end and old quantum exceed the timer.
                    check(d.pc==0x131 && d.cycles==start+7 && m.dsp_ticks_==2191954050ull &&
                        d.pc_stack_==stack && m.link.Control()==0x400 && m.link.Irq2Asserted() &&
                        m.scanline_events_==346540,"host write catches DSP past the next timer");
                }else if(write && crossing){
                    check(mk2::WordsDigest(d.Registers())==k_irq2.rows[k_irq2.steps-1],
                        "scanline consumes old idle instructions before queued host IRQ2");
                    auto expected_stack=stack;expected_stack[0]=0x132;
                    check(d.pc_stack_==expected_stack && d.interrupt_.pc==0x132 && d.interrupt_.mstat==k_irq2.start[8] &&
                        d.interrupt_.imask==k_irq2.start[9] && d.interrupt_.astat==irq2_astat && m.link.Control()==0x400 && m.link.Irq2Asserted(),
                        "IRQ2 bank/return state or input latch differs from Original");
                    check(m.SchedulerClocks()==std::array<uint64_t,13>{2191954050ull,2191954100ull,136997131,136997128,2191954500ull,2192180920ull,0,2191960375ull,2192000000ull,346540,1,21919790432ull,118526},
                        "host synchronization changes scanline/SPORT/DMA clocks");
                }else if(write){
                    check(d.pc==0x132 && d.cycles==start+5 && d.pc_stack_==stack && m.link.Control()==0x400 &&
                        m.link.Irq2Asserted() && m.scanline_events_==346539,"no-timer host write loses its old slice boundary");
                }else{
                    check(d.pc==0x131 && d.cycles==start+7 && d.pc_stack_==stack && m.link.Control()==0xc00 &&
                        !m.link.Irq2Asserted() && m.scanline_events_==346540,"ordinary timer spuriously dispatches IRQ2");
                }
            };
            replay(true,true);replay(true,false);replay(false,true);replay(true,true,true);
        }

        dsp.i[0] = 0x111; dsp.i[4] = 0x4234;
        step(dsp, 0x1d5);
        check(dsp.pc == 0x234 && dsp.pc_sp == 0, "indirect jump uses masked I4 without inventing a call frame");
        dsp.cntr = 0x1234; dsp.cntr_sp = 2; dsp.sstat = 0x51;
        step(dsp, 0x955);
        check(dsp.ay0 == 0x1234 && dsp.cntr_sp == 2, "reading CNTR does not pop its counter stack");
        dsp.ar = 0xc123;
        step(dsp, 0x957);
        check(dsp.cntr == 0x123 && dsp.cntr_sp == 2 && dsp.sstat == 0x51,
              "counter overwrite masks fourteen bits without pushing or changing SSTAT");
        dsp.m[6] = -1;
        step(dsp, 0x942);
        check(dsp.cntr == 0x3fff && dsp.cntr_sp == 3 && dsp.counters_[2] == 0x123,
              "normal counter write preserves the previous CNTR on its physical stack");
        dsp.ar = 0xab56;
        step(dsp, 0x366);
        check(dsp.px == 0x56 && dsp.ar == 0xab56, "internal PX write truncates to eight bits");
        dsp.dm[0x1fd] = 0xab56;
        step(dsp, 0x4e);
        check(dsp.px == 0x56 && dsp.accesses.back().value == 0xab56 &&
              dsp.accesses.back().address == 0x39fd, "DM-to-PX keeps the full physical read before truncation");
        dsp.astat = 0x95; dsp.si = 0x8001; dsp.se = 0xffff; dsp.ar = 0x3456;
        step(dsp, 0x965);
        check(dsp.sr1 == 0 && dsp.sr0 == 0x4000 && dsp.mr0 == 0x3456 && dsp.astat == 0x95,
              "shift with internal move uses old SI/SE then copies AR to MR0 without changing flags");
        dsp.si = 0x8001; dsp.se = 0xffff; dsp.sr1 = 0x1234; dsp.sr0 = 0x20; dsp.mr2 = 0x7f;
        step(dsp, 0x945);
        check(dsp.sr1 == 0x1234 && dsp.sr0 == 0x4020 && dsp.se == 0x7f && dsp.astat == 0x95,
              "parallel shift uses old SE before the move changes SE");
        dsp.si = 0x8001; dsp.se = 0xffff; dsp.i[1] = 0x3800; dsp.m[1] = 1; dsp.dm[0] = 0x1234;
        step(dsp, 0x944);
        check(dsp.sr1 == 0x4000 && dsp.sr0 == 0x8000 && dsp.si == 0x1234 && dsp.i[1] == 0x3801 &&
              dsp.astat == 0x95, "DAG read occurs after the shift of original SI and modifies its address once");
        dsp.si = 0x8001; dsp.se = 0xffff; dsp.ar = 0x3456; dsp.i[0] = 0x3800; dsp.m[0] = 1;
        step(dsp, 0xa2a);
        check(dsp.dm[0] == 0x3456 && dsp.sr0 == 0x4000 && dsp.sr1 == 0 && dsp.i[0] == 0x3801,
              "DAG write stores original AR and performs the low logical shift");
        for (const auto vector : {std::array<uint16_t, 3>{0x8001, 0xe000, 0xffff},
                                  std::array<uint16_t, 3>{0x7fff, 0x1fff, 0}}) {
            dsp.sr0 = vector[0]; dsp.astat = 0x95;
            step(dsp, 0x32c);
            check(dsp.sr0 == vector[1] && dsp.sr1 == vector[2] && dsp.astat == 0x95,
                  "arithmetic low shift sign extends the old aliased SR0 and leaves ASTAT unchanged");
        }
        for (uint8_t mode : {uint8_t(0), uint8_t(4)}) {
            dsp.sr0 = 0xffff; dsp.astat = 0xff; dsp.mstat = mode;
            step(dsp, 0x38e);
            check(dsp.af == 0 && dsp.astat == (mode ? 0xf5 : 0xf1),
                  "NOT SR0 to AF recalculates NZC and respects sticky overflow without saturation");
        }
        dsp.i[0] = 0x3800; dsp.m[0] = 1; dsp.dm[0] = 0x1234;
        step(dsp, 0x375);
        check(dsp.dm[0] == 0 && dsp.i[0] == 0x3801 && dsp.accesses.back().value == 0,
              "immediate DAG write keeps the real memory lane and one address modification");
        dsp.mstat = 8; dsp.ax0 = 0; dsp.ax1 = 0;
        dsp.external_pm[0x605] = 0x1b8000; dsp.external_pm[0x350] = 0;
        dsp.i[1] = 0x350; dsp.i[2] = 0x370; dsp.m[0] = 0;
        step(dsp, 0x2c7);
        step(dsp, 0x2c8);
        check(dsp.ar == 0x1b80 && dsp.af == 0 && dsp.ay1 == 0 && (dsp.astat & 1),
              "parallel ALU to AF preserves original AR before reading AY1 from its DAG");
        step(dsp, 0x2c9);
        check(dsp.pc == 0x2d4, "original zero-result branch reaches the measured volume update");
        step(dsp, 0x2d4); step(dsp, 0x2d5);
        step(dsp, 0x2d6);
        check(dsp.ar == 0x1b80 && dsp.af == 0 && dsp.accesses.back().address == 0x370 &&
              dsp.accesses.back().value == 0x1b80,
              "parallel DAG write uses retained AR then ALU updates AF without overwriting AR");
        step(dsp, 0x2d7); check(dsp.pc == 0x2d8, "original AF zero result keeps the volume history write");
        step(dsp, 0x2d8);
        check(dsp.accesses.back().address == 0x350 && dsp.accesses.back().value == 0x1b80,
              "original following write retains the complete volume history value");
        dsp.ax1 = 0x7fff; dsp.af = 0xffff; dsp.i[0] = 0x3800; dsp.dm[0] = 0x1234;
        step(dsp, 0x173);
        check(dsp.af == 0x8000 && dsp.ar == 0x1b80 && dsp.ax1 == 0x1234 && (dsp.astat & 15) == 6,
              "ALU-to-AF never saturates under MSTAT8 and reads old operands before its parallel move");
        {
            mk2::DcsLink banks_link;
            mk2::AdspBoot banks(boot, banks_link, rom);
            banks.trace.push_back(banks.Registers());
            // {bank latch, DM address}; the 16 low bytes read back are checked by SHA-256 only.
            const uint16_t latches[] = {0x000, 0x080, 0x0ff, 0x100, 0x180, 0x200, 0x300, 0x400, 0x500, 0x5ff, 0x600, 0x680, 0x700, 0x7ff, 0xffff, 0x0800};
            const bool window_end[] = {0, 0, 0, 0, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0};  // DM 0x2fff, else 0x2000
            std::vector<uint8_t> low;
            for (unsigned n = 0; n < 16; ++n) {
                banks.WriteData(0x3000, latches[n]);
                check(banks.rom_bank == (latches[n] & 0x7ff) && banks.DeviceState()[0] == banks.rom_bank &&
                      banks.accesses.back().value == latches[n], "six-socket bank latch differs from the board");
                const uint16_t value = banks.ReadData(window_end[n] ? 0x2fff : 0x2000);
                check((value >> 8) == 0xff,
                      "modulo lookup keeps the FF high byte of the board");
                low.push_back(uint8_t(value));
            }
            check(Sha256(low) == "c0eaddde620f7e875b45a33f3ca532bd858016ecbaf2c8f56b339a4591b54582",
                  "every banked ROM reload matches the authenticated ROMs");
            for (unsigned socket = 0; socket < 6; ++socket) {
                auto changed = rom; changed[(socket + 1) * 0x80000 - 1] ^= 1;
                bool rejected = false;
                try { mk2::AdspBoot invalid(boot, banks_link, changed); }
                catch (const std::runtime_error&) { rejected = true; }
                check(rejected, "every sound socket must authenticate before DSP construction");
            }
            mk2::DcsLink reload_link;
            mk2::AdspBoot reload(boot, reload_link, rom);
            reload.WriteData(0x3000, 1);
            reload.WriteControl(0x3fff, 0x0208);
            check(reload.ApplyPendingReset() && reload.pm[0] == U2Word(0x1000),
                  "bank-one software boot loads low firmware before its reset vector");
            reload.Step();
            check(reload.pc == 8 && reload.cycles == 1, "bank-one reset dispatches low firmware");
            reload.WriteData(0x3000, 0);
            reload.WriteControl(0x3fff, 0x0208);
            check(reload.ApplyPendingReset() && reload.pm[0] == U2Word(0),
                  "bank-zero software boot reloads first-boot firmware");
            reload.Step();
            check(reload.pc == 0x22 && reload.cycles == 1 && reload.boot_reloads == 2,
                  "bank-zero reset dispatches first-boot firmware");

            // The timed Original comparison is separate. Run the authenticated boot to the checksum loop.
            mk2::DcsLink checksum_link;
            mk2::AdspBoot checksum(boot, checksum_link, rom);
            checksum.SetTraceObservation(false);
            checksum.main_horizon_ = 10500000;
            auto advance_to = [&](uint16_t pc, uint64_t limit) {
                while (checksum.pc != pc && checksum.cycles < limit) {
                    checksum.Step();
                    if (checksum.accesses.size() > 4096) checksum.DiscardObservedAccesses();
                }
                if (checksum.pc != pc) throw std::runtime_error("checksum boot did not reach PC " +
                    std::to_string(pc) + "; current PC " + std::to_string(checksum.pc));
            };
            auto send = [&](uint16_t value) {
                checksum_link.HostWrite(0x01d01030, value);
                checksum_link.Synchronize();
            };
            auto reject_irq = [&] {
                const auto state = checksum.ExecutionState();
                const auto bus = checksum_link.ExecutionState();
                const auto accesses = checksum.AccessCount();
                bool rejected = false;
                try { checksum.Step(); }
                catch (const std::runtime_error& error) {
                    rejected = std::string(error.what()).find("ADSP IRQ entry outside translated boot scope") == 0;
                }
                check(rejected && checksum.ExecutionState() == state && checksum_link.ExecutionState() == bus &&
                      checksum.AccessCount() == accesses, "checksum IRQ rejection preserves CPU and bus state");
            };
            // Host words are synthetic: the checksum loops never read the latch outside the IRQ handler, which only
            // moves its low byte.
            send(0xff3c);
            advance_to(0x90, 16000000);
            for (const auto& event : std::array<std::array<uint16_t, 2>, 2>{{{0x90, 0xff5a}, {0x8e, 0xffa5}}}) {
                const auto pc = event[0];
                advance_to(pc, checksum.cycles + 32);
                send(event[1]);
                checksum.pm[pc] ^= 1;
                reject_irq();
                checksum.pm[pc] ^= 1;
                const auto cycle = checksum.cycles;
                const auto astat = checksum.astat;
                const auto stacks = checksum.ActiveStacks();
                for (unsigned n = 0; n < 6; ++n) checksum.Step();
                check(!checksum.accesses.empty(), "checksum IRQ performs a DCS latch read");
                const auto& input = checksum.accesses.back();
                check(!checksum_link.Irq2Asserted() && input.pc == 0x172 && input.address == 0x3400 &&
                      input.value == (event[1] & 0xffu) && input.cycle == cycle + 5 && input.space == 'r',
                      "checksum IRQ handler acknowledges the exact DCS input latch on its sixth cycle");
                for (unsigned n = 0; n < 4; ++n) checksum.Step();
                check(checksum.pc == pc && checksum.cycles == cycle + 10 && checksum.ActiveStacks() == stacks &&
                      checksum.astat == astat && checksum.mstat == 0x10 && checksum.imask == 0x24,
                      "checksum RTI restores suspended PC, stacks and status in ten cycles");
            }
            advance_to(0x91, checksum.cycles + 32);
            send(0xff5a);
            reject_irq();

            // General Test replay, run only on request: `--service <timeline>`. Open: it stops at the first untranslated
            // first-boot DSP PC 164 (0xa4) until the generator covers the General Test path, and the timeline comes from
            // a local MAME capture of the General Test (host writes and DCS outputs; no capture tool yet). Git keeps only
            // the SHA-256 of the timeline (plan 5.1, 16/11/2026, phase 7 part 11).
            if (argc == 4) {
                // Local file, decimal words: initial cycle and write; edge count, {cycle, write} per edge; first checksum
                // write cycle, TMS instruction-end count, {offset, write or 0} per end; output count, {ticks, DSP cycle,
                // PC, previous control, previous output, output} per DCS output.
                std::vector<uint64_t> timeline;
                {
                    std::ifstream in(argv[3]);
                    uint64_t word = 0;
                    while (in >> word) timeline.push_back(word);
                    check(in.eof() && !in.bad(), "General Test timeline holds only decimal words");
                }
                check(mk2::WordsDigest(timeline) == k_service_timeline_sha256,
                      "General Test timeline differs from the local capture pinned by SHA-256");
                size_t at = 0;
                const auto next = [&] { return timeline.at(at++); };
                // Original General Test. Start held in reset, then replay the captured service writes.
                mk2::DcsBootMachine service(boot, rom);
                service.main_horizon_ = service.dsp.main_horizon_ = 95000000;
                service.dsp.SetTraceObservation(false);
                uint64_t cycles = 0;
                auto finish = [&](uint64_t end, uint16_t data = 0) {
                    service.MainInstruction(end, data != 0, data);
                    cycles = end;
                    if (service.dsp.accesses.size() > 4096) service.dsp.DiscardObservedAccesses();
                };
                auto approach = [&](uint64_t end, unsigned cost) {
                    while (cycles + 100 < end) finish(cycles + 100);
                    while (cycles + cost < end) finish(cycles + 1);
                };
                const auto initial = next();
                finish(initial, uint16_t(next()));
                for (auto edges = next(); edges; --edges) {
                    const auto end = next();
                    approach(end, 3);
                    finish(end, uint16_t(next()));
                }
                // Both checksum IRQ2 writes and the TMS instruction ends between them.
                const auto first = next();
                approach(first, 3);
                for (auto ends = next(); ends; --ends) {
                    const auto offset = next();
                    finish(first + offset, uint16_t(next()));
                }

                const auto check_output = [&](uint64_t ticks, uint64_t dsp_cycle, uint16_t pc,
                                              uint16_t old_status, uint8_t old_value, uint8_t value) {
                    approach(ticks / 16, 1);
                    finish(ticks / 16);
                    check(service.NextTimerTicks() > ticks + 10, "DCS output test has no competing timer in the instruction");
                    service.RunDspUntil(ticks + 9);
                    check(service.dsp.pc == pc && service.dsp.cycles == dsp_cycle &&
                          service.link.Control() == old_status && service.link.HostReadOutput(false).value == old_value,
                          "DCS output retains its previous latch before the write retires");
                    const auto accesses = service.dsp.AccessCount();
                    service.RunDspUntil(ticks + 10);
                    check(service.dsp.pc == pc + 1 && service.dsp.cycles == dsp_cycle + 1 &&
                          service.dsp.AccessCount() == accesses + 1 && service.dsp.accesses.back().address == 0x3400 &&
                          service.dsp.accesses.back().value == value && service.dsp.accesses.back().space == 'd',
                          "authenticated DCS output instruction writes the physical latch in one cycle");
                    check(service.link.Control() == 0x800 && service.link.HostReadOutput(false).value == value &&
                          !service.link.Irq2Asserted(), "DCS output publishes at instruction retirement before the next fetch");
                };
                for (auto outputs = next(); outputs; --outputs) {
                    const auto ticks = next(), dsp_cycle = next(), pc = next(), old_status = next(), old_value = next();
                    check_output(ticks, dsp_cycle, uint16_t(pc), uint16_t(old_status), uint8_t(old_value), uint8_t(next()));
                }
                check(at == timeline.size(), "General Test timeline has trailing words");
            }

            mk2::AdspBoot u2_only(boot, banks_link, u2);  // U2 alone (global copy of socket one)
            u2_only.trace.push_back(u2_only.Registers());
            bool rejected = false;
            try { u2_only.WriteData(0x3000, 0x100); }
            catch (const std::runtime_error&) { rejected = true; }
            check(rejected && u2_only.rom_bank == 0 && u2_only.accesses.empty(),
                  "legacy U2-only context rejects another socket before bank latch or bus mutation");
        }
        std::cout << "MK2 resumed DSP contracts passed\n";
    } catch (const std::exception& error) { std::cerr << error.what(); return 1; }
}
