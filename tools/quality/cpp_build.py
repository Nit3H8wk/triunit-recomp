"""Parallel C++ build (workers sized by cores and free memory) with an optional pinned, bounded local ccache."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import io
import itertools
import json
import os
import re
import threading
import shutil
import sys
import time
import urllib.request
import zipfile
from tools.quality import run as q

VERSION = '4.14.2'
TOOL_DIRECTORY = q.ROOT / 'build/toolchain' / ('ccache-' + VERSION)
CCACHE = TOOL_DIRECTORY / 'ccache.exe'
CCACHE_SHA256 = '4dd46cbc8efe3d6f6b34bd49fd2474fd83b3fcf48784dd38fc4ea48dd8967270'
ARCHIVE_SHA256 = '6993ce645e53192cec592ee23186200b574ac4c59097ecde8d9cfd681b47ae84'
URL = f'https://github.com/ccache/ccache/releases/download/v{VERSION}/ccache-{VERSION}-windows-x86_64.zip'
CACHE_DIRECTORY = q.ROOT / 'build/native/compiler-cache'
# Bounded so a rebuild after an update recompiles only what changed (decision of 18/11/2026; was 64 MB).
MAX_CACHE_BYTES = 2000000000
CACHE_SIZE = '1900MB'   # ccache max_size, below MAX_CACHE_BYTES to leave room for its metadata
MSYS_CCACHE = q.DEFAULT_CC.parent / 'ccache.exe'   # the user's own toolchain: pacman -S mingw-w64-x86_64-ccache


def ccache_tool():
    """The pinned project ccache (--setup), else the one installed with the user's MSYS2 g++, else None (nothing is
    downloaded by a build)."""
    return CCACHE if CCACHE.is_file() else MSYS_CCACHE if MSYS_CCACHE.is_file() else None
on_unit = None   # optional callable(done, total) after each unit compiles (setup --progress)
MAX_WORKERS = 32
# Memory one compiler process reserves before it starts: at least UNIT_MEMORY, or BYTES_MEMORY per byte it reads (measured
# 18/11/2026: a 5.5 MB graph unit peaked at 1.7 GB in cc1plus, a 0.7 MB shard near 0.5 GB). Units wait while the
# reservations of the running ones would pass 80% of the free memory; one unit always runs.
UNIT_MEMORY = 600 << 20
BYTES_MEMORY = 0.3


def available_memory():
    import ctypes
    class Status(ctypes.Structure):
        _fields_ = [('length', ctypes.c_uint32), ('load', ctypes.c_uint32), ('total', ctypes.c_uint64),
                    ('available', ctypes.c_uint64), ('page_total', ctypes.c_uint64), ('page_available', ctypes.c_uint64),
                    ('virtual_total', ctypes.c_uint64), ('virtual_available', ctypes.c_uint64), ('extended', ctypes.c_uint64)]
    status = Status(length=ctypes.sizeof(Status))
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return UNIT_MEMORY * 4
    return int(status.available)


def auto_workers(units):
    """Compiler processes at once: one per core, never more than units (memory is gated per unit, see UNIT_MEMORY)."""
    return max(1, min(os.cpu_count() or 1, units, MAX_WORKERS))


class MemoryGate:
    """Reservations of the running compiler processes against a share of the free memory."""
    def __init__(self, total):
        self.free, self.running, self.lock = total, 0, threading.Condition()

    def __call__(self, need):
        gate = self

        class Hold:
            def __enter__(self):
                with gate.lock:
                    gate.lock.wait_for(lambda: gate.running == 0 or gate.free >= need)
                    gate.free -= need
                    gate.running += 1

            def __exit__(self, *_):
                with gate.lock:
                    gate.free += need
                    gate.running -= 1
                    gate.lock.notify_all()
        return Hold()


def weight(source, flags):
    """Bytes the compiler reads for `source`: its text plus the generated .inc graphs it includes (the slow units)."""
    total = source.stat().st_size
    folders = [source.parent, *(Path(str(f)[2:]) for f in flags if str(f).startswith('-I'))]
    for name in re.findall(r'#include\s+"([^"]+\.inc)"', source.read_text(encoding='utf-8', errors='replace')):
        found = next((d / name for d in folders if (d / name).is_file()), None)
        total += found.stat().st_size if found else 0
    return total


def route(args):
    """Recognize only the project's simple GCC compile/link form for the large MK2 core."""
    if len(args) < 5 or Path(args[0]) != q.DEFAULT_CC or str(args[-2]) != '-o':
        return None
    body = list(map(str, args[1:-2]))
    blocked = {'-c', '-S', '-E', '-M', '-MM', '-MD', '-MMD', '-fsyntax-only', '-shared', '-r',
               '-x', '-I', '-D', '-U', '-isystem', '-iquote', '-idirafter', '-isysroot',
               '-include', '-imacros', '-Xpreprocessor', '-Xassembler', '-Xlinker', '-MF', '-MT', '-MQ', '--'}
    if any(value in blocked or value.startswith(('-flto', '-save-temps', '-B', '-specs', '--specs', '-wrapper', '@')) for value in body):
        return None
    sources = [Path(value).absolute() for value in body if not value.startswith('-') and Path(value).suffix.lower() in ('.cpp', '.cc', '.cxx')]
    if len(sources) < 2 or q.ROOT / 'native/mk2/mk2_task_batch.cpp' not in sources:
        return None
    source_text = {str(p) for p in sources}
    flags, links = [], []
    last_source = max(i for i, value in enumerate(body) if str(Path(value).absolute()) in source_text)
    for i, value in enumerate(body):
        if not value.startswith('-'):
            if str(Path(value).absolute()) not in source_text:
                return None
        elif value.startswith(('-l', '-L', '-Wl,')):
            if i < last_source:
                return None
            links.append(value)
        elif value in ('-pthread', '-municode', '-static', '-s') or value.startswith(('-std=', '-O', '-I', '-D', '-U', '-g', '-fsanitize', '-fno-')) or (value.startswith('-W') and not value.startswith(('-Wa,', '-Wp,'))):
            flags.append(value)
        else:
            return None
    output = Path(args[-1]).absolute()
    if output.suffix.lower() != '.exe':
        return None
    return dict(compiler=args[0], flags=flags, sources=sources, link_flags=links, executable=output)


