"""Compact regressions of the per-instruction oracle (tools/oracle/mame_step.py, mk3_oracle.py) against the pinned
MAME 0.280. Translator evidence, "tradução igual ao Original por instrução, estado sintético" (D9), not route acceptance.

    python -m unittest tools.oracle.test_oracle
"""
import random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.oracle import mame_step,mk3_oracle as o

W=[0x01100000+16*i for i in range(4)];SEED=dict(zip(W,[0x1111,0x2222,0x3333,0x4444]))

class Oracle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.rom,cls.rows,cls.cases=o.load()

    def both(self,vecs,mutate=None):
        codes={v['pc']:(mutate or (lambda c:c))(self.cases[v['pc']][3]) for v in vecs}
        nat,_=o.native(codes,vecs);mame,rec=mame_step.run('mk3',vecs)
        self.assertFalse(rec['cleanup']['exists_after']);self.assertEqual(rec['missing'],0)
        return [o.compare(v,nat[v['id']],m) for v,m in zip(vecs,mame)],mame

    def test_transport_and_guards(self):
        r,_=mame_step.run('mk3',[dict(id='m',pc=0xff8003b0,st=0x10,regs={'b6':0x89abcdef},mem={0x01000100:0xbeef},watch=[0x01000100])])
        self.assertEqual((r[0]['regs']['a13'],r[0]['st'],r[0]['cycles'],r[0]['mem'][0x01000100]),(0x89abcdef,0x80000010,1,0xbeef))
        line='OR_R m FF8003C0 10 1 1 0 '+' '.join(['0']*15)
        with self.assertRaisesRegex(ValueError,'looping chain'):mame_step.parse(f'OR_NOP 300\n{line}\n{line}\n',[dict(id='m')])
        with self.assertRaisesRegex(RuntimeError,'over limit'):
            mame_step.run('mk3',[dict(id=f'v{i}',pc=0xff8003b0,st=0x10) for i in range(2000)],log_limit=100000)

    def test_wide_field_read_crossing_the_dword(self):
        """MOVE *A13,A13,0 with FS0=24 at bit offset 12 (RFIELDMAC_BIG reads the third word): MAME 0x322221."""
        v=dict(id='rf24',pc=0xff805000,st=0x18,regs={'a13':0x0110000c,'sp':0x01300000},mem=SEED,watch=W,io={})
        diff,m=self.both([v])
        self.assertEqual(m[0]['regs']['a13'],0x322221);self.assertIsNone(diff[0])

    def test_wide_field_write_follows_the_chip_d10(self):
        """MOVE A0,*A7,0 with FS0=24 at bit 12: the chip writes F111 BCDE 333A (D10); MAME's WFIELDMAC_BIG puts 333A on word 0.
        known_class accepts exactly that difference and rejects a native word 0 that is not the field's low part."""
        v=dict(id='wf24',pc=0xff801a90,st=0x18,regs={'a0':0xabcdef,'a7':0x0110000c,'sp':0x01300000},mem=SEED,watch=W,io={})
        nat,_=o.native({v['pc']:self.cases[v['pc']][3]},[v]);n=nat['wf24']
        mame,rec=mame_step.run('mk3',[v]);m=mame[0];self.assertFalse(rec['cleanup']['exists_after'])
        self.assertEqual([n['mem'][w] for w in W],[0xf111,0xbcde,0x333a,0x4444])
        self.assertEqual([m['mem'][w] for w in W],[0x333a,0xbcde,0x3333,0x4444])
        asm=self.cases[v['pc']][0];d=o.compare(v,n,m)
        self.assertEqual(o.known_class(v,n,m,asm,d),'wfieldmac-big')
        bad=dict(n,mem={**n["mem"],W[0]:0xf112})
        self.assertIsNone(o.known_class(v,bad,m,asm,o.compare(v,bad,m)))

    def test_shift_count_32_sites_and_negative_control(self):
        """SRL/SRA 20h,R (displayed 20h encodes count 0: front C's emitter change) equal MAME; a mutated count differs."""
        rng=random.Random(5);vecs=o.vectors(0xff8286a0,'SRL    20h,B0',16,rng)+o.vectors(0xff867fb0,'SRA    20h,B0',16,rng)
        diff,_=self.both(vecs);self.assertEqual([d for d in diff if d],[])
        bad,_=self.both(vecs,mutate=o.MUTATIONS['SRL K,R'])
        self.assertTrue(any(bad[:8]))   # the SRL site with count 0 -> 1 must be detected

if __name__=='__main__':unittest.main()
