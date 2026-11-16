"""tools/mk3/trace_stream.py Reader: online deduplication is independent of how the trace text is chunked."""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3.trace_stream import Reader

TRACE=(b'FF8148C0: SETF   10h,1,0\r\nFF8148D0: CALL   A1\r\nFFAE0000: RETS   \r\nFF8148E0: MOVK   1,A0\r\n'
       b'FF81A7D0: PUSHST \r\nFF81A7E0: RETI   \r\nFF8148F0: JUMP   B2\r\nFF900000: EXGPC  A3\r\nFF900010: RETS   \r\n'
       b'FF900020: CALLA  FF900000h\r\nFF900000: EXGPC  A3\r\nFF900010: TRAP   1\r\nFF81A7D0: PUSHST \r\n')


class Chunks(unittest.TestCase):
    def test_any_split_gives_the_same_sets(self):
        expect=None
        for size in (1,2,3,7,16,41,len(TRACE)):
            r=Reader({0xff81a7d0})
            for k in range(0,len(TRACE),size):r.feed(TRACE[k:k+size])
            r.finish()
            got=(r.pcs,r.pairs,r.lines)
            if expect is None:expect=got
            self.assertEqual(got,expect,size)
        pcs,pairs,lines=expect
        self.assertEqual(lines,13)
        self.assertEqual(len(pcs),10)
        self.assertEqual(pairs,{(b'FF8148D0',b'FFAE0000',b'CALL'),(b'FFAE0000',b'FF8148E0',b'RETS'),(b'FF8148E0',b'FF81A7D0',b'entry'),
                                (b'FF81A7E0',b'FF8148F0',b'RETI'),(b'FF8148F0',b'FF900000',b'JUMP'),(b'FF900000',b'FF900010',b'EXGPC'),
                                (b'FF900010',b'FF900020',b'RETS'),(b'FF900010',b'FF81A7D0',b'TRAP')})


if __name__=='__main__':unittest.main()