def unlinked(path):
    for parent in (path, *path.parents):
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Linked build path: ' + str(parent))


def cache_bytes(path):
    unlinked(path)
    total = 0
    pending = [path]
    while pending:
        with os.scandir(pending.pop()) as rows:
            for row in rows:
                item = Path(row.path)
                if item.is_symlink() or item.is_junction():
                    raise ValueError('Linked cache entry: ' + str(item))
                if row.is_dir(follow_symlinks=False):
                    pending.append(item)
                else:
                    try:
                        total += row.stat(follow_symlinks=False).st_size
                    except FileNotFoundError:
                        pass  # ccache may evict an entry while another build measures it.
    return total


def setup():
    """Explicit installation only; archive is checked in memory, never retained."""
    unlinked(TOOL_DIRECTORY)
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read(1848159)
    if len(data) != 1848158 or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('ccache archive identity mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = {Path(row.filename).name: row for row in archive.infolist() if not row.is_dir()}
        binary = archive.read(members['ccache.exe'])
        license_text = archive.read(members['LICENSE.md'])
    if hashlib.sha256(binary).hexdigest() != CCACHE_SHA256:
        raise ValueError('ccache executable identity mismatch')
    TOOL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, value in (('ccache.exe', binary), ('LICENSE.md', license_text)):
        target = TOOL_DIRECTORY / name
        unlinked(target)
        if target.exists() and target.read_bytes() != value:
            raise ValueError('Preserve existing different tool file: ' + str(target))
        if not target.exists():
            target.write_bytes(value)
    return {'version': VERSION, 'executable_sha256': CCACHE_SHA256, 'archive_sha256': ARCHIVE_SHA256,
            'path': str(CCACHE), 'archive_retained': False}


def failed(message, timed_out=False):
    return {'passed': False, 'timed_out': timed_out, 'exit_code': None,
            'owned_job_empty': True, 'descendants_after_exit': 0, 'metrics': {},
            'stdout': message, 'discarded_output_bytes': 0, 'wall_seconds': 0}


def build(compiler, flags, sources, link_flags, executable, scratch, *, env=None,
          timeout=240, workers=None, use_cache=None, cache_directory=CACHE_DIRECTORY,
          compile_from_scratch=False):
    """Compile separately, preserve source/link order, and always remove test objects."""
    # includes generated on this machine (generated/<game>/<sha>/), when a source names one
    from tools.setup.paths import generated_flags, generated_sources
    flags = [*flags, *generated_flags([*flags, *sources])]
    sources = [*sources, *generated_sources(sources)]
    if workers is None and sources:
        workers = auto_workers(len(sources))
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS or not sources or timeout <= 0:
        raise ValueError(f'Build requires sources, positive timeout and 1..{MAX_WORKERS} workers')
    compiler, scratch, executable = Path(compiler), Path(scratch).absolute(), Path(executable).absolute()
    unlinked(scratch)
    unlinked(executable)
    scratch, executable = scratch.resolve(), executable.resolve()
    if not executable.is_relative_to(scratch):
        raise ValueError('Build output must stay in the owned temporary directory')
    sources = [Path(p).absolute() for p in sources]
    if len(set(sources)) != len(sources):
        raise ValueError('Duplicate compilation source')
    tool = ccache_tool() or CCACHE
    enabled = tool.is_file() and compiler.resolve() == q.DEFAULT_CC.resolve() if use_cache is None else use_cache
    if enabled:
        unlinked(tool)
        if tool == CCACHE and q.sha(CCACHE) != CCACHE_SHA256:
            raise ValueError('ccache executable identity mismatch')
        if any(str(value).startswith(('-B', '-specs', '--specs', '-wrapper', '@')) for value in flags):
            raise ValueError('Tool-selection flags require legacy compilation')
    started = time.perf_counter()
    deadline = started + timeout
    units = []
    result = failed('Build did not finish')
    cache_report = {'enabled': bool(enabled), 'hits': 0, 'misses': 0, 'bytes': 0,
                    'limit_bytes': MAX_CACHE_BYTES, 'direct_mode': False, 'quota_verified': False}
    with q.scratch_tree() as (objects, cleanup):
        environment = {k: v for k, v in (env or {}).items() if not k.startswith('CCACHE_')}
        removed_env = tuple(k for k in os.environ if k.startswith('CCACHE_'))
        cache = Path(cache_directory).absolute()
        tool_files = {}
        cache_initialized = False
        configuration = None

        def command(args, *, cwd=q.ROOT):
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return failed('Shared compilation deadline expired', True)
            return q.command(args, objects, cwd=cwd, env=environment, timeout=remaining,
                             unset_env=removed_env)

        try:
            if enabled:
                unlinked(cache)
                cache = cache.resolve()
                if not cache.is_relative_to(q.ROOT / 'build/native'):
                    raise ValueError('Compiler cache must stay in project build/native')
                cache.mkdir(parents=True, exist_ok=True)
                cache_bytes(cache)
                marker = cache / 'mk-arcade-cache.json'
                identity = {'format': 1, 'kind': 'ccache-object-cache', 'limit_bytes': MAX_CACHE_BYTES}
                if marker.exists():
                    owned = json.loads(marker.read_text())
                    if {k: owned.get(k) for k in ('format', 'kind')} != {k: identity[k] for k in ('format', 'kind')}:
                        raise ValueError('Compiler cache ownership mismatch')
                    if owned != identity:   # our cache under an older size limit
                        marker.write_text(json.dumps(identity, sort_keys=True))
                elif any(cache.iterdir()):
                    raise ValueError('Preserve existing unowned cache directory')
                else:
                    try:
                        with marker.open('x') as stream:
                            json.dump(identity, stream, sort_keys=True)
                    except FileExistsError:
                        if json.loads(marker.read_text()) != identity:
                            raise ValueError('Compiler cache ownership mismatch')
                cache_initialized = True
                tool_files[str(compiler.resolve())] = q.sha(compiler)
                for name in ('cc1plus', 'as'):
                    found = command([compiler, '-print-prog-name=' + name])
                    if not found['passed']:
                        raise RuntimeError(found['stdout'])
                    path = Path(found['stdout'].strip())
                    if not path.is_absolute():
                        path = Path(shutil.which(str(path), path=environment.get('PATH', os.environ.get('PATH'))) or path)
                    path = path.resolve(strict=True)
                    tool_files[str(path)] = q.sha(path)
                fingerprint = objects / 'toolchain.json'
                fingerprint.write_text(json.dumps(tool_files, sort_keys=True, separators=(',', ':')))
                namespace = hashlib.sha256(fingerprint.read_bytes()).hexdigest()
                configuration = objects / 'ccache.conf'
                configuration.write_text('\n'.join([
                    'cache_dir = ' + cache.as_posix(), 'temporary_dir = ' + objects.as_posix(),
                    'max_size = ' + CACHE_SIZE, 'compiler_check = content', 'direct_mode = false',
                    'depend_mode = false', 'inode_cache = false',
                    'hard_link = false', 'file_clone = false',
                    'compression = true', 'hash_dir = true', 'debug = false',
                    'namespace = ' + namespace, 'extra_files_to_hash = ' + fingerprint.as_posix(),
                    'stats_log = ' + (objects / 'stats.log').as_posix(), '']), encoding='utf-8')
                environment['CCACHE_CONFIGPATH'] = str(configuration)
                cache_report.update(path=str(cache), tool=str(tool), tool_sha256=q.sha(tool), toolchain=tool_files)

            stop = []   # a failed unit: units not started yet are skipped

            def compile_one(item):
                number, source = item
                output = objects / (str(number) + '.o')
                if stop:
                    return {'passed': False, 'skipped': True, 'source': str(source), 'stdout': ''}, output
                # Relative filenames give regenerated units stable preprocessor paths.
                local = compile_from_scratch and source.parent == scratch
                args = [compiler, *flags, '-c', source.name if local else source, '-o', output]
                with memory(max(UNIT_MEMORY, int(weights[number] * BYTES_MEMORY))):
                    if stop:
                        return {'passed': False, 'skipped': True, 'source': str(source), 'stdout': ''}, output
                    execution = command(([tool] if enabled else []) + args, cwd=scratch if local else q.ROOT)
                execution['source'] = str(source)
                execution['object_bytes'] = output.stat().st_size if output.is_file() else 0
                if not execution['passed']:
                    stop.append(number)
                if on_unit:
                    on_unit(next(finished), len(sources))
                return execution, output

            finished = itertools.count(1)   # next() is atomic under the GIL: safe from every worker

            # Heaviest units first (longest-processing-time order); objects keep their source index for the link.
            weights = [weight(source, flags) for source in sources]
            memory = MemoryGate(int(available_memory() * 0.8))
            order = sorted(range(len(sources)), key=lambda i: -weights[i])
            with ThreadPoolExecutor(max_workers=workers) as pool:
                done = dict(zip(order, pool.map(compile_one, [(i, sources[i]) for i in order])))
            compiled = [done[i] for i in range(len(sources))]
            units = [q.compact(row) for row, _ in compiled]
            failures = [row for row, _ in compiled if not row['passed'] and not row.get('skipped')]
            if failures:
                result = dict(failures[0])
            else:
                if enabled and any(q.sha(Path(path)) != sha for path, sha in tool_files.items()):
                    command([tool, '--evict-namespace', namespace])
                    raise RuntimeError('Compiler toolchain changed during compilation')
                result = command([compiler, *flags, *[output for _, output in compiled],
                                  *link_flags, '-o', executable])
        except Exception as error:
            result = failed(str(error), time.perf_counter() >= deadline)
        finally:
            if enabled and cache_initialized:
                maintenance_deadline = time.perf_counter() + 15
                def maintain(args):
                    remaining = maintenance_deadline - time.perf_counter()
                    if remaining <= 0:
                        return failed('Compiler cache maintenance deadline expired', True)
                    return q.command(args, objects, cwd=q.ROOT, env=environment,
                                     timeout=remaining, unset_env=removed_env)
                try:
                    if configuration is not None and configuration.is_file():
                        cache_bytes(cache)
                        trimmed = maintain([tool, '--cleanup'])
                        if not trimmed['passed']:
                            raise RuntimeError(trimmed['stdout'])
                        if (objects / 'stats.log').is_file():
                            try:
                                stats = maintain([tool, '--print-log-stats', '--format', 'json'])
                                if not stats['passed']:
                                    raise RuntimeError(stats['stdout'])
                                values = json.loads(stats['stdout'])
                                cache_report['stats'] = values
                                cache_report['hits'] = values.get('direct_cache_hit', 0) + values.get('preprocessed_cache_hit', 0)
                                cache_report['misses'] = values.get('cache_miss', 0)
                            except Exception as error:
                                cache_report['statistics_error'] = str(error)
                                result.update(passed=False)
                except Exception as error:
                    cache_report['maintenance_error'] = str(error)
                    result.update(passed=False)
                    result['stdout'] += '\nCompiler cache maintenance: ' + str(error)
                finally:
                    try:
                        cache_report['bytes'] = cache_bytes(cache)
                        cache_report['quota_verified'] = cache_report['bytes'] <= MAX_CACHE_BYTES
                        if not cache_report['quota_verified']:
                            raise RuntimeError('Compiler cache exceeded its size budget')
                    except Exception as error:
                        cache_report.update(quota_verified=False, quota_error=str(error))
                        result.update(passed=False)
                        result['stdout'] += '\nCompiler cache quota: ' + str(error)
    result.update(build_units=units, compiler_cache=cache_report, object_cleanup=cleanup,
                  workers=workers, wall_seconds=round(time.perf_counter() - started, 6),
                  metrics_scope='linker driver only; per-compiler-driver metrics in build_units')
    return result


if __name__ == '__main__':
    if sys.argv[1:] != ['--setup']:
        raise SystemExit('Explicit tool installation: python -B -m tools.quality.cpp_build --setup')
    print(json.dumps(setup(), indent=2))
