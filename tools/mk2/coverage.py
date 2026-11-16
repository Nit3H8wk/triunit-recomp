"""Authenticated interval accounting and on-demand ROM -> AOT source provenance.

Candidate instruction bytes are not a proven code/data partition. No runtime
execution or equivalence is inferred from this static inventory.
"""
from collections import Counter,defaultdict
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk2 import generate_video_irq as emitter,run,package_native
from tools.mk2.offline_decode import decode
from tools.quality import run as q

ROOT=emitter.ROOT
FORMAT='MK2_ROM_CPP_COVERAGE_V1'
CASE=re.compile(r'^case 0x([0-9a-f]{8})u?: \{ // ([^\n]*)\n(.*?)^\}',re.M|re.S)
DCS_EXTERNAL = {'early': (0x800, 0x200), 'late': (0x2000, 0x300)}


def partition(size,spans):
    """Return [start,length,bitmask] runs, including every unknown byte once."""
    if type(size)is not int or size<=0:raise ValueError('Invalid region size')
    events=defaultdict(Counter)
    for start,end,label in spans:
        if not 0<=start<end<=size or label not in (1,2,4,8,16,32,64):
            raise ValueError('Invalid byte interval')
        events[start][label]+=1;events[end][label]-=1
    events[0];events[size];active=Counter();result=[];previous=0;mask=0
    for at,changes in sorted(events.items()):
        if at>previous:
            if result and result[-1][2]==mask:result[-1][1]+=at-previous
            else:result.append([previous,at-previous,mask])
        active.update(changes);mask=sum(label for label,count in active.items()if count>0)
        previous=at
    if sum(length for _,length,_ in result)!=size or any(active.values()):
        raise ValueError('Incomplete interval accounting')
    return result


