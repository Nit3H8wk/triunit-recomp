"""EXPERIMENTAL bounded MAME 0.280 debugger-console transport.

Prepend lua_source() to the existing autoboot Lua, instrument the existing
debugger script with instrument_script(), enable -oslog, omit -debuglog, and run
command(). Every console line and every unframed stdout/stderr diagnostic reaches
its callback synchronously.
Callbacks must return promptly and consume/compare records without retaining an
unbounded history. This transport does not replace any full observation check.

The unused, side-effect-suppressed debugger read only triggers a Lua read tap;
it executes no emulated instruction and never changes returned memory data.
Promotion requires complete baseline equivalence for the intended workload.
Startup command echoes retain MAME's 250-column console wrapping; generated
printf data uses direct frames and symlist fields remain unchanged. Reject MAME
diagnostics in both callbacks, including before the first observation.
"""
from pathlib import Path
import os
import queue
import re
import subprocess
import threading
import time

FLUSH = "do :maincpu.pb@01fffff0"
MAX_LINE_BYTES = 64 * 1024
MAX_FRAME_BYTES = 1024 * 1024


def instrument_script(script):
    """Route printf directly; MAME's console ring wraps text at 250 columns.

    Reserve only debugger temp9 for an observation-frame counter. It is not an
    emulated CPU register or memory. Existing scripts using it are rejected.
    """
    if re.search(r"\btemp9\b", script, re.I):
        raise ValueError("Streaming reserves debugger temp9")
    if re.search(r"(?m)^\s*printf\b", script):
        raise ValueError("Top-level printf runs before streaming initialization")
    pattern = r'\bprintf\s+"((?:\\.|[^"\\])*)"([^;{}\n]*)'
    def direct(match):
        fmt, parameters = match.groups()
        count = fmt.count(r"\n") + 1  # Debugger printf appends one extra newline.
        parameters = parameters.strip()
        if parameters and not parameters.startswith(","):
            raise ValueError("Unsupported debugger printf parameters")
        return (FLUSH + ';logerror "@@MK2_STREAM_DIRECT %d ' + str(count) + r'\n'
                + fmt + r'\n@@MK2_STREAM_DIRECT_END %d\n",(temp9=temp9+1)'
                + parameters + ',temp9')
    script = re.sub(pattern, direct, script)
    if re.search(r"\bprintf\b", script):
        raise ValueError("Unsupported debugger printf syntax")
    result = []
    for line in script.splitlines():
        if re.match(r"(?:bpset|wpset|wpdset|wpiset|wposet)\s", line):
            if not line.endswith("}") or not re.search(r";(?:g|go|quit)}$", line):
                raise ValueError("Streaming requires a generated BP/WP action ending in g/go/quit")
            line = re.sub(r";(g|go|quit)}$", lambda m: ";" + FLUSH + ";" + m[1] + "}", line)
        result.append(line)
    return "\n".join(result) + "\n"


def lua_source():
    """MAME's sequence-numbered console buffer fails closed on any overrun."""
    return r'''
-- Experimental streaming; retain subscriptions/tap until machine shutdown.
local stream_log = assert(manager.machine.debugger).consolelog
manager.machine.debugger:command("do temp9=0")
local stream_next, stream_frames, stream_bytes = 1, 0, 0
local function stream_drain()
    local rows, bytes = {}, 0
    for sequence = stream_next, #stream_log do
        -- Pinned sol2 leaks a registry reference on numeric userdata lookup.
        local row = assert(stream_log[tostring(sequence)], "MK2 stream console overrun") .. "\n"
        bytes = bytes + #row
        assert(#row <= 65536 and bytes <= 1048576, "MK2 stream frame/line overflow")
        rows[#rows + 1] = row
    end
    stream_next = #stream_log + 1
    if #rows > 0 then
        stream_frames = stream_frames + 1
        -- Both producer paths use stderr; separate CRT streams interleave writes.
        io.stderr:write(string.format("@@MK2_STREAM %d %d %d\n", stream_frames, #rows, bytes))
        io.stderr:write(table.concat(rows))
        io.stderr:write(string.format("@@MK2_STREAM_FRAME_END %d\n", stream_frames))
        io.stderr:flush()
        stream_bytes = stream_bytes + bytes
    end
end
_G.mk2_stream_tap = manager.machine.devices[":maincpu"].spaces["program"]:install_read_tap(
    0x01fffff0, 0x01ffffff, "mk2-debugger-stream", function() stream_drain() end)
_G.mk2_stream_stop = emu.add_machine_stop_notifier(function()
    stream_drain()
    manager.machine.debugger:command('logerror "@@MK2_STREAM_DIRECT_TOTAL %d\n",temp9')
    io.stderr:write(string.format("@@MK2_STREAM_END %d %d\n", stream_frames, stream_bytes))
    io.stderr:flush()
end)
stream_drain()
'''


