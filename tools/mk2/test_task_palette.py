"""Fixed translation contracts for the original palette queue consumer."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as g


class TaskPaletteGeneratorTests(unittest.TestCase):
    def test_return_can_reach_the_unexecuted_qualified_endpoint(self):
        try:
            code = g.emit_instruction(0x100, 16, "RETS", (0x0960,),
                                      {0x100}, {0x100: (0x200,)}, end=0x200)
        except ValueError as error:
            self.fail(f"Measured consumer return cannot reach its boundary: {error}")
        self.assertEqual(code, "o.ReturnSubroutine(0);")
        self.assertEqual(g.emit_instruction(0x100,16,"RETS",(0x0960,),
                         {0x100},{0x100:(0x210,)},end=0x200),code)


if __name__ == "__main__":
    unittest.main()
