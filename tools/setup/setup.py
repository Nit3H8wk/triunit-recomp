"""TriUnit Recomp setup: one entry point for every supported game.

    python tools/setup/setup.py --game mk3 --roms <folder with the user's ROM files>
    python tools/setup/setup.py --game mk3 --roms <folder> --no-compile      # authenticate and generate only
    python tools/setup/setup.py --game mk3 --roms <folder> --verify-only     # per-file check report, nothing written
    python tools/setup/setup.py --requirements                               # Windows, Python and compiler found here
    --progress <file>   keeps <file> (JSON, replaced atomically) at the current step; the launcher reads it

Steps (plan 2026-11-15-conformidade-legal.md, Fase 2):
  1. verify    every file of the supported revision by name, size, CRC32, SHA-1 and SHA-256; then the program image
  2. stage     link (or copy, across volumes) the verified files into roms/<game>/ (ignored by Git)
  3. decoder   compile the TMS34010 decoder from the pinned MAME sources (tools/setup/decoder.py)
  4. generate  translate the program image into C++ in generated/<game>/<program_sha256>/ (ignored by Git);
               MK2 also writes its factory CMOS seed there (the game's own factory boot, generated executor)
  5. accept    compare the generated output with the acceptance digests (tools/acceptance/)
  6. compile   build the game executable from the generated units with the project toolchain
  7. seed      MK3: the built executable runs the program's factory-settings restore from a cleared CMOS (the CMOS seed)
  8. install   the launcher package of the game from the executable just built (tools/setup/install.py)
The receipt (setup.json in the output folder) keeps only identities, digests, counts and timings.
"""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys,threading,time

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.setup import paths

ROOT=paths.ROOT
GAMES=('mk1','mk2','mk3')
ACCEPTED=ROOT/'tools/acceptance/generated.json'
VALIDATED_CC='16.1.0'   # g++ version that validated the routes (docs/PUBLISHING.md)
# Raised when a release changes what the setup builds: older records then ask for a new build (launcher_setup.hpp
# kSetupVersion, recomplauncher.json prepare.version).
SETUP_VERSION='2'
MIN_PYTHON=(3,12)       # Path.is_junction (link guards of the setup, the package writers and temporary_tree)
STEPS=('verify','stage','decoder','generate','accept','compile','seed','install')
PROGRESS=dict(file=None,started=0.0,state={},lock=threading.Lock())   # lock: the two compile workers report units


def progress(step=None,**fields):
    """Current step of the setup in the --progress file (best effort: a reader holding the file never fails the setup)."""
    with PROGRESS['lock']:
        state=PROGRESS['state']
        if step:state.update(step=step,units=None)
        state.update(fields,elapsed=round(time.perf_counter()-PROGRESS['started'],1))
        file=PROGRESS['file']
        if not file:return
        for _ in range(20):
            try:write_text(file.parent,file.name,json.dumps(state)+'\n');return
            except PermissionError:time.sleep(.05)


def units(done,total):progress(units=dict(done=done,total=total))


def requirements():
    """What the setup needs on this machine: 64-bit Windows, this Python and the validated g++."""
    import platform,subprocess
    from tools.quality import run as q
    version=None
    if q.DEFAULT_CC.is_file():
        try:version=subprocess.run([str(q.DEFAULT_CC),'-dumpfullversion'],capture_output=True,text=True,timeout=30).stdout.strip() or None
        except (OSError,subprocess.SubprocessError):pass
    found=dict(windows_64bit=sys.platform=='win32' and platform.machine().endswith('64'),python=platform.python_version(),
               compiler=dict(path=q.DEFAULT_CC.as_posix(),version=version,validated=VALIDATED_CC))
    found['python_supported']=sys.version_info>=MIN_PYTHON
    found['ok']=found['windows_64bit'] and found['python_supported'] and version==VALIDATED_CC
    return found


