"""Original loaded display IRQ drawing translation contracts."""
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g


class TaskDrawGeneratorTests(unittest.TestCase):
    def test_long_xori_keeps_zero_only_flags_and_three_cycles(self):
        code = g.emit_instruction(0x100, 48, "XORI 4h,A0", (0x0bc0, 4, 0), {0x130}, {})
        self.assertEqual(code, "s.a[0]^=0x00000004u; o.Zero(s.a[0]); o.Finish(0x00000130u,3);")

    def test_original_xy_move_add_and_nop(self):
        for asm, expected in (("MOVX A9,A10", "o.MoveX(s.a[9],s.a[10],"),
                              ("ADDXY A9,A2", "o.AddXY(s.a[2],s.a[9],"),
                              ("NOP", "o.Finish(")):
            self.assertIn(expected, g.emit_instruction(0x100, 16, asm, (0,), {0x110}, {}))

    def test_draw_context_stack_bases_and_base_alias(self):
        for op, base, regs in (("MMFM", "A3", "A8,A9,A11,A12"),
                               ("MMFM", "A10", "A0,A2-A4"),
                               ("MMFM", "A11", "A6-A10"),
                               ("MMTM", "A11", "A6-A10")):
            self.assertIn("," + base[1:] + ");", g.emit_instruction(
                0x100, 32, op + " " + base + "," + regs, (0, 0), {0x120}, {}))
        self.assertEqual(g.emit_instruction(0x100,32,"MMFM A3,A2-A4",(0,0),{0x120},{}),
                         "o.Mmfm(0x3800,0x00000120u,false,3);")

    def test_trap_requires_original_vector_and_measured_successor(self):
        self.assertEqual(g.emit_instruction(0x100, 16, "TRAP 1h", (0x901,), {0x200},
                                            {0x100: (0x200,)}),
                         "o.TrapOne(0x00000200u,0x00000110u);")
        for asm, edges in (("TRAP 0h", {0x100: (0x200,)}), ("TRAP 1h", {})):
            with self.assertRaises(ValueError):
                g.emit_instruction(0x100, 16, asm, (0,), {0x200}, edges)

    def test_jrhi_rejects_unknown_branch_and_retains_real_condition(self):
        code = g.emit_instruction(0x100, 16, "JRHI 200h", (0,), {0x110}, {0x100: (0x110,)})
        self.assertIn("(s.status&0x60000000)==0", code)
        self.assertIn("throw std::runtime_error", code)

    def test_paired_predecrement_draw_transfer_uses_four_cycles(self):
        code = g.emit_instruction(0x100, 16, "MOVE -*B14,-*B10,1", (0,), {0x110}, {})
        self.assertIn("o.Finish(0x00000110u,4)", code)
        self.assertLess(code.index("s.b[14] -="), code.index("o.ReadField"))
        self.assertLess(code.index("o.ReadField"), code.index("s.b[10] -="))


if __name__ == "__main__":
    unittest.main()
