"""K4 front A: offline checks of the R4 operator tapes (tools/mk3/operator_routes.py), the R5 VS-code tapes
(tools/mk3/secrets.py) and the strict-matrix / residue helpers (tools/mk3/strict_matrix.py); one native test (two builds,
no Original) of the PIXBLT B,XY 0xffae8690 path with ST.IE set (native/mk3/mk3_cmos_check.cpp, K4 A)."""
import subprocess,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,operator_routes as op,secrets,strict_matrix as sm

LEGAL={0:0x7f7f,1:0x77,3:explore.COIN1|explore.START1|explore.START2|0x2|0x10}   # explore.legal + the test switch (IN2 0x10)


def legal(tape):
    for c,p,v in tape:
        pressed=0xffff^v
        if p not in LEGAL or pressed&~LEGAL[p]:return False
        if p==0 and any((pressed>>s)&3==3 or (pressed>>s)&12==12 for s in (0,8)):return False
    return list(tape)==sorted(tape)


class Operator(unittest.TestCase):
    def test_tapes_legal_and_negatives(self):
        for name,s in op.route_specs().items():
            with self.subTest(name):
                self.assertTrue(legal(s['tape']))
                self.assertLess(s['tape'][-1][0],s['horizon'])
                dropped=set(s['tape'])-set(s['input_negative']['native'])
                self.assertEqual(len(dropped),1)
                self.assertNotEqual(dropped.pop()[2],0xffff)   # a press, so the negative changes a port read

    def test_menu_rows_reused(self):
        self.assertIn(op.TEST_PRESS,op.tape('r4util'))
        self.assertEqual(op.at(0),op.tower.MENU_FROM+8*op.T)

    def test_coin_hold(self):
        t=op.tape('r4coin');self.assertEqual([r[2] for r in t],[0xfffe,0xffff]);self.assertGreater(t[1][0]-t[0][0],2*op.T)

    def test_k9_holds_and_pricing(self):
        # r4hold: each stick hold is one press row and its release with no port-0 row between, longer than the 0Fh-tick repeat delay
        rows=[r for r in op.tape('r4hold') if r[1]==0]
        for v in (0xfffe,0xfffd):
            k=next(i for i,r in enumerate(rows) if r[2]==v and rows[i+1][0]-r[0]>=16*op.FRAME)
            self.assertEqual(rows[k+1][2],0xffff)
        # r4frac: STANDARD PRICING entry 4 (USA 4) of FFCEEC40 sets adjustment 0xA (word 11 of FFB06DD0's copy order) = 1; HUNGARY (61) = 0
        entry=lambda k:0xffceec40+0x1e0*(k-1)
        self.assertEqual([secrets.word(entry(4)+16*11),secrets.word(entry(61)+16*11)],[1,0])
        self.assertEqual([secrets.word(entry(4)+16*i) for i in (0,5)],[1,2])   # adj 2 (LEFT units) 1, adj 6 (units per credit) 2
        self.assertEqual(op.FRAC[6:9],[op.U]*3)


class Secrets(unittest.TestCase):
    def test_table(self):
        c=secrets.codes()
        self.assertEqual(len(c),20)
        self.assertEqual([e['index'] for e in c if not e['first']],[15])   # 688422 repeats entry 4
        self.assertEqual([e['mode'] for e in c],list(range(1,21)))
        for e in c:self.assertTrue(all(0<=d<=9 for d in e['digits']))

    def test_code_rows_count_presses(self):
        for e in secrets.codes():
            rows=secrets.code_rows(e['digits'])
            for box,(p,m) in enumerate(secrets.BUTTON):
                self.assertEqual(sum(1 for c,q,v in rows if q==p and (0xffff^v)&m),e['digits'][box])
            self.assertLess(rows[-1][0] if rows else 0,205993000)   # before the digits are compared

    def test_buttons_are_side_buttons(self):
        side={(0,b) for b in explore.P1['in0_buttons']+explore.P2['in0_buttons']}|{(1,b) for b in explore.P1['in1_buttons']+explore.P2['in1_buttons']}
        self.assertTrue(set(secrets.BUTTON)<=side)

    def test_routes_legal(self):
        specs=secrets.route_specs()
        self.assertEqual(len([n for n in specs if n.startswith('r5vs')]),19)
        pre,_=secrets.prelude()
        for name,s in specs.items():
            with self.subTest(name):
                self.assertTrue(legal(s['tape']))
                if name.startswith('r5vs'):self.assertTrue(set(pre)<=set(s['tape']))

    def test_hidden14_and_arena7(self):
        t,neg=secrets.hidden14_tape(),secrets.hidden14_tape(False)
        code=sorted(set(t)-set(neg));self.assertEqual(set(neg)-set(t),set())   # the negative only lacks the 10-box code
        self.assertEqual(len(code),2*len([1 for k in range(9) for p in (0,1) if any(d>k and secrets.HIDDEN_BUTTON[b][0]==p for b,d in enumerate(secrets.HIDDEN_CODE))]))
        self.assertTrue(secrets.HIDDEN14_OVER<code[0][0] and code[-1][0]<secrets.HIDDEN14_COMPARE)
        sp=secrets.route_specs()
        self.assertEqual(sp['r5arena7']['tape'],tuple(sorted((c+secrets.ARENA7_SHIFT,p,v) for c,p,v in sp['r5arena7']['input_negative']['native'])))


