"""Read-only MK3 2.1 Original observations of the Wolf-Unit DMA blitter (pinned MAME 0.280).

From reset, seeded factory CMOS, default DIPs, no inputs. One run combines:
- a Lua autoboot script with write taps on the DMA registers (both mirrors, W:123) and on video RAM
  (0x00000000-0x003fffff). Taps run before the handler. Per DMA register write: bit offset, data, mask and the
  machine time (the CPU local time inside the write). Per DMA_COMMAND write with bit 15: the 18 saved
  m_dma_register words before the write and two video RAM deltas, both read from the saved m_local_videoram
  item: P = changes since the last observation (CPU writes between DMAs, declared stimulus) and A = changes
  made by the DMA, closed at the next DMA register write, CPU video RAM write or machine stop. A video RAM
  change that bypasses the taps (shift-register transfers) would land in A and fail the comparison;
- the debugger: every DMA_COMMAND write (PC, totalcycles, cycles already counted by the instruction) and the
  state S = (DMA_COMMAND & 0x8000) | (INTPEND & INT1) at every instruction boundary where S changes or that
  follows a DMA_COMMAND write (forced row), with the start cycle of the previous instruction. Both reads are
  side-effect free (dma_r, io_register_r). One registerpoint does the bookkeeping and the test: once a
  registerpoint fires, the later ones are not evaluated at that instruction.
census() is a Lua-only run counting the DMA commands, scale registers and DMA_CONFIG of every trigger.
Logs live only in the scratch tree, removed on success and failure. Nothing is written to the machine.
"""
from collections import Counter
from pathlib import Path
import hashlib,json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms

ROOT=Path(__file__).resolve().parents[2]
CYCLE_AS=160*10**9  # TMS34010 cycle, 50 MHz / 8, in attoseconds

LUA=r'''
if mk3_dma_started then return end  -- mame.cpp re-arms the autoboot script on a soft reset; none happens here
mk3_dma_started = true
local machine = manager.machine
local video = assert(machine.devices[":video"])
local function bind(device, suffix)
    local found
    for name, index in pairs(device.items) do
        if name == suffix or name:sub(-#suffix - 1) == "/" .. suffix then
            assert(not found, "Ambiguous saved item " .. suffix)
            found = emu.item(index)
        end
    end
    return assert(found, "Missing saved item " .. suffix)
end
local vram, regs = bind(video, "m_local_videoram"), bind(video, "m_dma_register")
assert(vram.size == 2 and vram.count == 524288 and regs.size == 2 and regs.count == 18)
local BYTES, DETAIL = 1048576, DETAIL_FLAG
local out = assert(io.open("dma.txt", "w"))
local last, pending = string.rep("\0", BYTES), nil  -- m_local_videoram is value-initialised (midtunit_v.cpp:198)
local function diff(a, b)
    local t, n = {}, 0
    if a ~= b then
        for i = 1, BYTES, 1024 do
            if a:sub(i, i + 1023) ~= b:sub(i, i + 1023) then
                for j = i, i + 1022, 2 do
                    local v = string.unpack("<I2", b, j)
                    if string.unpack("<I2", a, j) ~= v then n = n + 1; t[n] = string.format("%X:%X", (j - 1) // 2, v) end
                end
            end
        end
    end
    return n .. " " .. table.concat(t, " ")
end
local function close(kind)
    if not pending then return end
    local s = vram:read_block(0, BYTES)
    out:write("A ", kind, " ", diff(pending, s), "\n")
    last, pending = s, nil
end
local census, writes, triggers = {}, 0, 0
local function dma_write(offset, data, mask)
    writes = writes + 1
    local config = regs:read(15)
    local number = (offset >> 4) & 15
    if (config >> 5) & 1 == 0 and (number == 12 or number == 13) then number = number + 4 end  -- register_map
    local value = (regs:read(number) & ((~mask) & 0xffff)) | (data & mask)
    if DETAIL then
        close("dma")
        local t = machine.time
        out:write(string.format("W %X %X %X %d %d\n", offset, data, mask, t.seconds, t.attoseconds))
    end
    if number == 1 and value & 0x8000 ~= 0 then
        triggers = triggers + 1
        local key = string.format("%04X %04X %04X %04X", value, regs:read(10), regs:read(11), config)
        census[key] = (census[key] or 0) + 1
        if DETAIL then
            local r = {}
            for i = 0, 17 do r[#r + 1] = string.format("%X", regs:read(i)) end
            local s = vram:read_block(0, BYTES)
            out:write("T ", table.concat(r, " "), "\nP ", diff(last, s), "\n")
            pending = s
        end
    end
end
mk3_dma_taps = {}
local space = machine.devices[":maincpu"].spaces["program"]
for _, base in ipairs({0x01a00000, 0x01a80000}) do
    mk3_dma_taps[#mk3_dma_taps + 1] = space:install_write_tap(base, base + 0xff, "mk3-dma", dma_write)
end
mk3_dma_taps[#mk3_dma_taps + 1] = space:install_write_tap(0x00000000, 0x003fffff, "mk3-vram", function() close("vram") end)
mk3_dma_stop = emu.add_machine_stop_notifier(function()
    close("stop")
    for key, count in pairs(census) do out:write("C ", key, " ", count, "\n") end
    out:write(string.format("N %d %d\n", writes, triggers))
    out:close()
end)
'''

