"""K3 (R1): special moves from the ROM recognizer tables (plan docs/superpowers/plans/2026-11-10-mk3-cobertura-em-ondas.md).

ROM evidence (MK3 rev. 2.1, TMS34010 bit addresses; readers confirmed in the Original by debugger read watchpoints,
build/native/mk3-m2/k3-waves.json):
- Button dispatch 0xff818be0-0xff818d00: A4 = PRESS 0xff977bd0 (A3 != 0) or RELEASE 0xff97b210; handler =
  *(*(A4 + 32*button) + 32*character), character = *A8(1F0h); `JUMP A4`. Button index (reader 0xff818ca0, one press
  each): HP 0, LP 1, BL 2, HK 3, LK 4, RUN 5.
- A list handler is `MOVI list,A14; JR FF991F70h`. 0xff991f70 walks entries of 0x160 bits until a zero long:
  +0x00 A0 and +0x20 A1 (state words for 0xff97f1c0), +0x40 kind (index into the jump table 0xff992160, 8 entries),
  +0x50 condition routine (0 = none), +0x70 action routine, +0x90 frame limit, +0xA0 and +0x100 two sequences of up to
  6 tokens (0 ends), newest first, picked by the facing test 0xff95da80 (`JRC` -> first set).
- Matcher 0xff982880: tokens >= 6 are read from the stick history (P1 0x1060D50, P2 0x1061900; reader 0xff982c10), each
  entry a long (frame, token << 16); the oldest matched token must be within the frame limit of @105D800. Stick tokens
  seen in the Original after known taps: 6 up, 7 down, 8 left, 9 right (absolute: the two sequences mirror 8 and 9).
- Tokens < 6 read the other history (0x1060AB0 / 0x1061660, button presses): their map is not read yet (open).
Inputs are legal taps of the side's own stick and button; whether a move was recognized is the first execution of its
action routine in the native (Profile::Game) after the press, then the whole route is compared with the Original.
"""
from pathlib import Path
import json,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import versus

ROOT=Path(__file__).resolve().parents[2]
PRESS,RELEASE,LIST_WALK,ENTRY=0xff977bd0,0xff97b210,0xff991f70,0x160
BUTTONS=('HP','LP','BL','HK','LK','RUN')
BUTTON_BITS={'HP':(0,0x10),'BL':(0,0x20),'HK':(0,0x40),'LP':(1,0x1),'LK':(1,0x2),'RUN':(1,0x4)}   # P1; P2: IN0 <<8, IN1 <<4
TOKEN_STICK={6:1,7:2,8:4,9:8}
FRAME=versus.FRAME
SPECS=ROOT/'tools/mk3/r1_specials.json'


def jr_target(rom,pc):
    """Target of a JRUC at pc (short 0xC0dd or long 0xC000 dddd), else None."""
    w=versus.word(pc,rom)
    if w>>8!=0xC0:return None
    d=w&0xff
    if d==0x80:return None
    if d:return pc+16+16*(d-256 if d&0x80 else d)
    d=versus.word(pc+16,rom);return pc+32+16*(d-65536 if d&0x8000 else d)


def entries(rom=None,characters=range(14)):
    """Every list entry of the press and release tables for the characters, decoded from the ROM."""
    rom=rom or versus.image();W=lambda a:versus.word(a,rom);L=lambda a:W(a)|W(a+16)<<16
    out=[]
    for table,base in (('press',PRESS),('release',RELEASE)):
        for b,name in enumerate(BUTTONS):
            t=L(base+32*b)
            for ch in characters:
                h=L(t+32*ch)
                if W(h)!=0x09EE or jr_target(rom,h+48)!=LIST_WALK:continue   # 48-bit immediate load into A14, then a relative jump to LIST_WALK
                x=L(h+16);n=0
                while L(x+ENTRY*n):
                    e=x+ENTRY*n;seq=lambda o:[t for t in (W(e+0x90+16*(o+i)) for i in range(6)) if t][:6]
                    out.append(dict(table=table,button=name,character=ch,handler=h,list=x,entry=e,kind=W(e+0x40),a0=L(e),a1=L(e+0x20),
                                    condition=L(e+0x50),action=L(e+0x70),frames=W(e+0x90),seq=(seq(1),seq(7))))
                    n+=1
    return out


