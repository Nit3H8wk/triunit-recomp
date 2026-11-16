"""K1 front B: tools/mk3/explore.py without builds or the Original (focal layer, seconds).

- random tapes: legal (replay.read_tape round trip, INPUT_PORTS(mk3) bits, no opposite stick directions), deterministic
  from the seed, different across seeds, within MAX_EVENTS;
- greedy cover and stop grouping on synthetic results;
- receipt digest: equal records give the recorded chain; one changed record field is found in its 64-record block;
  a changed Original-side identity requires a recapture; a changed executor does not; the 1 MB directory ceiling holds;
- first-execution packing is lossless; the route_verified.json writer keeps only passing receipts.
"""
from pathlib import Path
import copy,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import explore,replay_state

FIELDS=['totalcycles','ax0']


def record(k,events=True):
    r=dict(spec=1000+k,cycle=1000+k,pc=0xff800000+16*k,status=0x10,registers=[k]*31,hash={n:f'{k:x}' for n in replay_state.REGIONS},
           dma=[0]*18,io=[0]*32,control=0,adsp=dict(frozen=False,fields=[k,k]),pcm=dict(segment=0,hash='cbf29ce484222325'),samples='')
    if events:r['events']={n:[k,f'{k:x}'] for n in replay_state.STREAMS}
    return r


class Tapes(unittest.TestCase):
    def test_legal_deterministic(self):
        h=int(120*explore.TMS_HZ)
        a,b,c=(explore.random_tape(s,h) for s in (5,5,6))
        self.assertEqual(a,b);self.assertNotEqual(a['tape'],c['tape'])
        for s in range(40):
            t=explore.random_tape(s,h)
            self.assertTrue(explore.legal(t['tape']),s);self.assertLessEqual(len(t['tape']),explore.MAX_EVENTS)
            self.assertLessEqual(set(explore.FIGHT_TAPE[:6]),set(t['tape']))   # coin, coin, Start P1 as the J3 route
        self.assertFalse(explore.legal(((200000000,0,0xffff^3),)))             # up + down
        self.assertFalse(explore.legal(((200000000,3,0xffff^0x10),)))          # test switch: not an exploration input


class Cover(unittest.TestCase):
    def test_greedy_and_stops(self):
        s=lambda *ids:{k:[[i,0] for i in ids] if k=='TmsBlock' else [] for k in explore.KINDS}
        res=[dict(seed=0,sets=s(1,2),tape=(),end_cycle=10,frontier='none',dcs_frontier=''),
             dict(seed=1,sets=s(1,2,3,4),tape=((1000,0,1),),end_cycle=50,frontier='MK3 unobserved branch; PC 16; address 16',dcs_frontier=''),
             dict(seed=2,sets=s(4,5),tape=((1000,0,2),),end_cycle=20,frontier='MK3 unobserved branch; PC 16; address 16',dcs_frontier=''),
             dict(seed=3,sets=s(2),tape=(),end_cycle=30,frontier='other stop; PC 32',dcs_frontier='')]
        g=explore.greedy(res)
        self.assertEqual([t['seed'] for t in g['tapes']],[1,2]);self.assertEqual(g['keys'],5)
        stops=explore.group_stops(res)
        self.assertEqual((stops[0]['tapes'],stops[0]['pc'],stops[0]['reproducer']['seed']),(2,'0x10',2))   # the soonest reproducer
        self.assertEqual(len(stops),2)


