"""Byte provenance must preserve lanes, aliases, overlaps and unknowns."""
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))


class CoverageTests(unittest.TestCase):
    def test_runtime_semantics_change_invalidates_lookup(self):
        from tools.mk2.coverage import lookup
        from tools.quality import run as q
        with q.scratch_tree()as(scratch,cleanup):
            helper=scratch/'helper.hpp';helper.write_text('changed semantics')
            report={'format':'MK2_ROM_CPP_COVERAGE_V1','sources':{},'manifest_sha256':q.sha(q.ROOT/'tools/mk2/roms-l31.json'),
                    'compiler_dependencies':{'files':{str(helper):'0'*64}}}
            with self.assertRaisesRegex(ValueError,'Runtime source changed'):
                lookup(report,region='maincpu',bank='program',address=0xff800000)
        self.assertFalse(cleanup['exists_after'])

    def test_rom_manifest_identity_change_rejects_lookup(self):
        from tools.mk2.coverage import lookup
        report={'format':'MK2_ROM_CPP_COVERAGE_V1','sources':{},'manifest_sha256':'0'*64}
        with self.assertRaisesRegex(ValueError,'Manifest changed'):
            lookup(report,region='maincpu',bank='program',address=0xff800000)

    def test_partition_preserves_unknown_bytes_and_overlapping_candidates(self):
        from tools.mk2.coverage import partition
        self.assertEqual(partition(10,[(2,6,1),(4,8,2),(3,5,1)]),
                         [[0,2,0],[2,2,1],[4,2,3],[6,2,2],[8,2,0]])
        for spans in ([(-1,2,1)],[(8,11,1)],[(3,3,1)],[(2,4,0)]):
            with self.subTest(spans=spans),self.assertRaises(ValueError):partition(10,spans)

    def test_physical_slices_preserve_interleave_and_reload_without_double_counting(self):
        from tools.mk2.coverage import physical_slices
        lane={'path':'odd','size':4,'offset_bytes':1,'stride_bytes':2,'reload_offsets_bytes':[17]}
        self.assertEqual(physical_slices(lane,2,5),[(1,3,1)])
        self.assertEqual(physical_slices(lane,17,8),[(0,4,17)])
        self.assertEqual(physical_slices(lane,8,8),[])
        for start,length in ((-1,2),(0,0)):
            with self.assertRaises(ValueError):physical_slices(lane,start,length)

    def test_physical_inventory_keeps_nature_and_maturity_separate(self):
        from tools.mk2.coverage import physical_inventory
        roms = [
            {'path': 'even', 'region': 'maincpu', 'size': 4, 'offset_bytes': 0, 'stride_bytes': 2},
            {'path': 'odd', 'region': 'maincpu', 'size': 4, 'offset_bytes': 1, 'stride_bytes': 2,
             'reload_offsets_bytes': [17]},
        ]
        loaded = {'maincpu': [(0, 4, 1), (0, 4, 16), (2, 6, 2), (17, 18, 64), (4, 5, 4)]}
        result = physical_inventory(roms, loaded, {})
        self.assertEqual(result['physical_bytes'], 8)
        for name in ('even', 'odd'):
            self.assertEqual(result['roms'][name]['nature'],
                             {'code_evidence': 1, 'mixed': 1, 'data': 1, 'unknown': 1})
        self.assertEqual(result['roms']['even']['maturity_by_mask'], {'0': 2, '2': 2})
        self.assertEqual(result['roms']['odd']['maturity_by_mask'], {'0': 2, '2': 1, '10': 1})
        self.assertNotEqual(result['roms']['even']['interval_sha256'], result['roms']['odd']['interval_sha256'])
        for bad_roms, bad_physical in ((roms + roms, {}), (roms, {'other': [(0, 1, 2)]}),
                                       (roms, {'even': [(0, 5, 2)]})):
            with self.subTest(roms=bad_roms, physical=bad_physical), self.assertRaises(ValueError):
                physical_inventory(bad_roms, loaded, bad_physical)
        for bad_loaded in ({'other': [(0, 2, 1)]}, {'maincpu': [(6, 9, 1)]}, {'maincpu': [(8, 16, 1)]}):
            with self.subTest(loaded=bad_loaded), self.assertRaises(ValueError):
                physical_inventory(roms, bad_loaded, {})

    def test_blocks_keep_source_lines_and_stop_bodies_separate(self):
        from tools.mk2.coverage import blocks
        source='// header\ncase 0xff800000u: { // CLR A0\n o.Clear(s.a[0],0xff800010u);\n break;\n}\ncase 0xff800010u: { // REV\n throw std::runtime_error("unsupported");\n break;\n}\n'
        self.assertEqual(blocks(source),[(0xff800000,2,'CLR A0','generated'),(0xff800010,6,'REV','explicit_stop')])
        with self.assertRaisesRegex(ValueError,'Duplicate'):blocks(source+source)

    def test_program_manifest_must_match_the_authenticated_lane_loader(self):
        from tools.mk2 import coverage, run
        roms = run.read_manifest()['roms']
        lanes = coverage.program_lanes(roms)
        self.assertEqual([(entry['path'], entry['offset_bytes']) for entry in lanes],
                         [('uj12.l31', 0), ('ug12.l31', 1)])
        lanes[0]['offset_bytes'], lanes[1]['offset_bytes'] = lanes[1]['offset_bytes'], lanes[0]['offset_bytes']
        with self.assertRaisesRegex(ValueError, 'Program ROM lane mapping'):
            coverage.program_lanes(roms)

    def test_conditional_guards_are_partial_but_literal_dead_arms_are_not(self):
        from tools.mk2.coverage import blocks
        template='case 0xff800000u: { // JAN TARGET\n BODY\n break;\n}\n'
        for body,kind in ((
            'if((s.status&0x80000000)!=0) { throw std::runtime_error("unknown"); } else { o.Finish(0xff800030,4); }','partial'),(
            'if(true) { o.Finish(0xff800030,3); } else { throw std::runtime_error("unreachable"); }','generated'),(
            'if(true) { throw std::runtime_error("unknown"); } else { o.Finish(0xff800030,4); }','explicit_stop')):
            with self.subTest(body=body):self.assertEqual(blocks(template.replace('BODY',body))[0][3],kind)

    def test_lookup_rejects_unknown_region_bank_and_stale_source(self):
        from tools.mk2.coverage import lookup
        from tools.quality import run as q
        with q.scratch_tree()as(scratch,cleanup):
            p=scratch/'source.inc';p.write_text('changed')
            report={'format':'MK2_ROM_CPP_COVERAGE_V1','sources':{str(p):'0'*64}}
            with self.assertRaisesRegex(ValueError,'region/bank'):
                lookup(report,region='maincpu',bank='wrong',address=0xff800000)
            with self.assertRaisesRegex(ValueError,'Source changed'):
                lookup(report,region='maincpu',bank='program',address=0xff800000)
        self.assertFalse(cleanup['exists_after'])


if __name__=='__main__':unittest.main()
