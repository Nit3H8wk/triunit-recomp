"""J2: the native Wolf-Unit scanout (native/mk3/mk3_scanout.hpp) against the Original's screen, frame by frame.

Original: the pinned MAME 0.280 core of tools/mk3/reference.py (identities checked), reset with the CMOS seed, default
DIPs, no inputs, no debugger. A Lua frame notifier (video_manager::frame_update, called from the primary screen's
vblank_begin) reads screen_device::pixels() in memory: the visible 400 x 254 area of m_bitmap[m_curbitmap] through
the palette device at that instant (screen.cpp:961-996). video_output_update has already swapped m_curbitmap there
(screen.cpp:1266-1274), so the notifier of VBLANK k shows the pens of frame k-1 through the palette of VBLANK k. The
native preview (tools/mk3/preview.py, Profile::Game) prints both views per Present(): `rgb` (frame k, palette k) and
`prev` (frame k-1, palette k). Per frame only FNV-1a 64 hashes (RGB & 0xffffff, little-endian u32, the hash of
tools/mk3/replay_reference.py) and the palette RAM hash travel; for the first differing frame (if any) and one equal
frame both rasters are dumped as hex through the pipes and compared pixel by pixel in memory. Frames are aligned by
the machine time of the VBLANK (attoseconds), not by count.

Scope: reset -> one complete attract cycle of the `jogo` profile (FRAMES VBLANKs: the J2 attract route ends at the
second DCS 0x0451, TMS cycle 1,476,055,509 = 236.17 s, i.e. VBLANK 12,920 at 18.27925 ms; build/native/mk3-m2/j2-attract.json). Negative controls: the
other view (`rgb`) and a one-frame misalignment must disagree on frames whose content changes; one flipped pixel in a
dumped raster must count as exactly one differing pixel.

J3 route (test_fight_route): reset -> round start with the legal tape tools/mk3/fight_route.tape (FIGHT_FRAMES VBLANKs; the
low byte of DCS 0x233D is written at TMS 283,339,365 = VBLANK 2,480). Natively the tape goes through mk3-preview
--tape (Ops::ports from the first TMS boundary >= its cycle); on the Original through the mechanism of
tools/mk3/replay_reference.py: a debugger registerpoint `totalcycles>=temp9&&(st&0x2000000)==0` hits the boundary and
its Lua read tap arms the port value that a read tap on the io range returns; the frame notifier is the same. Extra
negative control: the native run without the Start press must differ from the Original with the full tape.
Receipt: build/native/mk3-m2/j3-host.json.
"""
from pathlib import Path
import json,math,sys,time,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms,replay_reference as rr
from tools.mk3.replay import read_tape

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/j3-host.json'
ATTO=10**18
FRAMES=12925
TAPE_FILE=ROOT/'tools/mk3/fight_route.tape'
FIGHT,FIGHT_CYCLE,FIGHT_FRAMES=0x233d,283339365,2485

LUA=r'''
local m=manager.machine
local s=m.screens[":screen"]
local main=m.devices[":maincpu"]
local function item(dev,suffix)
 local found
 for name,index in pairs(dev.items) do if name==suffix or name:sub(-#suffix-1)=="/"..suffix then assert(not found,suffix);found=emu.item(index) end end
 return assert(found,suffix)
end
local pal=item(main,":palette")
local P=0x100000001b3
local BASIS=0xcbf29ce484222325
local U16="<"..string.rep("I4",16)
local LAST=LAST_FRAME
local DUMPS=DUMP_SET
local HEX={} for c=0,255 do HEX[string.char(c)]=string.format("%02x",c) end
local function rgbhash(px)
 local h=BASIS
 for i=1,#px,64 do local w={string.unpack(U16,px,i)} for k=1,16 do h=(h~(w[k]&0xffffff))*P end end
 return h
end
local function words(it)
 local b=it:read_block(0,it.count*it.size);local h=BASIS
 for i=1,#b,64 do local w={string.unpack(U16,b,i)} for k=1,16 do h=(h~w[k])*P end end
 return h
end
local n=0
mk3_frames=emu.add_machine_frame_notifier(function()
 n=n+1
 local px,w,hgt=s:pixels()
 assert(w==400 and hgt==254 and #px==400*254*4,"screen geometry")
 local t=m.time
 print(string.format("MK3_FRAME %d %d %d %d %x %x",n,s:frame_number(),t.seconds,t.attoseconds,rgbhash(px),words(pal)))
 if DUMPS[n] then
  local out={} for i=1,#px,4 do out[#out+1]=HEX[px:sub(i+2,i+2)]..HEX[px:sub(i+1,i+1)]..HEX[px:sub(i,i)] end
  print("MK3_DUMP "..n.." "..table.concat(out))
 end
 if n>=LAST then m:exit() end
end)
'''


