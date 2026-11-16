"""Read-only observation of the MK3 2.1 serial PIC simulation in the pinned Original (MAME 0.280).

A Lua autoboot script reads the device's saved items (m_data, m_idx, m_buff, m_status, m_bits) at time 0
and after every security read, and finds the running_machine m_rand_seed item by value on the LCG orbit
of the constructor seed (machine.cpp: 0x9d14abd7). With debug=True the debugger also logs every security
read/write and every io_w offset-1 write (PIC reset_w line) with PC and totalcycles. Compact results only;
the scratch tree (nvram copy, logs) is removed on success and failure.
"""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,roms

ROOT=Path(__file__).resolve().parents[2]
ORBIT=4096

LUA=r'''
-- mame.cpp re-arms the autoboot timer on every soft reset: later runs only record the regenerated state.
if mk3_pic_dump then mk3_pic_dump("reset") return end
local machine = manager.machine
local pic = assert(machine.devices[":serial_security_sim"])
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
local data, idx, buff, status, bits = bind(pic, "m_data"), bind(pic, "m_idx"), bind(pic, "m_buff"), bind(pic, "m_status"), bind(pic, "m_bits")
assert(data.count == 16 and data.size == 1)
local orbit, s = {}, 0x9d14abd7
for n = 0, ORBIT do orbit[s] = n; s = (1664525 * s + 1013904223) & 0xffffffff end
local seed_items = {}
for i = 0, 100000 do
    local ok, item = pcall(emu.item, i)
    if not ok or item == nil then break end
    local ok2, size, count = pcall(function() return item.size, item.count end)
    if not ok2 or size == nil then break end
    if size == 4 and count == 1 and orbit[item:read(0)] then seed_items[#seed_items + 1] = item end
end
assert(#seed_items == 1, "m_rand_seed item not uniquely found: " .. #seed_items)
local seed = seed_items[1]
local out = assert(io.open("pic.txt", "w"))
local function dump(tag)
    local t = {}
    for i = 0, 15 do t[#t + 1] = string.format("%02X", data:read(i)) end
    out:write(string.format("PIC %s %s %d %d %d %d %d %d\n", tag, table.concat(t), idx:read(0), buff:read(0),
        status:read(0), bits:read(0), orbit[seed:read(0)] or -1, math.floor(machine.time:as_double() * 1e9 + 0.5)))
    out:flush()
end
dump("boot")
mk3_pic_dump = dump
local reset_ns, reset_done = RESET_NS, false
pic_frame = emu.add_machine_frame_notifier(function()
    if reset_ns > 0 and not reset_done and machine.time:as_double() * 1e9 >= reset_ns then reset_done = true; machine:soft_reset() end
end)
pic_tap = machine.devices[":maincpu"].spaces["program"]:install_read_tap(0x01600000, 0x0160001f, "mk3-pic", function(offset, value, mask)
    if machine.debugger and machine.debugger.execution_state ~= "run" then return end
    dump("read")
end)
pic_stop = emu.add_machine_stop_notifier(function() dump("stop"); out:close() end)
'''.replace('ORBIT',str(ORBIT))  # RESET_NS is substituted per capture

DEBUG='''focus :maincpu
wpset 1600000,20,w,1,{printf "MK3_W %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}
wpset 1600000,20,r,1,{printf "MK3_R %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}
wpset 1800000,80000,w,((wpaddr>>4)&7)==1,{printf "MK3_W %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}
go
'''

def parse(text):
    rows=[]
    for line in text.splitlines():
        if not line.startswith('PIC '):continue
        _,tag,data,idx,buff,status,bits,draws,time=line.split()
        rows.append(dict(tag=tag,data=bytes.fromhex(data).hex(),idx=int(idx),buff=int(buff),status=int(status),bits=int(bits),
                         rand_draws=int(draws),ns=int(time)))
    return rows

def capture(seconds=20,debug=True,soft_reset_ns=0):
    """Seeded factory CMOS, default DIPs (SERIAL_DIGIT 6), no inputs; optional Lua soft reset at the first frame after soft_reset_ns."""
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'pic.lua').write_text(LUA.replace('RESET_NS',str(int(soft_reset_ns))),encoding='ascii')
        args=[reference.CORE,'mk3','-rompath',ROOT/'roms','-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
              '-video','none','-sound','none','-nothrottle','-autoboot_delay','0','-autoboot_script','pic.lua',
              '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)]
        if debug:
            (temp/'pic.cmd').write_text(DEBUG,encoding='ascii')
            args+=['-debug','-debugger','windows','-debuglog','-debugscript','pic.cmd']
        run=q.command(args,temp,cwd=temp,timeout=900)
        if not run['passed']:raise RuntimeError('Reference run failed: '+run.get('stdout','')[-1000:])
        pic=parse((temp/'pic.txt').read_text('ascii')) if (temp/'pic.txt').is_file() else []
        bus=[]
        if debug:
            log=temp/'debug.log'
            if not log.is_file() or log.stat().st_size>64*1024*1024:raise ValueError('Missing or oversized debugger log')
            _,bus=reference.parse(log.read_text('utf-8'))
    if cleanup['exists_after']:raise ValueError('Reference scratch retained')
    if not pic or pic[0]['tag']!='boot' or pic[-1]['tag']!='stop':raise ValueError('Incomplete PIC observation')
    return dict(core_sha256=reference.CORE_SHA,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED),
                debug=debug,seconds=seconds,soft_reset_ns=soft_reset_ns,wall_seconds=run['wall_seconds'],pic=pic,bus=bus,cleanup=cleanup)

if __name__=='__main__':
    result=capture(int(sys.argv[1]) if len(sys.argv)>1 else 20,debug='--nodebug' not in sys.argv,soft_reset_ns=1e9 if '--reset' in sys.argv else 0)
    print(json.dumps(dict(result,pic=[r for r in result['pic'] if r['tag']!='read' or r['idx'] in (0,1,16)],reads=len(result['pic']),bus=[r for r in result['bus'] if r[2]!=0x01600000 or r[4]>3e6][:60],bus_rows=len(result['bus'])),indent=None))