def report(game,folder):
    """Every file of the manifest checked on its own (no stop at the first error), then the program image by the game's
    own verify. Reads only; status per file: ok, missing, link, or the first check that differs."""
    from tools.mk3.roms import digests
    manifest=json.loads(paths.manifest(game).read_text('utf-8'));folder=Path(folder);files=[]
    for rom in manifest['roms']:
        path=folder/rom['path'];status='ok'
        if path.is_symlink():status='link'
        elif not path.is_file():status='missing'
        elif path.stat().st_size!=rom['size']:status='size'
        else:
            seen=digests(path.read_bytes())
            status=next((k for k in ('crc32','sha1','sha256') if k in rom and seen[k]!=rom[k]),'ok')
        files.append(dict(name=rom['path'],status=status))
    out=dict(game=game,revision=manifest['revision'],checks=[k for k in ('size','crc32','sha1','sha256')
             if all(k in r for r in manifest['roms'])],files=files,program='not checked')
    if all(f['status']=='ok' for f in files):
        try:
            if game=='mk1':from tools.mk1.roms import verify;verify(folder)
            elif game=='mk2':from tools.mk2.run import verify_roms;verify_roms(folder)
            else:from tools.mk3.roms import verify;verify(folder)
            out['program']='ok'
        except (ValueError,SystemExit,OSError) as error:out['program']=str(error)
    out['ok']=out['program']=='ok'
    return out


def units_digest(texts):
    """The digest generate.py --check records: name, length and text of every unit, sorted by name."""
    return hashlib.sha256(''.join(f'{n}|{len(t)}|{t}' for n,t in sorted(texts.items())).encode()).hexdigest()


def stage(game,source,names):
    """Link the verified files into roms/<game>/ unless `source` already is that folder. Never overwrites a different file."""
    target=ROOT/'roms'/game;source=Path(source).resolve()
    if source==target.resolve():return dict(staged=0,folder=f'roms/{game}')
    target.mkdir(parents=True,exist_ok=True);done=0
    for name in names:
        src,dst=source/name,target/name
        if dst.exists():
            if dst.stat().st_size==src.stat().st_size and _sha(dst)==_sha(src):continue
            raise SystemExit(f'roms/{game}/{name} already exists with other contents; move it away and run the setup again')
        try:os.link(src,dst)
        except OSError:shutil.copy2(src,dst)
        done+=1
    return dict(staged=done,folder=f'roms/{game}')


def _sha(path):
    from tools.quality import run as q
    return q.sha(Path(path))


def write_text(folder,name,text):
    path=folder/name;partial=folder/(name+'.partial')
    partial.write_text(text,encoding='utf-8',newline='\n');os.replace(partial,path);return path


def accept(game,files):
    """files: {logical name: sha256}. Returns the names whose digest differs from tools/acceptance (absent = not pinned)."""
    pinned=json.loads(ACCEPTED.read_text('utf-8')).get(game,{}) if ACCEPTED.is_file() else {}
    legacy=json.loads((ROOT/'tools/acceptance/manifest.json').read_text('utf-8'))['files']
    out={}
    for name,digest in files.items():
        want=pinned.get(name) or (legacy.get(name) or {}).get('sha256')
        out[name]='not pinned' if want is None else ('equal' if want==digest else 'DIFFERS')
    return out


def toolchain():
    """Identity of the compiler the generated C++ is built with (validated toolchain; see docs/PUBLISHING.md)."""
    from tools.quality import run as q
    import subprocess
    cc=q.DEFAULT_CC
    if not cc.is_file():raise SystemExit(f'Compiler not found: {cc} (MSYS2 MinGW-w64 g++ {VALIDATED_CC} is the validated toolchain)')
    version=subprocess.run([str(cc),'--version'],capture_output=True,text=True).stdout.splitlines()[0]
    return dict(compiler=cc.name,version=version,sha256=_sha(cc))


