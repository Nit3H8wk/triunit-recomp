"""Original (pinned MAME 0.280, tools/mk3/reference.py identities) observations for tools/mk3/replay.py.

Read-only instrumentation, one debugger registerpoint `totalcycles>=temp9&&(st&0x2000000)==0` (the boundary rule of
tools/mk3/replay_state.py). MAME runs only the first matching registerpoint at an instruction hook, so the schedule
lives in Lua: at each hit the action prints PC, ST, totalcycles and the 31 registers, lists the ADSP symbols and
triggers a Lua read tap through a side-effect-suppressed debugger read of palette word 0x018fffe0. The tap reads that
totalcycles back from the debugger console, then in the native runner's order applies due tape events, takes the due
periodic record (several due specs give one record), the due dumps and END (record, END dumps, machine exit), and sets
temp9 to the next due cycle. The tap only reads: save items of main RAM, CMOS, palette, video RAM, DMA registers, TMS
I/O registers and the midwunit control latch; ADSP DM/PM through its spaces in the mapped RAM/ROM ranges only (no latch
or control register is read); the DMADAC ring since the previous record. It acts only while the debugger is stopped.

Input tape: from the boundary of its cycle on, a read tap on 0x01800000-0x0187ffff returns the armed word for that io
port (offset ((address-0x01800000)>>4)%16%8, as mk3::Ops::IoOffset), as the native run's mk3::Ops::ports does. The
empty tape installs no port tap and leaves MAME's own default ports (no input pressed, INPUT_PORTS(mk3) DIP defaults).

Event streams (events=True; tools/mk3/replay_state.py STREAMS): read-only debugger watchpoints on the sound port word
0x01680000 (writes), the DMA registers 0x01a00000-0x01a000ff and the mirror 0x01a80000-0x01a800ff (writes), io offsets
0-3 of 0x01800000-0x0187ffff (reads, the value after the tape override) and the CMOS 0x01400000-0x0145ffff (writes).
Each hit adds to its stream's count and running FNV-1a 64 (address, value, totalcycles low and high 32 bits) in debugger
temp registers; every checkpoint hit prints them (MK3_ES: cumulative since reset). The debugger's totalcycles inside an
access is the value cached at that instruction's hook, the instruction start (as native/tests/mk3_replay_main.cpp's
records); a Lua tap would see the machine time of the access instead (MMTM: start + 2 + 4k). dcs, input and cmos
events are also printed one by one (MK3_ED, MK3_EI, MK3_EC) for the whole-stream comparison.
"""
import math,re,time
from tools.mk3 import reference,roms
from tools.mk3.replay_state import STREAMS
from tools.quality import run as q

NL='\\n'
REGS=','.join(reference.REGISTERS)
DEVICE_READS=reference.DEVICES+((0xc0000000,0x200),)
NEVER=1<<62

