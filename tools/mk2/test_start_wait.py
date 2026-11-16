"""Post-C7 admission must not grant capabilities to an unrelated cold machine."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import test_coin_pair as pair_controls
from tools.mk2 import generate_video_irq as generated
from tools.mk2 import run, batch_reference


class StartWaitAdmissionTests(unittest.TestCase):
    compile_and_run = pair_controls.CoinPairPrimitiveTests.compile_and_run

    def test_wait_requires_one_native_batch_and_rejects_old_capture_windows(self):
        with self.assertRaises(ValueError):
            run.run('check',run.ROOT/'roms/mk2',start_wait=True)
        with self.assertRaises(ValueError):
            run.run('reset',run.ROOT/'roms/mk2',batch=True,coin_pair=True,start_wait=True)
        with self.assertRaises(ValueError):
            batch_reference.capture(run.ROOT,start_wait=True,window=batch_reference.PAIR_FILE_WINDOWS[0])

    def test_andn_clears_only_source_bits_and_changes_only_zero_flag(self):
        try:
            instruction=generated.emit_instruction(0x100,16,'ANDN A0,A1',(0x5201,),{0x110},{})
        except ValueError as error:
            self.fail('Measured ANDN cannot be translated: '+str(error))
        self.compile_and_run(r'''
    s.status=0xf0200030; s.a[0]=0xf0; s.a[1]=0x800000ff;
''' + instruction + r'''
    if(s.a[0]!=0xf0 || s.a[1]!=0x8000000f || s.status!=0xd0200030 || s.cycles!=1) return 1;
    s.status=0xd0200030; s.a[0]=0xffffffff; s.a[1]=0x8000000f;
''' + instruction + r'''
    if(s.a[1] || s.status!=0xf0200030 || s.cycles!=2) return 2;
''')

    def test_unqualified_wait_rejects_atomically_and_keeps_default_bounds(self):
        self.compile_and_run(r'''
    const auto before=machine->dsp.Registers();
    const auto device=machine->dsp.DeviceState();
    bool rejected=false;
    try { machine->AdmitStartWait(s.board); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->CoinPairAdmitted() || s.board.CoinPairAdmitted() ||
       machine->LastMainCycles() || machine->dsp.Registers()!=before ||
       machine->dsp.DeviceState()!=device || !s.board.input_events.empty()) return 1;
    rejected=false;
    try { s.board.HorizontalCount(5077312); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected) return 2;
    rejected=false;
    try { machine->MainInstruction(3658092); } catch(const std::runtime_error&) { rejected=true; }
    if(!rejected || machine->LastMainCycles()) return 3;
''')


if __name__ == '__main__':
    unittest.main()
