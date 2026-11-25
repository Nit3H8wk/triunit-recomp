"""MK3 2.1 native (J2; the file keeps its J2 name): build native/mk3/mk3_preview_main.cpp as mk3 with the whole-image TMS units and run it.

The build reuses tools/mk3/generate.py (one scan, units written into the scratch tree) and the bounded object cache of
tools/quality/cpp_build.py with generate.FLAGS (as generate.build), so the units hit the same cache entries; the shared MK1/MK2 host (native/src/mk5_window.cpp, mk5_audio_output.cpp) links with the MK2 package libraries.
Everything lives in one scratch tree removed at the end, also on failure. Nothing is installed.

    python tools/mk3/preview.py --window --audio                          # interactive, Original, Esc closes
    python tools/mk3/preview.py --window --audio --edition remastered     # Remastered layer 1 (presentation only)
    python tools/mk3/preview.py --frames 300 --hashes                     # headless smoke (JSON on stdout)
    python tools/mk3/preview.py --frames 2485 --tape tools/mk3/fight_route.tape --watch-dcs 0x233d   # reset -> round start

Presentation settings are the shared MK1_* variables (MK1_CRT_PRESET, MK1_SCANLINES, MK1_BEZEL, MK1_SCALEFX, ...): the
edition's video profile (EDITIONS) with the caller's own MK1_* values on top; MK1_FULLSCREEN defaults to 0. The window
run keeps its NVRAM in CMOS_PROFILE (started from the seed when empty); headless runs always start from the seed and
write nothing.
"""
from pathlib import Path
import argparse,json,os,re,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,reference_dma,roms

ROOT=Path(__file__).resolve().parents[2]
SOURCES=['native/mk3/mk3_preview_main.cpp','native/mk3/mk3_host.cpp','native/mk3/mk3_adsp.cpp','native/mk2/mk2_dcs.cpp',
         'native/src/mk5_program.cpp','native/src/' + ('mk5_window_linux.cpp' if sys.platform.startswith('linux') else 'mk5_window.cpp'),
         'native/src/mk5_audio_output.cpp']
if sys.platform.startswith('linux'):
    SOURCES.append('native/src/linux_main_wrapper.cpp')
CMOS_PROFILE=ROOT/'build/native/mk3-native/profiles/player'   # own profile: not the seed, the installed product or MK1/MK2
# Layer 1 video profiles per edition (the MK1/MK2 host presets: native/include/mk5_video_presets.hpp, bezel, ScaleFX).
EDITIONS={'original':{'MK1_CRT_PRESET':'off','MK1_SCANLINES':'0','MK1_SCALEFX':'0','MK1_BEZEL':'1'},
          'remastered':{'MK1_CRT_PRESET':'bvm-1080','MK1_SCANLINES':'0','MK1_SCALEFX':'100','MK1_BEZEL':'1'}}
UNDERRUN=re.compile(r'\{"audio_underrun_sample":\d+,"producer_gap_ms":\d+\}\r?\n?')
if sys.platform.startswith('linux'):
    LIBRARIES=['-lSDL3','-lvulkan']
else:
    LIBRARIES=['-l'+n for n in ('bcrypt','user32','gdi32','winmm','d3d12','dxgi','d3dcompiler','dxguid','windowscodecs','ole32','uuid')]