LUA=r'''
local m=manager.machine
local main,video,dac=m.devices[":maincpu"],m.devices[":video"],m.devices[":dcs:dac"]
local dsp=m.devices[":dcs:dcs"]
local function item(dev,suffix)
 local found
 for name,index in pairs(dev.items) do if name==suffix or name:sub(-#suffix-1)=="/"..suffix then assert(not found,suffix);found=emu.item(index) end end
 return assert(found,suffix)
end
local ram,cmos,pal=item(main,":mainram"),item(main,":nvram"),item(main,":palette")
local vram,dma,ctl,io=item(video,"m_local_videoram"),item(video,"m_dma_register"),item(video,"m_midtunit_control"),item(main,"m_IOregs")
local ring,bufin,enabled=item(dac,"m_buffer"),item(dac,"m_bufin"),item(dac,"m_enabled")
local ds,ps=dsp.spaces["data"],dsp.spaces["program"]
local P=0x100000001b3
local BASIS=0xcbf29ce484222325
local U16=string.rep("I4",16)
local function words(it)
 local s=it:read_block(0,it.count*it.size);assert(#s%64==0)
 local h=BASIS
 for i=1,#s,64 do local w={string.unpack("<"..U16,s,i)} for k=1,16 do h=(h~w[k])*P end end
 return h,s
end
local function dm_mapped(a) return a<0x3000 or (a>=0x3800 and a<0x3a00) end
local function pm_mapped(a) return a<0x400 or (a>=0x800 and a<0x2000) end
local function adsp_dm() local h,t=BASIS,{} for a=0,0x3fff do if dm_mapped(a) then local v=ds:read_u16(a);h=(h~v)*P;t[#t+1]=string.pack("<I2",v) end end return h,table.concat(t) end
local function adsp_pm() local h,t=BASIS,{} for a=0,0x1fff do if pm_mapped(a) then local v=ps:read_u32(a);h=(h~v)*P;t[#t+1]=string.pack("<I4",v) end end return h,table.concat(t) end
local function list(it,n) local t={} for k=0,n-1 do t[#t+1]=tostring(it:read(k)) end return table.concat(t,",") end
-- dmadac m_buffer holds float samples (4-byte items: int16 * (1/32767) in single precision, measured at the first
-- non-zero block); the stored int16 is recovered by rounding (injective for |s| <= 32768, error < 0.01).
assert(ring.size==4,"dmadac m_buffer item size")
local function sample(k) return math.floor(string.unpack("<f",string.pack("<I4",ring:read(k)))*32767+0.5)&0xffff end
local function segment(from,to) local h,n=BASIS,0 local k=from while k~=to do h=(h~sample(k))*P;n=n+1;k=(k+1)%ring.count end return n,h end
local HEX={} for c=0,255 do HEX[string.char(c)]=string.format("%02x",c) end
local REGION={ram=function() return select(2,words(ram)) end,cmos=function() return select(2,words(cmos)) end,
 palette=function() return select(2,words(pal)) end,vram=function() return select(2,words(vram)) end,
 dm=function() return select(2,adsp_dm()) end,pm=function() return select(2,adsp_pm()) end}
local FIRST,STEP,LAST,ENDC=SCHEDULE
local SAMPLES=SAMPLE_FLAG
local TAPE=TAPE_LIST
local POINTS=POINT_LIST
local DUMPS=DUMP_LIST
local END_DUMPS=END_DUMP_LIST
local prev,hits,ti,di,pi,rec,ended=0,0,1,1,1,FIRST,false
local override={}
local function stopped() return m.debugger.execution_state=="stop" end
local function record(spec)
 local b=bufin:read(0)
 local from_prev=prev
 local n1,h1=segment(prev,b)
 local n2,h2=segment(0,b)
 prev=b
 local hdm,hpm=adsp_dm(),adsp_pm()
 print(string.format("MK3_LUA %d %s %x %x %x %x %x %x %s %s %d %d %d %d %x %d %x",hits,spec,words(ram),words(cmos),words(pal),words(vram),hdm,hpm,
  list(dma,18),list(io,32),ctl:read(0),b,enabled:read(0),n1,h1,n2,h2))
 if SAMPLES then local t={} local k=from_prev while k~=b do t[#t+1]=string.format("%04x",sample(k));k=(k+1)%ring.count end print("MK3_SAMPLES "..hits.." "..table.concat(t)) end
end
local function dump(name) print("MK3_DUMP "..name.." "..(REGION[name]():gsub(".",HEX))) end
local function now()
 local log=m.debugger.consolelog
 for k=#log,math.max(1,#log-400),-1 do
  local line=log[tostring(k)]
  local tc=line and line:match("^MK3_CP %x+ %x+ (%d+) ")
  if tc then return math.tointeger(tonumber(tc)) end
 end
 error("checkpoint line not found in the debugger console")
end
replay_hit=main.spaces["program"]:install_read_tap(0x018fffe0,0x018fffef,"replay_hit",function(offset,data,mask)
 if not stopped() then return data end
 local ok,err=pcall(function()
  hits=hits+1
  local tc=now()
  print("MK3_HIT "..hits.." "..tc)
  while TAPE[ti] and TAPE[ti][1]<=tc do override[TAPE[ti][2]]=TAPE[ti][3];ti=ti+1 end
  if STEP>0 and rec<=tc and rec<=LAST then local due=rec;rec=rec+STEP*(1+(tc-rec)//STEP);record(tostring(due)) end
  while POINTS[pi] and POINTS[pi]<=tc do record(tostring(POINTS[pi]));pi=pi+1 end
  while DUMPS[di] and DUMPS[di][1]<=tc do dump(DUMPS[di][2]);di=di+1 end
  if not ended and ENDC<=tc then
   record("END");for _,name in ipairs(END_DUMPS) do dump(name) end;ended=true;print("MK3_EXIT "..tc);m:exit()
  end
  local next=NEVER_CYCLE
  if STEP>0 and rec<=LAST then next=math.min(next,rec) end
  if TAPE[ti] then next=math.min(next,TAPE[ti][1]) end
  if POINTS[pi] then next=math.min(next,POINTS[pi]) end
  if DUMPS[di] then next=math.min(next,DUMPS[di][1]) end
  if not ended then next=math.min(next,ENDC) else next=NEVER_CYCLE end
  m.debugger:command(string.format("temp9=0x%x",next))
 end)
 if not ok then print("MK3_LUA_ERROR "..tostring(err));m:exit() end
 return data
end)
if #TAPE>0 then
 replay_ports=main.spaces["program"]:install_read_tap(0x01800000,0x0187ffff,"replay_ports",function(offset,data,mask)
  local port=((offset-0x01800000)>>4)%16%8
  if override[port]~=nil and not stopped() then return override[port] end
  return data
 end)
end
'''