def setup_mk3(roms,compile_exe):
    from tools.mk3 import roms as mk3_roms,generate,preview
    from tools.setup import decoder,mk3
    receipt=dict(game='mk3',toolchain=toolchain());t=time.perf_counter()
    manifest=json.loads(mk3_roms.MANIFEST.read_text('utf-8'))
    progress('verify');receipt['verify']=mk3_roms.verify(roms,manifest)
    progress('stage');receipt['stage']=stage('mk3',roms,[r['path'] for r in manifest['roms']])
    progress('decoder');receipt['decoder']=decoder.tms34010().name
    progress('generate');out=paths.output('mk3');units_dir=out/'tms'
    if units_dir.exists():shutil.rmtree(units_dir)
    units_dir.mkdir(parents=True)
    if not paths.owned(units_dir):raise RuntimeError('generated/ is linked outside the project')
    rom=mk3_roms.program_image(ROOT/'roms/mk3',mk3_roms.definition())
    rows,proof=generate.scan(rom);texts,generation=generate.units(rom,rows)
    for name,text in texts.items():write_text(units_dir,name,text)
    adsp=mk3.adsp_dir()
    receipt['generate']=dict(units=len(texts),units_sha256=units_digest(texts),cases=generation['cases'],
                             candidate_pcs=generation['candidate_pcs'],adsp=sorted(mk3.ADSP_INCS),
                             scan={k:proof[k] for k in ('positions','truncated')})
    files={'mk3/tms_units':receipt['generate']['units_sha256'],**{f'native/mk3/{n}':_sha(adsp/n) for n in mk3.ADSP_INCS}}
    progress('accept');receipt['accept']=accept('mk3',files)
    receipt['generate_seconds']=round(time.perf_counter()-t,1)
    if compile_exe:
        from tools.quality import cpp_build,run as q
        progress('compile');t=time.perf_counter();scratch=out/'build'
        if scratch.exists():shutil.rmtree(scratch)
        scratch.mkdir()
        try:
            cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
            flags=[*generate.FLAGS,'-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/mk2'),mk3.include()]
            sources=[ROOT/p for p in preview.SOURCES]+[ROOT/'native/mk3'/n for n in generate.RUNTIME]+sorted(units_dir.glob('*.cpp'))
            built=cpp_build.build(cc,flags,sources,preview.LIBRARIES,scratch/'mk3.exe',scratch,env=env,timeout=3600,compile_from_scratch=True)
            if not built['passed']:raise SystemExit('MK3 build failed: '+json.dumps(q.compact(built))[:3000])
            os.replace(scratch/'mk3.exe',out/'mk3.exe')
        finally:shutil.rmtree(scratch,ignore_errors=True)
        receipt['compile']=dict(executable=str((out/'mk3.exe').relative_to(ROOT)).replace('\\','/'),sha256=_sha(out/'mk3.exe'),
                                seconds=round(time.perf_counter()-t,1))
        # The factory CMOS seed: the program's own restore from a cleared CMOS, run by the executable just built.
        progress('seed');receipt['seed']=mk3.factory_seed(out/'mk3.exe')
        receipt['accept'].update(accept('mk3',{'native/runtime/mk3-factory-default-cmos.bin':receipt['seed']['sha256']}))
    return receipt


def setup_mk2(roms,compile_exe):
    from tools.mk2 import run as mk2_run,package_native
    from tools.setup import decoder,mk2
    receipt=dict(game='mk2',toolchain=toolchain());t=time.perf_counter()
    manifest=mk2_run.read_manifest()
    progress('verify');receipt['verify']=mk2_run.verify_roms(roms,manifest)
    progress('stage');receipt['stage']=stage('mk2',roms,[r['path'] for r in manifest['roms']])
    progress('decoder');receipt['decoder']=decoder.tms34010().name
    progress('generate');out=mk2.inc_dir(ROOT/'roms/mk2')
    files=mk2.files()
    receipt['generate']=dict(includes=len(files),files=dict(files))
    seed=mk2.factory_seed(ROOT/'roms/mk2')
    files[mk2.SEED_LOGICAL]=_sha(seed)
    receipt['generate']['factory_seed']=dict(file=str(seed.relative_to(ROOT)).replace('\\','/'),sha256=files[mk2.SEED_LOGICAL])
    progress('accept');receipt['accept']=accept('mk2',files)
    receipt['generate_seconds']=round(time.perf_counter()-t,1)
    if compile_exe:
        from tools.quality import run as q
        progress('compile');t=time.perf_counter();scratch=out/'build'
        if scratch.exists():shutil.rmtree(scratch)
        scratch.mkdir()
        try:
            env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH'],'TEMP':str(scratch),'TMP':str(scratch)}
            built=q.command([q.DEFAULT_CC,*package_native.FLAGS,'-static',*[ROOT/p for p in package_native.SOURCES],
                             *package_native.LIBRARIES,'-Wl,--no-insert-timestamp','-o',scratch/'mk2-native.exe'],
                            scratch,cwd=ROOT,env=env,timeout=3600)
            if not built['passed']:raise SystemExit('MK2 build failed: '+json.dumps(q.compact(built))[:3000])
            os.replace(scratch/'mk2-native.exe',out/'mk2-native.exe')
        finally:shutil.rmtree(scratch,ignore_errors=True)
        receipt['compile']=dict(executable=str((out/'mk2-native.exe').relative_to(ROOT)).replace('\\','/'),
                                sha256=_sha(out/'mk2-native.exe'),seconds=round(time.perf_counter()-t,1))
    return receipt


