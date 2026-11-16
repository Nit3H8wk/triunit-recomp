"""Negative controls for complete chronological audio comparison."""
import copy,struct,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import dac_reference as reference


class DacReferenceTests(unittest.TestCase):
    def test_exact_float_payload_and_corruption_truncation_extra_samples(self):
        good=struct.pack('<3f',0,-1,1)
        self.assertEqual(reference.compare_float32(good,good,3,'test')['unequal_float32_bits'],0)
        for bad in (good[:-1],good+b'\0\0\0\0',struct.pack('<3f',0,1,1)):
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):
                reference.compare_float32(bad,good,3,'test')

    def test_rate_change_and_every_speaker_source_block_have_exact_boundaries(self):
        meta={'dac_blocks':[[n*2000000,48000 if n<4 else 31250,
                            961 if n==1 else 960 if n<4 else 626 if n==4 else 625] for n in range(1,11)],
              'speaker_blocks':[[n*2000000,961 if n==1 else 960] for n in range(1,11)]}
        reference.validate_blocks(meta)
        for field,index,column in (('dac_blocks',3,0),('dac_blocks',3,2),('dac_blocks',5,2),
                                   ('speaker_blocks',0,1),('speaker_blocks',5,0)):
            bad=copy.deepcopy(meta);bad[field][index][column]+=1
            with self.subTest(field=field,index=index,column=column),self.assertRaises(ValueError):
                reference.validate_blocks(bad)
        for field in meta:
            bad=copy.deepcopy(meta);bad[field].pop()
            with self.subTest(field=field),self.assertRaises(ValueError):reference.validate_blocks(bad)

    def test_pcm16_compares_every_converted_sample_and_rejects_corruption(self):
        speaker=struct.pack('<7f',-2,-1,-1/32768,0,1/32768,1,2)
        pcm=struct.pack('<7h',-32768,-32768,-1,0,1,32767,32767)
        self.assertEqual(reference.compare_pcm16(pcm,speaker)['samples_compared'],7)
        for bad in (pcm[:-1],pcm+b'\0\0',pcm[:4]+b'\0\0'+pcm[6:]):
            with self.subTest(length=len(bad)),self.assertRaises(ValueError):reference.compare_pcm16(bad,speaker)

    def test_failed_or_unknown_cleanup_cannot_report_success(self):
        good={'passed':True,'cleanup':{'exists_after':False}}
        self.assertTrue(reference.finalize_result(good))
        for result in ({'passed':True,'error':'injected cleanup failure','cleanup':{'exists_after':False}},
                       {'passed':True,'cleanup':{'exists_after':True}},
                       {'passed':True},
                       {'passed':False,'cleanup':{'exists_after':False}}):
            with self.subTest(result=result):
                self.assertFalse(reference.finalize_result(result))
                self.assertFalse(result['passed'])


if __name__=='__main__':unittest.main()
