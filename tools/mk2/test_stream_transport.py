"""Fail-closed controls for the experimental live debugger transport."""
import importlib.util
from pathlib import Path
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.quality import run as quality

SPEC = importlib.util.spec_from_file_location("stream_transport", Path(__file__).with_name("stream_transport.py"))
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)


def frame(sequence, lines):
    payload = "".join(lines).encode("utf-8")
    return (f"@@MK2_STREAM {sequence} {len(lines)} {len(payload)}\n".encode()
            + payload + f"@@MK2_STREAM_FRAME_END {sequence}\n".encode())


class StreamTests(unittest.TestCase):
    def decoder(self, *args, **kwargs):
        return transport.Decoder(*args, **kwargs)

    def test_fragmentation_preserves_every_field_cycle_and_diagnostic(self):
        rows, diagnostics = [], []
        decoder = self.decoder(rows.append, diagnostics.append)
        fields = [f"r{i} = {i:X}\n" for i in range(76)]
        fields[1] = "totalcycles = 10000000000001\n"
        wire = (b"startup diagnostic\n" + frame(1, fields) + b"@@MK2_STREAM_DIRECT_TOTAL 0\n"
                + f"@@MK2_STREAM_END 1 {sum(len(x.encode()) for x in fields)}\n".encode())
        for byte in wire.replace(b"\n", b"\r\n"):
            decoder.feed(bytes([byte]))
        decoder.finish()
        self.assertEqual(rows, fields)
        self.assertEqual(diagnostics, ["startup diagnostic\n"])
        self.assertEqual(decoder.lines, 76)
        self.assertEqual(decoder.frames, 1)

    def test_truncation_gap_wrong_length_and_interleaved_output_fail(self):
        for wire in (frame(2, ["pc = 1\n"]), frame(1, ["pc = 1\n"])[:-1],
                     b"@@MK2_STREAM 1 1 99\npc = 1\n@@MK2_STREAM_FRAME_END 1\n",
                     b"@@MK2_STREAM 1 1 7\nWARN!!\npc = 1\n@@MK2_STREAM_FRAME_END 1\n",
                     frame(1, ["pc = 1\n"]) + b"@@MK2_STREAM_END 1 0\n"):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                decoder = self.decoder(lambda line: None, lambda line: None)
                decoder.feed(wire)
                decoder.finish()

    def test_oversized_lines_fail_before_growing_without_bound(self):
        decoder = self.decoder(lambda line: None, lambda line: None, max_line_bytes=64)
        with self.assertRaisesRegex(ValueError, "line"):
            decoder.feed(b"x" * 65)

    def test_direct_long_records_keep_all_columns_and_require_footer(self):
        rows = []
        decoder = self.decoder(rows.append, lambda line: self.fail(line))
        row = "MK2_CPU " + " ".join(["FFFFFFFFFFFFFFFF"] * 76) + "\n"
        decoder.feed(b"@@MK2_STREAM_DIRECT 1 1\n" + row.encode()
                     + b"@@MK2_STREAM_DIRECT_END 1\n@@MK2_STREAM_DIRECT_TOTAL 1\n@@MK2_STREAM_END 0 0\n")
        decoder.finish()
        self.assertEqual(rows, [row])
        with self.assertRaises(ValueError):
            decoder = self.decoder(lambda line: None, lambda line: None)
            decoder.feed(b"@@MK2_STREAM_DIRECT 2 1\n")

    def test_all_76_individual_field_mutations_reach_exact_comparator(self):
        values = [str(i) for i in range(76)]
        values[1] = "9007199254740993"  # Exact cycle beyond floating-point precision.
        expected = "MK2_DSP " + " ".join(values) + "\n"
        for index in range(76):
            changed = values.copy()
            changed[index] = str(int(changed[index]) ^ 1)
            wire = frame(1, ["MK2_DSP " + " ".join(changed) + "\n"])
            with self.subTest(field=index), self.assertRaises(AssertionError):
                self.decoder(lambda line: self.assertEqual(line, expected), lambda line: None).feed(wire)

    def test_duplicate_sequences_and_missing_direct_totals_fail(self):
        for wire in (frame(1, ["x\n"]) + frame(1, ["y\n"]),
                     b"@@MK2_STREAM_DIRECT 1 1\nx\n@@MK2_STREAM_DIRECT_END 1\n@@MK2_STREAM_DIRECT 1 1\n",
                     b"@@MK2_STREAM_END 0 0\n"):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                decoder = self.decoder(lambda line: None, lambda line: None)
                decoder.feed(wire)
                decoder.finish()

    def test_nonzero_producer_exit_after_complete_protocol_fails(self):
        with quality.scratch_tree() as (scratch, cleanup):
            code = "import sys;print('@@MK2_STREAM_DIRECT_TOTAL 0\\n@@MK2_STREAM_END 0 0');sys.exit(7)"
            result = transport.command([sys.executable, "-B", "-c", code], scratch,
                                       lambda line: None, lambda line: None, timeout=3)
            self.assertFalse(result["passed"])
            self.assertTrue(result["final_marker"])
            self.assertEqual(result["exit_code"], 7)
            self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])

    def test_diagnostic_rejection_kills_producer_without_waiting_for_timeout(self):
        with quality.scratch_tree() as (scratch, cleanup):
            code = "import sys,time;print('[LUA ERROR] injected');sys.stdout.flush();time.sleep(30)"
            def reject(line):
                raise ValueError("diagnostic rejected: " + line)
            result = transport.command([sys.executable, "-B", "-c", code], scratch,
                                       lambda line: None, reject, timeout=3)
            self.assertFalse(result["passed"])
            self.assertFalse(result["timed_out"])
            self.assertIn("diagnostic rejected", result["error"])
            self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])

    def test_root_exit_with_inherited_output_child_fails_and_reaps_descendant(self):
        with quality.scratch_tree() as (scratch, cleanup):
            code = ("import subprocess,sys;subprocess.Popen([sys.executable,'-B','-c',"
                    "'import time;time.sleep(30)']);"
                    "print('@@MK2_STREAM_DIRECT_TOTAL 0\\n@@MK2_STREAM_END 0 0')")
            result = transport.command([sys.executable, "-B", "-c", code], scratch,
                                       lambda line: None, lambda line: None, timeout=3)
            self.assertFalse(result["passed"])
            self.assertFalse(result["timed_out"])
            self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])

    def test_script_boundaries_reject_uninitialized_counter_or_ambiguous_action(self):
        for script in ('printf "early"\ngo\n', 'do temp9=1\ngo\n',
                       'bpset 0,1,{printf "x";step}\n', 'bpset 0,1,{printf pc;g}\n'):
            with self.subTest(script=script), self.assertRaises(ValueError):
                transport.instrument_script(script)

    def test_child_output_is_consumed_online_and_cleaned_on_consumer_failure(self):
        with quality.scratch_tree() as (scratch, cleanup):
            script = scratch / "producer.py"
            script.write_text("import sys,time\nsys.stdout.write('@@MK2_STREAM 1 1 7\\npc = 1\\n@@MK2_STREAM_FRAME_END 1\\n');sys.stdout.flush();time.sleep(30)\n")
            def reject(line):
                raise ValueError("injected consumer failure")
            result = transport.command([sys.executable, "-B", script], scratch, reject,
                                       lambda line: None, timeout=3)
            self.assertFalse(result["passed"])
            self.assertIn("injected consumer failure", result["error"])
            self.assertFalse(result["timed_out"])
            self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])

    def test_child_timeout_and_missing_end_fail_and_reap(self):
        for body, timed_out in (("import time;time.sleep(30)", True), ("print('diagnostic')", False)):
            with self.subTest(body=body), quality.scratch_tree() as (scratch, cleanup):
                result = transport.command([sys.executable, "-B", "-c", body], scratch,
                                           lambda line: None, lambda line: None, timeout=0.3)
                self.assertFalse(result["passed"])
                self.assertEqual(result["timed_out"], timed_out)
                self.assertTrue(result["owned_job_empty"])
            self.assertFalse(cleanup["exists_after"])

    def test_slow_consumer_preserves_all_records_under_pipe_backpressure(self):
        with quality.scratch_tree() as (scratch, cleanup):
            script = scratch / "producer.py"
            script.write_text('''import sys
total=0
for sequence in range(1,1001):
 payload=''.join(f'{field} = {sequence*100+field}\\n' for field in range(76))
 total+=len(payload)
 sys.stdout.write(f'@@MK2_STREAM {sequence} 76 {len(payload)}\\n'+payload+f'@@MK2_STREAM_FRAME_END {sequence}\\n')
sys.stdout.write(f'@@MK2_STREAM_DIRECT_TOTAL 0\\n@@MK2_STREAM_END 1000 {total}\\n')
''')
            seen = 0
            def compare(line):
                nonlocal seen
                sequence, field = divmod(seen, 76)
                self.assertEqual(line, f"{field} = {(sequence+1)*100+field}\n")
                seen += 1
                if seen % 1000 == 0:
                    time.sleep(0.001)
            result = transport.command([sys.executable, "-B", script], scratch, compare,
                                       lambda line: self.fail(line), timeout=15)
            self.assertTrue(result["passed"], result)
            self.assertEqual(seen, 76000)
            self.assertEqual(result["console_lines"], 76000)
            self.assertTrue(result["owned_job_empty"])
        self.assertFalse(cleanup["exists_after"])


if __name__ == "__main__":
    unittest.main()