def attempt_rows(entry,side,variant,at):
    """Legal taps for one entry: the tokens of sequence `variant` oldest first (stick held 3 frames, 1 released), then
    the button (press table: pressed 4 frames; release table: held 12 frames and released) 1 frame after."""
    shift=8 if side=='p2' else 0;rows=[];c=at
    for tok in reversed(entry['seq'][variant]):
        if tok not in TOKEN_STICK:raise ValueError('button-history token: map not read')
        rows+=[(c,0,0xffff^(TOKEN_STICK[tok]<<shift)),(c+3*FRAME,0,0xffff)];c+=4*FRAME
    port,bit=BUTTON_BITS[entry['button']];bit=bit<<(shift if port==0 else (4 if side=='p2' else 0))
    hold=4 if entry['table']=='press' else 12
    rows+=[(c+FRAME,port,0xffff^bit),(c+FRAME+hold*FRAME,port,0xffff)]
    return rows,c+FRAME+(0 if entry['table']=='press' else hold*FRAME)


def recognized(native,base,fight,entry,side,variant,start):
    """Native run: base tape + the attempt at `start`; the action's first execution cycle if it is after the press."""
    rows,press=attempt_rows(entry,side,variant,start)
    o=native.run(0,0,0,press+60*FRAME,tuple(sorted(list(base)+rows)),first_all=True)
    from tools.mk3 import explore
    _,cyc=explore.first_set(o['summary'])
    c=cyc.get((0,entry['action'],0)) or min((v for (k,i,f),v in cyc.items() if k==0 and i==entry['action']),default=None)
    return (c if c is not None and c>=press else None),o['summary']['frontier']


def fight_cycle(native,p1,p2,shift):
    o=native.run(0,0,0,360000000+shift,versus.versus_tape(p1,p2,shift)['tape'],events=True)
    return next((c for c,v in versus.commands(o['events']) if v in versus.FIGHT_SOUND),None)


def plan_pair(native,p1,p2,shift,kinds=(0,),gap=150,log=print):
    """One versus route: P1 then P2 try each joystick entry of their character (kinds), one attempt every `gap`
    frames from 2 s after round start; an attempt keeps the first variant whose action runs (tried in the route prefix);
    attempts no variant recognizes stay in the tape list `missed` (not in the tape)."""
    fight=fight_cycle(native,p1,p2,shift);base=list(versus.versus_tape(p1,p2,shift)['tape']);at=fight+120*FRAME;done=[];missed=[]
    es=entries()
    for side,ch in (('p1',p1),('p2',p2)):
        for e in es:
            if e['character']!=ch or e['kind'] not in kinds:continue
            if any(t not in TOKEN_STICK for t in e['seq'][0]+e['seq'][1]):missed.append(dict(entry=e['entry'],side=side,reason='button tokens'));continue
            hit=None
            for variant in (0,1):
                c,frontier=recognized(native,base,fight,e,side,variant,at)
                if frontier!='none':missed.append(dict(entry=e['entry'],side=side,reason='native stop',frontier=frontier));break
                if c:hit=(variant,c);break
            if hit:
                rows,_=attempt_rows(e,side,hit[0],at);base+=rows
                done.append(dict(entry=e['entry'],side=side,character=ch,button=e['button'],table=e['table'],kind=e['kind'],variant=hit[0],at=at,action=e['action'],action_cycle=hit[1]))
                log(f'{side} {ch} {e["entry"]:#x} variant {hit[0]}')
            else:missed.append(dict(entry=e['entry'],side=side,reason='no variant recognized'))
            at+=gap*FRAME
    return dict(p1=p1,p2=p2,shift=shift,fight=fight,attempts=done,missed=missed,horizon=at+FRAME)


def tape_of(spec):
    base=list(versus.versus_tape(spec['p1'],spec['p2'],spec['shift'])['tape']);byentry={e['entry']:e for e in entries()}
    for a in spec['attempts']:base+=attempt_rows(byentry[a['entry']],a['side'],a['variant'],a['at'])[0]
    return tuple(sorted(base))


def route_specs(path=SPECS):
    if not path.is_file():return {}
    out={}
    for s in json.loads(path.read_text('utf-8'))['routes']:
        tape=tape_of(s);sel=versus.versus_tape(s['p1'],s['p2'],s['shift'])['select_at']
        no_p1_select=tuple(r for r in tape if not (r[0] in (sel,sel+versus.TAP) and r[1]==0))
        out[s['name']]=dict(tape=tape,horizon=s['horizon'],mutation=(0x30000,1,versus.CURSOR_FROM+s['shift']),input_negative=dict(native=no_p1_select,reference=tape),
                            criterion=f"versus P1 {s['p1']} x P2 {s['p2']}: {len(s['attempts'])} special moves from the ROM recognizer lists (round start at {s['fight']:,})",
                            wave=dict(family='R1',kind='specials',p1=s['p1'],p2=s['p2'],attempts=[{k:a[k] for k in ('entry','side','button','table','kind','variant','at')} for a in s['attempts']],
                                      missed=len(s['missed'])))
    return out
