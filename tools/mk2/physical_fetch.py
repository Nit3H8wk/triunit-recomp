"""Authenticate every physical fetch/data lane and consume typed suffix IRQ notes."""
from itertools import groupby,zip_longest
from tools.mk2.batch_reference import external_irq_bracket

def branch_taken(op,status):
 n,c,z,v=(bool(status&(1<<bit)) for bit in (31,30,29,28))
 conditions={'JR':True,'JA':True,'JREQ':z,'JAEQ':z,'JRNE':not z,'JANE':not z,
  'JRLT':n!=v,'JRGE':n==v,'JRLE':n!=v or z,'JRGT':n==v and not z,
  'JRC':c,'JAC':c,'JRNC':not c,'JANC':not c,'JRHI':not c and not z,
  'JRLS':c or z,'JRP':not n and not z,'JRN':n,'JRNN':not n,'JRV':v,'JRNV':not v}
 if op not in conditions:raise ValueError('Unqualified conditional fetch')
 return conditions[op]

def partition(rows,cpu,end,decoded,opcode,annotations):
 notes={};last_index=-1
 for note in annotations:
  if (not isinstance(note,(list,tuple)) or len(note)!=3 or any(type(x) is not int for x in note) or
      not last_index<note[0]<len(cpu) or note[1]&15 or note[2]!=0):
   raise ValueError('Invalid or duplicate typed INT1 annotation')
  notes[note[0]]=tuple(note);last_index=note[0]
 data=[];counts={'physical':0,'fetch':0,'data':0,'irq':0}
 groups=groupby(rows,key=lambda row:(row[5],row[3]))
 for index,(state,group) in enumerate(zip_longest(cpu,groups)):
  if state is None or group is None:raise ValueError('Missing or interleaved physical CPU group')
  key,iterator=group;lanes=list(iterator);pc,status,cycle=state[:3]
  if key!=(pc,cycle) or (index and cycle<=cpu[index-1][2]):raise ValueError('Physical CPU group order differs')
  if any(len(x)!=7 or any(type(n) is not int for n in x[:6]) or type(x[6]) is not bool or
         not 0<=x[2]<=0xffff or x[4]!=16 for x in lanes):raise ValueError('Invalid physical word lane')
  bits,flags,words,asm=decoded[pc];op=asm.split()[0]
  if bits not in (16,32,48,80) or len(words)*16!=bits or any(opcode(pc+n*16)!=w for n,w in enumerate(words)):
   raise ValueError('Unauthenticated decoded words/width')
  after=cpu[index+1] if index+1<len(cpu) else end
  irq=[];post=after
  if index in notes:
   post=external_irq_bracket(state,after,lanes,notes.pop(index));irq=lanes[-6:];lanes=lanes[:-6]
  elif after[0]==0xff8045d0 and op!='TRAP':
   raise ValueError('External INT1 requires explicit annotation')
  elif after[0]==0xff816370:
   if after[1]!=0x10 or after[2]<=cycle+16 or len(lanes)<6:raise ValueError('Invalid display IRQ bracket')
   irq=lanes[-6:];sp=after[18]
   return_pc=irq[0][2]|irq[1][2]<<16;saved=irq[2][2]|irq[3][2]<<16
   expected=[(return_pc,address,value,cycle,16,pc,write) for address,value,write in
     ((sp+32,return_pc&0xffff,True),(sp+48,return_pc>>16,True),
      (sp,saved&0xffff,True),(sp+16,saved>>16,True),
      (0xfffffea0,opcode(0xfffffea0),False),(0xfffffeb0,opcode(0xfffffeb0),False))]
   if (not saved&0x00200000 or sp&15 or not 0x01000000<=sp<=0x013fffc0 or
       return_pc&15 or [tuple(x) for x in irq]!=expected):raise ValueError('Display IRQ physical entry differs')
   post=list(after);post[:3]=return_pc,saved,after[2]-16;post[18]+=64;lanes=lanes[:-6]
  no_increment=op in ('CALLR','CALLA','DSJ','DSJEQ','DSJNE') or ((op.startswith('JR') or op.startswith('JA')) and bits>16)
  fetch_bits=bits
  if bits>16 and (op.startswith('JR') or op.startswith('JA')) and not branch_taken(op,status):fetch_bits=16
  if op in ('DSJ','DSJEQ','DSJNE'):
   register=asm.split(None,1)[1].split(',')[0]
   if register=='SP':rindex=18
   else:rindex=3+int(register[1:]) if register[0]=='A' else 19+int(register[1:])
   decrements=op=='DSJ' or (op=='DSJEQ' and bool(status&0x20000000)) or (op=='DSJNE' and not status&0x20000000)
   if post[rindex]!=((state[rindex]-1)&0xffffffff if decrements else state[rindex]):
    raise ValueError('DSJ counter does not match original conditional decrement')
   if not decrements or state[rindex]==1:fetch_bits=16
  if fetch_bits<bits and (post[0]!=pc+bits or post[1]!=status or post[2]!=cycle+(4 if bits==48 else 2)):
   raise ValueError('Skipped parameter lacks original fallthrough/cost bracket')
  expected_fetch=list(range(0,fetch_bits,16))
  args=asm.split(None,1)[1].split(',') if ' ' in asm else []
  two_offsets=op=='MOVE' and bits==48 and len(args)>1 and '(' in args[0] and '(' in args[1]
  for lane in lanes:
   callback,address,value,ticks,size,source,write=lane;delta=(callback-pc)&0xffffffff
   if not write and pc<=address<pc+bits:
    offset=address-pc
    stage=16 if offset==0 or no_increment else 48 if bits==80 and offset<48 else 32 if two_offsets and offset==16 else bits
    if (not expected_fetch or expected_fetch.pop(0)!=offset or delta!=stage or value!=opcode(address)):
     raise ValueError('Unauthenticated or unordered instruction fetch')
    counts['fetch']+=1
   else:
    stage=16 if no_increment else 48 if bits==80 and not write else bits
    if delta!=stage:raise ValueError('Ordinary data fetched PC stage differs')
    data.append([119 if write else 114,source,address,value,ticks,size])
  if expected_fetch:raise ValueError('Missing original instruction fetch')
  data.extend([119 if x[6] else 114,x[5],x[1],x[2],x[3],x[4]] for x in irq)
  counts['physical']+=len(lanes)+len(irq);counts['irq']+=len(irq)
 if notes:raise ValueError('Unconsumed typed IRQ annotations')
 counts['data']=len(data)
 return data,counts
