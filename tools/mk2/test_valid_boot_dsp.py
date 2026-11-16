"""Original valid-reset DSP cases retain exact authenticated opcode guards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_adsp as generate


class ValidBootDspTests(unittest.TestCase):
    @unittest.skipUnless((generate.ROOT/'roms/mk2/su2.l1').is_file(),'requires authenticated U2')
    def test_first_boot_selftest_cases_and_word_authentication(self):
        data=(generate.ROOT/'roms/mk2/su2.l1').read_bytes()
        source=generate.generate(data)
        for instruction in ('case 0x00049: CheckOpcode(0x400000);',
            'case 0x00010: CheckOpcode(0x18154f);','case 0x00154: CheckOpcode(0x0c0030);',
            'case 0x0006d: CheckOpcode(0x0c3000); Advance(); SelectBank(uint8_t(mstat | 0x10));',
            'case 0x00071: CheckOpcode(0x5800b1); Advance(); WriteProgramDag(4, 5, mr0);'):
            self.assertTrue(instruction in source,instruction)
        with patch.object(generate,'SELFTEST_SHA256','0'*64):
            with self.assertRaisesRegex(ValueError,'self-test DSP word'):generate.generate(data)


if __name__=='__main__':unittest.main()
