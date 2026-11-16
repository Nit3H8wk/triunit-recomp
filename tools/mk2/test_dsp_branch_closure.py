"""Static late-U2 direct-edge closure; this does not qualify runtime paths."""
from pathlib import Path
import hashlib
import json
import re
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

ROOT = Path(__file__).resolve().parents[2]
from tools.mk2 import oracle_digest
MANIFEST = Path(__file__).with_name('dsp_branch_closure.json')


def successors(pc, op):
    """Pinned adsp2100.cpp immediate control flow, with call continuations."""
    top, condition, target = op >> 16, op & 15, (op >> 4) & 0x3fff
    if 0x18 <= top <= 0x1b:
        return [target] + ([pc + 1] if condition != 15 else [])
    if 0x1c <= top <= 0x1f:
        return [target, pc + 1]
    if top in (0x0a, 0x0b):
        # Return/indirect destinations require separate context evidence.
        return [pc + 1] if condition != 15 else []
    if top == 3:
        return [((op >> 4) & 0xfff) | ((op & 12) << 10), pc + 1]
    return [pc + 1]


def word(data, pc):
    if not (0 <= pc < 0x400 or 0x800 <= pc < 0x1000):
        raise ValueError('Outside declared late image')
    offset = 0x1000 + pc * 4 if pc < 0x400 else 0x2000 + (pc - 0x800) * 4
    return int.from_bytes(data[offset:offset + 3], 'big')


def mapped_words(data, source):
    mapped = {}
    for line in source.splitlines():
        case = re.match(r'case 0x([0-9a-f]+):', line)
        if not case or not (int(case[1], 16) & 0x10000):
            continue
        pc = int(case[1], 16) & 0xffff
        op = word(data, pc)
        variants = [int(value, 16) for value in re.findall(r'CheckOpcode\(0x([0-9a-f]+)\)', line)]
        if op in variants:
            mapped[pc] = op
    return mapped


def missing_edges(mapped):
    return [(pc, target) for pc, op in sorted(mapped.items())
            for target in successors(pc, op) if target not in mapped]


class DspBranchClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
        path = ROOT / cls.manifest['u2']['path']
        if not path.is_file():
            raise unittest.SkipTest('Authenticated local U2 required for static ROM closure')
        cls.data = path.read_bytes()
        if hashlib.sha256(cls.data).hexdigest() != cls.manifest['u2']['sha256']:
            raise ValueError('U2 identity differs')
        cls.source = (__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir()/'mk2_adsp_boot.inc').read_text(encoding='utf-8')

    def test_manifest_words_are_authentic(self):
        # PCs only; their U2 words are checked by SHA-256 (tools/mk2/oracle_digest.py serialization).
        self.assertEqual(len(self.manifest['pcs']), 131)
        words = [word(self.data, int(pc, 16)) for pc in self.manifest['pcs']]
        self.assertEqual(oracle_digest.words_digest(words), self.manifest['words_sha256'])

    def test_current_late_image_direct_successors_are_mapped(self):
        mapped = mapped_words(self.data, self.source)
        self.assertFalse(missing_edges(mapped), missing_edges(mapped))
        for pc in self.manifest['pcs']:
            self.assertEqual(mapped.get(int(pc, 16)), word(self.data, int(pc, 16)), pc)

    def test_missing_crash_word_and_late_variant_are_detected(self):
        mapped = mapped_words(self.data, self.source)
        mapped.pop(0x2fa, None)
        mapped.pop(0x836, None)
        self.assertIn((0x2f9, 0x2fa), missing_edges(mapped))
        self.assertIn((0x82b, 0x836), missing_edges(mapped))

    def test_returns_and_indirect_targets_remain_unknown(self):
        self.assertEqual(successors(0x196, 0x0a000f), [])
        self.assertEqual(successors(0x1d5, 0x0b000f), [])
        self.assertEqual(successors(0x2f9, 0x182fc0), [0x2fc, 0x2fa])


if __name__ == '__main__':
    unittest.main()
