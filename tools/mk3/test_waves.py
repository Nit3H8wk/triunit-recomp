"""K3 front B: R2 tower and R1 special-move tapes from the ROM tables, and the R3 session generator (focal, no builds).

- ladders: 6 pointers at 0xffa000f0, three towers of 8/10/12 fights ended by 0xFFFF and closed by the bosses 0xF, 0x10;
- tower prelude and P1 macros: legal; a candidate's rows before a cut do not depend on its horizon (the planner's cut);
- special entries: 116 list entries in 75 (table, button, character) slots, 62 distinct handlers (press and release tables), mirrored sequences, legal taps per side;
- random sessions: legal, deterministic, with coin-in bursts.
"""
from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,specials,tower


class Tower(unittest.TestCase):
    def test_ladders(self):
        ls=tower.ladders()
        self.assertEqual([hex(l['pointer']) for l in ls][:2],['0xffa001b0','0xffa003c0'])
        for l in ls:
            for t,(w0,n) in tower.TOWERS.items():self.assertEqual((len(l['towers'][t]),l['towers'][t][-2:]),(n,[15,16]))
        self.assertEqual(ls[0]['towers'][2],[2,10,3,9,0,1,15,16])

    def test_tapes(self):
        for t in (2,1,0):self.assertTrue(explore.legal(tower.prelude(None,t)))
        self.assertTrue(explore.legal(tower.prelude(5,1)))
        for s in range(20):
            a=tower.p1_rows(s,3*10**8,4*10**8);b=tower.p1_rows(s,3*10**8,5*10**8)
            self.assertEqual([r for r in b if r[0]<4*10**8],[r for r in a if r[0]<4*10**8])
            self.assertTrue(explore.legal(tuple(sorted(list(tower.prelude(None,2))+a))))

    def test_menu_prelude(self):
        """Difficulty by the operator menu: the test switch (IN2 0x10, an operator input, not an exploration one) plus
        legal stick/HP presses, then the plain prelude shifted after the menu exit; nothing pressed twice at once."""
        m=tower.prelude(None,2,menu=True);op=[r for r in m if r[1]==3 and r[2]==0xffef]
        self.assertEqual(len(op),1);self.assertFalse(explore.legal(m))
        self.assertTrue(explore.legal(tuple(r for r in m if not (r[1]==3 and r[2]==0xffef))))
        self.assertEqual(len(tower.menu_rows()),2+2*len(tower.MENU_STEPS))
        self.assertLess(max(c for c,_,_ in tower.menu_rows()),min(c for c,_,_ in tower.prelude(None,2))+tower.MENU_SHIFT)

    def test_bot_rows(self):
        """The closed-loop bot sets only legal P1 values and continues with coin + Start after LOSE."""
        b=tower.Bot(1);seen=set();F=tower.FRAME
        out=b(10**9,[166,166,400,600,111,103,0,0],[0x23,0x3d])
        for k in range(1,400):out=b(10**9+k*F,[166,166,400+k%50,600-k%80,111,103-(k%20),0,0],[0,0x38] if k==100 else []);seen|={(p,v) for p,v in out.items()}
        self.assertTrue(all(explore.legal(((10**9,p,v),)) for p,v in seen))
        self.assertIn((3,0xfffe),seen);self.assertIn((3,0xfffb),seen)

    def test_tower_r2e11_route(self):
        """K9 A r2e11: legal but for the operator test switch; the input negative drops only the named lone press."""
        r=tower.route_specs()['r2e11'];t=r['tape'];gone=set(t)-set(r['input_negative']['native'])
        self.assertTrue(explore.legal(tuple(e for e in t if not (e[1]==3 and e[2]==0xffef))))
        self.assertEqual(len(gone),1);(c,p,v),=gone
        self.assertNotEqual(v,0xffff);self.assertTrue(all(abs(x[0]-c)>tower.FRAME for x in t if x!=(c,p,v)))
        self.assertEqual(r['horizon'],r['wave']['result']['formatter_tab']+tower.versus.TMS_HZ)


class Specials(unittest.TestCase):
    def test_entries(self):
        es=specials.entries()
        self.assertEqual((len(es),len({(e['table'],e['button'],e['character']) for e in es}),len({e['handler'] for e in es})),(116,75,62))
        self.assertEqual({e['kind'] for e in es},set(range(8)))
        for e in es:
            if all(t in specials.TOKEN_STICK for t in e['seq'][0]):
                self.assertEqual([{8:9,9:8}.get(t,t) for t in e['seq'][0]],e['seq'][1])   # the two facings mirror left/right
                for side in ('p1','p2'):self.assertTrue(explore.legal(tuple(sorted(specials.attempt_rows(e,side,0,3*10**8)[0]))))


class Sessions(unittest.TestCase):
    def test_session(self):
        h=int(180*explore.TMS_HZ);a,b=explore.random_session(3,h),explore.random_session(3,h)
        self.assertEqual(a,b);self.assertNotEqual(a['tape'],explore.random_session(4,h)['tape'])
        self.assertTrue(explore.legal(a['tape']));self.assertLessEqual(len(a['tape']),explore.SESSION_EVENTS)
        self.assertGreater(sum(1 for r in a['tape'] if r[1]==3 and r[0]>explore.FIGHT_TAPE[5][0]),0)


if __name__=='__main__':unittest.main()