def original(frames,dumps=(),tape=()):
    """Per VBLANK 1..frames: {as, number, rgb, palette}; dumps: {frame: hex RGB} (6 hex digits per pixel).
    tape: (cycle, port, value) rows applied at TMS boundaries as tools/mk3/replay_reference.py does (debugger + Lua taps)."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    lua=LUA.replace('LAST_FRAME',str(frames)).replace('DUMP_SET','{'+','.join(f'[{d}]=true' for d in dumps)+'}')
    debug=[]
    if tape:   # no schedule, no END: only the tape hits; the frame notifier ends the run
        lua=rr.lua(0,0,0,rr.NEVER,tape)+'\n'+lua
        debug=['-debug','-debugger','windows','-debuglog','-debugscript','tape.cmd']
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'frames.lua').write_text(lua,encoding='ascii')
        if tape:(temp/'tape.cmd').write_text(rr.script(tape[0][0]),encoding='ascii')
        run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle',*debug,'-autoboot_delay','0','-autoboot_script','frames.lua',
                       '-keyboardprovider','none','-mouseprovider','none','-joystickprovider','none','-lightgunprovider','none',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap',
                       '-seconds_to_run',str(math.ceil(frames*0.0183)+5)],temp,cwd=temp,timeout=3600,output_limit=64<<20)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    if not run['passed'] or run['discarded_output_bytes']:raise RuntimeError('Original run failed: '+run['stdout'][-1500:])
    hits=[int(l.split()[2]) for l in run['stdout'].splitlines() if l.startswith('MK3_HIT ')]
    if 'MK3_LUA_ERROR' in run['stdout'] or len(hits)!=len({c for c,_,_ in tape}):raise ValueError(f'tape hits {hits}: '+run['stdout'][-500:])
    rows,raster={},{}
    for line in run['stdout'].splitlines():
        p=line.split()
        if p[:1]==['MK3_FRAME']:
            n,number,sec,atto,h,pal=p[1:]
            rows[int(n)]=dict(number=int(number),**{'as':int(sec)*ATTO+int(atto)},rgb=f'{int(h,16):016x}',palette=f'{int(pal,16):x}')
        elif p[:1]==['MK3_DUMP']:raster[int(p[1])]=p[2]
    if sorted(rows)!=list(range(1,frames+1)):raise ValueError('Original frames missing')
    return dict(frames=rows,dumps=raster,wall_seconds=run['wall_seconds'],core_sha256=reference.CORE_SHA,tape_hits=hits,
                program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),cleanup=cleanup)


def pixel_diff(a,b):
    """Differing pixels of two hex rasters (400 x 254) and the first one as (x, y)."""
    if len(a)!=len(b)!=400*254*6:raise ValueError('raster size')
    diff=[i for i in range(0,len(a),6) if a[i:i+6]!=b[i:i+6]]
    first=(diff[0]//6%400,diff[0]//6//400) if diff else None
    return len(diff),first


def compare(native,orig,view='prev',shift=0):
    """Frames aligned by VBLANK time; equal/differing counts and the first differing frame for one native view."""
    by_time={int(f['as']):f for f in native}
    equal=differ=0;first=None;unaligned=0
    for n,o in sorted(orig.items()):
        f=by_time.get(o['as'])
        if f is None:unaligned+=1;continue
        g=by_time.get(o['as']+shift*18279250000000000) if shift else f
        if g is None:continue
        if g[view]==o['rgb']:equal+=1
        else:
            differ+=1
            if first is None:first=dict(frame=f['frame'],original_frame=n,cycle=f['cycle'])
    return dict(equal=equal,differ=differ,unaligned=unaligned,first=first)


def update_receipt(key,value):
    data=json.loads(RECEIPT.read_text('utf-8')) if RECEIPT.is_file() else {}
    data[key]=value
    RECEIPT.parent.mkdir(parents=True,exist_ok=True);RECEIPT.write_text(json.dumps(data,indent=1)+'\n',encoding='utf-8')


class ScanoutOriginal(unittest.TestCase):
    def test_scanout_equals_original(self):
        from tools.mk3 import preview
        started=time.perf_counter()
        with preview.Preview() as p:
            build=q.compact(p.build)
            native=p.run('--hashes','--frames',FRAMES,timeout=1800)
            frames=native['frames'];count=len(frames)
            self.assertGreater(count,100)
            orig=original(count)
            palette=sum(1 for f in frames if orig['frames'].get(f['frame'],{}).get('palette')==f['palette'])
            result=compare(frames,orig['frames'])
            current=compare(frames,orig['frames'],'rgb')
            shifted=compare(frames,orig['frames'],shift=1)
            # dumps: the first differing frame, else the last frame whose content changed (most detail)
            changed=[f['frame'] for f in frames[1:] if f['rgb']!=frames[f['frame']-2]['rgb']]
            probe=result['first']['frame'] if result['first'] else changed[-1]
            dumped=p.run('--dump',probe,'--frames',probe,timeout=900)['dumps'][0]
        o_dump=original(probe,dumps=(probe,))['dumps'][probe]
        diff_prev=pixel_diff(dumped['prev'],o_dump);diff_rgb=pixel_diff(dumped['rgb'],o_dump)
        flipped=dumped['prev'][:6]+('000000' if dumped['prev'][6:12]!='000000' else 'ffffff')+dumped['prev'][12:]
        negative_pixel=pixel_diff(flipped,o_dump)[0]-diff_prev[0]
        summary=native['summary']
        self.assertEqual(result['unaligned'],0)
        self.assertEqual(palette,count,'palette RAM at VBLANK')
        self.assertEqual(result['differ'],0,result['first'])
        self.assertEqual(diff_prev[0],0)
        self.assertGreater(current['differ'],0,'negative control: the un-swapped view must differ where content changes')
        self.assertGreater(shifted['differ'],0,'negative control: one-frame misalignment')
        self.assertIn(abs(negative_pixel),(1,))
        update_receipt('scanout_original',dict(passed=True,
            scope=f'reset -> one attract cycle ({FRAMES} VBLANKs) of the jogo profile, default inputs; visible 400x254 RGB after the palette, every VBLANK',
            frames_compared=count,frames_equal=result['equal'],frames_differ=result['differ'],distinct_frames=len({f['rgb'] for f in frames}),
            palette_equal_frames=palette,view='frame k-1 pens through the palette at VBLANK k (screen_device::pixels in the frame notifier)',
            alignment='VBLANK machine time in attoseconds, identical for every frame',
            pixel_compare=dict(frame=probe,pixels=400*254,differ=diff_prev[0],first=diff_prev[1],current_view_differ=diff_rgb[0]),
            negative_controls=dict(current_view_frames_differ=current['differ'],shifted_frames_differ=shifted['differ'],one_flipped_pixel_detected=negative_pixel==1),
            native_frontier=summary['frontier'],native_cycles=summary['cycles'],native_first_execution=summary['first_execution'],
            original=dict(core_sha256=orig['core_sha256'],program_sha256=orig['program_sha256'],seed_sha256=orig['seed_sha256'],wall_seconds=orig['wall_seconds']),
            timings_seconds=dict(build=build.get('wall_seconds'),native=native['wall_seconds'],original=orig['wall_seconds'],total=round(time.perf_counter()-started,1)),
            cleanup=dict(preview=p.cleanup['exists_after'],original=orig['cleanup']['exists_after'])))
        self.assertFalse(p.cleanup['exists_after'])

    def test_fight_route(self):
        from tools.mk3 import preview
        started=time.perf_counter();tape=read_tape(TAPE_FILE)
        start=next(i for i,e in enumerate(tape) if e[1]==3 and not e[2]&4);no_start=tape[:start]+tape[start+2:]
        with preview.Preview() as p:
            build=q.compact(p.build)
            neg=p.temp/'no-start.tape';neg.write_text(''.join(f'{c} {pt} {v}\n' for c,pt,v in no_start),encoding='ascii')
            native=p.run('--hashes','--tape',TAPE_FILE,'--watch-dcs',hex(FIGHT),'--frames',FIGHT_FRAMES,timeout=1800)
            negative=p.run('--hashes','--tape',neg,'--watch-dcs',hex(FIGHT),'--frames',FIGHT_FRAMES,timeout=1800)
            frames=native['frames'];count=len(frames)
            changed=[f['frame'] for f in frames[1:] if f['rgb']!=frames[f['frame']-2]['rgb']]
            orig=original(count,dumps=(changed[-1],),tape=tape)
            result=compare(frames,orig['frames'])
            probe=result['first']['frame'] if result['first'] else changed[-1]
            dumped=p.run('--dump',probe,'--frames',probe,'--tape',TAPE_FILE,timeout=900)['dumps'][0]
        o_dump=orig['dumps'][probe] if probe in orig['dumps'] else original(probe,dumps=(probe,),tape=tape)['dumps'][probe]
        palette=sum(1 for f in frames if orig['frames'].get(f['frame'],{}).get('palette')==f['palette'])
        current=compare(frames,orig['frames'],'rgb');shifted=compare(frames,orig['frames'],shift=1)
        without_start=compare(negative['frames'],orig['frames'])
        diff_prev=pixel_diff(dumped['prev'],o_dump)
        flipped=dumped['prev'][:6]+('000000' if dumped['prev'][6:12]!='000000' else 'ffffff')+dumped['prev'][12:]
        negative_pixel=pixel_diff(flipped,o_dump)[0]-diff_prev[0]
        s=native['summary'];n=negative['summary']
        self.assertFalse(p.cleanup['exists_after'])
        self.assertEqual((s['frontier'],s['tape']['applied']),('none',len(tape)))
        self.assertEqual(s['dcs']['watch_cycle'],FIGHT_CYCLE,s['dcs'])
        self.assertNotEqual(n['dcs']['watch_cycle'],FIGHT_CYCLE)
        self.assertEqual(result['unaligned'],0)
        self.assertEqual(palette,count,'palette RAM at VBLANK')
        self.assertEqual(result['differ'],0,result['first'])
        self.assertEqual(diff_prev[0],0)
        self.assertGreater(current['differ'],0);self.assertGreater(shifted['differ'],0);self.assertEqual(negative_pixel,1)
        self.assertGreater(without_start['differ'],0,'negative control: the tape without Start must diverge')
        update_receipt('scanout_fight',dict(passed=True,
            scope=f'reset -> round start ({count} VBLANKs) of the jogo profile with the legal tape {TAPE_FILE.relative_to(ROOT).as_posix()}; '
                  'visible 400x254 RGB after the palette, every VBLANK',
            tape=[list(e) for e in tape],native_dcs_0x233d_cycle=s['dcs']['watch_cycle'],original_dcs_0x233d_cycle=FIGHT_CYCLE,
            frames_compared=count,frames_equal=result['equal'],frames_differ=result['differ'],distinct_frames=len({f['rgb'] for f in frames}),
            palette_equal_frames=palette,original_tape_hits=orig['tape_hits'],
            pixel_compare=dict(frame=probe,pixels=400*254,differ=diff_prev[0],first=diff_prev[1]),
            negative_controls=dict(current_view_frames_differ=current['differ'],shifted_frames_differ=shifted['differ'],one_flipped_pixel_detected=negative_pixel==1,
                                   without_start=dict(native_dcs_0x233d_cycle=n['dcs']['watch_cycle'] or None,frames_differ=without_start['differ'],
                                                      first=without_start['first'])),
            native_frontier=s['frontier'],native_cycles=s['cycles'],native_first_execution=s['first_execution'],
            original=dict(core_sha256=orig['core_sha256'],program_sha256=orig['program_sha256'],seed_sha256=orig['seed_sha256'],wall_seconds=orig['wall_seconds']),
            timings_seconds=dict(build=build.get('wall_seconds'),native=native['wall_seconds'],native_without_start=negative['wall_seconds'],
                                 original=orig['wall_seconds'],total=round(time.perf_counter()-started,1)),
            cleanup=dict(preview=p.cleanup['exists_after'],original=orig['cleanup']['exists_after'])))


if __name__=='__main__':unittest.main()
