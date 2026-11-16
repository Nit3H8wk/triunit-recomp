"""Legal Start request, independent IN1 latch and fixed new endpoint guards."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair as pair_controls,run,batch_reference


class StartInputTests(unittest.TestCase):
    compile_and_run=pair_controls.CoinPairPrimitiveTests.compile_and_run

    def test_start_frame_latch_preserves_coin_and_rejects_backwards_requests(self):
        self.compile_and_run(r'''
    s.board.io[7]=288;
    s.board.SetCoin1(true,90); s.board.SetStart1(true,100);
    if(s.board.input1!=0xffff || s.board.input_events.size()!=2 ||
       s.board.input_events.back()!=std::array<uint64_t,4>{100,1,0xffff,4}) return 1;
    s.board.AdvanceScanlines(274);
    if(s.board.input1!=0xffff || s.board.input_events.size()!=2) return 2;
    s.board.AdvanceScanlines(275);
    if(s.board.input1!=0xfffa || s.board.input_events.size()!=4 ||
       s.board.input_events[2]!=std::array<uint64_t,4>{1827925,1,0xfffe,3} ||
       s.board.input_events[3]!=std::array<uint64_t,4>{1827925,1,0xfffa,5}) return 3;
    s.board.SetStart1(false,1828000); s.board.AdvanceScanlines(563);
    if(s.board.input1!=0xfffa || s.board.input_events.size()!=5) return 4;
    s.board.AdvanceScanlines(564);
    if(s.board.input1!=0xfffe || !s.board.requested_coin1 || s.board.requested_start1 ||
       s.board.input_events.back()!=std::array<uint64_t,4>{3655850,0,0xfffe,5}) return 5;
    const auto events=s.board.input_events;
    bool rejected=false;
    try { s.board.SetStart1(true,3655849); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || s.board.requested_start1 || s.board.input1!=0xfffe ||
       s.board.input_events!=events) return 6;
''')

    def test_cold_start_input_admission_rejects_without_mutation(self):
        self.compile_and_run(r'''
    const auto registers=machine->dsp.Registers(),device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitStartInput(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=registers ||
       machine->dsp.DeviceState()!=device || s.board.io!=io || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { s.board.HorizontalCount(7005801); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected) return 2;
    rejected=false;
    try { machine->MainInstruction(7005801); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 3;
''')

    def test_start_mode_conflicts_reject_and_manifest_has_measured_literals(self):
        calls=[lambda:run.run('check',run.ROOT/'roms/mk2',start_input=True),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,start_input=True,prestart_window=0),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,start_input=True,next_wait=True),
               lambda:batch_reference.capture(Path('unused'),start_input=True,prestart_window=0)]
        for call in calls:
            try:
                with self.assertRaises(ValueError):call()
            except TypeError as error:self.fail('Start input API missing: '+str(error))
        try:
            from tools.mk2 import generate_start_input as generated
        except ImportError as error:self.fail('Measured Start manifest missing: '+str(error))
        self.assertEqual((generated.START,generated.END,generated.CPU_ROWS,generated.PHYSICAL_ROWS),
                         (22081952,23108559,439431,813947))


if __name__=='__main__':unittest.main()
