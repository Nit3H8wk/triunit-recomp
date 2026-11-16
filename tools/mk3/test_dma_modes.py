"""J1 DMA modes: every dma_w path of native/mk3/mk3_dma.hpp against a separate Python transcription of the pinned
MAME 0.280 midtunit_v.cpp (dma_w V:699-840, dma_draw V:435-614) and the draw tables of midtunit_v.ipp (tag mame0280:
bpp 0 = 8 bits, mode 0 = dma_draw_none, XFlip = command bit 4, the 16 zero/nonzero pairs below).

Not a comparison with the Original: the Original from reset only exercises 0xc002, 0xc082 and 0x800c unscaled
(tools/mk3/test_dma.py). Cases: random registers over a synthetic 16 KiB graphics region for every (mode, xflip,
yflip, skip, LRSKIP layout, bpp) and the scaled branch, plus skipdma. The native side runs in the Game profile and must
record one DmaPath per distinct path. Negative controls: one-rule mutations of the transcription, each detected.
"""
import json,os,random,sys,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/dma-modes.json'
SKIP,COLOR,COPY=0,1,2
# midtunit_v.ipp INIT_TEMPLATED_DMA_DRAW_GROUP, (zero, nonzero) per mode; mode 0 is dma_draw_none
MODES=[None,(COPY,SKIP),(SKIP,COPY),(COPY,COPY),(COLOR,SKIP),(COLOR,SKIP),(COLOR,COPY),(COLOR,COPY),
       (SKIP,COLOR),(COPY,COLOR),(SKIP,COLOR),(COPY,COLOR),(COLOR,COLOR),(COLOR,COLOR),(COLOR,COLOR),(COLOR,COLOR)]


class Past(Exception):pass


