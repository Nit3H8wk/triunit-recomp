"""Safety and false-positive regressions for the quality entry point (no ROMs)."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("quality_runner", HERE / "run.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class RunnerTests(unittest.TestCase):
    def test_script_entry_point_can_load_shared_builder_without_pythonpath(self):
        code = (
            "import runpy; m=runpy.run_path(" + repr(str(HERE / 'run.py')) + "); "
            "owner=m['scratch_tree'](); scratch,cleanup=owner.__enter__(); "
            "result=m['command']([m['DEFAULT_CC'],'--version'],scratch); "
            "owner.__exit__(None,None,None); "
            "assert result['passed'],result; assert not cleanup['exists_after']"
        )
        with quality.scratch_tree() as (scratch, cleanup):
            result = quality.command([sys.executable, '-I', '-B', '-c', code], scratch)
        self.assertTrue(result['passed'], result)
        self.assertFalse(cleanup['exists_after'])

    def test_explicit_working_directory_contains_relative_outputs(self):
        with quality.scratch_tree() as (scratch, cleanup):
            result = quality.command([sys.executable, "-c",
                                      "from pathlib import Path; Path('cwd-sentinel').write_text('ok')"],
                                     scratch, cwd=scratch)
            self.assertTrue(result["passed"], result)
            self.assertEqual((scratch / "cwd-sentinel").read_text(), "ok")
        self.assertFalse(cleanup["exists_after"])

    def test_no_empty_success(self):
        self.assertFalse(quality.all_passed([]))
        self.assertFalse(quality.all_passed([{"passed": False}]))
        self.assertTrue(quality.all_passed([{"passed": True}]))

    def test_timeout_fails_and_scratch_is_removed(self):
        with quality.scratch_tree() as (scratch, cleanup):
            result = quality.command([sys.executable, "-c", "import time; time.sleep(5)"],
                                     scratch, timeout=0.1)
            self.assertFalse(result["passed"])
            self.assertTrue(result["timed_out"])
            (scratch / "sentinel.txt").write_text("temporary")
        self.assertFalse(scratch.exists())
        self.assertFalse(cleanup["exists_after"])

    def test_nonzero_is_not_masked(self):
        with quality.scratch_tree() as (scratch, _):
            result = quality.command([sys.executable, "-c", "raise SystemExit(19)"], scratch)
        self.assertFalse(result["passed"])
        self.assertEqual(result["exit_code"], 19)

    def test_output_is_bounded_in_memory(self):
        with quality.scratch_tree() as (scratch, _):
            result = quality.command([sys.executable, "-c", "print('x'*300000)"], scratch)
        self.assertTrue(result["passed"])
        self.assertLessEqual(len(result["stdout"]), quality.OUTPUT_LIMIT)
        self.assertGreater(result["discarded_output_bytes"], 0)

    def test_explicit_output_budget_preserves_finite_observations_and_still_bounds(self):
        with quality.scratch_tree() as (scratch, _):
            result = quality.command([sys.executable, "-c", "print('x'*150000)"], scratch,
                                     output_limit=256*1024)
            bounded = quality.command([sys.executable, "-c", "print('x'*300000)"], scratch,
                                      output_limit=256*1024)
        self.assertTrue(result["passed"])
        self.assertEqual(result["discarded_output_bytes"], 0)
        self.assertEqual(result["stdout"].strip(), 'x'*150000)
        self.assertTrue(bounded["passed"])
        self.assertLessEqual(len(bounded["stdout"]), 256*1024)
        self.assertGreater(bounded["discarded_output_bytes"], 0)

    def test_exception_still_cleans_scratch(self):
        with self.assertRaisesRegex(RuntimeError, "fixture failure"):
            with quality.scratch_tree() as (scratch, cleanup):
                (scratch / "sentinel").write_text("test")
                raise RuntimeError("fixture failure")
        self.assertFalse(scratch.exists())
        self.assertFalse(cleanup["exists_after"])

    @unittest.skipUnless(sys.platform == "win32", "Win32 process ownership")
    def test_root_exit_with_live_descendant_fails_and_reaps_job(self):
        script = ("import subprocess,sys,time; "
                  "subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                  "time.sleep(.3)")
        with quality.scratch_tree() as (scratch, cleanup):
            result = quality.command([sys.executable, "-c", script], scratch, timeout=3)
        self.assertFalse(result["passed"])
        self.assertGreater(result["descendants_after_exit"], 0)
        self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])

    @unittest.skipUnless(sys.platform == "win32", "Win32 process ownership")
    def test_assignment_failure_never_executes_unowned_child(self):
        with quality.scratch_tree() as (scratch, _):
            sentinel = scratch / "must-not-exist"
            script = "from pathlib import Path; import sys; Path(sys.argv[1]).touch()"
            with mock.patch.object(quality.ProcessJob, "assign", side_effect=RuntimeError("fixture")):
                result = quality.command([sys.executable, "-c", script, str(sentinel)], scratch)
            self.assertFalse(result["passed"])
            self.assertFalse(sentinel.exists())

    @unittest.skipUnless(sys.platform == "win32", "Win32 process ownership")
    def test_short_child_shutdown_is_allowed_but_must_complete(self):
        script = ("import subprocess,sys; "
                  "subprocess.Popen([sys.executable,'-c','import time; time.sleep(.1)'])")
        with quality.scratch_tree() as (scratch, _):
            result = quality.command([sys.executable, "-c", script], scratch)
        self.assertTrue(result["passed"], result)
        self.assertTrue(result["owned_job_empty"])

    def test_headless_requires_real_progress_and_expected_boundary(self):
        game = {"scope": "mk5-main-loop", "stop": "main-di-limit",
                "main": {"executed": True, "calls": 8, "instructions": 100, "di_limit": 64},
                "body": {"normal_boot_complete": True}, "reference_model_cycles": 1000,
                "window_presented": False}
        audio = {"sound_frontier": "", "submitted": 10, "completed": 10,
                 "pcm_48k_s16_mono": 10, "underruns": 0}
        self.assertTrue(quality.validate_headless(game, audio))
        for patch in ({"stop": "untranslated-frontier"}, {"stop": "instruction-budget"},
                      {"main": {"executed": False}},
                      {"window_presented": True}, {"body": {"normal_boot_complete": False}}):
            self.assertFalse(quality.validate_headless({**game, **patch}, audio))
        for patch in ({"sound_frontier": "unknown"}, {"completed": 0},
                      {"underruns": 1}, {"submitted": 0}, {"pcm_48k_s16_mono": 11}):
            self.assertFalse(quality.validate_headless(game, {**audio, **patch}))

    def test_json_diagnostics_are_not_mistaken_for_game_result(self):
        game, audio = quality.parse_engine_output('{"audio_underrun_sample":9}\n'
            '{"scope":"mk5-main-loop"}\n{"audio":"original-Williams-ADPCM"}\n')
        self.assertEqual(game["scope"], "mk5-main-loop")
        self.assertEqual(audio["audio"], "original-Williams-ADPCM")
        with self.assertRaises(ValueError):
            quality.parse_engine_output('{"scope":"mk5-main-loop"}\n')

    def test_sanitizer_control_requires_expected_trap_not_runner_failure(self):
        result = {"exit_code": 3221225501, "owned_job_empty": True,
                  "descendants_after_exit": 0, "timed_out": False}
        self.assertTrue(quality.negative_control_detected(result, "undefined"))
        for patch in ({"exit_code": None}, {"exit_code": 1}, {"error": "launch failed"},
                      {"cleanup_error": "ownership failed"}, {"timed_out": True},
                      {"owned_job_empty": False}, {"descendants_after_exit": 1}):
            self.assertFalse(quality.negative_control_detected({**result, **patch}, "undefined"))

    def test_asan_prefers_separate_clang_toolchain_and_honors_explicit_compiler(self):
        self.assertEqual(quality.select_compiler(None, "address"), quality.ASAN_CC)
        self.assertEqual(quality.select_compiler(None, "none"), quality.DEFAULT_CC)
        explicit = Path("C:/custom/clang++.exe")
        self.assertEqual(quality.select_compiler(explicit, "address"), explicit)

    def test_asan_negative_control_requires_memory_error_report(self):
        clean = {"exit_code": 86, "owned_job_empty": True, "descendants_after_exit": 0,
                 "timed_out": False, "stdout": "ERROR: AddressSanitizer: heap-buffer-overflow"}
        self.assertTrue(quality.negative_control_detected(clean, "address"))
        for output in ("AddressSanitizer: failed to initialize", "AddressSanitizer DLL missing", ""):
            self.assertFalse(quality.negative_control_detected({**clean, "stdout": output}, "address"))


if __name__ == "__main__":
    unittest.main()
