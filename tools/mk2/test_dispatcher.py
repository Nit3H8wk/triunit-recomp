"""Dispatcher fixed translation and context-transfer contracts."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g
from tools.mk2 import generate_adsp as adsp


class DispatcherGeneratorTests(unittest.TestCase):
    def test_context_transfer_uses_normalized_mask_and_real_base(self):
        for op,base,words in (("MMFM","A1",(0x09a1,0x1f80)),
                              ("MMTM","A1",(0x0981,0x01f8)),
                              ("MMFM","A12",(0x09ac,0x0080))):
            if base == "A12":
                asm,mask = "MMFM A12,A7", "0x0100"
            else:
                asm,mask = f"{op} {base},A7-A12", "0x01f8"
            code = g.emit_instruction(0x100,32,asm,words,{0x120},{})
            self.assertIn(f"o.{'Mmfm' if op == 'MMFM' else 'Mmtm'}({mask},0x00000120u,false,{base[1:]})",code)

    def test_architectural_context_base_is_not_limited_to_observed_registers(self):
        self.assertIn('false,4',g.emit_instruction(0x100,32,"MMFM A4,A7",(0,0),{0x120},{}))

    def test_phase_endpoint_is_explicit(self):
        code = g.emit_instruction(0x100,16,"NOT A0",(0,),set(),{},end=0x110)
        self.assertIn("0x00000110u",code)
        with self.assertRaises(ValueError):
            g.emit_instruction(0x100,16,"NOT A0",(0,),set(),{},end=0x120)

    def test_task_pc_and_byte_store_keep_original_flags_and_cost(self):
        code = g.emit_instruction(0x100,16,"GETPC A7",(0,),{0x110},{})
        self.assertIn("s.a[7]=0x00000110u",code)
        self.assertNotIn("o.Load",code)
        code = g.emit_instruction(0x100,32,"MOVB A0,*A13(370h)",(0,0),{0x120},{})
        self.assertIn("o.WriteByte((s.a[13]+0x00000370u),s.a[0])",code)
        self.assertIn("0x00000120u,3",code)

    def test_indirect_jump_dispatches_actual_pc_and_unknown_code_rejects(self):
        from tools.mk2.test_coin_pair import CoinPairPrimitiveTests
        code = '{'+g.emit_instruction(0x100,16,"JUMP A7",(0,),{0x200},{0x100:(0x200,)})+'}\n'
        body='s.next_pc=0x100; s.a[7]=0x200;\n'+code
        body+='\nif(s.next_pc!=0x200 || s.cycles!=2 || s.a[7]!=0x200) return 1;\n'
        body+='s.next_pc=0x100; s.a[7]=0x20f;\n'+code
        body+='\nif(s.next_pc!=0x200 || s.cycles!=4 || s.a[7]!=0x20f) return 2;\n'
        body+='s.next_pc=0x100; s.a[7]=0x210; bool rejected=false;\n'+code
        body+='try { switch(s.next_pc) { case 0x200: break; default: throw std::runtime_error("untranslated PC"); } } catch(const std::runtime_error&) { rejected=true; }\n'
        body+='if(!rejected || s.next_pc!=0x210 || s.cycles!=6 || s.a[7]!=0x210) return 3;\n'
        CoinPairPrimitiveTests.compile_and_run(self,body)

    def test_first_task_command_uses_original_firmware_queue_path(self):
        self.assertEqual(adsp.translate(0x183b7f), "pc = 0x03b7;")
        self.assertIn("ReadData(0x05f8)",adsp.translate(0x885f82))
        self.assertIn("l[6] = (0x0010) & 0x3fff",adsp.translate(0x38010a))
        self.assertEqual(adsp.translate(0x7800e9),"WriteDag(6, 5, sr0);")
        self.assertIn("WriteData(0x05f8, i[6])",adsp.translate(0x985f82))

    def test_object_descriptor_offset_copy_costs_five_cycles(self):
        code = g.emit_instruction(0x100,48,"MOVE *A5(40h),*A8(100h),1",(0,0,0),{0x130},{})
        self.assertIn("0x00000130u,5",code)
        self.assertLess(code.index("o.ReadField"),code.index("o.WriteField"))


if __name__ == "__main__":
    unittest.main()
