"""Compact original-MAME CPU boundaries for operator settings; no guest state writes."""
from pathlib import Path
import json
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2 import batch_reference, native, run, reference
from tools.quality import run as quality


def capture(image, dsw=0xfc7d,draw_setup=None,trace_start_pc=0xff80dd30,trace_stop_pc=None):
    if len(image)!=16384 or dsw & ~0xc000 != 0x3c7d:
        raise ValueError('Only original MK2 blood/violence DIP variations are selected')
    if quality.sha(batch_reference.MAME)!=batch_reference.MAME_SHA:
        raise ValueError('Original MAME executable identity differs')
    directory=quality.ROOT/'roms/mk2'
    run.verify_roms(directory)
    with quality.scratch_tree() as (scratch,cleanup):
        native.prepare_reference_roms(directory,scratch/'mk2',run.read_manifest())
        nvram=scratch/'nvram/mk2';nvram.mkdir(parents=True)
        (nvram/'nvram').write_bytes(image)
        cfg=scratch/'cfg';cfg.mkdir()
        fields=''.join(f'<port tag=":DSW" type="DIPSWITCH" mask="{mask}" defvalue="{mask}" value="{dsw & mask}" />' for mask in (0x4000,0x8000))
        (cfg/'mk2.cfg').write_text('<?xml version="1.0"?><mameconfig version="10"><system name="mk2"><input>'+fields+'</input></system></mameconfig>',encoding='ascii')
        registers=[f'a{n}' for n in range(15)]+['sp']+[f'b{n}' for n in range(15)]
        fmt='OPERATOR '+' '.join(['%X']*35)+'\\n'
        script='focus :maincpu\nobserve :dcs:dcs\n'
        points=[(pc,'1','g') for pc in (0xffa5a6e0,0xffa5b090,0xff811340,0xff815090,0xff8114d0,0xff811710,0xff8044f0,0xff804630)]
        points.append((0xff816370,'totalcycles>689500&&totalcycles<689d00','g'))
        draw_condition='totalcycles>6e0000&&a0==1&&a1==106b870&&a8==ffaf3020'
        points.extend([(0xff80dd30,'totalcycles<=6e0000||a0!=1||a1!=106b870||a8!=ffaf3020','g'),(0xff80dd30,draw_condition,'quit')])
        if draw_setup is not None:
            points=[(pc,(condition+f'&&totalcycles!={draw_setup:x}') if pc==trace_start_pc else condition,action) for pc,condition,action in points]
            script+=f'bpset {trace_start_pc:x},totalcycles=={draw_setup:x},{{trace draw.trace,:maincpu,noloop;g}}\n'
        for number,(pc,condition,action) in enumerate(points,1):
            if pc!=0xff80dd30:action=f'bpdisable {number+(draw_setup is not None):x};'+action
            if (action=='quit' or pc==trace_stop_pc) and draw_setup is not None:action='trace off;'+action
            expressions=['pc','st','totalcycles',*registers]
            if pc==0xff816370:
                # CPU34 is reconstructed before IRQ entry using the original stack.
                # This row's DSP76 remains the observed IRQ-entry-time state; no
                # pre-IRQ DSP boundary is inferred from it or used by the runtime.
                expressions[0:3]=['d@(sp+20)','d@sp','totalcycles-10']
                expressions[18]='sp+40'
            script+=f'bpset {pc:x},{condition},{{printf "{fmt}",'+','.join(expressions)+',w@1600030;symlist :dcs:dcs;'+action+'}\n'
        script+='go\n'
        (scratch/'operator.cmd').write_text(script,encoding='ascii')
        lua='''local machine=manager.machine
local last_packet=0
local dsp=machine.devices[":dcs:dcs"]
local tap=dsp.spaces["data"]:install_read_tap(0x400,0x5df,"operator-sport",function(offset,data)
 if machine.debugger.execution_state~="run" or (offset~=0x400 and offset~=0x4f0) then return end
 local pc=dsp.state["PC"].value
 if pc>=0x130 and pc<=0x138 and machine.time:as_double()>0.07 then
  last_packet=math.floor(machine.time:as_double()*100000000+0.5)
 end
end)
operator_stop=emu.add_machine_stop_notifier(function()
 print("OPERATOR_SPORT "..tostring(last_packet+768000));tap:remove()
end)
'''
        (scratch/'operator.lua').write_text(lua,encoding='ascii')
        args=[batch_reference.MAME,'mk2','-noreadconfig','-nowriteconfig','-rompath',scratch,
              '-video','none','-sound','none','-nothrottle','-skip_gameinfo','-noplugins',
              '-debug','-debugger','windows','-debuglog','-debugscript','operator.cmd',
              '-autoboot_delay','0','-autoboot_script','operator.lua',
              '-nvram_directory',scratch/'nvram','-cfg_directory',cfg,
              '-snapshot_directory',scratch/'snap','-homepath',scratch/'home','-seconds_to_run','2']
        result=quality.command(args,scratch,cwd=scratch,timeout=60)
        if not result['passed']:raise RuntimeError(str(result))
        sport_rows=[int(line.split()[1]) for line in result['stdout'].splitlines() if line.startswith('OPERATOR_SPORT ')]
        if len(sport_rows)!=1 or sport_rows[0]<117000000:raise ValueError('Original SPORT deadline observation incomplete')
        log=scratch/'debug.log'
        if not log.is_file() or log.stat().st_size>65536:raise ValueError('Original boundary log is missing or oversized')
        rows=[];dsp_rows=[];symbols={}
        def finish_dsp():
            if not symbols:return
            dsp_rows.append([symbols[key] & (0x3fff if re.fullmatch(r'm[0-7]',key) else 0xffffffffffffffff) for key in reference.DSP_REGISTERS])
            symbols.clear()
        for line in log.read_text().splitlines():
            if line.startswith('OPERATOR '):
                finish_dsp()
                row=[int(value,16) for value in line.split()[1:]]
                if len(row)!=35 or row[-1]!=dsw:raise ValueError('Original DIP/boundary identity differs: '+str(row))
                rows.append(row)
            elif '=' in line:
                match=re.fullmatch(r'\s*([a-zA-Z0-9_]+)\s*=\s*([0-9a-fA-F]+)(?:  \(read-only\))?\s*',line)
                if match:symbols[match[1].lower()]=int(match[2],16)
        finish_dsp()
        if len(rows)<11 or len(dsp_rows)!=len(rows):raise ValueError('Original boundary sample is incomplete: '+str(rows))
        trace_count=None
        if draw_setup is not None:
            trace=scratch/'draw.trace'
            if not trace.is_file() or trace.stat().st_size>16*1024*1024:raise ValueError('Original instruction trace missing or oversized')
            with trace.open() as stream:trace_count=sum(bool(re.match(r'^[0-9A-Fa-f]{8}:',line)) for line in stream)
            if not trace_count:raise ValueError('Original instruction trace has no complete instruction rows')
    if cleanup['exists_after']:raise ValueError('Operator reference scratch retained')
    return {'cpu34':[row[:-1] for row in rows],'dsp76':dsp_rows,'draw_instructions':trace_count,'sport_deadline':sport_rows[0],'dsw':dsw,'cleanup':cleanup}


if __name__=='__main__':
    from tools.mk2 import profile
    image=profile.FACTORY_SEED.read_bytes()
    print(json.dumps(capture(image,int(sys.argv[1],0) if len(sys.argv)>1 else 0xfc7d)))