FNV_P,FNV_BASIS='100000001b3','cbf29ce484222325'   # debugger numbers are hexadecimal
# (stream, base, size, condition, count/hash temp registers, per-event printf or None); temp9 is the schedule.
EVENT_WATCHES=(('dcs',0x01680000,0x10,'1',1,2,'MK3_ED %d %X'),('dma',0x01a00000,0x100,'1',3,4,None),('dma',0x01a80000,0x100,'1',3,4,None),
               ('input',0x01800000,0x80000,'((wpaddr>>4)&7)<4',5,6,'MK3_EI %d %X %X'),('cmos',0x01400000,0x60000,'1',7,8,'MK3_EC %d %X %X'))


def event_watches():
    """wpset lines of the event streams: count and running FNV-1a 64 in temp registers, optional per-event printf."""
    lines=[f'temp{k}=0' for k in (1,3,5,7)]+[f'temp{k}={FNV_BASIS}' for k in (2,4,6,8)]
    for name,base,size,cond,n,h,fmt in EVENT_WATCHES:
        mix=f'temp{h}'
        for v in ('wpaddr','wpdata','(totalcycles&ffffffff)','(totalcycles>>20)'):mix=f'(({mix})^{v})*{FNV_P}'
        args={'MK3_ED %d %X':'totalcycles,wpdata','MK3_EI %d %X %X':'totalcycles,wpaddr,wpdata','MK3_EC %d %X %X':'totalcycles,wpaddr,wpdata'}
        show=f'printf "{fmt}{NL}",{args[fmt]};' if fmt else ''
        lines.append(f'wpset {base:x},{size:x},{"r" if name=="input" else "w"},{cond},{{temp{n}=temp{n}+1;temp{h}={mix};{show}g}}')
    return lines


def script(first,window=None,windows=(),events=False):
    """Debugger script: the scheduling registerpoint (first due cycle `first`), the write/read window(s) and the event streams."""
    regs=' '.join(['%X']*31)
    es=f'printf "MK3_ES %X %X %X %X %X %X %X %X{NL}",temp1,temp2,temp3,temp4,temp5,temp6,temp7,temp8;' if events else ''
    lines=['focus :maincpu',f'temp9={first:#x}',
           f'rpset totalcycles>=temp9&&(st&0x2000000)==0,{{printf "MK3_CP %X %X %d {regs}{NL}",pc,st,totalcycles,{REGS};{es}symlist :dcs:dcs;do :maincpu.pw@018fffe0;g}}']
    lines+=event_watches() if events else []
    spans=([window] if window else [])+list(windows)
    if spans:
        cond='||'.join(f'(totalcycles>={lo:#x}&&totalcycles<={hi:#x})' for lo,hi in spans)
        lines.append(f'wpset 0,ffffffff,w,{cond},{{printf "MK3_W %X %X %X %d %d{NL}",pc,wpaddr,wpdata,totalcycles,wpsize;g}}')
        lines+=[f'wpset {base:x},{size:x},r,{cond},{{printf "MK3_R %X %X %X %d %d{NL}",pc,wpaddr,wpdata,totalcycles,wpsize;g}}' for base,size in DEVICE_READS]
    return '\n'.join(lines+['go'])+'\n'