class Matrix(unittest.TestCase):
    def test_cause(self):
        c=sm.cause('MK3 PC outside the authenticated fixed translation; PC 4288685056; address 4288685056')
        self.assertEqual((c['kind'],c['pc']),('TmsBlock','0xffa02400'))
        self.assertIsNone(sm.cause('none'))
        self.assertEqual(sm.kind('MK3 PIXBLT B,XY with interrupts enabled is not translated; PC 1'),'other')

    def test_reader_class(self):
        self.assertTrue(sm.reader_class(0x187ffa0).startswith('DIP switches'));self.assertTrue(sm.reader_class(0x187ffb0).startswith('input port IN2'))
        self.assertEqual(sm.reader_class(0x1408380),'CMOS')
        self.assertEqual(sm.reader_class(0x1062220),'RAM game state')
        self.assertEqual(sm.reader_class(None),'register/indirect state')


class PixbltInterruptible(unittest.TestCase):
    """SWITCH TEST from reset (operator_routes r4sw steps up to the test): negative = mk3_cmos_check.cpp before the K3-K10 fix (aff1137, parent of 3700b6f) (rejects
    'PIXBLT B,XY with interrupts enabled' at 0xffae8690, cycle 257,987,865); the working tree runs to the horizon in
    Profile::Game and notes DevicePath 0xffae8690; Strict rejects it unless that key is route-verified."""
    def test_switch_test(self):
        from tools.mk3 import generate,replay
        from tools.quality import run as q
        tape=op.tower.menu_rows([op.HP,op.HP,op.W,op.W,op.W]);horizon=op.at(1)+4*op.T
        key=['DevicePath',0xffae8690,0]
        with q.scratch_tree() as (temp,cleanup):
            head=temp/'mk3_cmos_check.cpp'
            old=subprocess.run(['git','show','aff11377bbc4a183f282329b70f81de2e60cf9fc:native/mk3/mk3_cmos_check.cpp'],cwd=op.ROOT,capture_output=True,check=True).stdout.decode()
            # The old StepGenerated with today's machine reset (PowerOn of the working tree; the old file started from the
            # hand-written reset prefix, deleted on 16/11/2026, which reached the same state: plan 2026-11-15, 5.1).
            now=(op.ROOT/'native/mk3/mk3_cmos_check.cpp').read_text('utf-8')
            power=now[now.index('ResetTrace PowerOn('):now.index('\n}\n',now.index('ResetTrace PowerOn('))+3]
            assert old.count('auto s = RunToCmosCheck(program);')==1
            old=old.replace('auto s = RunToCmosCheck(program);','auto s = PowerOn(program);').replace('#include "mk3_cpu.hpp"\n','#include "mk3_cpu.hpp"\n#include "mk5_program.hpp"\n',1)
            head.write_text(old[:old.rindex('}')]+power+'}\n',encoding='utf-8',newline='\n')
            saved=generate.RUNTIME
            generate.RUNTIME=tuple(str(head) if n=='mk3_cmos_check.cpp' else n for n in saved)
            try:
                with replay.Native(profile='game') as n:neg=n.run(0,0,0,horizon,tape)
            finally:generate.RUNTIME=saved
        self.assertFalse(cleanup.get('exists_after'))
        self.assertIn('PIXBLT B,XY with interrupts enabled is not translated; PC 4289627792',neg['summary']['frontier'])
        self.assertEqual(neg['records'][-1]['cycle'],257987865)
        with replay.Native(profile='game') as n:pos=n.run(0,0,0,horizon,tape,first_all=True)
        self.assertEqual(pos['summary']['frontier'],'none');self.assertGreaterEqual(pos['records'][-1]['cycle'],horizon)
        sets,_=explore.first_set(pos['summary']);self.assertIn([0xffae8690,0],sets['DevicePath'])
        with replay.Native(profile='strict-routes') as n:st=n.run(0,0,0,horizon,tape)
        if ('DevicePath',0xffae8690,0) in explore.verified_keys():self.assertEqual(st['summary']['frontier'],'none')
        else:   # Strict stops at or before the unverified IE path (the menu blocks before it are not route-verified yet either)
            self.assertNotEqual(st['summary']['frontier'],'none');self.assertLessEqual(st['records'][-1]['cycle'],257987865)


if __name__=='__main__':unittest.main()