def physical_slices(rom,start,length):
    """Map a loaded-region interval back to physical [begin,end) lane offsets."""
    if start<0 or length<=0:raise ValueError('Invalid loaded interval')
    stride=rom['stride_bytes'];size=rom['size']
    if stride<=0 or size<=0:raise ValueError('Invalid ROM mapping')
    result=[]
    for base in (rom['offset_bytes'],*rom.get('reload_offsets_bytes',[])):
        first=max(0,(start-base+stride-1)//stride)
        after=min(size,(start+length-base+stride-1)//stride)
        if first<after:result.append((first,after,base))
    return result


def program_lanes(roms):
    lanes = sorted((rom for rom in roms if rom['region'] == 'maincpu'), key=lambda rom: rom['offset_bytes'])
    actual = [(rom['path'], rom['offset_bytes'], rom['stride_bytes'], rom['size'],
               tuple(rom.get('reload_offsets_bytes', ()))) for rom in lanes]
    expected = [(name, offset, 2, emitter.PROGRAM_LANE_BYTES, ()) for offset, name in enumerate(emitter.PROGRAM_LANES)]
    if actual != expected:
        raise ValueError('Program ROM lane mapping differs from authenticated loader')
    return lanes


def physical_inventory(roms, loaded_spans, physical_spans):
    """Partition each physical ROM once, retaining overlaps across reload aliases."""
    names = {rom['path'] for rom in roms}
    if not names or len(names) != len(roms) or physical_spans.keys() - names:
        raise ValueError('Invalid physical inventory ROM set')
    regions = defaultdict(list)
    for rom in roms:
        regions[rom['region']].append(rom)
    mapped = {name: list(physical_spans.get(name, ())) for name in names}
    for region, spans in loaded_spans.items():
        if region not in regions:
            raise ValueError('Unknown loaded inventory region: ' + region)
        for start, end, label in spans:
            projected = 0
            for rom in regions[region]:
                for first, after, _ in physical_slices(rom, start, end-start):
                    mapped[rom['path']].append((first, after, label))
                    projected += after-first
            if projected != end-start:
                raise ValueError(f'Loaded inventory interval outside unambiguous {region} mapping')
    result = {}
    for rom in roms:
        name = rom['path']
        intervals = partition(rom['size'], mapped[name])
        nature, maturity = Counter(), Counter()
        for _, length, mask in intervals:
            nature[('unknown', 'code_evidence', 'data', 'mixed')[mask & 3]] += length
            maturity[str(mask >> 3)] += length
        result[name] = {
            **rom, 'nature': dict(nature), 'maturity_by_mask': dict(maturity),
            'interval_runs': len(intervals),
            'interval_sha256': hashlib.sha256(json.dumps(intervals, separators=(',', ':')).encode('ascii')).hexdigest(),
        }
    return {
        'physical_bytes': sum(rom['size'] for rom in roms), 'roms': result,
        'interval_encoding': 'Compact ASCII JSON rows [physical_offset,length,mask]',
        'interval_mask_bits': {'1': 'static code evidence', '2': 'identified data', '4': 'ambiguous candidate',
                               '8': 'decoded instruction', '16': 'generated', '32': 'guarded body', '64': 'explicit stop'},
        'maturity_mask_bits': {'1': 'decoded instruction', '2': 'generated', '4': 'guarded body', '8': 'explicit stop'},
    }


def blocks(source):
    result=[];seen=set();line=1;previous=0
    for match in CASE.finditer(source):
        pc=int(match[1],16)
        if pc in seen:raise ValueError('Duplicate static PC')
        seen.add(pc);line+=source.count('\n',previous,match.start());previous=match.start()
        body=match[3].strip()
        literal=re.match(r'if\((true|false)\) \{ (.*?) \} else \{ (.*?) \}',body,re.S)
        if literal:body=literal[2]if literal[1]=='true'else literal[3]
        kind='explicit_stop'if body.startswith('throw std::runtime_error(')else'partial'if re.search(r'\bthrow\s+std::runtime_error\(',body)else'generated'
        result.append((pc,line,match[2],kind))
    return result


def dsp_physical_offset(data, image, pc):
    if image == 'boot':
        return (0x1c if pc == 4 else pc)*4 if 0 <= pc < (data[3]+1)*8 else None
    if image == 'low':
        return 0x1000+pc*4 if 0 <= pc < (data[0x1003]+1)*8 else None
    base, count = DCS_EXTERNAL[image]
    if 0x800 <= pc < 0x800+count:
        return base+(pc-0x800)*4
    return None


def dsp_entries(source,data):
    """Preserve distinct boot/early/late U2 images, including slot4 relocation."""
    for line,text in enumerate(source.splitlines(),1):
        match=re.match(r'case 0x([0-9a-f]+): (.*)',text)
        if not match:continue
        key=int(match[1],16);pc=key&0xffff
        if key<0x10000:
            images=('boot',)
        elif pc<0x400:images=('low',)
        elif 0x800<=pc<0x1000:images=DCS_EXTERNAL
        else:raise ValueError('Unknown DSP mapping')
        guards={int(word,16)for word in re.findall(r'CheckOpcode\(0x([0-9a-f]{6})\)',match[2])}
        found=set()
        for image in images:
            offset = dsp_physical_offset(data, image, pc)
            if offset is None:
                continue
            word=int.from_bytes(data[offset:offset+3],'big')
            if offset+3<=len(data) and word in guards:
                found.add(word);yield pc,image,offset,line,word
        if found!=guards:raise ValueError(f'DSP guard lacks source provenance at {pc:04x}')


def audit(rom_directory):
    started=time.perf_counter();manifest=run.read_manifest()
    verified=run.verify_roms(rom_directory,manifest)
    lanes=program_lanes(manifest['roms'])
    rom=emitter.load_program(rom_directory)
    source_paths=sorted((ROOT/'native/mk2').glob('*.inc'))
    source_paths=[p for p in source_paths if p.name=='mk2_adsp_boot.inc' or CASE.search(p.read_text(encoding='utf8'))]
    sources={p.relative_to(ROOT).as_posix():q.sha(p)for p in source_paths}
    with q.scratch_tree()as(scratch,dependency_cleanup):
        env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
        runtime=package_native.identities(scratch,env)
    selected={};source_blocks={};canonical=__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir()/'mk2_first_fight.inc'
    # Later canonical entries define counting once; every overlay remains queryable.
    for path in sorted(source_paths,key=lambda p:p==canonical):
        entries=blocks(path.read_text(encoding='utf8'));source_blocks[path]=entries
        for pc,line,asm,kind in entries:selected[pc]=(asm,kind)
    rows,proof=decode(rom,selected)
    spans={entry['path']:[]for entry in manifest['roms']};counts=Counter();opcodes=Counter()
    partial=[]
    for pc,(asm,kind) in selected.items():
        size,_,_,actual=rows[pc]
        if asm!=actual:raise ValueError(f'Comment differs from ROM decoder at {pc:08x}')
        counts[kind]+=1
        if kind!='generated':opcodes[asm.split()[0]]+=1
        if kind=='partial':partial.append({'pc_bits':f'{pc:08x}','asm':asm,'gap':'reachable arm may reject; generated text is not complete native coverage'})
        offset=(pc-0xff800000)//8
        for entry in lanes:
            spans[entry['path']].extend((a,b,{'generated':1,'explicit_stop':2,'partial':16}[kind])for a,b,_ in physical_slices(entry,offset,size//8))
    dsp_path=__import__('tools.setup.mk2',fromlist=['inc_dir']).inc_dir()/'mk2_adsp_boot.inc';u2=(rom_directory/'su2.l1').read_bytes()
    dsp=list(dsp_entries(dsp_path.read_text(encoding='utf8'),u2))
    spans['su2.l1'].extend((offset,offset+3,4)for _,_,offset,_,_ in dsp)
    physical=[]
    for entry in manifest['roms']:
        if entry['region']=='video':spans[entry['path']].append((0,entry['size'],8))
        intervals=partition(entry['size'],spans[entry['path']]);totals=Counter()
        for _,length,mask in intervals:totals[str(mask)]+=length
        physical.append({**entry,'interval_columns':['offset_bytes','length_bytes','mask'],
                         'intervals':intervals,'byte_counts':dict(totals)})
    if sources!={p.relative_to(ROOT).as_posix():q.sha(p)for p in source_paths}:
        raise ValueError('Source changed during audit')
    if verified!=run.verify_roms(rom_directory,manifest):raise ValueError('ROM changed during audit')
    return {'format':FORMAT,'scope':'Static candidate intervals and physical byte accounting; no gameplay or hardware equivalence certified.',
            'program_sha256':hashlib.sha256(rom).hexdigest(),'manifest_sha256':q.sha(run.MANIFEST),
            'decoder_sha256':emitter.DECODER_SHA256,'sources':sources,'rom_directory':str(rom_directory.resolve()),
            'compiler_dependencies':runtime,'dependency_cleanup':dependency_cleanup,
            'overlays_in_product_sources':{name:name in runtime['files']for name in sources},
            'mask_bits':{'1':'generated TMS candidate','2':'explicit-stop TMS candidate','4':'guarded DSP image bytes','8':'video asset data','16':'partially generated TMS candidate with reachable guard'},
            'unknown_mask':0,'overlap_policy':'bitwise union; candidates do not establish executable code; physical reload aliases count once',
            'case_counts':dict(counts),'partial_sites':partial,'stop_opcodes':dict(opcodes),'dsp_image_entries':len(dsp),
            'physical_roms':physical,'decoder_proof':proof,'elapsed_seconds':round(time.perf_counter()-started,3),
            'remaining':['code/data ambiguities','indirect target closure','writable executable images','CPP without PC-labelled case blocks','dispatcher precedence and executed artifact not proved by compiler include dependencies','full runtime certification']}


def lookup(report,*,region,bank,address):
    if report.get('format')!=FORMAT:raise ValueError('Invalid coverage format')
    if (region,bank)!=('maincpu','program') and not(region=='dcs' and bank in ('boot','low','early','late')):
        raise ValueError('Unknown region/bank')
    for name,digest in report['sources'].items():
        if q.sha(ROOT/name)!=digest:raise ValueError('Source changed: '+name)
    if q.sha(run.MANIFEST)!=report['manifest_sha256']:raise ValueError('Manifest changed')
    for name,digest in report['compiler_dependencies']['files'].items():
        if q.sha(ROOT/name)!=digest:raise ValueError('Runtime source changed: '+name)
    directory=Path(report['rom_directory']);run.verify_roms(directory)
    result=[]
    if region=='maincpu':
        if address&15 or not 0xff800000<=address<=0xfffffff0:raise ValueError('Invalid bit PC')
        rows,_=decode(emitter.load_program(directory),[address]);size,_,words,asm=rows[address]
        offset=(address-0xff800000)//8
        physical=[{'path':entry['path'],'begin':a,'end':b,'loaded_base':base,'stride':entry['stride_bytes']}
                  for entry in program_lanes(report['physical_roms'])
                  for a,b,base in physical_slices(entry,offset,size//8)]
        for name in report['sources']:
            for pc,line,_,kind in blocks((ROOT/name).read_text(encoding='utf8')):
                if pc==address:result.append({'pc_bits':pc,'asm':asm,'words':words,'bits':size,'physical':physical,'cpp':name,'line':line,'maturity':kind,'runtime_verified':False})
    else:
        data=(directory/'su2.l1').read_bytes();name='native/mk2/mk2_adsp_boot.inc'
        for pc,image,offset,line,word in dsp_entries((ROOT/name).read_text(encoding='utf8'),data):
            if pc==address and image==bank:result.append({'pc_words':pc,'image':image,'physical':[{'path':'su2.l1','begin':offset,'end':offset+3}],'word':word,'cpp':name,'line':line,'maturity':'generated','runtime_verified':False})
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--rom-directory',type=Path,default=ROOT/'roms/mk2');parser.add_argument('--region');parser.add_argument('--bank');parser.add_argument('--address',type=lambda value:int(value,0))
    args=parser.parse_args()
    if args.address is not None:
        print(json.dumps(lookup(json.loads(args.report.read_text()),region=args.region,bank=args.bank,address=args.address),indent=2));return
    if args.report.exists():parser.error('Preserve existing report; choose a new path')
    result=audit(args.rom_directory);args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,separators=(',',':'))+'\n')
    print(json.dumps({k:v for k,v in result.items()if k not in ('sources','physical_roms')},indent=2))


if __name__=='__main__':main()
