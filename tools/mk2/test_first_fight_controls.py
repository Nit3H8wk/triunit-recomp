"""Additional physical control paths keep their real from-reset prefix."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class FirstFightControlTests(unittest.TestCase):
    def test_simultaneous_held_controls_keep_the_original_latch_and_release(self):
        from tools.mk2 import generate_first_fight as fight
        for name,port,field,pressed,end,count in (
                ('right_high_punch_held',':IN0','P1 High Punch',[65511,65535,65535],134025042,1854857),
                ('right_low_punch_held',':IN2','P1 Low Punch',[65527,65535,65534],134025001,1852801)):
            branch=fight.measured.get('control_branches',{}).get(name)
            self.assertIsNotNone(branch,'Original simultaneous held control is not translated: '+name)
            self.assertEqual(branch['start_cpu34_sha256'],fight.interval(85)['end_cpu34_sha256'])
            self.assertEqual(branch['actions'],[
                {'port':':IN0','field':'P1 Right','press_frame':1122,'release_frame':1154},
                {'port':port,'field':field,'press_frame':1122,'release_frame':1154}])
            self.assertEqual(branch['physical_latches'],[
                [1123,2052759775,*pressed],[1155,2111253375,65535,65535,65535]])
            self.assertEqual((branch['end'],branch['cpu_rows']),(end,count))
            self.assertEqual(branch['end_cpu34_cycle'],branch['end'])
            self.assertFalse(branch['qualified_integral'])
            for source,targets in branch['successors'].items():
                self.assertIn(int(source,16),fight.PCS)
                self.assertTrue(set(int(t,16) for t in targets)<=set(fight.SUCCESSORS[int(source,16)]))

    def test_low_punch_path_is_measured_and_retains_all_authenticated_successors(self):
        from tools.mk2 import generate_first_fight as fight
        branch = fight.measured.get('control_branches', {}).get('low_punch')
        self.assertIsNotNone(branch, 'Original low-punch path is not translated')
        self.assertEqual(branch['start_cpu34_sha256'], fight.interval(85)['end_cpu34_sha256'])
        self.assertEqual(branch['action'], {'port': ':IN2', 'field': 'P1 Low Punch',
                                          'press_frame': 1122, 'release_frame': 1126})
        self.assertEqual(branch['start'], 128083937)
        self.assertEqual((branch['end'], branch['cpu_rows']), (130025934, 590489))
        self.assertEqual(branch['physical_latches'], [[1123, 2052759775, 65535, 65535, 65534],
                                                     [1127, 2060071475, 65535, 65535, 65535]])
        self.assertEqual(branch['end_cpu34_cycle'], branch['end'])
        self.assertGreater(branch['cpu_rows'], 0)
        self.assertFalse(branch['qualified_integral'])
        self.assertNotEqual(branch['end_cpu34_sha256'], fight.interval(86)['end_cpu34_sha256'])
        for source, targets in branch['successors'].items():
            self.assertIn(int(source, 16), fight.PCS)
            self.assertTrue(set(int(t, 16) for t in targets) <= set(fight.SUCCESSORS[int(source, 16)]))

    def test_right_path_is_measured_with_the_original_physical_latches(self):
        from tools.mk2 import generate_first_fight as fight
        branch = fight.measured.get('control_branches', {}).get('right')
        self.assertIsNotNone(branch, 'Original right path is not translated')
        self.assertEqual(branch['start_cpu34_sha256'], fight.interval(85)['end_cpu34_sha256'])
        self.assertEqual((branch['end'], branch['cpu_rows']), (130026104, 575765))
        self.assertEqual(branch['action'], {'port': ':IN0', 'field': 'P1 Right',
                                          'press_frame': 1122, 'release_frame': 1126})
        self.assertEqual(branch['physical_latches'], [[1123, 2052759775, 65527, 65535, 65535],
                                                     [1127, 2060071475, 65535, 65535, 65535]])
        self.assertFalse(branch['qualified_integral'])
        for source, targets in branch['successors'].items():
            self.assertIn(int(source, 16), fight.PCS)
            self.assertTrue(set(int(t, 16) for t in targets) <= set(fight.SUCCESSORS[int(source, 16)]))


if __name__ == '__main__':
    unittest.main()
