"""MK3 replay checkpoint records: parsing of the native runner and Original observations, and their comparison.

A checkpoint is the first TMS instruction boundary at a cycle >= C with ST.P clear (a PIXBLT restart re-entry is not
a boundary). Natively: mk3::Board::stop, called before every instruction with Board::Cycles() (the instruction start);
in the Original: a debugger registerpoint `totalcycles>=C&&(st&0x2000000)==0`, evaluated by the instruction hook before
every instruction. Both see the state after the timeslice-start interrupt check and with the ADSP as of the end of the
previous timeslice (the scheduler contract of native/mk3/mk3_board.hpp; tools/mk3/test_cosim.py compares the same
boundaries). Several C due at one boundary give one record (both sides advance C past the boundary).

Per record: PC, ST, totalcycles, the 31 registers; main RAM, CMOS, palette, video RAM, ADSP DM and PM (mapped ranges
of native/tests/mk3_cosim_tests.cpp) as FNV-1a 64 hashes of every word; the 18 DMA registers, the 32 TMS I/O registers
and the midwunit control latch in full; the ADSP debugger symbols (tools/mk3/test_adsp.py masks) and the DAC samples
stored since the previous record (count and hash). A hash establishes equality of that region only up to collision;
replay.py compares whole regions byte by byte at the records the bisection brackets (dump) and at END.
"""
import json

REGIONS=('ram','cmos','palette','vram','dm','pm')
# Event streams (native/tests/mk3_replay_main.cpp `events`, tools/mk3/replay_reference.py events=True): per record the
# count and running FNV-1a 64 (address, value, cycle low, cycle high per event; cycle = instruction start) of the events
# since reset; the whole dcs ([cycle, value]), input ([cycle, port, value]) and cmos ([cycle, address, value]) streams at END.
STREAMS=('dcs','dma','input','cmos')
FULL_STREAMS=('dcs','input','cmos')
REGION_BYTES=dict(ram=0x80000,cmos=0xc000,palette=0x10000,vram=0x100000,dm=2*(0x3000+0x200),pm=4*(0x400+0x1800))
FNV_BASIS,FNV_PRIME,MASK=0xcbf29ce484222325,0x100000001b3,(1<<64)-1


def fnv(values,h=FNV_BASIS):
    for v in values:h=((h^v)*FNV_PRIME)&MASK
    return h


def parse_native(text):
    """Native runner stdout: header (ADSP field names), records, dumps, summary and window."""
    out=dict(records=[],dumps={},summary=None,window=None,fields=None)
    for line in text.splitlines():
        if not line.startswith('{'):continue
        row=json.loads(line)
        if 'fields' in row and 'spec' not in row:out['fields']=row['fields']
        elif 'dump' in row:out['dumps'][(row['dump'],row['spec'])]=bytes.fromhex(row['hex'])
        elif 'frontier' in row:out['summary']=row
        elif 'events_total' in row:out['events']=row
        elif 'window' in row:out['window']=row
        else:out['records'].append(row)
    if out['fields'] is None or out['summary'] is None or not out['records'] or out['records'][-1]['spec']!='end':
        raise ValueError('Incomplete native replay output')
    return out


def difference(n,r,fields,masks,ignore=()):
    """First difference between a native and an Original record (same spec), as (region, detail), or None.
    ignore: regions left out (negative controls set aside an open divergence class this way, explicitly)."""
    for key in ('cycle','pc','status','registers'):
        if n[key]!=r[key]:return 'cpu',f'{key}: native {n[key]} reference {r[key]}'
    for name in REGIONS:
        if name in ignore:continue
        if n['hash'][name]!=r['hash'][name]:return name,f'{name} hash: native {n["hash"][name]} reference {r["hash"][name]}'
    for key in ('dma','io','control'):
        if key not in ignore and n[key]!=r[key]:
            if isinstance(n[key],list):
                k=next(i for i,(a,b) in enumerate(zip(n[key],r[key])) if a!=b)
                return key,f'{key}[{k}]: native {n[key][k]:#x} reference {r[key][k]:#x}'
            return key,f'{key}: native {n[key]:#x} reference {r[key]:#x}'
    if 'events' in n and 'events' in r:   # both sides observed the streams
        for name in STREAMS:
            if name not in ignore and n['events'][name]!=r['events'][name]:
                return 'events.'+name,f'{name} events since reset: native {n["events"][name]} reference {r["events"][name]}'
    a=n['adsp']
    if not a['frozen'] and 'adsp' not in ignore:
        for name,value,mask in zip(fields,a['fields'],masks):
            if name=='totalcycles':continue   # the debugger's ADSP totalcycles needs an ADSP hook (test_cosim)
            if value&mask!=r['adsp'][name]&mask:return 'adsp',f'adsp {name}: native {value&mask:#x} reference {r["adsp"][name]&mask:#x}'
    return None if 'pcm' in ignore else pcm_difference(n,r)


def pcm_difference(n,r):
    """DAC samples stored since the previous record. The Original's are the DMADAC ring entries from the previous
    m_bufin to the current one; dmadac enable(0) (dcs_reset, DAC stop) restarts m_bufin at 0 without clearing the ring,
    so when that happened in between, the ring holds only the samples stored after it: they must be the last native
    ones (the samples stored before it in the interval are not observable at this record)."""
    samples=bytes.fromhex(n['samples']);values=[int.from_bytes(samples[i:i+2],'little') for i in range(0,len(samples),2)]
    q=r['pcm']
    if len(values)!=n['pcm']['segment']:return 'pcm','native sample segment truncated'
    if len(values)==q['segment'] and f'{fnv(values):x}'==q['hash']:return None
    b=q['since_reset']['segment']
    if b<=len(values) and f'{fnv(values[len(values)-b:]):x}'==q['since_reset']['hash']:return None
    return 'pcm',f'DAC samples since the previous record: native {len(values)} {fnv(values):x} reference {q["segment"]} {q["hash"]} (m_bufin {q["bufin"]}, since reset {b} {q["since_reset"]["hash"]})'



def first_difference(native,reference,fields,masks,ignore=()):
    """(index, region, detail) of the first differing record pair, or None. Specs must agree one to one."""
    nat,ref=native['records'],reference['records']
    for k,(n,r) in enumerate(zip(nat,ref)):
        if n['spec']!=r['spec']:return k,'schedule',f'record {k}: native spec {n["spec"]} reference {r["spec"]}'
        if (d:=difference(n,r,fields,masks,ignore)):return (k,*d)
    if len(nat)!=len(ref):return min(len(nat),len(ref)),'schedule',f'records: native {len(nat)} reference {len(ref)}'
    return None


def stream_difference(native,reference):
    """Whole streams at the end: totals (count and hash) of all four, events of dcs/input/cmos one by one.
    {name: None | first difference}."""
    out={}
    for name in STREAMS:
        n,r=native['events']['events_total'][name],reference['events']['events_total'][name]
        d=None if n==r else dict(total=dict(native=n,reference=r))
        if name in FULL_STREAMS:
            a,b=native['events']['events_full'][name],reference['events']['events_full'][name]
            if a!=b:
                k=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
                d=dict(d or {},index=k,native=a[k] if k<len(a) else None,reference=b[k] if k<len(b) else None,native_count=len(a),reference_count=len(b))
        out[name]=d
    return out


def byte_difference(a,b):
    """First differing byte offset of two whole regions, or None."""
    if a==b:return None
    k=next((i for i,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
    return dict(offset=k,native=a[k:k+8].hex(),reference=b[k:k+8].hex(),native_bytes=len(a),reference_bytes=len(b))