def setup_mk1(roms,compile_exe):
    from tools.mk1 import roms as mk1_roms
    from tools.setup import decoder,mk1
    receipt=dict(game='mk1',toolchain=toolchain());t=time.perf_counter()
    manifest=mk1_roms.manifest()
    progress('verify');receipt['verify']=mk1_roms.verify(roms,manifest)
    progress('stage');receipt['stage']=stage('mk1',roms,[r['path'] for r in manifest['roms']])
    progress('decoder');receipt['decoder']=decoder.tms34010().name
    progress('generate');out=mk1.inc_dir(ROOT/'roms/mk1')
    files=mk1.files()
    receipt['generate']=dict(includes=len(files),files=files)
    progress('accept');receipt['accept']=accept('mk1',files)
    receipt['generate_seconds']=round(time.perf_counter()-t,1)
    if compile_exe:
        from tools.mk1 import build
        progress('compile');t=time.perf_counter();built=build.engine(out)
        if not built['passed']:raise SystemExit('MK1 build failed: '+json.dumps(built)[:3000])
        receipt['compile']=dict(executable=str((out/'mk5-native-audio.exe').relative_to(ROOT)).replace('\\','/'),
                                sha256=_sha(out/'mk5-native-audio.exe'),seconds=round(time.perf_counter()-t,1))
        # CMOS seed: the game's factory restore from a blank CMOS, run by the compiled engine (tools/setup/mk1.make_seed).
        progress('seed');t=time.perf_counter();seed,digest=mk1.make_seed(out/'mk5-native-audio.exe')
        receipt['seed']=dict(file=str(seed.relative_to(ROOT)).replace('\\','/'),sha256=digest,seconds=round(time.perf_counter()-t,1))
        receipt['accept'].update(accept('mk1',{'mk1/factory-cmos':digest}))
    return receipt


SETUP={'mk1':setup_mk1,'mk2':setup_mk2,'mk3':setup_mk3}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game',choices=GAMES)
    ap.add_argument('--roms',type=Path,help='folder with the ROM files of your own board')
    ap.add_argument('--no-compile',action='store_true',help='stop after generating and checking the C++')
    ap.add_argument('--verify-only',action='store_true',help='check every ROM file and report; nothing is written')
    ap.add_argument('--requirements',action='store_true',help='report the Windows, Python and compiler found')
    ap.add_argument('--progress',type=Path,help='JSON file kept at the current step (read by the launcher)')
    a=ap.parse_args(argv)
    if a.requirements:
        found=requirements();print(json.dumps(found,indent=1));return 0 if found['ok'] else 1
    if not a.game or not a.roms:ap.error('--game and --roms are required')
    if not a.roms.is_dir():ap.error(f'not a folder: {a.roms}')
    if a.progress:PROGRESS['file']=a.progress.absolute();a.progress.parent.mkdir(parents=True,exist_ok=True)
    PROGRESS.update(started=time.perf_counter(),state=dict(game=a.game,mode='verify' if a.verify_only else 'setup',
                                                           steps=STEPS,state='running'))
    progress('verify')
    try:
        if sys.version_info<MIN_PYTHON:
            raise SystemExit(f'Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or later is required (found {sys.version.split()[0]})')
        if a.verify_only:
            found=report(a.game,a.roms);print(json.dumps(found,indent=1))
            progress(state='done' if found['ok'] else 'failed',report=found);return 0 if found['ok'] else 1
        from tools.quality import cpp_build
        cpp_build.on_unit=units
        receipt=SETUP[a.game](a.roms,not a.no_compile)
        receipt['setup_version']=SETUP_VERSION
        out=paths.output(a.game);out.mkdir(parents=True,exist_ok=True)
        (out/'setup.json').write_text(json.dumps(receipt,indent=1)+'\n',encoding='utf-8')
        bad=[k for k,v in receipt.get('accept',{}).items() if v=='DIFFERS']
        if bad:
            print(json.dumps(receipt,indent=1))
            message='Generated output differs from the acceptance digests: '+', '.join(bad)
            print(message,file=sys.stderr);progress(state='failed',message=message);return 1
        if 'compile' in receipt:
            # 8. install: the launcher package from the executable just built (tools/setup/install.py).
            from tools.setup import install
            progress('install');t=time.perf_counter()
            receipt['install']=dict(install.INSTALL[a.game]((ROOT/receipt['compile']['executable']).parent),seconds=round(time.perf_counter()-t,1))
            if receipt['install']['executable_sha256']!=receipt['compile']['sha256']:raise RuntimeError('installed executable differs from the build')
            (out/'setup.json').write_text(json.dumps(receipt,indent=1)+'\n',encoding='utf-8')
        print(json.dumps(receipt,indent=1))
        progress(state='done');return 0
    except BaseException as error:
        progress(state='failed',message=str(error) or type(error).__name__);raise


if __name__=='__main__':raise SystemExit(main())
