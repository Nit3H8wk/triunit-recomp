"""MK3 rev. 2.1 delivery tools (plan docs/superpowers/plans/2026-11-13-mk3-entrega-final.md).

forms [--report F]: the form certificate, a static measure counted apart. Residue = the static closure from the vectors,
  the lot-measured PCs and the route-verified TmsBlock keys (tools/mk3/generate.py closures, the roots of
  strict_matrix.residue; pointer candidates excluded) minus those executed PCs. Form of an instruction = the generator's
  own identity of what it emits: generate.form(asm) (mnemonic, operand shape, field number), the instruction size in bits
  and the mould = the C++ that generate.units emitted for that PC with its operand values masked (s.a[n]/s.b[n] -> R, every
  number -> N). The mould tells apart what form() alone does not (MPYS into SP or a B register, DIVS with an even Rd, the
  K/R shift families); the operand shape over-splits register lists (MMTM/MMFM), which only adds entries (`mould_on_routes`
  marks a never-exercised form whose mould ran under another operand shape, field or size). A residue form
  is exercised when a route-verified TmsBlock of tools/mk3/route_verified.json has the same form: both go through
  generate.emit_unverified, the lot-measured PCs through another emitter and are left out. It promotes nothing to
  verified: an exercised form says the mould ran on a route equal to the Original, not that this PC's operands, data or
  reachability were compared. Untranslated positions (DW/EMU, explicit Reject in both profiles) are listed apart.
report --out F.md: the delivery report (Markdown and F.json) from the existing receipts only (route_verified.json, the
  latest k<N>-integration.json, k<N>-residue.json and rm2-r<N>.json, the install receipt, the form certificate). Runs
  nothing; receipts that disagree with each other are listed under `stale`. The residue is never counted as verified.
"""
from pathlib import Path
import argparse,collections,datetime,hashlib,json,re,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.mk3 import generate,roms

ROOT=generate.ROOT
M2=ROOT/'build/native/mk3-m2'
FORMS=M2/'k10-forms.json'
INSTALL=ROOT/'build/native/mk3-native/install.json'
CASE=re.compile(r'case 0x([0-9a-f]{8})u: \{ // (.*)\n    (.*)\n    break;\n\}\n')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def mould(code):
    """The emitted case with its operand values masked (the o.Block(pc) prefix of the unverified candidate dropped)."""
    code=re.sub(r'^o\.Block\(0x[0-9a-f]{8}u\); ','',code)
    return re.sub(r'\b(?:0x[0-9a-f]+|\d+)u?\b','N',re.sub(r'\bs\.[ab]\[\d+\]','R',code))


def inputs():
    """(forms {pc: (form, bits, mould)}, asm {pc: text}, residue PCs, route-verified TmsBlock PCs); one scan, one generation."""
    rom=roms.program_image(ROOT/'roms/mk3',roms.definition());rows,_=generate.scan(rom)
    sources,_=generate.units(rom,rows);forms={};asm={}
    for text in sources.values():
        for m in CASE.finditer(text):
            pc=int(m[1],16);asm[pc]=' '.join(m[2].split());forms[pc]=(generate.form(m[2]),rows[pc][0],mould(m[3]))
    route={pc for pc,_ in generate.route_keys()['keys']['TmsBlock']}
    executed=route|set(generate.verified())|generate.EXTERNAL_PCS
    (static,_),_,_=generate.closures(rom,rows,executed)
    return forms,asm,set(static)-executed,route


