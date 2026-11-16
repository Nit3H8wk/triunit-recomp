"""Open items of the one-day plan, generated from the receipts in build/native/day1/ (no hand-written item).

    python tools/oracle/day1_report.py            # open items, Markdown on stdout
    python tools/oracle/day1_report.py --d10      # cases that follow the hardware (D10)
"""
import json,sys
from pathlib import Path
DAY1=Path(__file__).resolve().parents[2]/'build/native/day1'

def load(name):
    p=DAY1/name
    return json.loads(p.read_text('utf-8')) if p.exists() else None

D10_MK2=('ABS R',)   # D10 (user, 15/11/2026): where the pinned MAME differs from the chip, the hardware is the Original

def receipts():return (load(n) for n in ('front-b.json','front-c.json','front-d.json','front-d-regress.json','suite.json','recapture.json'))

def hardware():
    """D10 cases: the native follows the chip; each line says what the receipts measured against MAME."""
    b,c,d,*_=receipts();t=b['totals']['known_open'];out=[]
    for k,v in b['d10'].items():
        out.append(f"MK3 `{k}` ({t.get(k,0)} vetores, ex. `{v['pc']}` {v['asm']}): MAME {v['mame']}; nativo {v['native']}. Causa: {v['cause']}")
    rows=[x for x in c['checks']['abs_v']['rows'] if x['input']=='80000000']
    sites=next(x['sites'] for x in c['open'] if x['form']=='ABS R')
    out.append(f"MK2 `ABS R` ({sites} sítios): com 80000000h, MAME V=0 e nativo V=1 em {sum(1 for x in rows if x['native_V']==1)} de "
               f"{len(rows)} vetores (`checks.abs_v`); sem mudança no código")
    probes={p['id']:p for p in d['probes']}
    for k,pid in (('wfieldmac-big','probe-wfield24-cross'),('abs-int-min-v','probe-abs-int-min')):
        p=probes[pid]
        out.append(f"MK1 `{k}` ({d['summary']['mame_side_vectors'][k]} vetores): sonda `{pid}`: nativo = hardware {p['native_matches_expected']}, "
                   f"MAME = hardware {p['mame_matches_expected']}; sem mudança no código")
    return out

def items():
    b,c,d,r,s,cap=receipts()
    out=[]
    for k,v in b['open'].items():
        out.append(f"MK3 `{k}` (`{v.get('pc','-')}` {v['asm']}): Original {v['mame']}; nativo {v['native']}. Próxima sonda: {v['next_probe']}")
    t=b['totals']
    if t['unexplained']:out.append(f"MK3: {t['unexplained']} vetores sem explicação em {', '.join(t['forms_with_unexplained'])}")
    out.append(f"MK3: {t['device_operand_sites']} sítios de {t['device_operand_forms']} formas com operando de dispositivo, sem oráculo por instrução; "
               f"formas não traduzidas (guard): {', '.join(b['untranslated_forms'])}")
    seen=set()
    for o in c['open']:
        if o['form'] in seen or o['form'] in D10_MK2:continue
        seen.add(o['form']);n=max(x['sites'] for x in c['open'] if x['form']==o['form'])
        out.append(f"MK2 `{o['form']}` ({o['status']}, {n} sítios, ex. `{o['pcs'][0]}`): {c['open_notes'].get(o['form'],'')}")
    out.append(f"MK2: {c['open_notes']['field_fs24']}; {c['summary']['all_sites']['device_sites_listed']} sítios de dispositivo listados, sem oráculo")
    sd=r['setf_decision']
    out.append(f"MK1 `SETF K,0,1`: {sd['status']}. Negativo: {sd['negative']}. Próxima sonda: {sd['next_probe']}")
    for v in d['summary']['no_oracle']:out.append(f"MK1 sem oráculo: {v}")
    if s is None or not s.get('passed'):out.append('Suíte de integração não verde ou ausente (`suite.json`)')
    if cap is None:out.append('Recaptura dos 64 recibos do MK3: sem recibo final (`recapture.json` ausente)')
    else:
        bad=[n for n,v in cap['routes'].items() if not v['passed']]+[f['name'] for f in cap['failed']]
        if bad:out.append(f"Recaptura: {len(bad)} rotas sem aceite: {', '.join(bad)}")
    return out

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    print('\n'.join(f'- {i}' for i in (hardware() if '--d10' in sys.argv else items())))
