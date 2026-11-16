"""MK1 rev 5.0 ROM set of the user (manifest tools/mk1/roms-l1.json: names, sizes and SHA-256 only)."""
from pathlib import Path
import hashlib,json

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'tools/mk1/roms-l1.json'
ROMS=ROOT/'roms/mk1'
BASE=0xff800000   # bit address of the first program byte


def manifest():
    return json.loads(MANIFEST.read_text('utf-8'))


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):h.update(block)
    return h.hexdigest()


def verify(folder,data=None):
    """Every file of the manifest by name, size and SHA-256, then the interleaved program image."""
    data=data or manifest();rows=[]
    for rom in data['roms']:
        name=rom['path']
        if not name or any(c in name for c in '/\\:') or name in ('.','..'):raise ValueError('Invalid ROM name: '+name)
        path=Path(folder)/name
        if not path.is_file():raise SystemExit(f'MK1 ROM missing: {name}')
        if path.stat().st_size!=rom['size']:raise SystemExit(f'MK1 ROM size differs: {name}')
        if _sha(path)!=rom['sha256']:raise SystemExit(f'MK1 ROM SHA-256 differs: {name} (supported revision: {data["revision"]})')
        rows.append(name)
    image=program_image(folder,data)
    return dict(verified=len(rows),program_sha256=hashlib.sha256(image).hexdigest())


def program_image(folder=ROMS,data=None):
    """1 MiB program image (lane 0 bytes at even offsets, lane 1 at odd), refused unless it has the manifest digest."""
    data=data or manifest()
    lanes={r['program_lane']:(Path(folder)/r['path']).read_bytes() for r in data['roms'] if r['region']=='program'}
    image=bytearray(2*len(lanes[0]));image[0::2]=lanes[0];image[1::2]=lanes[1]
    if hashlib.sha256(image).hexdigest()!=data['program_sha256']:raise ValueError('MK1 program image differs from rev 5.0')
    return bytes(image)


def u3(folder=ROMS,data=None):
    data=data or manifest()
    row=next(r for r in data['roms'] if r['region']=='sound')
    blob=(Path(folder)/row['path']).read_bytes()
    if hashlib.sha256(blob).hexdigest()!=row['sha256']:raise ValueError('MK1 sound program differs from rev 5.0')
    return blob
