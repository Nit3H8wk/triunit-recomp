"""Closed original post-release intervals and cold admission boundaries."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import run,batch_reference,test_coin_pair


class SelectionTests(unittest.TestCase):
    compile_and_run=test_coin_pair.CoinPairPrimitiveTests.compile_and_run

    def test_selection_mode_rejects_mixed_endpoints_before_rom_io(self):
        for call in (lambda:run.run('check',run.ROOT/'roms/mk2',selection_window=0),
                     lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,selection_window=0,start_release=True),
                     lambda:run.run('reset',run.ROOT/'roms/mk2',batch=True,selection_window=0,prestart_window=0),
                     lambda:batch_reference.capture(Path('unused'),selection_window=0,start_input=True)):
            try:
                with self.assertRaises(ValueError):call()
            except TypeError as error:self.fail('Selection endpoint missing: '+str(error))

    def test_six_intervals_keep_measured_boundaries_and_closed_indices(self):
        try:
            from tools.mk2 import generate_selection as selection
        except ImportError as error:self.fail('Selection manifest missing: '+str(error))
        ends=[25032908,26060966,27090324,28004306,29031744,30060282]
        counts=[465650,464865,466299,413320,465493,465734]
        self.assertEqual([(selection.interval(i)['end'],selection.interval(i)['cpu_rows']) for i in range(6)],list(zip(ends,counts)))
        for index in (-1,6,True,'0',None):
            with self.assertRaises(ValueError):selection.interval(index)

    def test_cold_selection_admission_cannot_extend_any_machine_or_board_clock(self):
        self.compile_and_run(r'''
    const auto before=machine->dsp.Registers(),device=machine->dsp.DeviceState();
    const auto io=s.board.io;
    bool rejected=false;
    try { machine->AdmitSelection(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=before ||
       machine->dsp.DeviceState()!=device || s.board.io!=io || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { machine->MainInstruction(24004882); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 2;
''')


if __name__=='__main__':unittest.main()
