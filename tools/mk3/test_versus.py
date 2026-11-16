"""K2 front B: tools/mk3/versus.py without builds or the Original (focal layer, seconds; reads the authenticated ROM).

- ROM tables: the 5x3 select grid (15 characters, a permutation of 0-14, the hidden slot 7 = character 14), the four
  cursor tables, the start positions and the arena cycle constant as read by their reader PCs;
- cursor paths reach every fighter from both start positions without crossing the locked slot; slot 7 is unreachable
  (negative);
- versus tapes are legal (explore.legal), deterministic from the seed and differ across seeds; the select rows press only
  the side's own stick bits and High Punch;
- the planned routes of tools/mk3/r1_routes.json: every fighter as P1 and as P2, every arena 0-10 (the chain route's
  consecutive matches give 10 and 0), legal tapes, the input negative differs
  from the route only by the P1 select press, the RAM negative falls before it.
"""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,versus as vs


class Tables(unittest.TestCase):
    def test_grid_and_moves(self):
        g=vs.grid()
        self.assertEqual(sorted(e['character'] for e in g),list(range(15)))
        self.assertEqual(g[vs.HIDDEN]['character'],14)
        self.assertEqual([e['x'] for e in g[:5]],[0x45,0x7a,0xaf,0xe4,0x119]);self.assertEqual([e['x'] for e in g[10:]],[0x45,0x7a,0xaf,0xe4,0x119])
        self.assertEqual(sorted({e['y'] for e in g if e['position']!=vs.HIDDEN}),[0x25,0x66,0xa7])
        self.assertEqual(len(vs.fighters()),14);self.assertEqual(sorted(vs.fighters()),list(range(14)))
        self.assertEqual((g[vs.START['p1']]['character'],g[vs.START['p2']]['character']),(12,13))
        m=vs.moves()
        for p in range(15):   # a 5x3 grid without wrap: each table moves one cell or stays at the edge
            r,c=divmod(p,5)
            self.assertEqual((m['up'][p],m['down'][p],m['left'][p],m['right'][p]),(5*max(r-1,0)+c,5*min(r+1,2)+c,5*r+max(c-1,0),5*r+min(c+1,4)))
        self.assertEqual((vs.word(0xff8125f0),vs.word(0xff812600)),(0x0b40,0xffff^vs.ARENA_CYCLE))   # CMPI Bh,A0 (the arena wraps at 11; the immediate is stored complemented)
        self.assertEqual(vs.ARENA_CYCLE,11)

    def test_paths(self):
        f=vs.fighters();m=vs.moves()
        for side,start in vs.START.items():
            for ch,pos in f.items():
                p=start
                for d in vs.path(start,pos):p=vs.hop(m,p,d);self.assertNotEqual(p,vs.HIDDEN)
                self.assertEqual(p,pos,(side,ch))
        with self.assertRaises(ValueError):vs.path(0,vs.HIDDEN)      # negative: the locked slot is never entered


class Tapes(unittest.TestCase):
    def test_versus_tape(self):
        h=95*vs.TMS_HZ
        a=vs.versus_tape(3,9,781250,5,200000000,h);b=vs.versus_tape(3,9,781250,5,200000000,h);c=vs.versus_tape(3,9,781250,6,200000000,h)
        self.assertEqual(a,b);self.assertNotEqual(a['tape'],c['tape'])
        for t in (a,c):self.assertTrue(explore.legal(t['tape']));self.assertLessEqual(len(t['tape']),512)
        sel,_=vs.select_rows(3,9)
        for cyc,port,v in sel:
            pressed=0xffff^v;self.assertEqual(port,0);self.assertEqual(pressed&~0x0f0f&~0x1010,0)
        self.assertFalse(explore.legal(((200000000,0,0xffff^(vs.STICK['left']|vs.STICK['right'])),)))   # negative: opposite directions
        for s in range(20):
            r=vs.random_versus(s,90*vs.TMS_HZ);self.assertTrue(explore.legal(r['tape']));self.assertEqual(r,vs.random_versus(s,90*vs.TMS_HZ))

    def test_chain_rows(self):
        j=vs.join_rows(400000000,'p2',30000000)
        self.assertEqual([0xffff^v for c,p,v in j if p==3 and v!=0xffff],[vs.COIN1,vs.COIN1,vs.START2])
        self.assertEqual([(p,0xffff^v) for c,p,v in j if p==0 and v!=0xffff],[(0,0x1000)])
        rows=vs.attack_rows([1000000,9000000],[5000000],['p1','p2'],30000000)
        self.assertTrue(explore.legal(tuple(sorted(rows))))
        self.assertTrue(all(c<5000000 or c>=9000000 for c,p,v in rows if v!=0xffff))   # no attack between the win and the next round start
        self.assertEqual({0xffff^v for c,p,v in rows if c>=9000000}-{0},{0x400,0x400|0x1000,0x400|0x4000})   # P2 walks left and attacks

    def test_planned_routes(self):
        specs=vs.route_specs();single={n:s for n,s in specs.items() if 'arenas' not in s['versus']}
        self.assertEqual(len(single),14)
        self.assertEqual({s['versus']['p1'] for s in single.values()},set(range(14)))
        self.assertEqual({s['versus']['p2'] for s in single.values()},set(range(14)))
        arenas={s['versus']['arena'] for s in single.values()}|{a for s in specs.values() for a in s['versus'].get('arenas',())}
        self.assertEqual(arenas,set(range(vs.ARENA_CYCLE)))   # every versus arena of the cycle
        for name,s in specs.items():
            self.assertIn(name,explore.ROUTE_SPECS);self.assertTrue(explore.legal(s['tape']),name)
            neg=s['input_negative'];diff=set(neg['reference'])-set(neg['native'])
            self.assertEqual(len(diff),2);self.assertEqual(set(neg['native'])-set(neg['reference']),set())
            self.assertTrue(all(p==0 and (0xffff^v) in (0x10,0) for c,p,v in diff),diff)
            self.assertLess(s['mutation'][2],min(c for c,_,_ in diff));self.assertGreater(s['horizon'],s['versus']['fight'])


if __name__=='__main__':unittest.main()