def certificate(forms,asm,residue,route):
    exercised={forms[pc] for pc in route};ran={k[2] for k in exercised};by=collections.defaultdict(list)
    for pc in sorted(residue):by[forms[pc]].append(pc)
    never=[dict(form=k[0],bits=k[1],mould=k[2],translated='o.Reject("untranslated TMS form"' not in k[2],
                mould_on_routes=k[2] in ran,pcs=len(v),   # the same mould ran under another operand shape, field or size
                examples=[f'{pc:08x} {asm[pc]}' for pc in v[:3]]) for k,v in by.items() if k not in exercised]
    never.sort(key=lambda r:(-r['translated'],-r['pcs'],r['form']))
    count=lambda rows:dict(forms=len(rows),pcs=sum(r['pcs'] for r in rows))
    return dict(residue=dict(pcs=len(residue),forms=len(by)),route=dict(blocks=len(route),forms=len(exercised)),
                residue_forms_exercised_on_routes=dict(forms=len(by)-len(never),pcs=len(residue)-sum(r['pcs'] for r in never)),
                never_exercised=dict(translated=count([r for r in never if r['translated']]),
                                     untranslated=count([r for r in never if not r['translated']]),forms=never),
                residue_pcs_with_every_form_exercised=len(residue)-sum(r['pcs'] for r in never))


def latest(pattern):
    """The receipt of M2 with the highest round number in `pattern` (one group), or None."""
    found=[(int(m[1]),p) for p in M2.glob('*.json') if (m:=re.fullmatch(pattern,p.name))]
    return max(found)[1] if found else None


def forms_report(report=FORMS):
    residue=latest(r'k(\d+)-residue\.json');counted=residue and json.loads(residue.read_text('utf-8'))['denominators']['residue_pcs']
    out=dict(schema='mk3-form-certificate/1',at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
             method=' '.join(__doc__.split('forms [--report F]: ')[1].split('report --out')[0].split()),
             identities=dict(program_sha256=generate.PROGRAM['sha256'],route_verified_sha256=sha(generate.ROUTES),
                             routes=generate.route_keys()['routes'],generator_sha256=sha(generate.__file__),
                             emitter_sha256=sha(generate.emitter.__file__)),
             **certificate(*inputs()))
    out['residue_receipt']=residue and dict(path=residue.relative_to(ROOT).as_posix(),residue_pcs=counted,same_count=counted==out['residue']['pcs'])
    out['counting']='static measure counted apart; an exercised form promotes no residue PC to verified'
    Path(report).write_text(json.dumps(out,indent=1)+'\n',encoding='utf-8')
    return out


