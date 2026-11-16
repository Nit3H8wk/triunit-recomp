"""J1 front A receipt (build/native/mk3-m2/j1-tms.json): whole-image TMS candidate of tools/mk3/generate.py.

Records the single aligned scan, the candidate (measured / closure of vectors + measured / pointer candidates only),
cases emitted and pending forms, computed-transfer sites, the identity of the measured-only emission against the
committed .inc slices it replaces (git HEAD, read-only), cold and cached builds of the reset driver, and a Game
profile probe: the whole board (mk3::Board with the DCS and DMA) from reset until the first rejection or a cycle
bound, with the compact first-execution counts. The probe is an observation of the candidate, not a comparison
with the Original. Test outcomes are added with --test NAME=SECONDS (after the tests ran).
"""
from pathlib import Path
import argparse,json,os,re,subprocess,sys,time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q,cpp_build
from tools.setup import mk3 as setup_mk3
from tools.mk3 import generate,reference,reference_dma,roms

ROOT=Path(__file__).resolve().parents[2]
RECEIPT=ROOT/'build/native/mk3-m2/j1-tms.json'
FORMER=('cmos_check','pic_check','init','text','serial','sound','eint','frame','frames','dma_frames')
CASE=re.compile(r'^case 0x([0-9a-f]{8})u: \{ // [^\n]*\n.*?^\}\n',re.M|re.S)
PROBE=r'''#include "mk3_board.hpp"
#include "mk3_dcs.hpp"
#include <cstdio>
#include <fstream>
#include <iterator>
int wmain(int, wchar_t** argv) try {
    const auto program = mk3::LoadProgram(argv[1]);
    std::ifstream seed(argv[2], std::ios::binary);
    const std::vector<uint8_t> cmos{std::istreambuf_iterator<char>(seed), std::istreambuf_iterator<char>()};
    std::vector<uint8_t> gfx; std::ifstream list(argv[3]); std::string path;
    for (size_t offset, size; list >> offset >> size && std::getline(list >> std::ws, path);) {
        std::ifstream rom(path, std::ios::binary); std::vector<char> data(size); rom.read(data.data(), std::streamsize(size));
        if (gfx.size() < (offset & ~size_t(3)) + 4 * size) gfx.resize((offset & ~size_t(3)) + 4 * size);
        for (size_t i = 0; i < size; ++i) gfx[offset + 4 * i] = uint8_t(data[i]);
    }
    mk3::FirstExecution log;
    const auto u2 = mk3::LoadDcsU2(argv[1]);   // the Board keeps references to its images
    mk3::Board b(program, cmos, u2, gfx);
    b.SetProfile(mk3::Profile::Game, &log);
    b.o.profile = mk3::Profile::Game; b.o.first = &log;   // the Ops profile (Board::SetProfile does not set it yet)
    const uint64_t bound = std::stoull(argv[4]);
    b.stop = [&](const mk3::Board& board) { return board.Cycles() >= bound; };
    std::string why = "cycle bound";
    try { b.Run(); } catch (const std::exception& e) { why = e.what(); }
    unsigned counts[7] = {};
    for (const auto& e : log.order) ++counts[unsigned(e.kind)];
    std::printf("{\"stop\":\"%s\",\"pc\":%u,\"cycles\":%llu,\"instructions\":%llu,\"first_executions\":[%u,%u,%u,%u,%u,%u,%u],\"dcs_frontier\":\"%s\"}\n",
                why.c_str(), b.s.pc, (unsigned long long)b.Cycles(), (unsigned long long)b.s.instructions, counts[0], counts[1], counts[2], counts[3],
                counts[4], counts[5], counts[6], b.dcs_frontier.c_str());
    return 0;
} catch (const std::exception& e) { std::printf("{\"setup_error\":\"%s\"}\n", e.what()); return 0; }
'''