class Decoder:
    """Incremental line framing, bounded independently of total trace length."""
    def __init__(self, on_line, on_diagnostic, max_line_bytes=MAX_LINE_BYTES):
        self.on_line, self.on_diagnostic = on_line, on_diagnostic
        self.max_line_bytes = max_line_bytes
        self.pending = bytearray()
        self.frames = self.lines = self.bytes = self.ring_bytes = self.diagnostics = 0
        self.direct_frames = 0
        self.direct = self.direct_total = False
        self.remaining = self.frame_bytes = self.expected_bytes = 0
        self.footer = self.ended = False

    def feed(self, block):
        # Even a caller passing a huge block cannot make the retained line grow.
        for offset in range(0, len(block), 4096):
            for part in block[offset:offset + 4096].splitlines(keepends=True):
                self.pending.extend(part)
                if len(self.pending) > self.max_line_bytes + 2:
                    raise ValueError("Streaming line exceeds bounded line limit")
                if not self.pending.endswith(b"\n"):
                    if len(self.pending) > self.max_line_bytes:
                        raise ValueError("Streaming line exceeds bounded line limit")
                    continue
                raw = bytes(self.pending[:-1]).removesuffix(b"\r") + b"\n"
                self.pending.clear()
                if len(raw) > self.max_line_bytes:
                    raise ValueError("Streaming line exceeds bounded line limit")
                self._line(raw)

    def _line(self, raw):
        line = raw.decode("utf-8", errors="strict")
        if self.remaining:
            self.frame_bytes += len(raw)
            if self.frame_bytes > self.expected_bytes:
                raise ValueError("Streaming frame byte count exceeded")
            self.on_line(line)
            self.lines += 1
            self.bytes += len(raw)
            if not self.direct:
                self.ring_bytes += len(raw)
            self.remaining -= 1
            if not self.remaining:
                self.footer = True
            return
        if self.footer:
            expected = (f"@@MK2_STREAM_DIRECT_END {self.direct_frames}\n" if self.direct
                        else f"@@MK2_STREAM_FRAME_END {self.frames}\n")
            if line != expected or not self.direct and self.frame_bytes != self.expected_bytes:
                raise ValueError(f"Streaming frame footer/byte count mismatch: expected {expected.strip()!r}, got {line[:100]!r}; bytes {self.frame_bytes}/{self.expected_bytes}")
            self.footer = False
            self.direct = False
            return
        match = re.fullmatch(r"@@MK2_STREAM_DIRECT (\d+) (\d+)\n", line)
        if match:
            sequence, count = map(int, match.groups())
            if self.ended or self.direct_total or sequence != self.direct_frames + 1 or not 0 < count <= MAX_FRAME_BYTES:
                raise ValueError("Direct streaming frame sequence/size mismatch")
            self.direct_frames = sequence
            self.direct = True
            self.remaining, self.expected_bytes, self.frame_bytes = count, MAX_FRAME_BYTES, 0
            return
        match = re.fullmatch(r"@@MK2_STREAM_DIRECT_TOTAL (\d+)\n", line)
        if match:
            if self.direct_total or self.ended or int(match[1]) != self.direct_frames:
                raise ValueError("Direct streaming final count mismatch")
            self.direct_total = True
            return
        match = re.fullmatch(r"@@MK2_STREAM (\d+) (\d+) (\d+)\n", line)
        if match:
            sequence, count, size = map(int, match.groups())
            if (self.ended or self.direct_total or sequence != self.frames + 1 or not 0 < count <= MAX_FRAME_BYTES
                    or not count <= size <= MAX_FRAME_BYTES):
                raise ValueError("Streaming frame sequence/size mismatch")
            self.frames = sequence
            self.remaining, self.expected_bytes, self.frame_bytes = count, size, 0
            return
        match = re.fullmatch(r"@@MK2_STREAM_END (\d+) (\d+)\n", line)
        if match:
            if self.ended or not self.direct_total or tuple(map(int, match.groups())) != (self.frames, self.ring_bytes):
                raise ValueError("Streaming final counts mismatch")
            self.ended = True
            return
        if line.startswith("@@MK2_STREAM"):
            raise ValueError("Malformed streaming control line")
        self.on_diagnostic(line)
        self.diagnostics += 1

    def finish(self):
        if self.pending or self.remaining or self.footer or not self.ended or not self.direct_total:
            raise ValueError("Incomplete streaming capture or missing final marker")