def delivery(forms=FORMS):
    """(markdown, data) of the delivery report, from the receipts on disk."""
    load=lambda p:json.loads(Path(p).read_text('utf-8')) if p and Path(p).is_file() else None
    rel=lambda p:p and (Path(p).relative_to(ROOT).as_posix() if Path(p).is_relative_to(ROOT) else str(p))
    rv=load(generate.ROUTES);rv_sha=sha(generate.ROUTES)
    ip,rp,mp=latest(r'k(\d+)-integration\.json'),latest(r'k(\d+)-residue\.json'),latest(r'rm2-r(\d+)\.json')
    integ,res,rm,inst,fc=load(ip),load(rp),load(mp),load(INSTALL),load(forms)
    den=res['denominators'];classified={k:dict(entries=len(v['entries']),pcs=v['pcs']) for k,v in res['classified'].items()}
    cpcs=sum(v['pcs'] for v in classified.values());cent=sum(v['entries'] for v in classified.values())
    stale=[]
    if integ.get('route_verified_sha256')!=rv_sha:stale.append(f'{rel(ip)} names route_verified {str(integ.get("route_verified_sha256"))[:12]}, the file is {rv_sha[:12]}')
    if integ.get('receipts')!=len(rv['routes']):stale.append(f'{rel(ip)} has {integ.get("receipts")} receipts, route_verified.json {len(rv["routes"])} routes')
    if res.get('route_receipts')!=len(rv['routes']):stale.append(f'{rel(rp)} counted {res.get("route_receipts")} receipts, route_verified.json {len(rv["routes"])} routes')
    if rm['matrix']['routes']!=len(rv['routes']) or (rm.get('matrix_scope') or {}).get('partial'):
        stale.append(f'{rel(mp)} is a partial or older matrix ({rm["matrix"]["routes"]} routes, route_verified.json {len(rv["routes"])})')
    if inst and inst['package'].get('units_sha256')!=integ.get('units_sha256'):stale.append('installed units differ from the integration units')
    if fc is None:stale.append(f'form certificate {rel(forms)} missing')
    elif fc['identities']['route_verified_sha256']!=rv_sha or fc['residue']['pcs']!=den['residue_pcs']:stale.append(f'{rel(forms)} was made for another route_verified.json or residue')
    passed=bool(integ.get('passed') or integ.get('passed_after_rerun'))
    data=dict(schema='mk3-delivery-report/1',at=datetime.datetime.now().astimezone().isoformat(timespec='seconds'),
        sources=dict(route_verified=rel(generate.ROUTES),integration=rel(ip),residue=rel(rp),remaster=rel(mp),install=rel(INSTALL),forms=rel(forms)),
        program_sha256=rv['program_sha256'],route_verified_sha256=rv_sha,units_sha256=integ.get('units_sha256'),
        routes=[dict(name=r['name'],receipt_sha256=r['receipt_sha256']) for r in rv['routes']],
        verified_on_routes={k:len(rv.get(k,[])) for k in generate.KINDS},verified_in_lot=dict(TmsPcs=den['lot_measured_pcs']),
        integration=dict(date=integ.get('date'),passed=passed,first_pass=integ.get('passed'),rerun=integ.get('rerun') and {k:integ['rerun'][k] for k in ('lane','step','cause') if k in integ['rerun']},
                         lanes={k:v.get('passed') for k,v in integ.get('lanes',{}).items()}),
        residue=dict(counted_as='not verified',pcs=den['residue_pcs'],entries=den['entries'],without_entry_from_executed=den['residue_pcs_without_entry_from_executed'],
                     pointer_candidate_only_pcs=den['pointer_candidate_only_pcs'],classified=dict(pcs=cpcs,entries=cent,by_class=classified),
                     unclassified=dict(pcs=den['residue_pcs']-cpcs,entries=den['entries']-cent),by_reader=res['classes']),
        forms=fc and dict(counting=fc['counting'],residue=fc['residue'],exercised=fc['residue_forms_exercised_on_routes'],
                          never_exercised={k:fc['never_exercised'][k] for k in ('translated','untranslated')},
                          never_exercised_forms=[{k:r[k] for k in ('form','bits','pcs','translated','mould_on_routes','examples')} for r in fc['never_exercised']['forms']]),
        remaster=dict(milestone=rm.get('milestone'),matrix=rm['matrix'],matrix_passed=rm.get('matrix_passed'),windows_passed=rm.get('windows_passed'),
                      partial=bool((rm.get('matrix_scope') or {}).get('partial')),pngs=[p['path'] for p in rm.get('pngs',[])]),
        install=inst and dict(passed=inst.get('passed'),label=inst.get('label'),executable_sha256=inst['package'].get('executable_sha256'),
                              units_sha256=inst['package'].get('units_sha256'),launcher_sha256=inst.get('launcher_sha256')),
        open=[f'resíduo sem classe: {den["residue_pcs"]-cpcs} PCs em {den["entries"]-cent} entradas',
              *[f'resíduo, classe aberta "{k}": {v["pcs"]} PCs em {v["entries"]} entradas' for k,v in classified.items() if 'incomplete' in k or k.startswith('legal')],
              *([f'formas traduzidas nunca exercitadas em rota: {fc["never_exercised"]["translated"]["forms"]} ({fc["never_exercised"]["translated"]["pcs"]} PCs)'] if fc else []),
              *rm.get('open',[])],
        limits=['Remasterizada com a música original (RM3 sem assets de MK3 em music/)',
                'minijogo 642468 em vizinho mais próximo (sem classe própria na camada 2)'],
        stale=stale)
    v,r,f=data['verified_on_routes'],data['residue'],data['forms']
    md=[f'# MK3 rev. 2.1 nativo: relatório de entrega ({data["at"][:10]})','',
        f'Programa `{data["program_sha256"]}`. Unidades `{data["units_sha256"]}`. `route_verified.json` `{rv_sha}`.','',
        '## Verificado em rota (igual ao Original desde o reset)','',
        f'{len(data["routes"])} rotas. '+', '.join(f'{k} {n}' for k,n in v.items())+'.',
        f'Integração {rel(ip)} ({data["integration"]["date"]}): {"passou" if passed else "NÃO passou"}'
        +(f'; refeito: {data["integration"]["rerun"]["step"]} ({data["integration"]["rerun"]["cause"]})' if data['integration']['rerun'] else '')+'.','',
        '## Verificado em lote (contado à parte)','',f'{den["lot_measured_pcs"]} PCs do TMS medidos em lote.','',
        '## Resíduo (não verificado)','',
        f'{r["pcs"]} PCs traduzidos que nenhuma rota executou, em {r["entries"]} entradas ({r["without_entry_from_executed"]} PCs sem entrada vinda de código executado). '
        f'Com classe: {cpcs} PCs em {cent} entradas; sem classe: {r["unclassified"]["pcs"]} PCs em {r["unclassified"]["entries"]} entradas. Classe não é verificação.','',
        '| Classe | Entradas | PCs |','|---|---|---|',*[f'| {k} | {x["entries"]} | {x["pcs"]} |' for k,x in sorted(classified.items(),key=lambda i:-i[1]['pcs'])],'',
        '## Certificado de formas (medida estática, contada à parte)','']
    if f:
        md+=[f'{f["residue"]["forms"]} formas nas {f["residue"]["pcs"]} instruções do resíduo; {f["exercised"]["forms"]} formas ({f["exercised"]["pcs"]} PCs) já rodaram em rota igual ao Original. '
             f'Nunca exercitadas: {f["never_exercised"]["translated"]["forms"]} formas traduzidas ({f["never_exercised"]["translated"]["pcs"]} PCs) e '
             f'{f["never_exercised"]["untranslated"]["forms"]} sem tradução ({f["never_exercised"]["untranslated"]["pcs"]} PCs, rejeição explícita). Nada disso promove PC a verificado.','',
             '| Forma | Bits | PCs | Exemplo |','|---|---|---|---|',
             *[f'| `{x["form"]}`{"" if x["translated"] else " (sem tradução)"} | {x["bits"]} | {x["pcs"]} | `{x["examples"][0]}` |' for x in f['never_exercised_forms']],'']
    else:md+=['Certificado ausente.','']
    m=data['remaster']['matrix']
    md+=['## Remasterizada (camada 2)','',
         f'{rel(mp)}{" (matriz parcial)" if data["remaster"]["partial"] else ""}: {m["canonical_equal"]}/{m["routes"]} rotas com canônico igual em {m["frames"]} quadros, '
         f'unclassified_draws {m["bound"]["unclassified_draws"]}, objetos em vizinho mais próximo {m["bound"]["world_draws"]}.','',
         '## Instalado','',(f'`{data["install"]["label"]}`, exe `{data["install"]["executable_sha256"]}`, unidades `{data["install"]["units_sha256"]}`.' if inst else 'Sem recibo de instalação.'),'',
         '## Abertos','',*[f'- {x}' for x in data['open']],'','## Limites conhecidos','',*[f'- {x}' for x in data['limits']],'',
         '## Recibos em desacordo','',*([f'- {x}' for x in stale] or ['Nenhum.']),'',
         '## Rotas e hashes dos recibos','',*[f'- {x["name"]} `{x["receipt_sha256"][:16]}`' for x in data['routes']],'']
    return '\n'.join(md),data


def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('forms').add_argument('--report',type=Path,default=FORMS)
    rp=sub.add_parser('report');rp.add_argument('--out',type=Path,required=True);rp.add_argument('--forms',type=Path,default=FORMS)
    a=ap.parse_args()
    if a.cmd=='forms':
        out=forms_report(a.report);print(json.dumps({k:v for k,v in out.items() if k!='method'},indent=1));return 0
    md,data=delivery(a.forms)
    a.out.write_text(md,encoding='utf-8');a.out.with_suffix('.json').write_text(json.dumps(data,indent=1,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(markdown=str(a.out),bytes=len(md.encode()),stale=data['stale'],open=len(data['open'])),indent=1));return 0


if __name__=='__main__':raise SystemExit(main())
