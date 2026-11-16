"""Observation may be omitted by presentation without changing native execution."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair


class ContinuationObservationTests(unittest.TestCase):
    compile_and_run = test_coin_pair.CoinPairPrimitiveTests.compile_and_run

    def test_shared_host_controls_use_mk2_ports_without_phantom_service_or_volume(self):
        self.compile_and_run(r'''
    // Independent wiring table: host bit -> MK2 port/mask, from the pinned input table.
    constexpr unsigned port[32]={0,0,0,0,0,0,0,3,0,0,0,0,0,0,0,3,
                                 1,1,1,3,3,1,3,3,3,2,2,3,2,2,3,3};
    constexpr uint16_t mask[32]={1,2,4,8,16,32,64,0,256,512,1024,2048,4096,8192,16384,0,
                                1,2,4,0,0,32,0,0,0,16,32,0,1,2,0,0};
    for(unsigned bit=0;bit<32;++bit) {
        mk2::BoardBootControls board;board.io[8]=0x2000;board.io[7]=288;
        board.SetHostInputs(~(uint32_t(1)<<bit),1);
        board.AdvanceScanlines(275);
        std::array<uint16_t,3> expected{0xffff,0xffff,0xffff};
        if(port[bit]<3) expected[port[bit]]^=mask[bit];
        if(board.input0!=expected[0] || board.input1!=expected[1] || board.input2!=expected[2] ||
           board.dip_switches!=0xfc7d || board.ReadBootInput(0x01600000)!=expected[0] ||
           board.ReadBootInput(0x01600010)!=expected[1] || board.ReadBootInput(0x01600020)!=expected[2]) return 1;
    }
    mk2::BoardBootControls all;all.io[8]=0x2000;all.io[7]=288;
    all.SetHostInputs(0,1);all.AdvanceScanlines(275);
    if(all.input0!=0x8080 || all.input1!=0xffd8 || all.input2!=0xffcc) return 2;
''')

    def test_host_requests_latch_on_original_frame_edge_and_reject_script_mixing(self):
        self.compile_and_run(r'''
    auto& board=s.board;board.io[7]=288;
    board.SetHostInputs(0,1);
    board.AdvanceScanlines(274);
    if(board.input0!=0xffff || board.input1!=0xffff || board.input2!=0xffff ||
       board.input_events.size()!=1) return 1;
    board.AdvanceScanlines(275);
    if(board.input0!=0x8080 || board.input1!=0xffd8 || board.input2!=0xffcc ||
       board.input_events.size()!=2 || board.input_events.back()[0]!=1827925 ||
       board.input_events.back()[3]!=7) return 2;
    const auto events=board.input_events;
    bool rejected=false;try {board.SetHostInputs(0xffffffff,0);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || board.input_events!=events) return 3;
    for(unsigned control=0;control<3;++control) {
        rejected=false;try {
            if(control==0)board.SetP1HighPunch(true,1827926);
            else if(control==1)board.SetCoin1(true,1827926);
            else board.SetStart1(true,1827926);
        }catch(const std::runtime_error&){rejected=true;}
        if(!rejected || board.input_events!=events || board.requested_p1_high_punch ||
           board.requested_coin1 || board.requested_start1) return 4;
    }
    board.SetHostInputs(0xffffffff,1827926);board.AdvanceScanlines(563);
    if(board.input0!=0x8080 || board.input_events.size()!=3) return 5;
    board.AdvanceScanlines(564);
    if(board.input0!=0xffff || board.input1!=0xffff || board.input2!=0xffff ||
       board.input_events.size()!=4 || board.input_events.back()[0]!=3655850) return 6;
    board.SetHostInputs(0xffffffff,3655851);board.AdvanceScanlines(853);
    if(board.input_events.size()!=5) return 7; // No physical edge when held released.
    mk2::BoardBootControls scripted;scripted.SetCoin1(false,0);
    rejected=false;try {scripted.SetHostInputs(0,1);}catch(const std::runtime_error&){rejected=true;}
    if(!rejected || scripted.input_events.size()!=1 || scripted.input1!=0xffff) return 8;
''')

    def test_consuming_dsp_access_history_keeps_absolute_positions_and_device_state(self):
        self.compile_and_run(r'''
    auto& dsp=machine->dsp;
    dsp.accesses.push_back({0,0x100,0x1234,0,'d'});
    dsp.accesses.push_back({0,0x101,0x5678,0,'d'});
    const auto registers=dsp.Registers(),device=dsp.DeviceState();
    if(dsp.AccessCount()!=2) return 1;
    dsp.DiscardObservedAccesses();
    if(!dsp.accesses.empty() || dsp.AccessCount()!=2 || dsp.Registers()!=registers ||
       dsp.DeviceState()!=device) return 2;
    dsp.accesses.push_back({0,0x102,0x9abc,0,'d'});
    if(dsp.AccessCount()!=3) return 3;
    dsp.DiscardObservedAccesses();dsp.DiscardObservedAccesses();
    if(!dsp.accesses.empty() || dsp.AccessCount()!=3 || dsp.Registers()!=registers ||
       dsp.DeviceState()!=device) return 4;
''')

    def test_bus_and_checkpoints_are_optional_and_default_to_complete_observation(self):
        self.compile_and_run(r'''
    if(!out->observe_history) return 1;
    o.Record('r',0x01000000,0x1234);o.Checkpoint("before");
    if(out->bus.size()!=1 || out->points.size()!=1) return 2;
    const auto cpu=s;const auto dsp=machine->dsp.Registers();
    out->observe_history=false;
    o.Record('w',0x01000010,0x5678);o.Checkpoint("omitted");
    if(out->bus.size()!=1 || out->points.size()!=1 || s.next_pc!=cpu.next_pc ||
       s.status!=cpu.status || s.cycles!=cpu.cycles || s.instructions!=cpu.instructions ||
       s.a!=cpu.a || s.b!=cpu.b || machine->dsp.Registers()!=dsp) return 3;
    out->observe_history=true;
    o.Record('w',0x01000010,0x5678);o.Checkpoint("after");
    if(out->bus.size()!=2 || out->points.size()!=2) return 4;
''')


if __name__ == '__main__':
    unittest.main()
