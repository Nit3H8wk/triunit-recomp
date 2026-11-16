"""Terminal state comparison must catch hidden divergence and incomplete capture."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q


class ReplayStateTests(unittest.TestCase):
    def test_irq_and_latches_cannot_differ_with_identical_pcm_and_dsp_registers(self):
        from tools.mk2.replay_state import compare_state,FILES
        with q.scratch_tree()as(scratch,cleanup):
            a=scratch/'a';b=scratch/'b';a.mkdir();b.mkdir()
            for name,size in FILES.items():(a/name).write_bytes(bytes(size));(b/name).write_bytes(bytes(size))
            for name,size in (('dsp-irq1.bin',2),('dcs-latches.bin',6)):
                (a/name).write_bytes(bytes(size));(b/name).write_bytes(bytes(size))
            for name,size in (('dsp-irq1.bin',2),('dcs-latches.bin',6)):
                data=bytearray(size);data[-1]=1;(b/name).write_bytes(data)
                with self.subTest(name=name):self.assertFalse(compare_state(a,b)['passed'])
                (b/name).write_bytes(bytes(size))
        self.assertFalse(cleanup['exists_after'])

    def test_active_stacks_and_dac_ring_are_required_with_identical_pcm_and_dsp76(self):
        from tools.mk2.replay_state import compare_state, FILES
        with q.scratch_tree() as (scratch, cleanup):
            native = scratch / 'native'
            original = scratch / 'original'
            for directory in (native, original):
                directory.mkdir()
                for name, size in FILES.items():
                    (directory / name).write_bytes(bytes(size))
            self.assertTrue(compare_state(native, original)['passed'])
            for name, size in (('dsp-stack.bin', 27 * 4), ('dsp-dac-ring.bin', 32768 * 4)):
                with self.subTest(name=name):
                    self.assertEqual(FILES[name], size)
                    path = original / name
                    path.write_bytes(bytes(size - 2) + b'\x01\x00')
                    result = compare_state(native, original)
                    self.assertFalse(result['passed'])
                    self.assertEqual(result['files'][name]['first_offset'], size - 2)
                    path.write_bytes(bytes(size))
        self.assertFalse(cleanup['exists_after'])

    def test_cycles_use_executor_frontier_and_keep_debugger_cache_as_evidence(self):
        from tools.mk2.replay_state import save_dsp_snapshot
        import struct
        with q.scratch_tree()as(scratch,cleanup):
            values=list(range(76));values[1]=9
            (scratch/'debug.log').write_text('DSP_STATE '+' '.join(f'{n:X}'for n in values)+' 0 0\n')
            (scratch/'dsp-execute-cycles.bin').write_bytes(struct.pack('<Q',10))
            result=save_dsp_snapshot(scratch)
            self.assertEqual(struct.unpack('<76Q',(scratch/'dsp-registers.bin').read_bytes())[1],10)
            self.assertEqual(result,{'debugger_cached_cycles':9,'executor_cycles':10,'debugger_irq1':0,'debugger_curpc':0})
        self.assertFalse(cleanup['exists_after'])

    def test_each_state_byte_and_exact_length_are_required(self):
        from tools.mk2.replay_state import compare_state,FILES
        with q.scratch_tree()as(scratch,cleanup):
            a=scratch/'a';b=scratch/'b';a.mkdir();b.mkdir()
            for name,size in FILES.items():(a/name).write_bytes(bytes(size));(b/name).write_bytes(bytes(size))
            self.assertTrue(compare_state(a,b)['passed'])
            for name,size in FILES.items():
                with self.subTest(name=name):
                    p=b/name;data=bytearray(size);data[size//2]=1;p.write_bytes(data)
                    result=compare_state(a,b)
                    self.assertFalse(result['passed']);self.assertEqual(result['files'][name]['first_offset'],size//2)
                    p.write_bytes(bytes(size-1));self.assertFalse(compare_state(a,b)['passed'])
                    p.write_bytes(bytes(size)+b'\0');self.assertFalse(compare_state(a,b)['passed'])
                    p.unlink();self.assertFalse(compare_state(a,b)['passed']);p.write_bytes(bytes(size))
        self.assertFalse(cleanup['exists_after'])

    def test_dsp_snapshot_rejects_missing_duplicate_or_changed_register(self):
        from tools.mk2.replay_state import dsp_snapshot
        values=list(range(76));line='DSP_STATE '+' '.join(f'{n:X}'for n in values)+' 0 0'
        self.assertEqual(dsp_snapshot(line),{'registers':values,'irq1':0,'curpc':0})
        for text in ('',line+'\n'+line,'DSP_STATE 0 1'):
            with self.subTest(text=text[:30]),self.assertRaises(ValueError):dsp_snapshot(text)


if __name__=='__main__':unittest.main()
