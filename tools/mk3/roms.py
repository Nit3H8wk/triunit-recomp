"""MK3 rev 2.1 ROM identity: driver definition -> authenticated local files, no payload copies."""
from pathlib import Path
import argparse,hashlib,json,re,sys,zlib

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'docs/investigation/sources/midwunit.cpp'
SOURCE_COMMIT='4f9dcc832cc0089de2451696320f671e87da79f4'
MANIFEST=Path(__file__).with_name('roms-21.json')
LOAD=re.compile(r'ROM_LOAD(16|32)_BYTE\(\s*"([^"]+)",\s*0x([0-9a-f]+),\s*0x([0-9a-f]+),\s*CRC\(([0-9a-f]{8})\)\s*SHA1\(([0-9a-f]{40})\)',re.I)
REGION=re.compile(r'ROM_REGION\w*\(\s*0x([0-9a-f]+),\s*"([^"]+)"',re.I)

def digests(data):
    return dict(size=len(data),crc32=f'{zlib.crc32(data)&0xffffffff:08x}',sha1=hashlib.sha1(data).hexdigest(),sha256=hashlib.sha256(data).hexdigest())

def definition(source=SOURCE,machine='mk3'):
    text=source.read_text('utf-8');start=text.index(f'ROM_START( {machine} )');block=text[start:text.index('ROM_END',start)]
    rows,region=[],None
    for line in block.splitlines():
        if m:=REGION.search(line):region=m.group(2);continue
        if m:=LOAD.search(line):
            width,name,offset,size,crc,sha1=m.groups()
            rows.append(dict(path=name,region=region,offset_bytes=int(offset,16),stride_bytes=2 if width=='16' else 4,size=int(size,16),crc32=crc.lower(),sha1=sha1.lower()))
    if not rows:raise ValueError('Empty driver definition')
    return rows

def program_image(directory,rows):
    """TMS34010 program region: ROM_LOAD16_BYTE pair, little-endian words."""
    pair=[r for r in rows if r['region']=='maincpu']
    if len(pair)!=2:raise ValueError('MK3 requires one interleaved program pair')
    image=bytearray(sum(r['size'] for r in pair))
    for r in pair:image[r['offset_bytes']::2]=(Path(directory)/r['path']).read_bytes()
    return bytes(image)

def verify(directory,manifest=None):
    manifest=json.loads(MANIFEST.read_text('utf-8')) if manifest is None else manifest
    directory=Path(directory);rows=[]
    for rom in manifest['roms']:
        name=rom['path']
        if not name or any(c in name for c in '/\\:') or name in ('.','..'):raise ValueError(f'Invalid ROM path: {name}')
        path=directory/name
        if path.is_symlink() or not path.is_file():raise ValueError(f'ROM missing: {name}')
        data=path.read_bytes();observed=digests(data)
        for key in ('size','crc32','sha1','sha256'):
            if observed[key]!=rom[key]:raise ValueError(f'ROM {key} mismatch: {name}')
        rows.append(name)
    if len(rows)!=manifest['rom_count']:raise ValueError('ROM count differs from the revision')
    program=hashlib.sha256(program_image(directory,manifest['roms'])).hexdigest()
    if program!=manifest['program_sha256']:raise ValueError('Program image differs from the revision')
    return dict(verified=len(rows),program_sha256=program,reset_vector=manifest['reset_vector'])

def generate(directory=ROOT/'roms/mk3'):
    rows=definition()
    for row in rows:
        observed=digests((Path(directory)/row['path']).read_bytes())
        for key in ('size','crc32','sha1'):
            if observed[key]!=row[key]:raise ValueError(f'Local ROM differs from driver {key}: {row["path"]}')
        row['sha256']=observed['sha256']
    program=program_image(directory,rows)
    reset=int.from_bytes(program[-4:],'little')  # TMS34010 reset vector at 0xffffffe0: low word first
    return dict(game='mk3',revision='2.1',machine='mk3',driver='midway/midwunit.cpp',board='Wolf-Unit',
                cpu='TMS34010 50 MHz',sound='DCS Audio 8K (ADSP-2105 10 MHz)',security='midway_serial_pic_sim upper=528',
                source=str(SOURCE.relative_to(ROOT)).replace('\\','/'),source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),source_commit=SOURCE_COMMIT,
                rom_count=len(rows),program_sha256=hashlib.sha256(program).hexdigest(),reset_vector=f'0x{reset:08x}',roms=rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--write',action='store_true');p.add_argument('--verify',type=Path)
    a=p.parse_args()
    if a.write:
        data=generate();MANIFEST.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in data.items() if k!='roms'},indent=2))
    if a.verify:print(json.dumps(verify(a.verify)))
    return 0

if __name__=='__main__':raise SystemExit(main())
