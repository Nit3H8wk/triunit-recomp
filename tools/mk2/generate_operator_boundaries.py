"""Emit comparison guards from the digests of the original operator-boundary observations.

The repository keeps only `operator_boundary_digests.json` (cycles, PCs, trace-row counts, deadlines and the SHA-256
of each selected CPU34/DSP76 row, tools/mk2/oracle_digest.py). The raw rows are regenerated locally by the oracle
(tools/mk2/operator_reference.py: pinned MAME + the user's ROMs); `digest_manifest` turns such a raw capture manifest
(families -> DIP -> cpu34/dsp76 lists) into the versioned digest form:

    python tools/mk2/generate_operator_boundaries.py --from-raw RAW_OPERATOR.json RAW_CREDIT.json
"""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.mk2.oracle_digest import cpu34_digest, words_digest

ROOT=Path(__file__).resolve().parents[2]
MANIFEST=Path(__file__).with_name('operator_boundary_digests.json')
OUTPUT=ROOT/'native/mk2/mk2_operator_boundaries.hpp'
STAGES=['Text','Post','Reset','Button','Irq','Startup','Yield','Setup','Trap','Dma','Draw','StartupDi']
PCS=[0xffa5a6e0,0xffa5b090,0xff811340,0xff815090,0xff8114d0,0xff811710,None,None,0xff8044f0,0xff804630,None,None]
FAMILIES=('variants','freeplay_variants','credit_insufficient_variants','credit_eligible_variants')
DSWS=(0xfc7d,0xbc7d,0x7c7d,0x3c7d)
FACTS=('draw_trace_rows','dispatcher_trace_rows','video_irq_trace_rows','sport_deadline')


def select(cpu34):
    """Indices of the twelve guarded boundaries inside one raw CPU34 trace of the Original."""
    yields=[n for n,cpu in enumerate(cpu34) if cpu[0]==0xff80dd30]
    indices=[]
    for n,pc in enumerate(PCS):
        if n in (6,7,10):index=yields[{6:0,7:1,10:-1}[n]]
        elif n==11:index=next(i for i,cpu in enumerate(cpu34) if 6854000<cpu[2]<6855500)
        else:index=next(i for i,cpu in enumerate(cpu34) if cpu[0]==pc)
        indices.append(index)
    return indices


def digest_manifest(operator_raw,credit_raw):
    """Raw oracle manifests (never versioned) -> digest-only manifest (versioned)."""
    raw=dict(operator_raw);raw.update(credit_raw)
    out={'serialization':'SHA-256 of consecutive 8-byte little-endian words; CPU34 = next PC, ST, cycles, A0..A15, '
                         'B0..B14; DSP76 = AdspBoot::Registers() as observed by MAME (native compares with DSP76[1]-1)',
         'provenance':{'operator':{k:operator_raw[k] for k in ('scope','mame_sha256') if k in operator_raw},
                       'startup_credit':credit_raw.get('provenance',{})},
         'stages':STAGES}
    for family in FAMILIES:
        out[family]={}
        for dsw in DSWS:
            variant=raw[family][str(dsw)]
            boundaries={}
            for stage,index in zip(STAGES,select(variant['cpu34'])):
                cpu=variant['cpu34'][index]
                boundaries[stage]={'pc':cpu[0],'cycle':cpu[2],'cpu34_sha256':cpu34_digest(cpu),
                                   'dsp76_sha256':words_digest(variant['dsp76'][index])}
            entry={'boundaries':boundaries}
            entry.update({k:variant[k] for k in FACTS if k in variant})
            out[family][str(dsw)]=entry
    return out


def load():
    return json.loads(MANIFEST.read_text(encoding='utf8'))


def profiles():
    return [(family,dsw) for family in FAMILIES for dsw in DSWS]


