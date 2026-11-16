"""Indexed original waiting intervals must retain scope and reject invalid selection."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair as pair_controls
from tools.mk2 import run, batch_reference


class PreStartWaitTests(unittest.TestCase):
    compile_and_run=pair_controls.CoinPairPrimitiveTests.compile_and_run

    def test_cold_prestart_scope_rejects_without_mutating_devices_or_bounds(self):
        self.compile_and_run(r'''
    const auto registers=machine->dsp.Registers();
    const auto device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitPreStartWait(s.board); } catch(const std::runtime_error&) { rejected=true; }
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

    def test_index_zero_is_an_endpoint_and_bad_or_combined_modes_reject(self):
        calls=[lambda:run.run('check',run.ROOT/'roms/mk2',prestart_window=0),
               lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,next_wait=True,prestart_window=0),
               lambda:batch_reference.capture(Path('unused'),start_wait=True,prestart_window=0)]
        for value in (-1,16,True,False,0.0):
            calls.append(lambda value=value:run.run('reset',run.ROOT/'roms/mk2',batch=True,prestart_window=value))
        for call in calls:
            try:
                with self.assertRaises(ValueError):call()
            except TypeError as error:self.fail('Pre-Start index API missing: '+str(error))

    def test_first_and_last_literal_reference_boundaries_and_invalid_indices(self):
        try:
            from tools.mk2 import generate_prestart_wait as generated
        except ImportError as error:self.fail('Measured interval manifest missing: '+str(error))
        self.assertEqual((generated.interval(0)['start'],generated.interval(0)['end'],generated.interval(0)['cpu_rows']),(6087360,7005800,392474))
        self.assertEqual((generated.interval(15)['start'],generated.interval(15)['end']),(21051634,22081952))
        for value in (-1,16,True,False,0.0):
            with self.assertRaises(ValueError):generated.interval(value)


if __name__=='__main__':unittest.main()
