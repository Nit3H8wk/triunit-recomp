"""Next original wait cannot grant execution scope to an unrelated machine."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair as pair_controls
from tools.mk2 import run, batch_reference


class NextWaitAdmissionTests(unittest.TestCase):
    compile_and_run = pair_controls.CoinPairPrimitiveTests.compile_and_run

    def test_cold_next_wait_rejects_atomically_and_preserves_default_limits(self):
        self.compile_and_run(r'''
    const auto before=machine->dsp.Registers();
    const auto device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitNextWait(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=before ||
       machine->dsp.DeviceState()!=device || s.board.io!=io || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { s.board.HorizontalCount(6087361); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected) return 2;
    rejected=false;
    try { machine->MainInstruction(6087361); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles() || machine->dsp.Registers()!=before) return 3;
''')

    def test_next_wait_rejects_nonbatch_and_mixed_endpoints_before_execution(self):
        calls=(lambda:run.run('check',run.ROOT/'roms/mk2',next_wait=True),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,start_wait=True,next_wait=True),
               lambda:batch_reference.capture(Path('unused'),start_wait=True,next_wait=True))
        for call in calls:
            try:
                with self.assertRaises(ValueError): call()
            except TypeError as error:
                self.fail('Next wait API is missing: '+str(error))


if __name__ == '__main__':
    unittest.main()