def former_emission(text):
    """Measured-only emission now vs the committed slices it replaces (identical case text, except checked edges)."""
    old={}
    for name in FORMER:
        source=subprocess.run(['git','show',f'HEAD:native/mk3/mk3_{name}.inc'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8')
        for m in CASE.finditer(source.replace('\r\n','\n')):old[int(m[1],16)]=m[0]
    new={int(m[1],16):m[0] for source in text.values() for m in CASE.finditer(source)}
    changed=[pc for pc in old if new.get(pc)!=old[pc]]
    edges=[pc for pc in changed if 'o.Reject("unobserved branch"' in old[pc] and 'o.Edge(' in new.get(pc,'')]
    left=sum(source.count('o.Reject("unobserved branch"') for source in text.values())
    return dict(former_cases=len(old),identical=len(old)-len(changed),changed_only_by_checked_edges=len(edges),
                other_changes=len(changed)-len(edges),unobserved_branch_rejections_left=left)

def builds(rows):
    """Reset driver: cold (no cache), then twice with the cache (the second is the incremental case)."""
    out=[];env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
    for label,cache in (('cold_no_cache',False),('cache_first',None),('cache_incremental',None)):
        with q.scratch_tree() as (temp,cleanup):
            units,_=generate.write(temp,generate_rom(),rows)
            sources=[ROOT/'native/tests/mk3_reset_tests.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp']
            result=cpp_build.build(q.DEFAULT_CC,[*generate.FLAGS,'-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/mk2'),setup_mk3.include()],
                                   [*sources,*units],['-lbcrypt'],temp/'mk3-reset.exe',temp,env=env,timeout=1800,use_cache=cache,compile_from_scratch=True)
            cc=result['compiler_cache']
            out.append(dict(build=label,passed=result['passed'],wall_seconds=round(result['wall_seconds'],1),translation_units=len(sources)+len(units),
                            cache_hits=cc['hits'],cache_misses=cc['misses'],cache_bytes=cc['bytes'],cache_limit_bytes=cc['limit_bytes'],
                            slowest_unit_seconds=round(max(u['wall_seconds'] for u in result['build_units']),1)))
        out[-1]['cleanup']=dict(exists_after=cleanup['exists_after'])
    return out

def probe(rows,bound):
    env={'PATH':str(q.DEFAULT_CC.parent)+os.pathsep+os.environ['PATH']}
    with q.scratch_tree() as (temp,cleanup):
        (temp/'probe.cpp').write_text(PROBE,encoding='utf-8')
        units,_=generate.write(temp,generate_rom(),rows);exe=temp/'probe.exe'
        sources=[temp/'probe.cpp',ROOT/'native/mk3/mk3_adsp.cpp',*(ROOT/'native/mk3'/n for n in generate.RUNTIME),ROOT/'native/mk2/mk2_dcs.cpp',ROOT/'native/src/mk5_program.cpp']
        build=cpp_build.build(q.DEFAULT_CC,[*generate.FLAGS,'-I'+str(ROOT/'native/include'),'-I'+str(ROOT/'native/mk3'),'-I'+str(ROOT/'native/mk2'),setup_mk3.include()],
                              [*sources,*units],['-lbcrypt'],exe,temp,env=env,timeout=1800,compile_from_scratch=True)
        if not build['passed']:return dict(built=False,output_tail=build['stdout'][-1500:])
        (temp/'gfx.txt').write_text(''.join(f'{o} {s} {p}\n' for p,o,s in reference_dma.graphics_rows()),encoding='utf-8')
        run=q.command([exe,ROOT/'roms/mk3',reference.SEED,temp/'gfx.txt',str(bound)],temp,cwd=ROOT,env=env,timeout=1800)
        result=json.loads(run['stdout'].strip().splitlines()[-1]) if run['passed'] and run['stdout'].strip() else dict(exit_code=run.get('exit_code'),output_tail=run['stdout'][-1500:])
        result['run_seconds']=round(run['wall_seconds'],1)
    kinds=('TmsBlock','TmsEdge','AdspBlock','AdspEdge','DmaPath','IrqPath','DevicePath')
    if 'first_executions' in result:result['first_executions']=dict(zip(kinds,result['first_executions']))
    result['cleanup']=dict(exists_after=cleanup['exists_after']);result['bound_cycles']=bound
    return result

def generate_rom():return roms.program_image(ROOT/'roms/mk3',roms.definition())

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test',action='append',default=[],help='NAME=SECONDS of a passed test, added to the receipt')
    parser.add_argument('--probe-cycles',type=int,default=120_000_000)
    a=parser.parse_args()
    if a.test:
        data=json.loads(RECEIPT.read_text('utf-8'))
        for item in a.test:name,seconds=item.split('=');data.setdefault('tests',{})[name]=dict(passed=True,wall_seconds=float(seconds))
        RECEIPT.write_text(json.dumps(data,indent=1)+'\n',encoding='utf-8');return 0
    rom=generate_rom();started=time.perf_counter();rows,proof=generate.scan(rom);scanned=time.perf_counter()
    text,receipt=generate.units(rom,rows)
    data=dict(format='MK3_J1_TMS_V1',program_sha256=generate.PROGRAM['sha256'],
              scan=dict(positions=proof['positions'],truncated=proof['truncated'],calls=proof['calls'],decoder_sha256=proof['decoder_sha256'],
                        decoder_build_seconds=round(proof['compile_seconds'],2),decode_seconds=round(proof['decode_seconds'],2),
                        wall_seconds=round(scanned-started,2),cleanup=dict(exists_after=proof['cleanup']['exists_after'])),
              candidate=receipt,
              units=dict(files=len(text),bytes=sum(len(t) for t in text.values()),lines=sum(t.count('\n') for t in text.values())),
              measured_emission=former_emission(text),
              builds=builds(rows),game_probe=probe(rows,a.probe_cycles),
              counting_rule='verified = measured PCs compared with the Original; emitted-unverified and pointer-candidate PCs are not coverage')
    RECEIPT.parent.mkdir(parents=True,exist_ok=True);RECEIPT.write_text(json.dumps(data,indent=1)+'\n',encoding='utf-8')
    print(json.dumps({k:data[k] for k in ('scan','measured_emission','builds','game_probe')},indent=1))
    return 0

if __name__=='__main__':raise SystemExit(main())
