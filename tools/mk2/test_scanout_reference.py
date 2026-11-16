"""Reject lost raster boundaries and changed pixels in the integral screen gate."""
import io
import errno
import inspect
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native
from tools.quality import run as quality


class ScanoutReferenceTests(unittest.TestCase):
    def test_persisted_boot_reference_uses_exact_cmos_without_scripted_input(self):
        self.assertIn('cmos_image',inspect.signature(native.capture_screen).parameters)
        from tools.mk2 import batch_reference
        image=bytes(range(256))*64
        from tools.mk2 import oracle_digest
        frontier=native.frontier('cmos-boot')
        expected=[frontier['pc'],0x10,frontier['cycle']]+list(range(31))
        frontier=dict(frontier,sha256=oracle_digest.cpu34_digest(expected))
        with quality.scratch_tree() as (scratch,cleanup):
            def capture(argv,directory,**kwargs):
                self.assertEqual((scratch/'nvram/mk2/nvram').read_bytes(),image)
                lua=(scratch/'frames.lua').read_text()
                self.assertNotIn('set_value',lua)
                self.assertNotIn('mk2_reference_coin_subscription',lua)
                self.assertIn('for frame=0,56 do',lua)
                script=(scratch/'frames.cmd').read_text()
                self.assertIn('bpset ff811340,totalcycles==64d2a9',script)
                self.assertNotIn('MK2_FRAME_INPUT',script)
                self.assertIn('save frame-cmos.bin,1400000,20000',script)
                (scratch/'debug.log').write_text('MK2_FRAME_CPU '+' '.join(f'{n:X}' for n in expected)+'\n')
                (scratch/'frame-inputs.json').write_text('[]')
                return {'passed':True,'stdout':'','discarded_output_bytes':0}
            with patch.object(native,'prepare_reference_roms'),\
                 patch.object(quality,'sha',return_value=batch_reference.MAME_SHA),\
                 patch.object(quality,'command',side_effect=capture),\
                 patch.object(quality,'compact',side_effect=dict),\
                 patch.object(native,'frontier',return_value=frontier):
                result=native.capture_screen(scratch,scratch,{'roms':[]},'cmos-boot',cmos_image=image)
            self.assertEqual(result['cpu34'],expected)
            self.assertEqual(result['inputs'],[])
        self.assertFalse(cleanup['exists_after'])

    def test_reference_rejects_missing_wrong_sized_or_mixed_cmos_before_launch(self):
        for through,image in [('cmos-boot',None),('cmos-boot',bytes(16383)),
                              ('cmos-boot',bytes(16385)),('first-draw',bytes(16384))]:
            with self.subTest(through=through,size=None if image is None else len(image)),\
                 patch.object(quality,'command',side_effect=AssertionError('must not launch')):
                with self.assertRaises(ValueError):
                    native.capture_screen(Path('unused'),Path('unused'),{},through,cmos_image=image)

    def test_reference_roms_on_another_volume_are_copied_and_sources_preserved(self):
        with quality.scratch_tree() as (scratch,cleanup):
            source=scratch/'roms';source.mkdir()
            (source/'original.bin').write_bytes(b'authenticated ROM fixture')
            with patch.object(native.os,'link',side_effect=OSError(errno.EXDEV,'different volume')):
                native.prepare_reference_roms(source,scratch/'mk2',
                    {'roms':[{'path':'original.bin','upstream_name':'mame.bin'}]})
            self.assertEqual((scratch/'mk2/mame.bin').read_bytes(),b'authenticated ROM fixture')
            self.assertEqual((source/'original.bin').read_bytes(),b'authenticated ROM fixture')
        self.assertFalse(cleanup['exists_after'])

    def frames(self, pixel=0xff102030, tick=94875):
        return io.BytesIO(struct.pack('<QII2I',tick,2,1,pixel,0xffaabbcc))

    def test_compares_every_pixel_and_records_the_exact_boundary(self):
        result=native.compare_frames(self.frames(),self.frames(),expected_frames=1)
        self.assertTrue(result['passed'])
        self.assertEqual(result['pixels_compared'],2)
        self.assertEqual(result['frames'][0]['tick_100mhz'],94875)

    def test_rejects_a_changed_pixel_even_when_geometry_and_time_match(self):
        with self.assertRaisesRegex(ValueError,'pixel'):
            native.compare_frames(self.frames(),self.frames(0xff102031),expected_frames=1)

    def test_rejects_a_shifted_boundary_or_truncated_frame(self):
        for other in (self.frames(tick=94876),io.BytesIO(self.frames().getvalue()[:-1]),io.BytesIO()):
            with self.subTest(data=other.getvalue()):
                with self.assertRaises(ValueError):
                    native.compare_frames(self.frames(),other,expected_frames=1)

    def test_rejects_extra_frames_in_either_input(self):
        raw=self.frames().getvalue()
        for left,right in ((raw*2,raw),(raw,raw*2)):
            with self.assertRaises(ValueError):
                native.compare_frames(io.BytesIO(left),io.BytesIO(right),expected_frames=1)


if __name__=='__main__':unittest.main()
