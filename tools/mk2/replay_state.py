"""Complete terminal DSP registers/memories/device fields for legal replays."""
import hashlib
import re
import struct
from tools.mk2 import batch_reference,reference

BOARD_FILES={'cmos.bin':16384,'ram.bin':524288,'palette.bin':65536,'vram.bin':1048576,
             'io.bin':56,'dma.bin':36,'shiftreg.bin':8192,'display.bin':4}
FILES={'dsp-registers.bin':76*8,'dsp-pm.bin':1024*4,'dsp-dm.bin':512*2,
       'dsp-external-pm.bin':2048*4,'dsp-external-dm.bin':2048*2,
       'dsp-control.bin':32*2,'dsp-control-raw.bin':32*2,'dsp-device.bin':17*8,
       'dsp-irq1.bin':2,'dcs-latches.bin':6,'dsp-stack.bin':27*4,'dsp-dac-ring.bin':32768*4}


def compare_state(native,original):
    result={}
    for name,size in FILES.items():
        a=(native/name).read_bytes()if(native/name).is_file()else b''
        b=(original/name).read_bytes()if(original/name).is_file()else b''
        first=next((n for n,(x,y)in enumerate(zip(a,b))if x!=y),None)
        if first is None and len(a)!=len(b):first=min(len(a),len(b))
        result[name]={'passed':len(a)==len(b)==size and a==b,'expected_bytes':size,
                      'native_bytes':len(a),'original_bytes':len(b),'first_offset':first,
                      'native_sha256':hashlib.sha256(a).hexdigest(),'original_sha256':hashlib.sha256(b).hexdigest()}
    return {'passed':all(row['passed']for row in result.values()),'files':result,
            'scope':'Terminal DSP76, complete PM/DM, raw and mapped control, 17 DCS device fields, active stack slots, IRQ1, latches and the full DAC ring.',
            'remaining':'Inactive stack slots, pending DCS pre-output, scheduler deadlines and full ordered intermediate bus/IRQ events require their own proofs.'}


def dsp_snapshot(text):
    rows=[line.split()[1:]for line in text.splitlines()if line.startswith('DSP_STATE ')]
    if len(rows)!=1 or len(rows[0])!=len(batch_reference.DSP_SYMBOLS):
        raise ValueError('Incomplete or duplicate terminal DSP snapshot')
    if any(not re.fullmatch('[0-9a-fA-F]{1,16}',v)for v in rows[0]):raise ValueError('Invalid DSP symbol')
    values=[int(v,16)&(0x3fff if re.fullmatch('m[0-7]',name)else 0xffffffffffffffff)
            for name,v in zip(reference.DSP_REGISTERS,rows[0])]
    return {'registers':values,'irq1':int(rows[0][76],16),'curpc':int(rows[0][77],16)}


def native_source(source):
    marker='            words("dma.bin",current.State().video.DmaRegisters(s.board));'
    assert source.count(marker)==1
    return source.replace(marker,marker+r'''
            words("shiftreg.bin",current.State().video.shift_register);
            words("display.bin",std::array<uint16_t,2>{s.board.vcount,s.board.display_address});
            const auto wide=[&](const char* name,const auto& values) {
                std::ofstream file(output/name,std::ios::binary);
                for(const auto value:values)for(unsigned n=0;n<sizeof(value);++n)file.put(char(value>>(n*8)));
                file.close();if(!file)throw std::runtime_error("Terminal DSP capture failed");
            };
            wide("dsp-registers.bin",machine->dsp.Registers());
            wide("dsp-stack.bin",machine->dsp.ActiveStacks());
            wide("dsp-dac-ring.bin",machine->dsp.DacBuffer(32768));
            wide("dsp-pm.bin",machine->dsp.pm);wide("dsp-dm.bin",machine->dsp.dm);
            wide("dsp-external-pm.bin",machine->dsp.external_pm);wide("dsp-control-raw.bin",machine->dsp.control);
            std::vector<uint16_t> mapped_control;
            for(unsigned n=0;n<32;++n)mapped_control.push_back(machine->dsp.ReadControl(uint16_t(0x3fe0+n)));
            wide("dsp-control.bin",mapped_control);
            wide("dsp-device.bin",machine->dsp.DeviceState());
            wide("dsp-irq1.bin",std::array<uint8_t,2>{uint8_t(machine->dsp.sport_irq1_asserted),uint8_t(machine->dsp.sport_irq1_latched)});
            const auto latches=machine->link.ExecutionState();
            wide("dcs-latches.bin",std::array<uint16_t,3>{uint16_t(latches.at(0)),uint16_t(latches.at(1)),uint16_t(latches.at(2))});
            std::vector<uint16_t> external_dm;
            for(auto value:machine->dsp.external_pm)external_dm.push_back(uint16_t(value>>8));
            wide("dsp-external-dm.bin",external_dm);
''')


