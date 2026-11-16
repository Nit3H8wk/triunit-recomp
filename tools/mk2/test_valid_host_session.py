"""Finite persistent host sessions stop at genuine cooperative boundaries."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import native, profile
from tools.quality import run as quality
from unittest import mock


def synthetic(expected):
    """Raw Original rows are not versioned (only their SHA-256): a stand-in CPU34 row at the frontier's PC/cycle and the
    frontier re-pointed to its digest, so the receipt logic is exercised without observed values."""
    from tools.mk2 import oracle_digest
    row = [expected['pc'], 0x10, expected['cycle']] + list(range(31))
    return row, dict(expected, sha256=oracle_digest.words_digest(row[:expected['words']]))


DRAW_CPU, DRAW = synthetic(native.frontier('cmos-draw'))
REAL_FRONTIER = native.frontier


def result(*, early=False):
    cpu = DRAW_CPU.copy()
    if not early:
        cpu[2] = 148081944 + 1000
    frames = cpu[2] * 16 // 1827925
    start = 7316296
    return {
        'scope': 'mk2-native-cmos-host-check', 'through': 'cmos-host',
        'input': 'valid-cmos-host-keyboard-xinput-finite',
        'gameplay_complete': False, 'execution_continues': False,
        'termination': 'finite_valid_cmos_host_stop_requested' if early else 'finite_valid_cmos_host_boundary',
        'frontier_pc': cpu[0], 'cpu34': cpu, 'frames': frames,
        'width': 400, 'height': 254, 'frame_sha256': ['0' * 64] * frames,
        'host_controls': {
            'origin': 'valid_cmos_draw', 'start_cycle': start,
            'stop_after_cycle': 148081944, 'maximum_cycle': 150023965,
            'provider_admitted': not early, 'provider_requests': 0 if early else 1,
            'stop_requested': early,
            'last_input': 0xffffffff,
            'last_input_tick': 0 if early else start * 16 + 16,
            'stop_observed_tick': 1 if early else 0,
            'events': [] if early else [[start * 16 + 16, (1 << 48) - 1, (1 << 48) - 1, 6]],
        },
    }


class ValidHostSessionTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(native, 'frontier', side_effect=lambda through, *a, **k:
                                  DRAW if through == 'cmos-draw' and not a and not k else REAL_FRONTIER(through, *a, **k))
        patch.start()
        self.addCleanup(patch.stop)

    def test_early_close_requires_exact_draw_before_provider_admission(self):
        observed = result(early=True)
        native.validate_valid_host_boundary(observed)
        for field in ('cpu34', 'provider_admitted', 'provider_requests', 'events', 'stop_requested'):
            changed = copy.deepcopy(observed)
            if field == 'cpu34':
                changed[field][33] ^= 1
            elif field == 'provider_admitted':
                changed['host_controls'][field] = True
            elif field == 'provider_requests':
                changed['host_controls'][field] = 1
            elif field == 'events':
                changed['host_controls'][field] = [[7316296 * 16, 0, 0, 6]]
            else:
                changed['host_controls'][field] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                native.validate_valid_host_boundary(changed)

    def test_finite_host_rejects_unqualified_termination_origin_and_events(self):
        observed = result()
        native.validate_valid_host_boundary(observed)
        changes = [
            ('origin', 'cold_first_fight'), ('start_cycle', 7316295),
            ('maximum_cycle', 150023966), ('provider_requests', 2),
            ('events', [[7316296 * 16 - 1, 0, 0, 6]]),
            ('events', [[7316296 * 16 + 16, 1 << 48, 0, 6]]),
            ('events', [[7316296 * 16 + 16, 0, 0, 0]]),
        ]
        for field, value in changes:
            changed = copy.deepcopy(observed)
            changed['host_controls'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                native.validate_valid_host_boundary(changed)
        changed = copy.deepcopy(observed)
        changed['host_controls']['last_input_tick'] = 1
        with self.assertRaises(ValueError):
            native.validate_valid_host_boundary(changed)
        for tick, value in [(0, 0xffffffef), (7316296 * 16 + 16, 0xffffffef)]:
            changed = copy.deepcopy(observed)
            changed['host_controls']['last_input_tick'] = tick
            changed['host_controls']['last_input'] = value
            with self.subTest(tick=tick, value=value), self.assertRaises(ValueError):
                native.validate_valid_host_boundary(changed)
        changed = copy.deepcopy(observed)
        changed['host_controls']['stop_requested'] = True
        changed['host_controls']['last_input_tick'] = 0
        changed['host_controls']['stop_observed_tick'] = 1
        changed['termination'] = 'finite_valid_cmos_host_stop_requested'
        with self.assertRaises(ValueError):
            native.validate_valid_host_boundary(changed)
        changed['host_controls']['stop_observed_tick'] = 7316296 * 16 + 32
        changed['host_controls']['last_input'] = 0xffffffef
        with self.assertRaises(ValueError):
            native.validate_valid_host_boundary(changed)
        for field, value in [('gameplay_complete', True), ('execution_continues', True),
                             ('termination', 'gameplay_complete'), ('frames', observed['frames'] - 1)]:
            changed = copy.deepcopy(observed)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                native.validate_valid_host_boundary(changed)

    def test_last_shared_input_matches_physical_ports_for_punches_and_kicks(self):
        # P1/P2 low buttons occupy PORT2, beyond the packed lower 32 bits.
        for shared, physical in [(0xffffffef, 0xffffffffffef),
                                 (0xefffffff, 0xfffeffffffff),
                                 (0xdfffffff, 0xfffdffffffff),
                                 (0xfdffffff, 0xffefffffffff),
                                 (0xfbffffff, 0xffdfffffffff)]:
            observed = result()
            observed['host_controls']['last_input'] = shared
            observed['host_controls']['events'][0][1] = physical
            with self.subTest(shared=shared, physical=physical):
                native.validate_valid_host_boundary(observed)

    def test_host_requires_explicit_existing_profile_and_window_before_build(self):
        missing = native.run(quality.ROOT / 'missing-roms', through='cmos-host', window=True, host_controls=True)
        self.assertFalse(missing['passed'])
        self.assertEqual(missing['error'], 'cmos-host requires an existing explicit --profile')
        self.assertNotIn('build', missing)
        with quality.scratch_tree() as (scratch, cleanup):
            directory = scratch / 'profile'
            initial = profile.prepare(directory)
            for window, controls, reference in [(False, True, False), (True, False, False), (True, True, True)]:
                observed = native.run(quality.ROOT / 'missing-roms', through='cmos-host',
                    window=window, host_controls=controls, reference_frames=reference, profile_directory=directory)
                self.assertFalse(observed['passed'])
                self.assertEqual(observed['error'], 'Valid CMOS host requires --window --host-controls without reference capture')
                self.assertNotIn('build', observed)
                self.assertEqual(profile.load(directory), initial)
        self.assertFalse(cleanup['exists_after'])


if __name__ == '__main__':
    unittest.main()
