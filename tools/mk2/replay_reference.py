"""Exact Original endpoint comparison for a reset-and-input native replay."""
import hashlib
import json
import time
from tools.mk2 import batch_reference as batch, native, reference, run, replay_audio,replay_state
from tools.quality import run as q


def compare(directory, capture, state, native_directory, env, *,wall_seconds=180):
    if q.sha(batch.MAME)!=batch.MAME_SHA:raise ValueError('Original executable identity differs')
    directory.mkdir();native.prepare_reference_roms(q.ROOT/'roms/mk2',directory/'mk2',run.read_manifest())
    nv=directory/'nvram/mk2';nv.mkdir(parents=True);(nv/'nvram').write_bytes(capture['cmos'])
    regs=','.join([f'a{n}'for n in range(15)]+['sp']+[f'b{n}'for n in range(15)])
    fmt=' '.join(['%X']*34)+r'\n'
    command='focus :maincpu\n'+f'bpset {state["pc"]:x},totalcycles=={state["cycles"]:x},{{printf "REPLAY_CPU {fmt}",pc,st,totalcycles,{regs};save cmos.bin,1400000,20000;save ram.bin,1000000,400000;save palette.bin,1800000,80000;do :maincpu.pw@01ffffe0;quit}}\ngo\n'
    command=replay_state.original_command(command)
    (directory/'observe.cmd').write_text(command,encoding='ascii')
    lua=r'''local m=manager.machine;local main=m.devices[":maincpu"];local video=m.devices[":video"];local screen=m.screens[":screen"]
local function tick()return math.floor(m.time:as_double()*100000000+0.5)end
local function bind(device,suffix)
 local found;for name,index in pairs(device.items)do if name==suffix or name:sub(-#suffix-1)=="/"..suffix then assert(not found);found=emu.item(index)end end;return assert(found,suffix)
end
local function dump(label,item,count)
 local f=assert(io.open(label,"wb"));for n=0,count-1 do assert(f:write(string.pack("<I2",assert(item:read(n)))))end;assert(f:close())
end
replay_tap=main.spaces["program"]:install_read_tap(0x01ffffe0,0x01ffffef,"replay",function()
 dump("vram.bin",bind(video,"m_local_videoram"),524288);dump("io.bin",bind(main,"m_IOregs"),28);dump("dma.bin",bind(video,"m_dma_register"),18)
 dump("shiftreg.bin",bind(main,"m_shiftreg"),4096)
 local bus=main.spaces["program"];local display=assert(io.open("display.bin","wb"))
 assert(display:write(string.pack("<I2I2",bus:read_u16(0xc00001d0),bus:read_u16(0xc00001e0))))
 assert(display:close())
end)
local rows=INPUT_ROWS;local cursor=1;local requested=0xffffffff
local mapping={}
for player=1,2 do
 for n,name in ipairs({"Up","Down","Left","Right","High Punch","Block","High Kick"})do
  mapping[#mapping+1]={n-1+(player-1)*8,":IN0","P"..player.." "..name}
 end
end
for _,row in ipairs({{16,":IN1","Coin 1"},{17,":IN1","Coin 2"},{18,":IN1","1 Player Start"},{21,":IN1","2 Players Start"},
 {28,":IN2","P1 Low Punch"},{29,":IN2","P1 Low Kick"},{25,":IN2","P2 Low Punch"},{26,":IN2","P2 Low Kick"}})do mapping[#mapping+1]=row end
for _,row in ipairs(mapping)do row[4]=assert(m.ioport.ports[row[2]].fields[row[3]],row[3])end
replay_frames=emu.add_machine_frame_notifier(function()
 local t=tick();while rows[cursor]and rows[cursor][1]<=t do requested=rows[cursor][2];cursor=cursor+1 end
 for _,row in ipairs(mapping)do row[4]:set_value((requested&(1<<row[1]))==0 and 1 or 0)end
end)
coroutine.wrap(function()
 local ending=FRAME_END;local rows={}
 for y=20,273 do
  local at=ending-(274-y)*6325;emu.wait(emu.attotime.from_ticks(at,100000000)-m.time+emu.attotime(0,1));assert(tick()==at)
  local bus=main.spaces["program"];local first,last=bus:read_u16(0xc0000010)*2,bus:read_u16(0xc0000020)*2
  assert(first==90 and last==490 and bus:read_u16(0xc0000050)==20 and bus:read_u16(0xc0000060)==274)
  local row={};for x=first,last-1 do local rgb=screen:pixel(x,y);row[#row+1]=string.char((rgb>>16)&255,(rgb>>8)&255,rgb&255)end;rows[#rows+1]=table.concat(row)
 end
 local f=assert(io.open("frame.rgb","wb"));assert(f:write(table.concat(rows)));assert(f:close())
end)()
'''
    inputs='{'+','.join('{'+str(t)+','+str(v)+'}'for t,v in capture['inputs'])+'}'
    first=lua.index('coroutine.wrap(function()');last=lua.index('end)()',first)+len('end)()');raster=lua[first:last]
    for frame in capture.get('snapshot_frames',[]):
        lua+='\n'+raster.replace('FRAME_END',str(frame*1827925)).replace('"frame.rgb"',f'"frame-{frame}.rgb"')
    lua=lua.replace('INPUT_ROWS',inputs).replace('FRAME_END',str(state['frames']*1827925))
    lua=replay_audio.original_lua(lua,state['cycles'])
    lua=replay_state.original_lua(lua)
    (directory/'observe.lua').write_text(lua,encoding='ascii')
    args=[batch.MAME,'mk2','-noreadconfig','-nowriteconfig','-rompath',directory,'-video','none','-sound','none','-nothrottle','-skip_gameinfo','-noplugins','-frameskip','0',
          '-keyboardprovider','none','-mouseprovider','none','-lightgunprovider','none','-joystickprovider','none','-debug','-debugger','windows','-debuglog','-debugscript','observe.cmd',
          '-autoboot_delay','0','-autoboot_script','observe.lua','-nvram_directory',directory/'nvram','-cfg_directory',directory/'cfg','-homepath',directory/'home','-seconds_to_run',str(state['cycles']//6250000+5)]
    execution=q.command(args,directory,cwd=directory,env=env,timeout=wall_seconds)
    r={'passed':False,'scope':'Original CPU34, board memories and display, complete sampled/final rasters, all audio and terminal DSP/DCS state.',
       'execution':q.compact(execution),'mame_sha256':batch.MAME_SHA,'observer_sha256':hashlib.sha256(lua.encode('ascii')).hexdigest()}
    for line in execution['stdout'].splitlines():reference.reject_mame_diagnostic(line)
    if not execution['passed'] or execution['discarded_output_bytes']:return r
    comparison_started = time.perf_counter()
    points=[[int(v,16)for v in line.split()[1:]]for line in (directory/'debug.log').read_text().splitlines()if line.startswith('REPLAY_CPU ')]
    r['cpu34_equal']=points==[state['cpu34']];r['observed_cpu34']=points
    r['memories']={}
    for name,size in replay_state.BOARD_FILES.items():
        a=(native_directory/name).read_bytes();path=directory/name;b=path.read_bytes()if path.is_file()else b''
        first_offset=next((n for n,(x,y)in enumerate(zip(a,b))if x!=y),min(len(a),len(b))) if a!=b else None
        r['memories'][name]={'passed':len(a)==len(b)==size and a==b,'bytes':size,'first_offset':first_offset,
                             'native_bytes':len(a),'original_bytes':len(b),
                             'native_sha256':hashlib.sha256(a).hexdigest(),'original_sha256':hashlib.sha256(b).hexdigest()}
    a=(native_directory/'last-frame.ppm').read_bytes().split(b'\n',3)[3]
    path=directory/'frame.rgb';b=path.read_bytes()if path.is_file()else b''
    r['raster']={'passed':len(a)==len(b)==304800 and a==b,'pixels':101600,'native_sha256':hashlib.sha256(a).hexdigest(),'original_sha256':hashlib.sha256(b).hexdigest()}
    r['sampled_rasters']=[]
    for frame in capture.get('snapshot_frames',[]):
        name=f'frame-{frame}.rgb';a=(native_directory/name).read_bytes();b=(directory/name).read_bytes()
        r['sampled_rasters'].append({'frame':frame,'passed':len(a)==len(b)==304800 and a==b,'pixels':101600,
                                    'native_sha256':hashlib.sha256(a).hexdigest(),'original_sha256':hashlib.sha256(b).hexdigest()})
    try:
        r['audio']=replay_audio.compare(native_directory,directory,state['cycles'])
    except replay_audio.SampleMismatch as mismatch:
        r['audio']={'passed':False,'first_difference':mismatch.difference}
    r['dsp_cycle_observation']=replay_state.save_dsp_snapshot(directory)
    r['dsp_terminal']=replay_state.compare_state(native_directory,directory)
    r['passed']=r['cpu34_equal']and all(v['passed']for v in r['memories'].values())and r['raster']['passed']and r['audio']['passed']and all(v['passed']for v in r['sampled_rasters'])and r['dsp_terminal']['passed']
    r['comparison_seconds'] = time.perf_counter()-comparison_started
    return r
