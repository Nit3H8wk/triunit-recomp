"""Fixed translation contracts for the measured second cooperative yield."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g


class TaskResumeGeneratorTests(unittest.TestCase):
    def emit(self, *args):
        try:
            return g.emit_instruction(*args)
        except ValueError as error:
            self.fail(f"Measured instruction has no fixed translation: {error}")

    def test_signed_greater_equal_uses_equal_sign_and_overflow(self):
        code = self.emit(0x100, 16, "JRGE 200h", (0,),
                                  {0x110, 0x200}, {0x100: (0x110, 0x200)})
        self.assertIn("((s.status>>31)^((s.status>>28)&1))==0", code)
        self.assertIn("0x00000200u,2", code)
        self.assertIn("0x00000110u,1", code)

    def test_pixel_read_preserves_alias_and_uses_original_operation(self):
        code = self.emit(0x100, 16, "PIXT *B2,B2", (0xfa52,), {0x110}, {})
        self.assertEqual(code, "o.PixelRead(s.b[2],s.b[2],0x00000110u);")
        with self.assertRaises(ValueError):
            g.emit_instruction(0x100, 16, "PIXT *A2,A2", (0xfa42,), {0x110}, {})

    def test_fill_uses_restartable_xy_operation_and_rejects_other_forms(self):
        self.assertEqual(self.emit(0x100, 16, "FILL XY", (0x0fe0,), {0x110}, {}),
                         "o.FillXY(0x00000110u);")
        with self.assertRaises(ValueError):
            g.emit_instruction(0x100, 16, "FILL L", (0x0fc0,), {0x110}, {})


if __name__ == "__main__":
    unittest.main()