DEBUG='''focus :maincpu
rpset {((temp1=temp0)+(temp0=totalcycles)+(temp4=cycles)+(temp7=temp6)+(temp6=0))<0||temp7||(((w@1a00010)&8000)|((w@c0000120)&2))!=temp5},{printf "MK3_DS %X %d %d %X %d\\n",pc,totalcycles,temp1,(temp5=((w@1a00010)&8000)|((w@c0000120)&2)),temp7;g}
wpset 1a00010,10,w,1,{printf "MK3_DC %X %X %X %d %d %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize,temp4-cycles,(temp6=1);g}
wpset 1a80010,10,w,1,{printf "MK3_DC %X %X %X %d %d %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize,temp4-cycles,(temp6=1);g}
go
'''

def graphics_rows(directory=ROOT/'roms/mk3'):
    """[(path, region byte offset, size)] of the ROM_LOAD32_BYTE "video" region (W:725-751), stride 4."""
    rows=[r for r in roms.definition() if r['region']=='video']
    if len(rows)!=20 or any(r['stride_bytes']!=4 for r in rows):raise ValueError('Unexpected MK3 graphics layout')
    return [(Path(directory)/r['path'],r['offset_bytes'],r['size']) for r in rows]

def graphics_image(directory=ROOT/'roms/mk3'):
    """The loaded bytes of the "video" region (0x1200000 of 0x2000000), for identity only."""
    rows=graphics_rows(directory);image=bytearray(max((o&~3)+4*s for _,o,s in rows))
    for path,offset,size in rows:
        data=path.read_bytes()
        if len(data)!=size:raise ValueError(f'Graphics ROM size differs: {path.name}')
        image[offset:offset+4*size:4]=data
    return bytes(image)

def words(field):
    """'n idx:val ...' -> {index: value}."""
    n,*pairs=field.split()
    out={int(a,16):int(b,16) for a,b in (p.split(':') for p in pairs)}
    if len(out)!=int(n):raise ValueError('Malformed video RAM delta')
    return out

def parse_lua(text):
    writes,triggers,census,totals=[],[],Counter(),None
    for line in text.splitlines():
        kind,_,rest=line.partition(' ')
        if kind=='W':
            offset,data,mask,s,a=rest.split()
            writes.append(dict(offset=int(offset,16),data=int(data,16),mask=int(mask,16),atto=int(s)*10**18+int(a)))
        elif kind=='T':triggers.append(dict(write=len(writes)-1,registers=[int(x,16) for x in rest.split()]))
        elif kind=='P':triggers[-1]['pre']=words(rest)
        elif kind=='A':
            closer,_,field=rest.partition(' ')
            triggers[-1]['closed_by']=closer;triggers[-1]['post']=words(field)
        elif kind=='C':*key,count=rest.split();census[' '.join(key)]=int(count)
        elif kind=='N':totals=[int(x) for x in rest.split()]
        else:raise ValueError('Unexpected Lua row: '+line[:80])
    if totals is None:raise ValueError('Lua observation did not reach machine stop')
    return writes,triggers,census,totals

def parse_debug(text):
    commands,states=[],[]
    for line in text.splitlines():
        f=line.split()
        if not f or not f[0].startswith('MK3_'):
            if 'rror' in line and not line.startswith('>'):raise ValueError('MAME diagnostic: '+line)
            continue
        if f[0]=='MK3_DC':
            if f[5]!='16':raise ValueError('non-16-bit DMA_COMMAND write: '+line)
            commands.append(dict(pc=int(f[1],16),address=int(f[2],16),data=int(f[3],16),cycle=int(f[4]),elapsed=int(f[6])))
            if not 0<=int(f[6])<256:raise ValueError('implausible in-instruction cycle offset: '+line)
        elif f[0]=='MK3_DS':states.append(dict(pc=int(f[1],16),boundary=int(f[2]),previous=int(f[3]),state=int(f[4],16),forced=f[5]=='1'))
    return commands,states