class Preview:
    """Context manager: builds mk3 once into a scratch tree; run() executes it there."""
    def __enter__(self):
        self._tree=q.scratch_tree();self.temp,self.cleanup=self._tree.__enter__()
        try:
            from tools.mk3 import generate
            from tools.quality import cpp_build
            started=time.perf_counter()
            rom=roms.program_image(ROOT/'roms/mk3',roms.definition())
            rows,_=generate.scan(rom);units,self.generation=generate.write(self.temp,rom,rows);self.units=units
            self.generation_seconds=round(time.perf_counter()-started,3)
            cc=q.DEFAULT_CC;self.env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
            self.exe=self.temp/'mk3'
            from tools.setup import mk3 as setup_mk3
            flags=[*generate.FLAGS,'-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/mk2'),setup_mk3.include()]
            sources=[ROOT/p for p in SOURCES]+[ROOT/'native/mk3'/n for n in generate.RUNTIME]+list(units)
            self.build=cpp_build.build(cc,flags,sources,LIBRARIES,self.exe,self.temp,env=self.env,timeout=1800,compile_from_scratch=True)
            if not self.build['passed']:raise RuntimeError('preview build failed: '+json.dumps(q.compact(self.build))[:3000])
            (self.temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        except BaseException:
            self.__exit__(None,None,None);raise
        return self

    def __exit__(self,*_):
        self._tree.__exit__(None,None,None)
        if self.cleanup.get('exists_after'):raise RuntimeError('preview scratch retained')

    def run(self,*options,timeout=900,window_env=None,output_limit=64<<20,cwd=ROOT):
        env=dict(self.env)
        if window_env is not None:env.update(window_env)
        run=q.command([self.exe,ROOT/'roms/mk3',reference.SEED,self.temp/'gfx.txt',*map(str,options)],self.temp,cwd=cwd,env=env,
                      timeout=timeout,output_limit=output_limit)
        # mk5_audio_output writes its underrun records (with their CRLF) to std::clog, merged here: one can land inside a
        # stdout line
        lines=[];underruns=[u.strip() for u in UNDERRUN.findall(run['stdout'])]
        for l in UNDERRUN.sub('',run['stdout']).splitlines():
            if not l.startswith('{'):continue
            try:lines.append(json.loads(l))
            except ValueError as e:raise RuntimeError(f'preview output line is not JSON ({e}): {l[:300]!r}') from None
        summary=next((l for l in reversed(lines) if l.get('preview')),None)
        if not run['passed'] or summary is None or run['discarded_output_bytes']:
            raise RuntimeError('preview run failed: '+run['stdout'][-2000:])
        return dict(summary=summary,frames=[l for l in lines if 'frame' in l and 'rgb' in l],dumps=[l for l in lines if 'dump' in l],
                    census=next((l for l in lines if 'dma_census' in l),None),states=[l for l in lines if 'save_state' in l],
                    ahead=[l for l in lines if 'ahead' in l],underrun_records=underruns,
                    wall_seconds=run['wall_seconds'],log=[l for l in run['stdout'].splitlines() if not l.startswith('{')][-20:])


def window_settings(edition='original'):
    """The edition's video profile under the caller's MK1_* settings (q.command drops inherited ones); windowed by default."""
    env=dict(EDITIONS[edition],**{k:v for k,v in os.environ.items() if k.startswith('MK1_')})
    env.setdefault('MK1_FULLSCREEN','0')
    return env


def main():
    p=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--window',action='store_true');p.add_argument('--audio',action='store_true')
    p.add_argument('--frames',type=int,default=0);p.add_argument('--linger',type=float)
    p.add_argument('--hashes',action='store_true');p.add_argument('--strict',action='store_true')
    p.add_argument('--edition',choices=sorted(EDITIONS),default='original');p.add_argument('--tape',type=Path);p.add_argument('--watch-dcs')
    p.add_argument('--cmos-profile',type=Path,default=CMOS_PROFILE,help='NVRAM directory of the window run (default: %(default)s)')
    a=p.parse_args()
    options=['--edition',a.edition,*(['--window','--cmos-profile',a.cmos_profile.absolute()] if a.window else []),
             *(['--tape',a.tape.absolute()] if a.tape else []),*(['--watch-dcs',a.watch_dcs] if a.watch_dcs else []),*(['--audio'] if a.audio else []),*(['--frames',a.frames] if a.frames else []),
             *(['--linger',a.linger] if a.linger is not None else []),*(['--hashes'] if a.hashes else []),*(['--strict'] if a.strict else [])]
    with Preview() as preview:
        out=preview.run(*options,timeout=6*3600,window_env=window_settings(a.edition) if a.window else None)
        build=q.compact(preview.build)
    s=out['summary'];s.pop('window',None)
    print(json.dumps(dict(summary=s,build_seconds=build.get('wall_seconds'),cleanup=preview.cleanup,log=out['log']),indent=1))


if __name__=='__main__':main()
