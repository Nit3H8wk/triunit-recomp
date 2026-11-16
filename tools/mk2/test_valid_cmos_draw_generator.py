"""The finite valid-CMOS draw translation stays reproducible and rejects other ROMs."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_valid_cmos_draw as generator

class ValidCmosDrawGeneratorTests(unittest.TestCase):
    @unittest.skipUnless((generator.shared.ROOT/'roms/mk2').is_dir(),'requires authenticated MK2 L3.1 ROMs')
    def test_fixed_translation_reproduces_qualified_first_draw(self):
        rom=generator.shared.load_program(generator.shared.ROOT/'roms/mk2')
        self.assertEqual(generator.generate(rom),(__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir() and generator.OUTPUT).read_text())

    def test_other_program_or_missing_bytes_never_generate(self):
        for rom in (bytes(0x100000),b''):
            with self.subTest(size=len(rom)),self.assertRaisesRegex(ValueError,'authenticated L3.1 program'):
                generator.generate(rom)

if __name__=='__main__':unittest.main()
