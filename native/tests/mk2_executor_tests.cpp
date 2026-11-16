// Generated executor from reset: full-state SHA-256 at each requested (PC, cycle) and at the delivery boundary.
// usage: mk2_executor_tests ROM_DIRECTORY DSW_HEX CMOS_IMAGE|- [PC:CYCLE ...]
//        mk2_executor_tests ROM_DIRECTORY DSW_HEX - trap-vector
//        mk2_executor_tests ROM_DIRECTORY DSW_HEX - display-irq
#include "native/mk2/mk2_executor.hpp"
#include "native/mk2/mk2_dcs.hpp"
#include "native/tests/mk2_state_digest.hpp"
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>

int main(int argc,char** argv) { try {
    if (argc<4) throw std::runtime_error("usage: mk2_executor_tests ROMS DSW CMOS|- [PC:CYCLE ...]");
    const auto program=mk2::LoadProgram(argv[1]);
    const auto rom=mk2::LoadDcsDataRoms(argv[1]);
    const auto boot=mk2::DecodeDcsBoot({rom.begin(),rom.begin()+0x1000});
    const auto dsw=uint16_t(std::stoul(argv[2],nullptr,16));
    std::vector<uint8_t> image;
    const bool cold=std::string(argv[3])=="-";
    if (!cold) {
        std::ifstream input(argv[3],std::ios::binary);
        if (!input) throw std::runtime_error("cannot open CMOS image");
        image.assign(std::istreambuf_iterator<char>(input),{});
    }
    auto machine=std::make_unique<mk2::DcsBootMachine>(boot,rom);
    machine->dsp.SetTraceObservation(false);
    mk2::GeneratedBoot generated(program,*machine,cold?nullptr:&image,dsw);
    if (argc==5 && std::string(argv[4])=="trap-vector") {
        // First cold drawing TRAP, reached by the executor from the user's ROMs: every vector byte is checked
        // before the stack, flags, bus, clock or instruction count change.
        generated.RunToPc(0xff8044f0);
        auto& state=generated.State();
        auto& s=state.ready;
        mk2::Program changed=program;
        mk2::BootOps o(changed,*machine,state);
        const size_t vector=(0xffffffc0u-0xff800000u)/8;
        const auto before=s;const auto bus=state.bus.size();const auto clocks=machine->LastMainCycles();
        for (unsigned n=0;n<4;++n) {
            changed.bytes[vector+n]^=1;bool rejected=false;
            try{o.TrapOne(0xff8045d0,0xff804500);}
            catch(const std::runtime_error& e){rejected=std::string(e.what())=="MK2 drawing TRAP vector is not authenticated";}
            if(!rejected || s.next_pc!=before.next_pc || s.cycles!=before.cycles || s.status!=before.status ||
               s.a!=before.a || s.b!=before.b || state.bus.size()!=bus || machine->LastMainCycles()!=clocks ||
               s.instructions!=before.instructions) throw std::runtime_error("TRAP vector byte not checked first");
            changed.bytes[vector+n]^=1;
        }
        // The same context with one field changed leaves the qualified set before any push or status change.
        if (s.cycles!=1259215) throw std::runtime_error("first cold drawing TRAP left its measured cycle");
        for (unsigned field=0;field<6;++field) {
            auto invalid=std::make_unique<mk2::BootContinuation>(state);
            auto& r=invalid->ready;
            if (field==0) r.next_pc+=16;
            if (field==1) ++r.cycles;
            if (field==2) r.status^=1;
            if (field==3) r.a[15]+=16;
            if (field==4) r.board.io[17]^=2;
            if (field==5) r.board.io[18]=2;
            const auto sp=r.a[15];
            mk2::BootOps rejected_ops(program,*machine,*invalid);
            bool rejected=false;
            try{rejected_ops.TrapOne(0xff8045d0,0xff804500);}
            catch(const std::runtime_error& e){rejected=std::string(e.what())=="MK2 TRAP outside qualified drawing context";}
            if (!rejected || invalid->bus.size()!=bus || r.a[15]!=sp || machine->LastMainCycles()!=clocks)
                throw std::runtime_error("changed TRAP context accepted or mutated before rejection");
        }
        std::cout<<"trap-vector 4 6"<<std::endl;
        return 0;
    }
    if (argc==5 && std::string(argv[4])=="display-irq") {
        // Cold asynchronous display IRQs, (PC, cycle) of the Original; ST, SP and IO17/18 come from the executor
        // (nothing observed is versioned). Each context passes the guard (stopping at the absent vector), every changed
        // field rejects before stack, bus or clock mutation, and the last one enters with the real vector.
        static constexpr std::pair<uint32_t,uint64_t> contexts[]={
            {0xff807e60,1256726},{0xff807ea0,2284906},{0xff807e40,2399155},{0xff807ea0,2513396},
            {0xff807dd0,2627642},{0xff807ea0,2741888},{0xff807df0,2856137},{0xff807e20,2970380},
            {0xff807da0,3084623},{0xff807e70,3198869},{0xff807d50,3313133},{0xff807f00,3427359},
            {0xff807ea0,3541606},{0xff807da0,3655853}};
        auto& state=generated.state_;
        auto& s=state.ready;
        mk2::BootOps o(program,*machine,state);
        const mk2::Program missing;
        uint32_t previous_pc=0;uint64_t previous_cycle=0;
        unsigned checked=0;
        for (const auto& [pc,cycle] : contexts) {
            while (!(s.next_pc==pc && s.cycles==cycle)) {
                if (s.cycles>cycle) throw std::runtime_error("executor passed display IRQ context "+std::to_string(cycle));
                while (generated.next_<generated.boundaries_.size()) {
                    const auto& b=generated.boundaries_[generated.next_];
                    if (s.next_pc!=b.pc || (b.cycle && s.cycles!=b.cycle)) break;
                    generated.Apply(b);++generated.next_;
                }
                previous_pc=s.next_pc;previous_cycle=s.cycles;
                if (!generated.Delivered()) { generated.Step(o); continue; }
                // After the first draw the cold batch takes display IRQs through DisplayInterrupt (mk2_task_batch.cpp)
                // and runs the same generated closure; the guard below proves each context equals the Original's.
                if ((s.status&0x00200000) && (s.board.io[17]&s.board.io[18])) o.DisplayInterrupt();
                try { if (!mk2::ExecuteGeneratedInstruction(o)) throw std::runtime_error("MK2 PC outside the generated closure"); }
                catch (const std::exception& e) { throw std::runtime_error(std::string(e.what())+"; cycle "+std::to_string(s.cycles)); }
                // Legal coin input of the cold route (mk2_task_batch.cpp coin queue and accounting windows).
                if (!s.board.requested_coin1 && s.board.input_events.size()==4 && s.cycles*16>=51181900)
                    s.board.SetCoin1(true,51181900);
                if (s.board.input_events.size()==6 && s.cycles*16>=54837750) s.board.SetCoin1(false,54837750);
            }
            if (!(s.status&0x00200000) || !(s.board.io[17]&s.board.io[18]))
                throw std::runtime_error("display IRQ context without an enabled pending interrupt");
            const auto bus=state.bus.size();const auto clocks=machine->LastMainCycles();
            auto expect=[&](mk2::BootContinuation& copy,const mk2::Program& p,const char* message) {
                const auto before=copy.ready;
                mk2::BootOps ops(p,*machine,copy);
                bool rejected=false;
                try{ops.DisplayInterrupt();}catch(const std::runtime_error& e){rejected=std::string(e.what())==message;}
                const auto& after=copy.ready;
                if (!rejected || copy.bus.size()!=bus || machine->LastMainCycles()!=clocks || after.a!=before.a ||
                    after.status!=before.status || after.next_pc!=before.next_pc || after.cycles!=before.cycles)
                    throw std::runtime_error(std::string("display IRQ check failed: ")+message+"; cycle "+std::to_string(cycle));
            };
            {auto copy=std::make_unique<mk2::BootContinuation>(state);expect(*copy,missing,"MK2 first DI vector is not authenticated");}
            for (unsigned field=0;field<7;++field) {
                auto copy=std::make_unique<mk2::BootContinuation>(state);
                auto& r=copy->ready;
                if (field==0) r.next_pc+=16;
                if (field==1) ++r.cycles;
                if (field==2) r.status^=0x40000000;
                if (field==3) r.status^=1;
                if (field==4) r.a[15]+=16;
                if (field==5) r.a[15]+=32;
                if (field==6) r.board.io[17]^=2;
                expect(*copy,missing,"MK2 asynchronous DI outside qualified polling contexts");
            }
            ++checked;
        }
        // Real vector: pushes next PC then the unmodified status, reads the vector and charges sixteen cycles; the
        // lanes carry the preceding instruction's PC and cycle (debugger cache), no instruction is invented.
        state.observe_history=true;state.bus.clear();
        const auto pc=s.next_pc;const auto status=s.status;const auto sp=s.a[15];
        const auto cycle=s.cycles;const auto instructions=s.instructions;
        o.DisplayInterrupt();
        const std::array<std::array<uint32_t,2>,6> lanes{{{sp-32,pc&0xffff},{sp-16,pc>>16},{sp-64,status&0xffff},
            {sp-48,status>>16},{0xfffffea0,0x6370},{0xfffffeb0,0xff81}}};
        bool entered=s.next_pc==0xff816370 && s.status==0x10 && s.cycles==cycle+16 && s.a[15]==sp-64 &&
            s.instructions==instructions && state.bus.size()==6 && machine->LastMainCycles()==s.cycles;
        for (unsigned n=0;entered && n<6;++n)
            entered=state.bus[n].address_bit==lanes[n][0] && state.bus[n].value==lanes[n][1] &&
                state.bus[n].pc==previous_pc && state.bus[n].cycle==previous_cycle && state.bus[n].kind==(n<4?'w':'r');
        if (!entered) throw std::runtime_error("display IRQ entry differs at the last context");
        std::cout<<"display-irq "<<checked<<std::endl;
        return 0;
    }
    for (int n=4;n<argc;++n) {
        const std::string point=argv[n];
        const auto colon=point.find(':');
        const auto pc=uint32_t(std::stoul(point.substr(0,colon)));
        const auto cycle=std::stoull(point.substr(colon+1));
        generated.RunTo(pc,cycle);
        std::cout<<pc<<' '<<cycle<<' '<<mk2test::StateDigest(generated.State(),*machine)<<'\n';
    }
    // A boundary already passed is rejected instead of being approximated.
    bool rejected=false;
    try { generated.RunTo(generated.State().ready.next_pc,generated.State().ready.cycles-1); } catch (const std::runtime_error&) { rejected=true; }
    if (!rejected) throw std::runtime_error("executor accepted a passed boundary");
    const auto& delivered=generated.Deliver();
    if (!generated.Delivered()) throw std::runtime_error("executor stopped before its delivery boundary");
    std::cout<<"deliver "<<delivered.ready.next_pc<<' '<<delivered.ready.cycles<<' '<<mk2test::StateDigest(delivered,*machine)<<'\n';
} catch (const std::exception& e) { std::cerr<<e.what()<<'\n'; return 1; } }
