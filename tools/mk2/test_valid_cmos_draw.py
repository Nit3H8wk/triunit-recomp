"""The persistent first draw has a complete, finite CPU/raster boundary."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from unittest import mock
from tools.mk2 import native, oracle_digest
from tools.quality import run as quality


# Original FC7D first draw: only its CPU34 SHA-256 is versioned (the local oracle regenerates the row).
END = {'pc': 0xff80dd30, 'cycle': 7316296, 'words': 34,
       'sha256': 'd73e16802db7d0d363fac475f467ef5018a9f8a7ce6692c4c206f8f4113e255c'}


def synthetic(expected):
    """A stand-in CPU34 row at the frontier's PC/cycle and the frontier re-pointed to its digest."""
    row = [expected['pc'], 0x10, expected['cycle']] + list(range(31))
    return row, dict(expected, sha256=oracle_digest.words_digest(row[:expected['words']]))


class ValidCmosDrawTests(unittest.TestCase):
    def test_persisted_credits_select_exact_original_boundaries(self):
        from tools.mk2 import profile
        import json
        fixture=json.loads((quality.ROOT/'tools/mk2/startup_credit_fixture.json').read_text())
        image=bytearray(profile.FACTORY_SEED.read_bytes())
        for at,value in fixture['changed_words']:image[at:at+2]=value.to_bytes(2,'little')
        for credits,selected,cycle in ((0,0,7316296),(1,2,7316274),(2,3,7316278),(99,3,7316278)):
            image[540]=credits
            self.assertEqual(native.startup_profile(image),selected)
            self.assertEqual(native.frontier('cmos-draw',cmos_image=image)['cycle'],cycle)
        image[0x1096]=1
        self.assertEqual(native.startup_profile(image),1)

    def test_operator_dip_uses_each_original_cpu_boundary_and_rejects_other_bits(self):
        for dsw,cycle in ((0xfc7d,7316296),(0xbc7d,7316232),(0x7c7d,7316232),(0x3c7d,7316346)):
            expected=native.frontier('cmos-draw',dsw)
            self.assertEqual(expected['cycle'],cycle)
            self.assertRegex(expected['sha256'],'^[0-9a-f]{64}$')
            cpu,patched=synthetic(expected)
            frames=cycle*16//1827925
            observed={'scope':'mk2-native-cmos-draw-check','through':'cmos-draw',
                'gameplay_complete':False,'execution_continues':False,
                'termination':'finite_valid_cmos_draw_complete','frontier_pc':cpu[0],
                'cpu34':cpu.copy(),'frames':frames,'width':400,'height':254,
                'frame_sha256':['0'*64]*frames}
            with mock.patch.object(native,'frontier',return_value=patched):
                native.validate_boundary(observed,'cmos-draw',dsw)
                observed['cpu34'][2]+=1
                with self.assertRaises(ValueError):native.validate_boundary(observed,'cmos-draw',dsw)
            observed['cpu34'][2]-=1
            with self.assertRaises(ValueError):native.validate_boundary(observed,'cmos-draw',dsw)
        for dsw in (0xffff,0xfcfd,0x7c7c,True):
            with self.assertRaises(ValueError):native.frontier('cmos-draw',dsw)

    def test_operator_comparison_header_reproduces_original_manifest(self):
        from tools.mk2 import generate_operator_boundaries as generator
        self.assertEqual((__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir() and generator.OUTPUT).read_text(),generator.generate())

    def test_free_play_has_its_own_original_timing_without_changing_the_paid_proof(self):
        for dsw,cycle in ((0xfc7d,7316382),(0xbc7d,7316318),(0x7c7d,7316318),(0x3c7d,7316262)):
            self.assertEqual(native.frontier('cmos-draw',dsw,True)['cycle'],cycle)
            self.assertNotEqual(native.frontier('cmos-draw',dsw,True),native.frontier('cmos-draw',dsw,False))

    def test_full_boundary_rejects_changed_cpu_rasters_or_unbounded_claims(self):
        self.assertEqual(native.frontier('cmos-draw'), END)
        END_CPU34, patched = synthetic(END)
        frames = END_CPU34[2] * 16 // 1827925
        observed = {
            'scope': 'mk2-native-cmos-draw-check', 'through': 'cmos-draw',
            'gameplay_complete': False, 'execution_continues': False,
            'termination': 'finite_valid_cmos_draw_complete',
            'frontier_pc': END_CPU34[0], 'cpu34': END_CPU34,
            'frames': frames, 'width': 400, 'height': 254,
            'frame_sha256': ['0' * 64] * frames,
        }
        with self.assertRaises(ValueError):
            native.validate_boundary(observed, 'cmos-draw')
        restore = mock.patch.object(native, 'frontier', return_value=patched)
        restore.start()
        self.addCleanup(restore.stop)
        native.validate_boundary(observed, 'cmos-draw')
        for field in ('cpu34', 'frames', 'gameplay_complete', 'execution_continues', 'termination'):
            invalid = copy.deepcopy(observed)
            if field == 'cpu34':
                invalid[field][33] ^= 1
            elif field == 'frames':
                invalid[field] -= 1
            elif field == 'termination':
                invalid[field] = 'gameplay_complete'
            else:
                invalid[field] = True
            with self.subTest(field=field), self.assertRaises(ValueError):
                native.validate_boundary(invalid, 'cmos-draw')

    def test_requires_existing_explicit_profile_before_build_or_reset(self):
        result = native.run(quality.ROOT / 'missing-roms', through='cmos-draw')
        self.assertFalse(result['passed'])
        self.assertEqual(result['error'], 'cmos-draw requires an existing explicit --profile')
        self.assertNotIn('build', result)
        with quality.scratch_tree() as (scratch, cleanup):
            missing = scratch / 'missing-profile'
            result = native.run(quality.ROOT / 'missing-roms', through='cmos-draw', profile_directory=missing)
            self.assertFalse(result['passed'])
            self.assertIn('persistence', result)
            self.assertNotIn('build', result)
            self.assertFalse(missing.exists())
        self.assertFalse(cleanup['exists_after'])


if __name__ == '__main__':
    unittest.main()