def original_command(command):
    marker=';quit}'
    assert command.count(marker)==1
    commands=';do :maincpu.pb@01ffffc0;save dsp-pm.bin,0:dcs:dcs,400;saved dsp-dm.bin,3800:dcs:dcs,200;saved dsp-control.bin,3fe0:dcs:dcs,20;save dsp-external-pm.bin,800:dcs:dcs,800;saved dsp-external-dm.bin,0:dcs:dcs,800'
    return command.replace(marker,commands+marker)


def original_lua(lua):
    marker=' dump("vram.bin",bind(video,"m_local_videoram"),524288);'
    assert lua.count(marker)==1
    fields=','.join('"'+name+'"'for name in reference.DCS_DEVICE_FIELDS)
    extra='''
 local device=assert(m.devices[":dcs"]);local dac=assert(m.devices[":dcs:dac"])
 local dsp=assert(m.devices[":dcs:dcs"])
 local stacks=assert(io.open("dsp-stack.bin","wb"))
 for _,layout in ipairs({{"pc",16,16,1},{"cntr",4,4,1},{"loop",4,4,1},{"stat",4,1,3}})do
  local name,capacity,represented,width=table.unpack(layout)
  local count=assert(bind(dsp,"m_"..name.."_sp"):read(0))
  local item=bind(dsp,"m_"..name.."_stack")
  assert(item.count==capacity*width and count<=represented and count>=0)
  for n=0,represented*width-1 do
   local value=n<count*width and assert(item:read(n)) or 0
   assert(stacks:write(string.pack("<I4",value)))
  end
 end
 assert(stacks:close())
 local ring=bind(dac,"m_buffer")
 assert(ring.count==32768)
 local ring_file=assert(io.open("dsp-dac-ring.bin","wb"))
 for n=0,ring.count-1 do
  assert(ring_file:write(string.pack("<I4",assert(ring:read(n))&0xffffffff)))
 end
 assert(ring_file:close())
 local irq=assert(io.open("dsp-irq1.bin","wb"));assert(irq:write(string.pack("<I1I1",bind(dsp,"m_irq_state"):read(1),bind(dsp,"m_irq_latch"):read(1))));assert(irq:close())
 local latches=assert(io.open("dcs-latches.bin","wb"))
 for _,name in ipairs({"m_latch_control","m_input_data","m_output_data"})do assert(latches:write(string.pack("<I2",bind(device,name):read(0))))end;assert(latches:close())
 dump("dsp-control-raw.bin",bind(device,"m_control_regs"),32)
 local cycles=bind(assert(m.devices[":dcs:dcs"]),"m_totalcycles")
 local clock=assert(io.open("dsp-execute-cycles.bin","wb"));assert(clock:write(string.pack("<I8",assert(cycles:read(0)))));assert(clock:close())
 local fields={FIELDS};local file=assert(io.open("dsp-device.bin","wb"))
 for n,name in ipairs(fields)do
  local item=bind(n<=14 and device or dac,"m_"..(n<=14 and name or ({"enabled","bufin","bufout"})[n-14]))
  assert(item.count==1);assert(file:write(string.pack("<I8",assert(item:read(0)))))
 end
 assert(file:close())
'''.replace('FIELDS',fields)
    return lua.replace(marker,extra+marker)+batch_reference.compact_dsp_lua()


def save_dsp_snapshot(directory):
    observed=dsp_snapshot((directory/'debug.log').read_text());values=observed['registers']
    clock=(directory/'dsp-execute-cycles.bin').read_bytes()
    if len(clock)!=8:raise ValueError('Incomplete DSP executor cycle observation')
    cached=values[1];values[1]=struct.unpack('<Q',clock)[0]
    (directory/'dsp-registers.bin').write_bytes(struct.pack('<76Q',*values))
    return {'debugger_cached_cycles':cached,'executor_cycles':values[1],
            'debugger_irq1':observed['irq1'],'debugger_curpc':observed['curpc']}
