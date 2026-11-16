"""K5 front B: static checks of the finishing-move evidence and route specs (tools/mk3/finishes.py); no native build."""
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,finishes,specials,versus

KINDS=(0xff982520,0xff9825b0,0xff982330,0xff9823b0,0xff9822f0,0xff982290,0xff9823b0,0xff9823b0)


class Finishes(unittest.TestCase):
    def test_kind_table(self):
        W=versus.word
        self.assertEqual(tuple(W(finishes.KIND_TABLE+32*k)|W(finishes.KIND_TABLE+32*k+16)<<16 for k in range(8)),KINDS)
        self.assertEqual(W(0xff9823e0),0x0b40);self.assertEqual(W(0xff9823f0)^0xffff,finishes.FINISH)   # CMPI 3h,A0 (immediate stored inverted) after MOVE @1062250h,A0

    def test_classes_by_action(self):
        by={}
        for e in specials.entries():
            c=finishes.CLASSES.get(e['action'])
            if c:by.setdefault(c,set()).add(e['kind'] if c!='stage' else e['condition'])
        self.assertEqual(by['kind3'],{3});self.assertEqual(by['kind45'],{4,5});self.assertEqual(by['kind6'],{6});self.assertEqual(by['kind7'],{7})
        self.assertEqual(by['kind2'],{2});self.assertEqual(by['stage'],{finishes.STAGE_CONDITION})

    def test_repeated_tokens_released(self):
        e=next(x for x in specials.entries() if x['character']==10 and x['condition']==0xff992da0)   # RUN BL BL BL HK
        rows,trigger=finishes.attempt_rows(e,'p1',0,1000000)
        downs=[r for r in rows if r[2]!=0xffff]
        self.assertEqual(len(downs),5);self.assertEqual(trigger,downs[-1][0])
        self.assertTrue(all(b[0]-a[0]>=finishes.TAP*versus.FRAME for a,b in zip(downs,downs[1:])))

    def test_gap_and_chunk_cut(self):
        e=next(x for x in specials.entries() if x['entry']==0xff991c50)   # char 0 kind 6: LK RUN RUN HK
        rows,trigger=finishes.attempt_rows(e,'p1',0,1000000,gap=23)
        downs=[r[0] for r in rows if r[2]!=0xffff]
        self.assertEqual(len(downs),4);self.assertEqual(trigger,downs[-1]);self.assertEqual(downs[-1]-downs[0],35*versus.FRAME)
        F,a=versus.FRAME,10**6   # before the versus tape's first row
        s=dict(p1=10,p2=0,shift=0,cut=a+45*F,chunks=[dict(seed=1,start=a,end=a+50*F,cut=a+20*F),dict(seed=2,start=a+30*F,end=a+50*F)])
        rows=[r for r in finishes.chunk_tape(s) if r[0]<a+60*F]
        self.assertTrue([r for r in rows if r[0]<a+20*F]);self.assertFalse([r for r in rows if a+20*F<r[0]<a+30*F or r[0]>a+45*F])
        self.assertIn((a+20*F,0,0xffff),rows);self.assertIn((a+45*F,1,0xffff),rows)

    def test_chain_cut(self):
        import json
        cut=697000000;chain=next(x for x in json.loads(versus.SPECS.read_text('utf-8'))['routes'] if x['name']=='versus_chain')
        base=[r for r in versus.chain_tape(chain)['tape'] if r[0]<cut]
        rows=finishes.chunk_tape(dict(chain='versus_chain',cut=cut))
        self.assertEqual(rows,base+[(cut,0,0xffff),(cut,1,0xffff)]);self.assertTrue(base and max(r[0] for r in base)<cut)
        over=finishes.chunk_tape(dict(chain='versus_chain',cut=cut,chain_fields=dict(attackers=['p2']*5)))
        self.assertNotEqual(over,rows)   # fields override the chain (all rounds attacked by P2)

    def test_route_specs(self):
        specs=finishes.route_specs()
        for n,s in specs.items():
            self.assertTrue(explore.legal(s['tape']),n)
            self.assertEqual(len(s['input_negative']['native']),len(s['tape'])-1,n)
            if 'attempts' in s['wave']:self.assertGreater(s['horizon'],max(a['at'] for a in s['wave']['attempts']),n)
            else:self.assertGreater(s['horizon'],next(r[0] for r in s['tape'] if r not in s['input_negative']['native']),n)

    def test_versus_bot(self):
        F=versus.FRAME;b=finishes.VersusBot(dict(plan=['p1'],join_delay=10*F,select_after=20*F))
        w=lambda h2=166,x2=50,s2=1,k2=0:[166,h2,0,x2,1,s2,0,k2]   # health, x, state, streak
        self.assertEqual(b(0,w(),[0x23,0x3D]),{0:0xffff,1:0xffff});self.assertTrue(b.fighting)   # round start: idle one frame
        self.assertEqual(b(2*F,w(),[])[0],0xffff^(8|0x10))       # P2 to the right and near: right + HP
        self.assertEqual(b(3*F,w(x2=500),[])[0],0xffff^8)        # far: walk right
        self.assertEqual(b(4*F,w(h2=0),[]),{0:0xffff,1:0xffff});self.assertFalse(b.fighting)   # KO: released
        b(5*F,w(h2=0,s2=2),[]);self.assertEqual(b.match,1)      # P2 state 1 -> 2: match over, P2 streak 0: join
        self.assertEqual(b(15*F,w(h2=0,s2=2),[]),{3:0xffff^versus.COIN1})
        s=next(x for x in json.loads(finishes.SPECS.read_text('utf-8'))['routes'] if x['name']=='r1fin16');t=finishes.chunk_tape(s);o=s['bot']
        self.assertTrue(set(versus.versus_tape(o['p1'],o['p2'],o['shift'])['tape'])<=set(t));self.assertEqual(t,sorted(t));self.assertLessEqual(t[-1][0],s['horizon'])

    def test_held(self):
        rows=[(10,0,0xffff^4),(20,0,0xffff),(15,1,0xfffe)]   # P1 left held 10-20, an IN1 row inside
        out=sorted(finishes.held(rows,0,0x10,12,30))
        self.assertEqual(out,[(10,0,0xffff^4),(12,0,0xffff^0x14),(15,1,0xfffe),(20,0,0xffff^0x10),(30,0,0xffff)])
        self.assertEqual(sorted(finishes.held(rows,0,0x10,5,20)),[(5,0,0xffef),(10,0,0xffff^0x14),(15,1,0xfffe),(20,0,0xffff)])


if __name__=='__main__':unittest.main()