def command(args, scratch, on_line, on_diagnostic, timeout=2400, *, decoder=None, env=None):
    """Own/reap the process tree, with two 4-KiB queued blocks and no log file.

    A protocol/consumer/diagnostic error kills the producer and fails the run.
    Windows CRT CRLF conversion is undone at the text line boundary, matching
    the LF bytes MAME writes to debug.log. Interleaved diagnostics inside a frame
    fail validation; diagnostics outside frames are delivered without truncation.
    """
    from tools.quality import run as quality
    scratch = Path(scratch).absolute()
    for path in (scratch, *scratch.parents):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked streaming scratch path")
    scratch = scratch.resolve(strict=True)
    if scratch.parent != quality.STAGE.resolve(strict=True) or not scratch.name.startswith("temporary-quality-"):
        raise ValueError("Streaming requires quality.scratch_tree()")
    if "-debuglog" in list(map(str, args)):
        raise ValueError("Experimental streaming must omit -debuglog")
    started = time.monotonic()
    result = {"passed": False, "timed_out": False, "experimental": True}
    custom_decoder = decoder is not None
    decoder = decoder if custom_decoder else Decoder(on_line, on_diagnostic)
    blocks, stopping = queue.Queue(maxsize=2), threading.Event()
    process = job = reader = None
    metrics = {}
    diagnostic_tail = b""

    def read_output():
        try:
            while not stopping.is_set():
                block = os.read(process.stdout.fileno(), 4096)
                while not stopping.is_set():
                    try:
                        blocks.put(block, timeout=0.05)
                        break
                    except queue.Full:
                        pass
                if not block:
                    return
        except Exception as exc:
            if not stopping.is_set():
                result["reader_error"] = repr(exc)

    try:
        job = quality.ProcessJob() if os.name == "nt" else None
        environment = dict(os.environ)
        if env:
            environment.update(env)
        environment.update(TEMP=str(scratch), TMP=str(scratch), PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONOPTIMIZE", None)
        environment.pop("ASAN_SAVE_DUMPS", None)
        for key in list(environment):
            if key.startswith("MK1_"):
                del environment[key]
        process = subprocess.Popen(list(map(str, args)), cwd=scratch, env=environment,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   creationflags=4 if job else 0)
        if job:
            job.assign(process)
            job.resume(process)
        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        root_exited = None
        while True:
            if time.monotonic() - started > timeout:
                result["timed_out"] = True
                raise TimeoutError("Streaming producer timed out")
            if "reader_error" in result:
                raise RuntimeError(result["reader_error"])
            metrics.update(quality.process_metrics(process))
            try:
                block = blocks.get(timeout=0.05)
            except queue.Empty:
                block = None
            if block == b"":
                break
            if block:
                diagnostic_tail = (diagnostic_tail + block)[-4000:]
                decoder.feed(block)
            if process.poll() is not None:
                root_exited = root_exited or time.monotonic()
                if time.monotonic() - root_exited > 0.5:
                    raise RuntimeError("Owned child still holds streaming output after root exit")
        process.wait(timeout=1)
        decoder.finish()
        if process.returncode != 0:
            raise RuntimeError(f"Streaming producer exit code {process.returncode}")
        if job and job.active():
            raise RuntimeError("Streaming producer left descendants")
        result["passed"] = True
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        stopping.set()
        if job:
            try:
                job.close()
                result["owned_job_empty"] = True
            except Exception as exc:
                result.update(passed=False, cleanup_error=repr(exc))
        if process and process.poll() is None:
            process.kill()
        if process:
            try:
                process.wait(timeout=10)
                metrics.update(quality.process_metrics(process))
            except Exception as exc:
                result.update(passed=False, cleanup_error=repr(exc))
        if reader:
            reader.join(timeout=5)
            if reader.is_alive():
                result.update(passed=False, cleanup_error="Streaming reader did not stop")
        if process and process.stdout and (not reader or not reader.is_alive()):
            process.stdout.close()
        result.update(exit_code=process.returncode if process else None, metrics=metrics,
                      console_lines=decoder.lines, console_bytes=decoder.bytes,
                      frames=decoder.frames, diagnostic_lines=decoder.diagnostics,
                      direct_frames=decoder.direct_frames,
                      final_marker=decoder.ended, queued_byte_limit=8192,
                      line_byte_limit=None if custom_decoder else MAX_LINE_BYTES,
                      producer_frame_byte_limit=None if custom_decoder else MAX_FRAME_BYTES,
                      wall_seconds=round(time.monotonic() - started, 6))
        if not result["passed"]:
            result["stdout"] = diagnostic_tail.decode("utf-8", errors="replace")
    return result
