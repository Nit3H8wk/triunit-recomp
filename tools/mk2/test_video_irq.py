"""Closed offline TMS translation boundaries; no proprietary ROM data required."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g

class VideoIrqGeneratorTests(unittest.TestCase):
    def test_changed_or_missing_program_rejects_before_decoder(self):
        with self.assertRaisesRegex(ValueError, "authenticated"):
            g.generate(b"")

    def test_entry_is_original_long_movi(self):
        code = g.emit_instruction(0x100, 48, "MOVI 81261A8Ch,A0", (0x09e0,0x1a8c,0x8126), {0x130}, {})
        self.assertIn("o.Load(s.a[0],0x81261a8cu,0x00000130u,3)", code)
        self.assertNotIn("o.Clear", code)

    def test_sign_extension_and_immediate_cycle_cost(self):
        code = g.emit_instruction(0x100,32,"MOVI FFFCh,A0",(0x09c0,0xfffc),{0x120},{})
        self.assertIn("0xfffffffcu",code)
        self.assertIn(",2)",code)

    def test_setf_decoder_32_bit_alias_retains_encoded_zero_width_and_sign(self):
        for field in (0,1):
            for sign in (0,1):
                opcode=0x540|(field<<9)|(sign<<5)
                code=g.emit_instruction(0x100,16,f'SETF 20h,{sign},{field}',(opcode,),{0x110},{})
                self.assertEqual(code,f'o.SetField(0x{sign<<5:x},0x00000110u'+(',true'if field else '')+');')
        for width,opcode in ((0x21,0x740),(0x20,0x741),(0x20,0x540),(0x20,0x760)):
            with self.assertRaises(ValueError):
                g.emit_instruction(0x100,16,f'SETF {width:X}h,0,1',(opcode,),{0x110},{})

    def test_dsj_and_dsjs_have_distinct_taken_costs(self):
        for op,size,words,taken,done in (("DSJ",32,(0,0),3,2),("DSJS",16,(0,),2,3)):
            code=g.emit_instruction(0x100,size,op+" A2,100h",words,{0x100,0x100+size},{0x100:(0x100,0x100+size)})
            self.assertIn(f"0x00000100u,{taken}",code)
            self.assertIn(f"0x{0x100+size:08x}u,{done}",code)
            self.assertNotIn("o.Arithmetic",code)

    def test_unobserved_branch_is_explicit_rejection(self):
        code=g.emit_instruction(0x100,16,"JREQ 200h",(0,),{0x110},{0x100:(0x110,)})
        self.assertIn("throw std::runtime_error",code)
        self.assertIn("0x00000110u,1",code)

    def test_memory_pair_orders_reads_before_postincrements_and_stores(self):
        code=g.emit_instruction(0x100,16,"MOVE *A2+,*A3+,1",(0,),{0x110},{})
        self.assertLess(code.index("o.ReadField"),code.index("s.a[2] +="))
        self.assertLess(code.index("s.a[2] +="),code.index("o.WriteField"))
        self.assertLess(code.index("o.WriteField"),code.index("s.a[3] +="))
        self.assertIn("0x00000110u,4",code)

    def test_decoder_omitted_b_suffix_is_original_signed_byte_read(self):
        code=g.emit_instruction(0x100,48,"MOVE @1D00000h,A1",(0x07e1,0,0x01d0),{0x130},{})
        self.assertIn("int8_t(o.Read8(0x01d00000u))",code)
        self.assertIn("0x00000130u,5",code)
        self.assertNotIn("ReadField",code)

    def test_unknown_syntax_and_unobserved_call_are_fatal(self):
        with self.assertRaises(ValueError):
            g.emit_instruction(0x100,16,"MAGIC A0",(0,),{0x110},{})
        with self.assertRaises(ValueError):
            g.emit_instruction(0x100,32,"CALLR 200h",(0,0),{0x120},{})

if __name__=="__main__":
    unittest.main()
