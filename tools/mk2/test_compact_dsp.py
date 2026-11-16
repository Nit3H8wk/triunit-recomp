"""Compact debugger rows must preserve every field, access and IRQ in order."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import batch_reference as b
from tools.mk2 import test_task_batch as fixtures


class CompactDspTests(unittest.TestCase):
    def protocol(self):
        debug,_,_,_,_=fixtures.BatchTests.protocol()
        names=tuple(b.reference.DSP_REGISTERS)+('irq1','curpc')
        values={key:((index*0x123456789abcdef)&((1<<64)-1)) for index,key in enumerate(names)}
        values.update(pc=0x130,totalcycles=744144,irq1=1,curpc=0x12f)
        legacy=[f'{key} = {values[key]:X}' for key in names]
        payload='DSP_STATE '+' '.join(f'{values[key]:X}' for key in names)
        markers=['MK2_DSP_BEGIN','MK2_DSP_ACCESS 72 200 ABC']
        old=debug[:3]+[markers[0],*legacy,markers[1],*legacy]+debug[3:]
        compact=debug[:3]+[markers[0],payload,markers[1],payload]+debug[3:]
        return debug,old,compact,payload

    def test_all_uint64_fields_access_curpc_and_irq_equal_legacy_symbols(self):
        _,old,compact,_=self.protocol()
        expected=b.parse_debug_lines(old)
        observed=b.parse_debug_lines(compact)
        self.assertEqual(observed,expected)
        self.assertEqual(observed['accesses'],[[114,0x12f,0x200,0xabc,744144]])
        self.assertEqual(observed['irq_hooks'],[[0x130,744144,1]])
        row=list(expected['trace'])[0]
        for field in range(76):
            bad=row.copy();bad[field]^=1
            parser=b.DebugParser(expected_dsp_trace=[bad])
            with self.subTest(field=field),self.assertRaises(ValueError):
                for line in compact:parser.feed(line)
                parser.finish()

    def test_truncation_duplicate_unknown_uint64_and_unframed_payload_rejected(self):
        debug,_,compact,payload=self.protocol()
        for bad in (' '.join(payload.split()[:-1]),payload+' 0',payload+' G',
                    payload.replace('130','-1',1),payload.replace('130','10000000000000000',1),
                    payload.replace('DSP_STATE','DSP_STATEjunk')):
            with self.subTest(payload=bad[:35]),self.assertRaises(ValueError):
                b.parse_debug_lines(debug[:3]+['MK2_DSP_BEGIN',bad]+debug[3:])
        for bad in (debug[:3]+['MK2_DSP_BEGIN',payload,payload]+debug[3:],
                    debug[:3]+[payload]+debug[3:],compact+[payload]):
            with self.assertRaises(ValueError):b.parse_debug_lines(bad)


if __name__=='__main__':unittest.main()