class Receipts(unittest.TestCase):
    def test_digest_and_negatives(self):
        recs=[record(k) for k in range(200)];links=explore.chain(recs,FIELDS)
        self.assertEqual(len(links),4);self.assertEqual(explore.chain(copy.deepcopy(recs),FIELDS),links)
        for path,change in ((('hash','ram'),'0'),(('events','dma'),[0,'0']),(('registers',),None)):
            bad=copy.deepcopy(recs);r=bad[130]
            if path==('registers',):r['registers'][3]^=1
            else:r[path[0]][path[1]]=change
            got=explore.chain(bad,FIELDS)
            self.assertEqual(next(k for k,(a,b) in enumerate(zip(got,links)) if a!=b),130//explore.CHAIN,path)
        bad=copy.deepcopy(recs);bad[5]['adsp']['fields'][0]^=1       # totalcycles is not compared: the digest ignores it
        self.assertEqual(explore.chain(bad,FIELDS),links)

    def test_recapture_and_ceiling(self):
        ids=dict(core_sha256='c',program_sha256='p',seed_sha256='s',tape_sha256=explore.tape_sha(()),observer_sha256='o')
        rec=dict(identities=dict(ids,debugger='x'),tape=[],executor=dict(executor_sha256='e1'))
        self.assertEqual(explore.needs_recapture(rec,ids),[])
        self.assertEqual(explore.needs_recapture(rec,dict(ids,program_sha256='q')),['program_sha256'])
        self.assertEqual(explore.needs_recapture(rec,dict(ids,tape_sha256=explore.tape_sha(((1000,0,1),)))),['tape_sha256'])
        rec['executor']['executor_sha256']='e2';self.assertEqual(explore.needs_recapture(rec,ids),[])   # the native side is what regression checks
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            explore.write_receipt(dict(name='a',pad='x'*600000),d,1000000)
            explore.write_receipt(dict(name='a',pad='x'*700000),d,1000000)                             # replacing itself is fine
            with self.assertRaises(ValueError):explore.write_receipt(dict(name='b',pad='x'*400000),d,1000000)
            self.assertEqual(sorted(p.name for p in d.iterdir()),['a.json'])

    def test_pack_and_verified(self):
        pairs=sorted([[0xff800000+16*k,(k*7)%3] for k in range(500)]+[[0xffa00000,0xff800010]])
        self.assertEqual(explore.unpack(explore.pack(pairs)),pairs)
        fe=lambda ids:{k:dict(packed=explore.pack([[i,0] for i in ids] if k=='TmsBlock' else []),sha256='') for k in explore.KINDS}
        rs=[dict(name='r1',passed=True,identities=dict(program_sha256='p'),first_executions=fe([3,1])),
            dict(name='r2',passed=False,identities=dict(program_sha256='p'),first_executions=fe([9])),
            dict(name='r3',passed=True,identities=dict(program_sha256='p'),first_executions=fe([1,2]))]
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);old=explore.ROUTES;explore.ROUTES=d
            try:
                for r in rs:(d/f'{r["name"]}.json').write_text(json.dumps(r),encoding='utf-8')
                data=explore.write_verified(rs,d/'v.json');back=json.loads((d/'v.json').read_text('utf-8'))
            finally:explore.ROUTES=old
        self.assertEqual(back['schema'],'mk3-route-verified/1');self.assertEqual([r['name'] for r in back['routes']],['r1','r3'])
        self.assertEqual(back['TmsBlock'],[[1,0],[2,0],[3,0]]);self.assertEqual(back,json.loads(json.dumps(data)))


class Compact(unittest.TestCase):
    def test_upgrade_lossless(self):
        tape=((125000000,3,0xfffe),(125625000,3,0xffff),(200000000,0,0xffef))
        cmos=[[1000+7*k,0x1400000+16*(k%40),k&0xff] for k in range(300)]
        cs=explore.compact_stream(cmos)
        old=dict(schema='mk3-route-receipt/1',name='r',tape=[list(e) for e in tape],identities=dict(tape_sha256=explore.tape_sha(tape)),
                 events=dict(dcs=[[5,1]],input=dict(count=9,sha256='i'),cmos=dict(count=300,sha256=cs['sha256'],events=cmos)),integral=dict(at='t'))
        raw=json.dumps(old).encode();new=explore.upgrade_receipt(old,raw)
        self.assertEqual(new['schema'],explore.SCHEMA);self.assertEqual(explore.receipt_tape(new),list(tape));self.assertEqual(explore.receipt_tape(old),list(tape))
        self.assertEqual(explore.stream_rows(new['events']['cmos']),cmos);self.assertEqual(new['events']['input'],old['events']['input'])
        self.assertEqual((new['integral'],explore.dcs_rows(new)),(old['integral'],old['events']['dcs']))
        self.assertEqual(new['reencoded']['from_sha256'],explore.hashlib.sha256(raw).hexdigest())
        bad=copy.deepcopy(old);bad['events']['cmos']['sha256']='x'
        with self.assertRaises(ValueError):explore.upgrade_receipt(bad,raw)
        bad=copy.deepcopy(old);bad['identities']['tape_sha256']='x'
        with self.assertRaises(ValueError):explore.upgrade_receipt(bad,raw)
        with self.assertRaises(ValueError):explore.upgrade_receipt(new,raw)
        self.assertNotIn('packed',explore.compact_stream(cmos,False))
        old['events']['totals']=old['events']['dma']={};new=json.loads(json.dumps(explore.upgrade_receipt(old,raw)))
        self.assertEqual(explore.lossless(old,new),[])
        bad=copy.deepcopy(new);bad['events']['cmos']['packed']=explore.pack(cmos[:-1],3)
        self.assertEqual(explore.lossless(old,bad),['events.cmos'])
        bad=copy.deepcopy(new);bad['integral']['at']='u';self.assertEqual(explore.lossless(old,bad),['integral'])


class Streams(unittest.TestCase):
    def test_stream_difference(self):
        ev=lambda dcs:dict(events_total={n:[len(dcs) if n=='dcs' else 0,'x'] for n in replay_state.STREAMS},
                           events_full=dict(dcs=dcs,input=[],cmos=[]))
        a=dict(events=ev([[10,1],[20,2]]));b=dict(events=ev([[10,1],[21,2]]))
        d=replay_state.stream_difference(a,b)
        self.assertEqual(d['dcs']['index'],1);self.assertIsNone(d['input'])
        self.assertTrue(all(v is None for v in replay_state.stream_difference(a,copy.deepcopy(a)).values()))


if __name__=='__main__':unittest.main()
