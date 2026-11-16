"""Streamed Original trace of a long MK3 route: executed TMS PCs and computed-transfer pairs, deduplicated online.

The pinned MAME (tools/mk3/reference.py identities; reset, CMOS seed, default DIPs, no input) runs with the debugger
`trace` command writing every executed instruction (`noloop`: no loop folding, so consecutive lines are consecutive
executions) into a Windows named pipe owned by this process. Nothing of the trace touches the disk: the reader keeps
only the set of PCs and the set of (source, destination, kind) pairs, where kind is the source's mnemonic for CALL Rn,
JUMP Rn, EXGPC, RETS, RETI and TRAP, or 'entry' for an arrival at an interrupt/TRAP vector handler from any other
instruction (an interrupt taken). The scratch tree (debugger script, CMOS copy, MAME's cfg) is bounded by CAP_BYTES and
the run is aborted if it grows past it. The result is a compact gzip JSON of the sets plus a cost summary.
"""
from pathlib import Path
import argparse,gzip,json,os,re,subprocess,sys,threading,time,uuid
import _winapi
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q
from tools.mk3 import reference,reference_video,roms

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/native/mk3-m2'
CAP_BYTES=64*1024*1024
LINE=re.compile(rb'^([0-9A-F]{8}): ',re.M)
TRANSFER=re.compile(rb'^([0-9A-F]{8}): (CALL +[AB]\d+|JUMP +[AB]\d+|EXGPC|RETS|RETI|TRAP)\b[^\n]*\n(?=([0-9A-F]{8}): )',re.M)


class Reader:
    """Online deduplication of trace text arriving in arbitrary chunks (a partial last line is carried over)."""
    def __init__(self,handlers):
        self.pcs,self.pairs,self.bytes,self.lines,self.tail=set(),set(),0,0,b''
        self.entry=re.compile(rb'^([0-9A-F]{8}): ([^\n]*)\n(?=('+b'|'.join(b'%08X'%h for h in sorted(handlers))+rb'): )',re.M)
        self.computed=re.compile(rb'(CALL +[AB]\d+|JUMP +[AB]\d+|EXGPC|RETS|RETI|TRAP)\b')

    def feed(self,data):
        self.bytes+=len(data)
        text=self.tail+data.replace(b'\r',b'')
        end=text.rfind(b'\n')
        if end<0:self.tail=text;return
        start=text.rfind(b'\n',0,end)   # the last complete line stays as the next chunk's first line (its pair needs the next PC)
        self.scan(text[:end+1])
        self.count(text[:start+1])
        self.tail=text[start+1:]

    def scan(self,text):
        for m in TRANSFER.finditer(text):self.pairs.add((m[1],m[3],m[2].split()[0]))
        for m in self.entry.finditer(text):
            if not self.computed.match(m[2]):self.pairs.add((m[1],m[3],b'entry'))

    def count(self,text):
        self.lines+=text.count(b'\n');self.pcs.update(LINE.findall(text))

    def finish(self):
        text=self.tail if self.tail.endswith(b'\n') else self.tail+b'\n'
        if text.strip():self.scan(text);self.count(text)
        self.tail=b''


def handlers():
    return set(reference_video.handlers(roms.program_image(ROOT/'roms/mk3',roms.definition())).values())


def tree_bytes(path):
    total=0
    for root,dirs,files in os.walk(path):
        for f in files:
            try:total+=os.path.getsize(os.path.join(root,f))
            except OSError:pass
    return total