def lua(first,step,last,end,tape=(),dumps=(),points=(),samples=False):
    mid=sorted(((c,n) for n,c in dumps if c),key=lambda d:d[0])
    return (LUA.replace('SCHEDULE',f'{first},{step},{last},{end}').replace('SAMPLE_FLAG','true' if samples else 'false').replace('NEVER_CYCLE',str(NEVER))
               .replace('POINT_LIST','{'+','.join(map(str,points))+'}').replace('TAPE_LIST','{'+','.join(f'{{{c},{p},{v}}}' for c,p,v in tape)+'}')
               .replace('END_DUMP_LIST','{'+','.join(f'"{n}"' for n,c in dumps if not c)+'}')
               .replace('DUMP_LIST','{'+','.join(f'{{{c},"{n}"}}' for c,n in mid)+'}'))


def parse(log,stdout):
    """Records: each MK3_LUA row with the state of its hit (debugger MK3_CP + symlist, in hit order); dumps; window."""
    hits,current=[],None
    events=dict(MK3_ED=[],MK3_EI=[],MK3_EC=[])
    for line in log.splitlines():
        part=line.strip().split()
        if not part:continue
        if part[0]=='MK3_CP':
            pc,st,cycles,*regs=part[1:]
            if len(regs)!=31:raise ValueError('Truncated checkpoint')
            current=dict(cycle=int(cycles),pc=int(pc,16),status=int(st,16),registers=[int(r,16) for r in regs],adsp={})
            hits.append(current)
        elif part[0]=='MK3_ES' and current is not None:
            if len(part)!=9:raise ValueError('Truncated event-stream line')
            current['events']={name:[int(part[1+2*k],16),f'{int(part[2+2*k],16):x}'] for k,name in enumerate(STREAMS)}
        elif part[0] in ('MK3_ED','MK3_EI','MK3_EC'):
            events[part[0]].append([int(part[1])]+[int(x,16) for x in part[2:]])
        elif current is not None and len(part)>2 and part[1]=='=':current['adsp'][part[0]]=int(part[2],16)
        elif re.search(r'error|unknown|invalid',line,re.I) and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
    if 'MK3_LUA_ERROR' in stdout:raise ValueError('Lua observer: '+stdout[stdout.index('MK3_LUA_ERROR'):][:300])
    marks=[l.split() for l in stdout.splitlines() if l.startswith('MK3_HIT ')]
    if [int(m[1]) for m in marks]!=list(range(1,len(marks)+1)) or len(marks)>len(hits) or len(hits)>len(marks)+1:
        raise ValueError(f'hits: debugger {len(hits)} Lua {len(marks)}')
    for m,h in zip(marks,hits):
        if int(m[2])!=h['cycle']:raise ValueError('hit cycle read back differs')
    records=[]
    for l in (l.split() for l in stdout.splitlines() if l.startswith('MK3_LUA ')):
        cp=dict(hits[int(l[1])-1]);cp['adsp']=dict(cp['adsp']);spec=l[2];cp['hit']=int(l[1])
        cp['spec']='end' if spec=='END' else int(spec)
        cp['hash']=dict(zip(('ram','cmos','palette','vram','dm','pm'),(f'{int(h,16):x}' for h in l[3:9])))
        cp['dma']=[int(v) for v in l[9].split(',')];cp['io']=[int(v) for v in l[10].split(',')]
        cp['control']=int(l[11])
        bufin,enabled,n1,h1,n2,h2=int(l[12]),int(l[13]),int(l[14]),l[15],int(l[16]),l[17]
        cp['pcm']=dict(bufin=bufin,enabled=enabled,segment=n1,hash=f'{int(h1,16):x}',since_reset=dict(segment=n2,hash=f'{int(h2,16):x}'))
        records.append(cp)
    samples={int(p[1]):p[2] if len(p)>2 else '' for p in (l.split() for l in stdout.splitlines() if l.startswith('MK3_SAMPLES '))}
    for r in records:
        if r['hit'] in samples:r['pcm']['samples']=samples[r['hit']]
    dumps=[(p[1],bytes.fromhex(p[2] if len(p)>2 else '')) for p in (l.split() for l in stdout.splitlines() if l.startswith('MK3_DUMP '))]
    rows=lambda tag:[[int(p[1],16),int(p[2],16),int(p[3],16),int(p[4])] for p in (l.split() for l in log.splitlines()) if p and p[0]==tag]
    streams=None
    if records and 'events' in records[-1]:   # whole streams: the events of instructions before the END boundary
        end=records[-1]['cycle']
        streams=dict(events_total=records[-1]['events'],events_full=dict(
            dcs=[[c,v] for c,v in events['MK3_ED'] if c<end],
            input=[[c,((a-0x01800000)>>4)%16%8,v] for c,a,v in events['MK3_EI'] if c<end],
            cmos=[[c,a,v] for c,a,v in events['MK3_EC'] if c<end]))
        for name,full in streams['events_full'].items():
            if len(full)!=records[-1]['events'][name][0]:raise ValueError(f'{name} events: {len(full)} printed, {records[-1]["events"][name][0]} counted')
    return dict(records=records,dumps=dumps,hits=len(marks),window=dict(writes=rows('MK3_W'),reads=rows('MK3_R')),events=streams)


