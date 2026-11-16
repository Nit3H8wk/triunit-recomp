"""Real-ROM controls for the optional bounded decoder batch size."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.mk2 import offline_decode as decoder, generate_video_irq as generated


class BatchSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.image = generated.load_program(ROOT / 'roms/mk2')

    def decode(self, pcs, **kwargs):
        return decoder.decode(self.image, pcs, **kwargs)

    def test_larger_batch_keeps_every_requested_instruction_identical(self):
        pcs = tuple(generated.PCS) + (0xff804110, 0xffa54ea0)
        baseline, old = self.decode(pcs, batch_instructions=512)
        larger, new = self.decode(pcs, batch_instructions=8192)
        self.assertEqual(larger, baseline)
        self.assertEqual(set(larger), set(pcs))
        self.assertLessEqual(new['calls'], old['calls'])
        for proof in (old, new):
            self.assertFalse(proof['cleanup']['exists_after'])

    def test_invalid_batch_sizes_fail_before_tool_access(self):
        for value in (0, -1, 8193, True, 1.5, '8192', None):
            with self.subTest(value=value), patch.object(decoder.quality, 'sha',
                    side_effect=AssertionError('tool accessed')):
                with self.assertRaises(ValueError):
                    self.decode((0xff804110,), batch_instructions=value)

    def test_single_instruction_batch_and_cached_rows_preserve_values(self):
        baseline, _ = self.decode((0xff804110,), batch_instructions=512)
        cache = {}
        actual, first = self.decode((0xff804110,), batch_instructions=1, cache=cache)
        again, second = self.decode((0xff804110,), batch_instructions=8192, cache=cache)
        self.assertEqual(actual, baseline)
        self.assertEqual(again, baseline)
        self.assertEqual((first['calls'], second['calls']), (1, 0))
        self.assertFalse(second['cleanup']['exists_after'])

    def test_large_batch_still_rejects_mutated_real_decoder_words(self):
        real = subprocess.run
        def changed(*args, **kwargs):
            result = real(*args, **kwargs)
            lines = result.stdout.splitlines()
            fields = lines[0].split('\t')
            words = fields[3].split()
            words[0] = f'{int(words[0],16)^1:04x}'
            fields[3] = ' '.join(words) + ' '
            lines[0] = '\t'.join(fields)
            result.stdout = '\n'.join(lines) + '\n'
            return result
        with patch.object(decoder.subprocess, 'run', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'Decoded words differ'):
                self.decode((0xff804110,), batch_instructions=8192)


if __name__ == '__main__':
    unittest.main()
