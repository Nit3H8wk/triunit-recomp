"""Small real-compiler checks; no ROMs, GPU or retained test artifacts."""
import importlib.util
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.quality import run as q

MODULE = ROOT / 'tools/quality/cpp_build.py'
if MODULE.is_file():
    spec = importlib.util.spec_from_file_location('cpp_build', MODULE)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
else:
    builder = None


class CppBuildTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(builder, 'shared object builder has not been implemented')
        self.owner = q.scratch_tree()
        self.scratch, self.cleanup = self.owner.__enter__()
        self.addCleanup(self.close)
        a, b = self.scratch / 'one', self.scratch / 'two'
        a.mkdir(); b.mkdir()
        self.header = b / 'value.hpp'
        self.header.write_text('#define VALUE 2\n')
        self.main = a / 'same.cpp'
        self.main.write_text('#include <cstdio>\nextern int value();\nint main(){std::printf("%d",EXPECTED+value());}\n')
        self.other = b / 'same.cpp'
        self.other.write_text('#include "value.hpp"\nint value(){return VALUE;}\n')
        self.flags = ['-std=c++17', '-O1', '-Wall', '-Wextra', '-Werror', '-DEXPECTED=40']
        self.env = {'PATH': str(q.DEFAULT_CC.parent) + os.pathsep + os.environ['PATH']}
        self.cache = self.scratch / 'cache'

    def close(self):
        self.owner.__exit__(None, None, None)
        self.assertFalse(self.cleanup['exists_after'])

    def build(self, *, name='result', flags=None, cached=False, timeout=60, workers=2):
        executable = self.scratch / (name + '.exe')
        result = builder.build(q.DEFAULT_CC, self.flags if flags is None else flags,
            [self.main, self.other], [], executable, self.scratch, env=self.env,
            timeout=timeout, workers=workers, use_cache=cached, cache_directory=self.cache)
        return result, executable

    def output(self, executable):
        result = q.command([executable], self.scratch, env=self.env)
        self.assertTrue(result['passed'], result['stdout'])
        return result['stdout']

    def test_parallel_units_preserve_flags_linking_and_same_basename_sources(self):
        result, executable = self.build()
        self.assertTrue(result['passed'], result['stdout'])
        self.assertEqual(self.output(executable), '42')
        self.assertEqual(len(result['build_units']), 2)
        self.assertFalse(result['object_cleanup']['exists_after'])
        self.assertFalse(list(self.scratch.rglob('*.o')))

    def test_warm_cache_reuses_real_objects_without_retaining_test_objects(self):
        first, a = self.build(name='first', cached=True)
        second, b = self.build(name='second', cached=True)
        self.assertTrue(first['passed'], first['stdout'])
        self.assertTrue(second['passed'], second['stdout'])
        self.assertEqual(self.output(a), self.output(b))
        self.assertEqual(second['compiler_cache']['hits'], 2)
        self.assertEqual(second['compiler_cache']['misses'], 0)
        self.assertLessEqual(second['compiler_cache']['bytes'], 64000000)
        self.assertFalse(list(self.scratch.rglob('*.o')))

    def test_recreated_generated_unit_hits_the_shared_cache(self):
        if not builder.CCACHE.is_file():
            self.skipTest('Pinned compiler cache executable unavailable')
        for index, content in enumerate((17, 17, 29)):
            with q.scratch_tree() as (scratch, cleanup):
                source = scratch/'mk2_generated_cache_control.cpp'
                source.write_text(f'int main() {{return {content};}}\n')
                executable = scratch/'control.exe'
                result = builder.build(q.DEFAULT_CC, self.flags, [source], [], executable, scratch,
                                       env=self.env, compile_from_scratch=True)
                self.assertTrue(result['passed'], result['stdout'])
                self.assertEqual(q.command([executable], scratch)['exit_code'], content)
                self.assertTrue(result['compiler_cache']['quota_verified'])
                if index == 1:
                    self.assertEqual(result['compiler_cache']['hits'], 1)
            self.assertFalse(cleanup['exists_after'])

    def test_same_size_same_mtime_header_change_invalidates_cached_code(self):
        first, _ = self.build(name='first', cached=True)
        self.assertTrue(first['passed'], first['stdout'])
        before = self.header.stat()
        self.header.write_text('#define VALUE 3\n')
        os.utime(self.header, ns=(before.st_atime_ns, before.st_mtime_ns))
        second, executable = self.build(name='second', cached=True)
        self.assertTrue(second['passed'], second['stdout'])
        self.assertEqual(self.output(executable), '43')
        self.assertEqual(second['compiler_cache']['misses'], 1)

    def test_compiler_flags_invalidate_cache_and_ambient_ccache_settings_are_isolated(self):
        first, _ = self.build(name='first', cached=True)
        self.assertTrue(first['passed'], first['stdout'])
        poison = {'CCACHE_COMPILER': 'missing-compiler.exe', 'CCACHE_SLOPPINESS': 'time_macros,include_file_mtime',
                  'CCACHE_DIR': str(self.scratch / 'unrequested-cache')}
        with patch.dict(os.environ, poison):
            second, executable = self.build(name='second', flags=self.flags[:-1] + ['-DEXPECTED=41'], cached=True)
        self.assertTrue(second['passed'], second['stdout'])
        self.assertEqual(self.output(executable), '43')
        self.assertGreater(second['compiler_cache']['misses'], 0)
        self.assertFalse((self.scratch / 'unrequested-cache').exists())

    def test_compile_failure_preserves_existing_executable_and_cleans_objects(self):
        target = self.scratch / 'result.exe'
        target.write_bytes(b'preserved-existing-file')
        self.other.write_text('this is not C++;\n')
        result, executable = self.build()
        self.assertFalse(result['passed'])
        self.assertEqual(executable.read_bytes(), b'preserved-existing-file')
        self.assertFalse(result['object_cleanup']['exists_after'])
        self.assertFalse(list(self.scratch.rglob('*.o')))

    def test_deadline_is_shared_and_expired_build_cannot_link(self):
        result, executable = self.build(timeout=0.001)
        self.assertFalse(result['passed'])
        self.assertTrue(result['timed_out'])
        self.assertFalse(executable.exists())
        self.assertFalse(result['object_cleanup']['exists_after'])

    def test_cached_timeout_keeps_failure_result_and_finalizes_cache_quota(self):
        clock = type('Clock', (), {})()
        expired = [False]
        clock.perf_counter = lambda: time.perf_counter() + (120 if expired[0] else 0)
        real = q.command
        def timeout_compile(args, *positional, **kwargs):
            if '-c' in args:
                kwargs['timeout'] = 0.001
            result = real(args, *positional, **kwargs)
            if '-c' in args:
                expired[0] = True
            return result
        with patch.object(builder, 'time', clock), patch.object(q, 'command', side_effect=timeout_compile):
            result, executable = self.build(cached=True)
        self.assertFalse(result['passed'])
        self.assertTrue(result['timed_out'])
        self.assertFalse(executable.exists())
        self.assertFalse(result['object_cleanup']['exists_after'])
        self.assertTrue(result['compiler_cache']['quota_verified'])
        self.assertLessEqual(result['compiler_cache']['bytes'], 64000000)

    def test_maintenance_failure_still_measures_cache_and_preserves_cleanup(self):
        real = q.command
        for mode in ('--print-log-stats', '--cleanup'):
            with self.subTest(mode=mode):
                clock = type('Clock', (), {})()
                expired = [False]
                clock.perf_counter = lambda: time.perf_counter() + (120 if expired[0] else 0)
                def fail_maintenance(args, *positional, **kwargs):
                    if mode in args:
                        expired[0] = True
                        return builder.failed('Simulated maintenance timeout', True)
                    return real(args, *positional, **kwargs)
                with patch.object(builder, 'time', clock), patch.object(q, 'command', side_effect=fail_maintenance):
                    result, _ = self.build(name='maintenance-' + mode[2:], cached=True)
                self.assertFalse(result['passed'])
                self.assertFalse(result['object_cleanup']['exists_after'])
                self.assertTrue(result['compiler_cache']['quota_verified'])
                self.assertGreater(result['compiler_cache']['bytes'], 0)
                self.assertLessEqual(result['compiler_cache']['bytes'], 64000000)

    def test_memory_gate_bounds_reservations_and_always_runs_one_unit(self):
        import threading
        gate = builder.MemoryGate(10)
        with gate(50):   # alone and above the budget: still runs
            pass
        lock, now, peak = threading.Lock(), [0], [0]

        def unit():
            with gate(4):
                with lock:
                    now[0] += 1
                    peak[0] = max(peak[0], now[0])
                time.sleep(0.05)
                with lock:
                    now[0] -= 1
        threads = [threading.Thread(target=unit) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual((peak[0], gate.free, gate.running), (2, 10, 0))

    def test_heavier_units_weigh_their_generated_includes(self):
        (self.scratch / 'graph.inc').write_text('x' * 5000)
        unit = self.scratch / 'unit.cpp'
        unit.write_text('#include "graph.inc"\n')
        self.assertEqual(builder.weight(unit, []), unit.stat().st_size + 5000)

    def test_invalid_worker_counts_and_empty_sources_are_rejected(self):
        for count in (0, builder.MAX_WORKERS + 1, True):
            with self.subTest(workers=count), self.assertRaises(ValueError):
                self.build(workers=count)
        with self.assertRaises(ValueError):
            builder.build(q.DEFAULT_CC, self.flags, [], [], self.scratch / 'empty.exe', self.scratch)

    def test_cache_tool_tampering_is_rejected_before_reuse(self):
        fake = self.scratch / 'ccache.exe'
        fake.write_bytes(b'not the pinned tool')
        with patch.object(builder, 'CCACHE', fake), self.assertRaisesRegex(ValueError, 'identity'):
            self.build(cached=True)

    def test_automatic_route_preserves_source_order_flags_and_link_options(self):
        self.assertTrue(callable(getattr(builder, 'route', None)), 'MK2 build routing is missing')
        source = ROOT / 'native/mk2/mk2_task_batch.cpp'
        argv = [q.DEFAULT_CC, '-O1', '-DVALUE=7', source, self.main, '-lbcrypt', '-o', self.scratch / 'out.exe']
        selected = builder.route(argv)
        self.assertEqual(selected['sources'], [source, self.main])
        self.assertEqual(selected['flags'], ['-O1', '-DVALUE=7'])
        self.assertEqual(selected['link_flags'], ['-lbcrypt'])
        for flag in ('-c', '-E', '-MM', '-flto', '-shared', '-save-temps', '-Bother',
                     '-specs=other', '--specs=other', '-include', '@response.cpp', '--'):
            with self.subTest(flag=flag):
                self.assertIsNone(builder.route(argv[:1] + [flag] + argv[1:]))
        self.assertIsNone(builder.route([q.DEFAULT_CC, '-o', self.scratch / 'x.exe', source, self.main]))
        self.assertIsNone(builder.route([q.DEFAULT_CC, '-lbcrypt', source, self.main, '-o', self.scratch / 'x.exe']))


if __name__ == '__main__':
    unittest.main()