def run(seconds,fold=False):
    if q.sha(reference.CORE)!=reference.CORE_SHA:raise ValueError('Reference core identity changed')
    identity=roms.verify(ROOT/'roms/mk3')
    name='\\\\.\\pipe\\mk3-trace-'+uuid.uuid4().hex
    pipe=_winapi.CreateNamedPipe(name,_winapi.PIPE_ACCESS_INBOUND,0,1,0,1<<20,0,_winapi.NULL)
    reader=Reader(handlers());errors=[]
    def pump():
        try:
            _winapi.ConnectNamedPipe(pipe,False)
            while True:
                try:data,_=_winapi.ReadFile(pipe,1<<20,False)
                except BrokenPipeError:break
                if not data:break
                reader.feed(data)
            reader.finish()
        except Exception as e:errors.append(repr(e))
    thread=threading.Thread(target=pump,daemon=True);thread.start()
    peak=0;aborted=None
    with q.scratch_tree() as (temp,cleanup):
        (temp/'nvram/mk3').mkdir(parents=True);(temp/'nvram/mk3/nvram').write_bytes(reference.SEED.read_bytes())
        (temp/'trace.cmd').write_text(f'focus :maincpu\ntrace {name},:maincpu{"" if fold else ",noloop"}\ngo\n',encoding='ascii')
        started=time.perf_counter()
        process=subprocess.Popen([str(reference.CORE),'mk3','-rompath',str(ROOT/'roms'),'-noreadconfig','-nowriteconfig','-skip_gameinfo','-noplugins',
                                  '-video','none','-sound','none','-nothrottle','-debug','-debugger','windows','-debugscript','trace.cmd',
                                  '-nvram_directory','nvram','-cfg_directory','cfg','-homepath','home','-snapshot_directory','snap','-seconds_to_run',str(seconds)],
                                 cwd=temp,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        while process.poll() is None:
            peak=max(peak,tree_bytes(temp))
            if peak>CAP_BYTES:aborted=f'scratch tree {peak} bytes > cap';process.kill();break
            if time.perf_counter()-started>3600:aborted='wall-clock limit';process.kill();break
            time.sleep(0.5)
        process.wait();wall=time.perf_counter()-started
        thread.join(120)
        peak=max(peak,tree_bytes(temp))
    _winapi.CloseHandle(pipe)
    if errors or thread.is_alive():raise RuntimeError(f'pipe reader: {errors}')
    pcs=sorted(int(p,16) for p in reader.pcs)
    pairs=sorted((int(a,16),int(b,16),k.decode()) for a,b,k in reader.pairs)
    kinds={}
    for _,_,k in pairs:kinds[k]=kinds.get(k,0)+1
    return dict(route='reset -> attract, inputs at rest, CMOS seed, default DIPs',seconds_emulated=seconds,
                mode='folded (MAME loop detection: PC set complete, pairs a subset)' if fold else 'noloop (every instruction)',wall_seconds=wall,
                realtime_ratio=seconds/wall,exit_code=process.returncode,aborted=aborted,bytes_transported=reader.bytes,instructions_traced=reader.lines,
                distinct_pcs=len(pcs),distinct_pairs=len(pairs),pairs_by_kind=kinds,disk_peak_bytes=peak,disk_cap_bytes=CAP_BYTES,
                identities=dict(core_sha256=reference.CORE_SHA,program_sha256=identity['program_sha256'],seed_sha256=q.sha(reference.SEED)),
                cleanup=cleanup),pcs,pairs


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds',type=int,default=30)
    parser.add_argument('--fold',action='store_true',help='MAME loop folding: complete PC set, partial pairs, far less volume')
    parser.add_argument('--output',type=Path,default=OUT/'j1-trace.json')
    args=parser.parse_args()
    args.output=args.output.resolve()
    summary,pcs,pairs=run(args.seconds,args.fold)
    roots=args.output.with_name(args.output.stem+'-roots.json.gz')
    payload=gzip.compress(json.dumps(dict(summary={k:v for k,v in summary.items() if k!='cleanup'},pcs=pcs,pairs=pairs),separators=(',',':')).encode(),9)
    if len(payload)>2*1024*1024:raise ValueError(f'compact set {len(payload)} bytes > 2 MiB')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    roots.write_bytes(payload)
    summary.update(roots=str(roots.relative_to(ROOT)).replace('\\','/'),roots_bytes=len(payload))
    args.output.write_text(json.dumps(summary,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='cleanup'},indent=1))
    return 0 if summary['aborted'] is None and summary['exit_code']==0 and summary['cleanup'].get('exists_after') is False else 1


if __name__=='__main__':raise SystemExit(main())