def mame(args,temp):
    run=q.command([reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                   '-video','none','-sound','none','-nothrottle','-autoboot_delay','0','-autoboot_script','dma.lua',
                   '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap']+args,temp,cwd=temp,timeout=1800)
    if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
    lua=temp/'dma.txt'
    if not lua.is_file() or lua.stat().st_size>512*1024*1024:raise ValueError('Missing or oversized Lua observation')
    return run,parse_lua(lua.read_text('ascii'))

def identities():
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    image=graphics_image()
    return dict(core_sha256=reference.CORE_SHA,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),
                graphics_loaded_bytes=len(image),graphics_sha256=hashlib.sha256(image).hexdigest())

def seeded(temp,detail):
    (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
    (temp/'dma.lua').write_text(LUA.replace('DETAIL_FLAG','true' if detail else 'false'),encoding='ascii')

def capture(seconds=4):
    """Every DMA register write, DMA trigger and DMA status/INT1 boundary change from reset to `seconds`."""
    ident=identities()
    with q.scratch_tree() as (temp,cleanup):
        seeded(temp,True);(temp/'dma.cmd').write_text(DEBUG,encoding='ascii')
        run,(writes,triggers,census,totals)=mame(['-debug','-debugger','windows','-debuglog','-debugscript','dma.cmd','-seconds_to_run',str(seconds)],temp)
        log=temp/'debug.log'
        if not log.is_file() or log.stat().st_size>256*1024*1024:raise ValueError('Missing or oversized debugger log')
        text=log.read_text('utf-8');debugger=text.splitlines()[0];commands,states=parse_debug(text)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    # Join: the debugger's DMA_COMMAND writes are the Lua writes to offset 1, in order, at the same time.
    lua_commands=[i for i,w in enumerate(writes) if (w['offset']>>4)&15==1]
    if len(lua_commands)!=len(commands) or totals[0]!=len(writes) or totals[1]!=len(triggers):raise ValueError('Lua and debugger observations differ in count')
    for i,c in zip(lua_commands,commands):
        w=writes[i]
        if w['data']!=c['data'] or w['offset']!=c['address'] or w['atto']!=(c['cycle']+c['elapsed'])*CYCLE_AS:
            raise ValueError(f'Lua write {i} differs from debugger DMA_COMMAND write {c}')
        w.update(cycle=c['cycle'],elapsed=c['elapsed'],pc=c['pc'])
    return dict(ident,debugger=debugger,seconds=seconds,wall_seconds=run['wall_seconds'],writes=writes,triggers=triggers,
                states=states,census=dict(census),cleanup=cleanup)

def census(seconds=25):
    """Lua-only: (command, SCALE_X, SCALE_Y, DMA_CONFIG) of every trigger from reset to `seconds`."""
    ident=identities()
    with q.scratch_tree() as (temp,cleanup):
        seeded(temp,False)
        run,(_,_,counts,totals)=mame(['-seconds_to_run',str(seconds)],temp)
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    return dict(ident,seconds=seconds,wall_seconds=run['wall_seconds'],register_writes=totals[0],triggers=totals[1],
                keys=dict(counts),cleanup=cleanup)

if __name__=='__main__':
    if '--census' in sys.argv:print(json.dumps(census(int(sys.argv[1]) if sys.argv[1:2]!=['--census'] else 25),indent=1));raise SystemExit
    r=capture(int(sys.argv[1]) if len(sys.argv)>1 else 4)
    t=r['triggers']
    print(json.dumps(dict({k:v for k,v in r.items() if k not in ('writes','triggers','states')},writes=len(r['writes']),triggers=len(t),
        states=r['states'][:12],state_rows=len(r['states']),first=[dict(registers=[hex(x) for x in x['registers']],pre=len(x['pre']),post=len(x['post']),
        closed_by=x['closed_by'],write=r['writes'][x['write']]) for x in t[:4]],closers=Counter(x['closed_by'] for x in t),
        pre_words=sum(len(x['pre']) for x in t),post_words=sum(len(x['post']) for x in t)),indent=1))