def capture(first,step,last,end,tape=(),dumps=(),window=None,points=(),samples=False,events=False,windows=()):
    """One Original run from reset with the CMOS seed and default DIPs: periodic records first, first+step, ... <= last,
    tape events, dumps ((region, cycle), 0 = at END) and END at the first boundary >= `end`, then exit.
    samples: each record also carries its DAC ring segment as 16-bit hex words (pcm['samples']).
    events: the event streams (module docstring), cumulative per record and whole at END; windows: more bus windows."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(reference.ROOT/'roms/mk3')
    due=min(([first] if step else [])+[end]+list(points)+[c for c,_,_ in tape]+[c for _,c in dumps if c])
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'replay.cmd').write_text(script(due,window,windows,events),encoding='ascii')
        (temp/'replay.lua').write_text(lua(first,step,last,end,tape,dumps,points,samples),encoding='ascii')
        started=time.perf_counter()
        run=q.command([reference.CORE,'mk3','-rompath',reference.ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                       '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debuglog','-debugscript','replay.cmd',
                       '-autoboot_delay','0','-autoboot_script','replay.lua','-keyboardprovider','none','-mouseprovider','none',
                       '-joystickprovider','none','-lightgunprovider','none',
                       '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap',
                       '-seconds_to_run',str(math.ceil(end/6250000)+3)],
                      temp,cwd=temp,timeout=max(1800,math.ceil(end/6250000)*6+600),output_limit=64<<20)   # ~0.47x real time, x2 for load
        wall=time.perf_counter()-started
        if not run['passed'] or run['discarded_output_bytes']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1500:])
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>256*1024*1024:raise ValueError('Missing or oversized debugger log')
        text=log.read_text('utf-8');log_bytes=log.stat().st_size
        out=parse(text,run['stdout']);debugger=text.splitlines()[0]
        if 'MK3_EXIT ' not in run['stdout'] or not out['records'] or out['records'][-1]['spec']!='end':raise ValueError('END checkpoint not reached')
        if len(out['dumps'])!=len(dumps):raise ValueError('Dumps not reached')
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    return dict(out,core_sha256=reference.CORE_SHA,debugger=debugger,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),
                wall_seconds=wall,stdout_bytes=len(run['stdout']),log_bytes=log_bytes,cleanup=cleanup,metrics=run.get('metrics',{}))