def generate():
    manifest=load()
    rows=[manifest[family][str(dsw)]['boundaries'] for family,dsw in profiles()]
    source='''#pragma once
#include "mk2_oracle_digest.hpp"
#include "mk2_reset.hpp"
namespace mk2 {
// Original MAME0.280 CPU34/DSP76 digests; tools/mk2/operator_reference.py regenerates the raw rows locally.
// Comparisons only: no register, memory or clock is assigned from this evidence.
enum class OperatorBoundary:unsigned {'''+','.join(STAGES)+'''};
inline bool OperatorDswSupported(uint16_t dsw){return (dsw&0x3fff)==0x3c7d;}
inline unsigned OperatorDswVariant(uint16_t dsw){if(!OperatorDswSupported(dsw))throw std::runtime_error("unsupported MK2 operator DIP");return unsigned(!(dsw&0x4000))+unsigned(!(dsw&0x8000));}
inline unsigned OperatorDswProfile(uint16_t dsw){if(!OperatorDswSupported(dsw))throw std::runtime_error("unsupported MK2 operator DIP");return ((~unsigned(dsw))>>14)&3;}
inline unsigned OperatorProfileIndex(uint16_t dsw,unsigned profile){if(profile>=4)throw std::runtime_error("unsupported MK2 startup profile");return OperatorDswProfile(dsw)+profile*4;}
inline bool OperatorFreePlay(const ResetTrace& s){if(s.cmos.size()!=8192)return false;for(unsigned n=0;n<4;++n)if(uint8_t(s.cmos[0x848+n]))return true;return false;}
// Firmware FFA53BA0: Free Play, then unsigned credit byte vs parameter 0B.
inline unsigned OperatorStartupProfile(const ResetTrace& s){if(OperatorFreePlay(s))return 1;if(s.cmos.size()!=8192)return 0;const auto credits=uint8_t(s.cmos[0x10e]);if(!credits)return 0;uint32_t price=0;for(unsigned n=0;n<4;++n)price=(price<<8)|uint8_t(s.cmos[0x82c+n]);return credits<price?2:3;}
'''
    source+='inline uint64_t OperatorCycle(uint16_t dsw,OperatorBoundary stage,unsigned profile=0){\n static constexpr uint64_t expected[16][12]={\n'
    source+=''.join(' {'+','.join(str(row[stage]['cycle'])+'ull' for stage in STAGES)+'},\n' for row in rows)
    source+=' };\n return expected[OperatorProfileIndex(dsw,profile)][unsigned(stage)];\n}\n'
    for kind,field in [('Cpu','cpu34_sha256'),('Dsp','dsp76_sha256')]:
        source+=f'inline const char* Operator{kind}Digest(uint16_t dsw,OperatorBoundary stage,unsigned profile=0){{\n static constexpr const char* expected[16][12]={{\n'
        source+=''.join(' {\n'+''.join('  "'+row[stage][field]+'",\n' for stage in STAGES)+' },\n' for row in rows)
        source+=' };\n return expected[OperatorProfileIndex(dsw,profile)][unsigned(stage)];\n}\n'
    source+='''inline bool OperatorHorizon(uint64_t horizon,OperatorBoundary stage){for(unsigned profile=0;profile<4;++profile)for(uint16_t dsw:{uint16_t(0xfc7d),uint16_t(0xbc7d),uint16_t(0x7c7d),uint16_t(0x3c7d)})if(horizon==OperatorCycle(dsw,stage,profile))return true;return false;}
inline bool OperatorCreditStartupHorizon(uint64_t horizon){for(unsigned profile:{2u,3u})for(uint16_t dsw:{uint16_t(0xfc7d),uint16_t(0xbc7d),uint16_t(0x7c7d),uint16_t(0x3c7d)})if(horizon==OperatorCycle(dsw,OperatorBoundary::Setup,profile))return true;return false;}
inline bool OperatorCpuBoundary(const ResetTrace& s,OperatorBoundary stage){if(!OperatorDswSupported(s.board.dip_switches))return false;return Cpu34Is(s,OperatorCpuDigest(s.board.dip_switches,stage,OperatorStartupProfile(s)));}
// MAME's concurrent terminal cycle cache is one instruction behind; native uses executed cycles.
inline bool OperatorDspBoundary(const std::vector<uint64_t>& actual,uint16_t dsw,OperatorBoundary stage,unsigned profile=0){return actual.size()==76&&Dsp76Digest(actual,true)==OperatorDspDigest(dsw,stage,profile);}'''
    fields=[('SportDeadline','sport_deadline'),('DrawInstructions','draw_trace_rows'),('DispatcherInstructions','dispatcher_trace_rows')]
    for name,field in fields:
        values=[]
        for family,dsw in profiles():
            value=manifest[family][str(dsw)].get(field)
            if value is None and field=='dispatcher_trace_rows':value=11248+5*((not(dsw&0x4000))+(not(dsw&0x8000)))
            values.append(str(value)+'ull')
        source+=f'\ninline uint64_t Operator{name}(uint16_t dsw,unsigned profile=0){{static constexpr uint64_t expected[]={{'+','.join(values)+'};return expected[OperatorProfileIndex(dsw,profile)];}\n'
    source+='}\n'
    return source


if __name__=='__main__':
    if sys.argv[1:2]==['--from-raw'] and len(sys.argv)==4:
        manifest=digest_manifest(*(json.loads(Path(p).read_text(encoding='utf8')) for p in sys.argv[2:4]))
        MANIFEST.write_text(json.dumps(manifest,indent=1)+'\n',encoding='utf-8',newline='\n')
    elif len(sys.argv)>1:raise SystemExit('usage: generate_operator_boundaries.py [--from-raw RAW_OPERATOR.json RAW_CREDIT.json]')
    OUTPUT.write_text(generate(),encoding='utf-8',newline='\n')
