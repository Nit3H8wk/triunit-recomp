"""Two-worker C++ build with an optional pinned, bounded local ccache."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import hashlib
import io
import json
import os
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
MAX_CACHE_BYTES = 64000000


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
          timeout=240, workers=2, use_cache=None, cache_directory=CACHE_DIRECTORY,
          compile_from_scratch=False):
    """Compile separately, preserve source/link order, and always remove test objects."""
    # includes generated on this machine (generated/<game>/<sha>/), when a source names one
    from tools.setup.paths import generated_flags
    flags = [*flags, *generated_flags([*flags, *sources])]
    if type(workers) is not int or not 1 <= workers <= 2 or not sources or timeout <= 0:
        raise ValueError('Build requires sources, positive timeout and1..2 workers')
    compiler, scratch, executable = Path(compiler), Path(scratch).absolute(), Path(executable).absolute()
    unlinked(scratch)
    unlinked(executable)
    scratch, executable = scratch.resolve(), executable.resolve()
    if not executable.is_relative_to(scratch):
        raise ValueError('Build output must stay in the owned temporary directory')
    sources = [Path(p).absolute() for p in sources]
    if len(set(sources)) != len(sources):
        raise ValueError('Duplicate compilation source')
    enabled = CCACHE.is_file() and compiler.resolve() == q.DEFAULT_CC.resolve() if use_cache is None else use_cache
    if enabled:
        unlinked(CCACHE)
        if q.sha(CCACHE) != CCACHE_SHA256:
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
                    if json.loads(marker.read_text()) != identity:
                        raise ValueError('Compiler cache ownership mismatch')
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
                    'max_size = 60MB', 'compiler_check = content', 'direct_mode = false',
                    'depend_mode = false', 'inode_cache = false',
                    'hard_link = false', 'file_clone = false',
                    'compression = true', 'hash_dir = true', 'debug = false',
                    'namespace = ' + namespace, 'extra_files_to_hash = ' + fingerprint.as_posix(),
                    'stats_log = ' + (objects / 'stats.log').as_posix(), '']), encoding='utf-8')
                environment['CCACHE_CONFIGPATH'] = str(configuration)
                cache_report.update(path=str(cache), tool_sha256=CCACHE_SHA256, toolchain=tool_files)

            def compile_one(item):
                number, source = item
                output = objects / (str(number) + '.o')
                # Relative filenames give regenerated units stable preprocessor paths.
                local = compile_from_scratch and source.parent == scratch
                args = [compiler, *flags, '-c', source.name if local else source, '-o', output]
                execution = command(([CCACHE] if enabled else []) + args, cwd=scratch if local else q.ROOT)
                execution['source'] = str(source)
                execution['object_bytes'] = output.stat().st_size if output.is_file() else 0
                return execution, output

            with ThreadPoolExecutor(max_workers=workers) as pool:
                compiled = list(pool.map(compile_one, enumerate(sources)))
            units = [q.compact(row) for row, _ in compiled]
            failures = [row for row, _ in compiled if not row['passed']]
            if failures:
                result = dict(failures[0])
            else:
                if enabled and any(q.sha(Path(path)) != sha for path, sha in tool_files.items()):
                    command([CCACHE, '--evict-namespace', namespace])
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
                        trimmed = maintain([CCACHE, '--cleanup'])
                        if not trimmed['passed']:
                            raise RuntimeError(trimmed['stdout'])
                        if (objects / 'stats.log').is_file():
                            try:
                                stats = maintain([CCACHE, '--print-log-stats', '--format', 'json'])
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
                            raise RuntimeError('Compiler cache exceeded its64 MB budget')
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
