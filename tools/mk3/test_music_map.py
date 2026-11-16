"""tools/mk3/music_map.py on synthetic route receipts in a scratch tree (removed at the end, also on failure).

    python -m unittest tools.mk3.test_music_map
"""
from pathlib import Path
import json,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import music_map as m


def writes(*commands,start=1000,step=10):
    """Sound-port byte writes of commands: high byte, then low byte."""
    out=[];cycle=start
    for c in commands:out+=[[cycle,c>>8],[cycle+1,c&0xff]];cycle+=step
    return out


class MusicMapTests(unittest.TestCase):
    def test_map_from_receipts(self):
        with q.scratch_tree() as (temp,cleanup):
            (temp/'fight.json').write_text(json.dumps(dict(events=dict(dcs=writes(0x0451,0x1234,0x2341,0x233d,0x1234,0x0021)+[[9999,0x12]]))),'utf-8')
            (temp/'attract.json').write_text(json.dumps(dict(events=dict(dcs=writes(0x1234,0x0451,0x1234)))),'utf-8')
            got=m.build(m.load(temp))
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(got['routes']['fight'],dict(writes=13,commands=6,unpaired_tail=[9999,0x12]))
        self.assertEqual(got['routes']['attract']['unpaired_tail'],None)
        c=got['commands']
        self.assertEqual(c['233d']['classe'],'fala');self.assertIn('FFAA6D00h',c['233d']['evidencia'])
        self.assertEqual((c['1234']['classe'],c['1234']['evidencia'],c['1234']['marca']),(m.UNCLASSIFIED,None,None))
        self.assertEqual(c['0021']['classe'],m.UNCLASSIFIED,'a mark is a context, not a class')
        self.assertEqual(c['1234']['contexts']['fight'],dict(count=2,first_cycle=1011,phases={'0451 '+m.MARKS[0x0451]:1,'233d round start':1}))
        self.assertEqual(c['1234']['contexts']['attract']['phases'],{'antes da primeira marca':1,'0451 '+m.MARKS[0x0451]:1})
        self.assertEqual(c['0451']['contexts']['fight']['phases'],{'0451 '+m.MARKS[0x0451]:1},'a mark opens its own phase')
        self.assertEqual((got['tracks_associated'],got['assets']),(0,0))
        self.assertEqual(got['classes'],{'fala':1,m.UNCLASSIFIED:4})

    def test_rejects_malformed_streams(self):
        for bad in ([[10,0x123],[11,0]],[[10,0],[9,1]],[[10]],[[True,1],[11,2]]):
            with self.assertRaises(ValueError,msg=bad):m.commands(bad)
        with q.scratch_tree() as (temp,cleanup):
            (temp/'route.json').write_text(json.dumps(dict(events=dict(dma=[]))),'utf-8')
            with self.assertRaises(ValueError):m.load(temp)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
