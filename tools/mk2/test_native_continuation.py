"""Fail closed when a finite translated frontend reaches a different boundary."""
import copy
import json
import importlib.util
import inspect
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality
from unittest import mock


def synthetic(expected):
    """Raw Original rows are not versioned (only their SHA-256): a stand-in CPU34 row at the frontier's PC/cycle and the
    frontier re-pointed to its digest, so the receipt logic is exercised without observed values."""
    from tools.mk2 import oracle_digest
    row = [expected['pc'], 0x10, expected['cycle']] + list(range(31))
    return row, dict(expected, sha256=oracle_digest.words_digest(row[:expected['words']]))


class NativeContinuationTests(unittest.TestCase):
    def test_full_first_fight_audio_requires_all_880_original_blocks(self):
        from tools.mk2.continuation_audio_reference import validate_blocks
        self.assertIn('blocks',inspect.signature(validate_blocks).parameters)
        meta={'dac_blocks':[[n*2000000,48000 if n<4 else 31250,
                    961 if n==1 else 960 if n<4 else 626 if n==4 else 625] for n in range(1,881)],
              'speaker_blocks':[[n*2000000,961 if n==1 else 960] for n in range(1,881)]}
        validate_blocks(meta,880)
        for field in ('dac_blocks','speaker_blocks'):
            bad=copy.deepcopy(meta);bad[field][-1][-1]-=1
            with self.subTest(field=field),self.assertRaises(ValueError):validate_blocks(bad,880)
            bad=copy.deepcopy(meta);bad[field].pop()
            with self.subTest(field=field),self.assertRaises(ValueError):validate_blocks(bad,880)

    def test_prolonged_audio_rejects_missing_or_mistimed_blocks(self):
        self.assertIsNotNone(importlib.util.find_spec('tools.mk2.continuation_audio_reference'))
        from tools.mk2.continuation_audio_reference import validate_blocks
        meta={'dac_blocks':[[n*2000000,48000 if n<4 else 31250,
                    961 if n==1 else 960 if n<4 else 626 if n==4 else 625] for n in range(1,57)],
              'speaker_blocks':[[n*2000000,961 if n==1 else 960] for n in range(1,57)]}
        validate_blocks(meta)
        for field in ('dac_blocks','speaker_blocks'):
            bad=copy.deepcopy(meta);bad[field][-1][0]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):validate_blocks(bad)
            bad=copy.deepcopy(meta);bad[field].pop()
            with self.subTest(field=field),self.assertRaises(ValueError):validate_blocks(bad)

    def test_extended_raster_modes_reach_rom_validation_without_a_build(self):
        for through in ('next-wait','first-fight'):
            with self.subTest(through=through):
                result=native.run(quality.ROOT/'missing-roms',reference_frames=True,through=through)
                self.assertFalse(result['passed'])
                self.assertNotIn('Raster reference',result['error'])
                self.assertNotIn('build',result)

    def test_unknown_frontier_rejected_before_rom_loading(self):
        result=native.run(quality.ROOT/'missing-roms',through='invented')
        self.assertFalse(result['passed'])
        self.assertIn('Unknown translated frontier',result['error'])
        self.assertNotIn('build',result)

    def test_complete_next_wait_boundary_and_missing_frame_or_wrong_cpu_rejected(self):
        observed={'scope':'mk2-native-translated-continuation-check','gameplay_complete':False,
            'termination':'translated_frontier_reached','execution_continues':False,
            'through':'next-wait','frontier_pc':0xff80dd30,
            'cpu34':None,
            'frames':61,'width':400,'height':254,'frame_sha256':['0'*64]*61}
        with self.assertRaises(ValueError):native.validate_boundary(observed,'next-wait')
        observed['cpu34'],patched=synthetic(native.frontier('next-wait'))
        with self.assertRaises(ValueError):native.validate_boundary(observed,'next-wait')
        patch=mock.patch.object(native,'frontier',return_value=patched);patch.start();self.addCleanup(patch.stop)
        native.validate_boundary(observed,'next-wait')
        for key,value in (('frames',60),('termination','finite_diagnostic_complete'),
                          ('gameplay_complete',True),('through','first-fight')):
            bad=copy.deepcopy(observed);bad[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):
                native.validate_boundary(bad,'next-wait')
        bad=copy.deepcopy(observed);bad['cpu34'][-1]^=1
        with self.assertRaises(ValueError):native.validate_boundary(bad,'next-wait')
        parsed,events=native.diagnostic_output(json.dumps(observed))
        self.assertEqual(parsed,observed)
        self.assertEqual(events,[])


if __name__=='__main__':unittest.main()