def dma_w(regs,gfx,vram,mutation=None):
    """dma_w on a DMA_COMMAND write with bit 15 -> pixels (None: reads past the loaded bytes)."""
    command=regs[1]
    st=dict(xpos=regs[4]&0x3ff,ypos=regs[5]&0x1ff,width=regs[6]&0x3ff,height=regs[7]&0x3ff,palette=regs[8]&0x7f00,
            color=regs[9]&0xff,yflip=(command&0x20)>>5,preskip=(command>>8)&3,postskip=(command>>10)&3,
            xstep=regs[10] or 0x100,ystep=regs[11] or 0x100,topclip=regs[12]&0x1ff,botclip=regs[13]&0x1ff,
            leftclip=regs[16]&0x3ff,rightclip=regs[17]&0x3ff)
    gfxoffset=regs[2]|regs[3]<<16
    if command&0x0f==0x0c:gfxoffset=0
    if gfxoffset>=0xf8000000:gfxoffset-=0xf8000000
    if gfxoffset>=0x10000000:return 0
    st['offset']=gfxoffset
    if command&0x40:st['startskip'],st['endskip']=regs[0]&0xff,regs[0]>>8
    else:st['startskip'],st['endskip']=0,regs[0]
    bpp=(command>>12)&7;bits=bpp or 8
    scale=not(st['xstep']==0x100 and st['ystep']==0x100)
    mode=command&0x0f
    if mutation=='mode5_as_c0p1' and mode==5:mode=6
    if MODES[mode]:
        new={}   # writes over the untouched video RAM; applied only when the draw completes (all reads inside)
        draw(st,gfx,new,bits,bool(command&0x10),bool(command&0x80),scale,*MODES[mode],mutation)
        vram.update(new)
    if not scale:return st['width']*st['height']
    return ((st['width']<<8)//st['xstep'])*((st['height']<<8)//st['ystep'])


def draw(st,base,vram,bpp,xflip,skip,scale,zero,nonzero,mutation):
    def extract(o,m):
        if (o>>3)+1>=len(base):raise Past
        return ((base[o>>3]|base[(o>>3)+1]<<8)>>(o&7))&m
    def idiv(a,b):return int(a/b)   # C division truncates toward zero
    height=st['height']<<8;offset=st['offset'];pal=st['palette'];color=pal|st['color']
    sy=st['ypos'];iy=0;mask=(1<<bpp)-1;xstep=st['xstep'] if scale else 0x100
    pre=post=0
    while iy<height:
        startskip=st['startskip']<<8;width=st['width']<<8;sx=st['xpos'];ix=0;o=offset
        if skip:
            value=extract(o,0xff);o+=8
            pre=(value&0x0f)<<(st['preskip']+8);tx=idiv(pre,xstep)
            if xflip and mutation!='preskip_ignores_xflip':sx=(sx-tx)&0x3ff
            else:sx=(sx+tx)&0x3ff
            ix+=tx*xstep
            post=((value>>4)&0x0f)<<(st['postskip']+8);width-=post
        if st['topclip']<=sy<=st['botclip']:
            if ix<startskip:
                tx=idiv(startskip-ix,xstep)*xstep;ix+=tx;o+=(tx>>8)*bpp
            if (width>>8)>st['width']-st['endskip']:width=(st['width']-st['endskip'])<<8
            row=sy*512
            while ix<width:
                if st['leftclip']<=sx<=st['rightclip']:
                    if zero==nonzero:
                        if zero==COLOR:vram[row+sx]=color
                        elif zero==COPY:vram[row+sx]=extract(o,mask)|pal
                    else:
                        pixel=extract(o,mask)
                        if pixel:
                            if nonzero==COLOR:vram[row+sx]=color
                            elif nonzero==COPY:vram[row+sx]=pixel|pal
                        else:
                            if zero==COLOR:vram[row+sx]=color
                            elif zero==COPY:vram[row+sx]=pal
                sx=(sx-1)&0x3ff if xflip else (sx+1)&0x3ff
                if not scale:ix+=0x100;o+=bpp
                else:
                    tx=ix>>8;ix+=xstep;tx=(ix>>8)-tx;o+=bpp*tx
        sy=(sy-1)&0x1ff if st['yflip'] and mutation!='no_yflip' else (sy+1)&0x1ff
        if not scale:
            iy+=0x100;width=st['width']
            if skip:
                offset+=8;width-=(pre+post)>>8
                if width>0:offset+=width*bpp
            else:offset+=width*bpp
        else:
            ty=iy>>8;iy+=st['ystep'];ty=(iy>>8)-ty
            if not skip:offset+=ty*st['width']*bpp
            elif ty:
                ty-=1
                o=offset+8;width=st['width']-((pre+post)>>8)
                if width>0:o+=width*bpp
                while ty:
                    ty-=1
                    value=extract(o,0xff);o+=8
                    shift=8 if mutation=='scaled_rows_plus_8' else 0
                    pre=(value&0x0f)<<(st['preskip']+shift);post=((value>>4)&0x0f)<<(st['postskip']+shift)
                    width=st['width']-pre-post
                    if width>0:o+=width*bpp
                offset=o


def cases(seed=0x6d6b33):
    rnd=random.Random(seed);out=[]
    for mode in range(16):
        for flags in range(16):   # xflip, yflip, LRSKIP layout (0x40), skip (0x80)
            for bpp in range(8):
                for scaled in (False,True):
                    command=0x8000|bpp<<12|rnd.randrange(16)<<8|((flags&1)<<4)|((flags&2)<<4)|((flags&4)<<4)|((flags&8)<<4)|mode
                    regs=[0]*18;regs[1]=command
                    regs[0]=rnd.choice((0,rnd.randrange(0x10000),rnd.randrange(8)|rnd.randrange(8)<<8))
                    regs[2]=rnd.randrange(0x10000);regs[3]=0        # source bit offset inside 8 KiB of the 16 KiB region
                    regs[2]&=0xffff>>(3 if bpp in (0,7,6) else 2)
                    regs[4]=rnd.choice((rnd.randrange(0x400),0x3fc,1));regs[5]=rnd.choice((rnd.randrange(0x200),0x1fe,1))
                    regs[6]=rnd.randrange(1,24);regs[7]=rnd.randrange(1,12)
                    regs[8]=rnd.randrange(0x10000);regs[9]=rnd.randrange(0x10000)
                    if scaled:regs[10]=rnd.choice((0x80,0xc0,0x140,0x200,0x55,0x100));regs[11]=rnd.choice((0x80,0x100,0xe0,0x180))
                    clip=rnd.random()<0.25   # a quarter of the cases with a random clip window
                    regs[12],regs[13]=(rnd.randrange(0x200),rnd.randrange(0x200)) if clip else (0,0x1ff)
                    regs[16],regs[17]=(rnd.randrange(0x400),rnd.randrange(0x400)) if clip else (0,0x3ff)
                    regs[14],regs[15]=rnd.randrange(0x10000),rnd.randrange(0x10000)&~0x20
                    out.append(regs)
    for hi in (0x1000,0xf800,0xffff,0x0fff):   # skipdma below / above the 0xf8000000 fold; last one in range
        regs=[0]*18;regs[1]=0xc002;regs[3]=hi;regs[6]=regs[7]=2;regs[13]=0x1ff;regs[17]=0x3ff;out.append(regs)
    return out


def expected(regs,gfx,mutation=None):
    vram={}   # sparse: word i holds (i * 7) & 0x7fff unless written
    try:pixels=dma_w(regs,gfx,vram,mutation)
    except Past:return 'REJECT'
    return pixels,{i:v for i,v in sorted(vram.items()) if v!=(i*7)&0x7fff}


def paths(all_cases):
    keys=set()
    for r in all_cases:
        c=r[1];scaled=(r[10] or 0x100)!=0x100 or (r[11] or 0x100)!=0x100
        src=0 if c&0x0f==0x0c else r[2]|r[3]<<16
        if src>=0xf8000000:src-=0xf8000000
        if c not in (0xc002,0xc082,0x800c) or scaled or src>=0x10000000:keys.add((c,scaled,src<0x10000000))
    return len(keys)


class DmaModes(unittest.TestCase):
    def test_every_path_against_the_source_transcription(self):
        rnd=random.Random(7);gfx=bytes(rnd.randrange(256) if i%5 else 0 for i in range(0x4000))
        all_cases=cases()
        cc=q.DEFAULT_CC;env={'PATH':str(cc.parent)+os.pathsep+os.environ['PATH']}
        with q.scratch_tree() as (temp,cleanup):
            exe=temp/'mk3-dma.exe'
            made=q.command([cc,'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static','-I'+str(ROOT/'native/mk3'),
                            ROOT/'native/tests/mk3_dma_tests.cpp','-o',exe],temp,cwd=ROOT,env=env,timeout=180)
            self.assertTrue(made['passed'],q.compact(made))
            (temp/'gfx.bin').write_bytes(gfx)
            (temp/'cases.txt').write_text(''.join('K '+' '.join(f'{v:X}' for v in r)+'\n' for r in all_cases),encoding='ascii')
            start=time.perf_counter()
            run=q.command([exe,'modes',temp/'gfx.bin',temp/'cases.txt'],temp,cwd=ROOT,env=env,timeout=300,output_limit=1<<26)
            native_s=time.perf_counter()-start
            self.assertTrue(run['passed'],q.compact(run))
            lines=run['stdout'].splitlines()
        self.assertFalse(cleanup['exists_after'])
        self.assertEqual(len(lines),len(all_cases)+1)
        def parse(line):
            if line.startswith('REJECT'):return 'REJECT'
            f=line.split();return int(f[1]),{int(a,16):int(b,16) for a,b in (x.split(':') for x in f[3:])}
        start=time.perf_counter();written=rejects=0
        for k,(regs,line) in enumerate(zip(all_cases,lines)):
            want=expected(regs,gfx);got=parse(line)
            self.assertEqual(got,want,f'case {k} command {regs[1]:#06x} scale {regs[10]:#x},{regs[11]:#x}')
            if want=='REJECT':rejects+=1
            else:written+=len(want[1])
        python_s=time.perf_counter()-start
        self.assertEqual(lines[-1],f'N {paths(all_cases)}','one first-execution entry per distinct unverified path')
        negatives={}
        for mutation in ('mode5_as_c0p1','preskip_ignores_xflip','no_yflip','scaled_rows_plus_8'):
            negatives[mutation]=any(expected(r,gfx,mutation)!=parse(l) for r,l in zip(all_cases,lines))
        self.assertTrue(all(negatives.values()),negatives)
        RECEIPT.parent.mkdir(parents=True,exist_ok=True)
        RECEIPT.write_text(json.dumps(dict(passed=True,cases=len(all_cases),scaled_cases=sum(1 for r in all_cases if r[10] or r[11]),
            vram_words_written=written,read_past_rejections=rejects,distinct_unverified_paths=paths(all_cases),
            negative_controls=negatives,timings_seconds=dict(build=made['wall_seconds'],native=native_s,python_transcription=python_s),
            scope='native Dma vs a Python transcription of midtunit_v.cpp/.ipp (mame0280) on synthetic registers and graphics; '
                  'not a comparison with the Original',cleanup=dict(exists_after=cleanup['exists_after'])),indent=1)+'\n',encoding='utf-8')


if __name__=='__main__':unittest.main()
