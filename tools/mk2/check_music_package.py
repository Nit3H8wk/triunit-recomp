"""MK2 Remastered music slots: music.json agrees with the compiled table; optional published first-fight check.

    python tools/mk2/check_music_package.py            # table check only (no ROM, no package)
    python tools/mk2/check_music_package.py --published  # also run the installed package in both modes
"""
from pathlib import Path
import argparse,hashlib,json,re,sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from tools.quality import run as q

HEADER=q.ROOT/'native/runtime/mk2_music_manifest.hpp'
RECIPE=Path(__file__).with_name('music.json')
CUSTOM=q.ROOT/'custom_audio/mk2'


def table():
    """(slots, [(command, slot index)]) parsed from the compiled header."""
    text=HEADER.read_text()
    slots=re.findall(r'"(music-\d\d)"',text.split('music_slots')[1].split('}};')[0])
    cues=[(int(c),int(s))for c,s in re.findall(r'\{(\d+),(\d+)\}',text.split('music_cues')[1].split('}};')[0])]
    return slots,cues


def consistency():
    recipe=json.loads(RECIPE.read_text())
    slots,cues=table()
    expected=[(command,index)for index,row in enumerate(recipe['slots'])for command in row['commands']]
    if slots!=[row['slot']for row in recipe['slots']]or cues!=expected:raise ValueError('music.json differs from mk2_music_manifest.hpp')
    if len({c for c,_ in cues})!=len(cues):raise ValueError('a DCS command maps to two slots')
    return {'slots':len(slots),'commands':len(cues)}


def published():
    from tools.mk2 import native
    product=q.ROOT/'build/native/mk2-native-v1/product'
    fields=dict(line.split('=',1)for line in(product/'native-package.ini').read_text().splitlines())
    executable=product/fields['executable'];digest=q.sha(executable)
    assert digest==fields['executable_sha256']
    report={'executable_sha256':digest,'modes':{}};observations=[]
    with q.scratch_tree()as(scratch,cleanup):
        for mode in ('original','remastered'):
            env={'MK1_MUSIC_MODE':mode,'MK1_GAME_VOLUME':'0','MK1_FULLSCREEN':'0','MK1_AUDIO_LATENCY':'balanced','MK1_GRAPHICS_VALIDATE':'1'}
            if mode=='remastered':env['MK1_MUSIC_DIRECTORY']=str(CUSTOM)
            result=q.command([executable,product/'roms','--window','--audio','--through','first-fight'],scratch,env=env,timeout=120,output_limit=256*1024)
            assert result['passed']and not result['discarded_output_bytes'],q.compact(result)
            observed,events=native.diagnostic_output(result['stdout']);native.validate_boundary(observed,'first-fight')
            audio=observed['audio']
            assert not events and audio['underruns']==audio['music_clipped']==0
            assert audio['channels']==(2 if mode=='remastered'else 1)and audio['music_mode']==mode
            report['modes'][mode]={'audio':audio,'frames':observed['frames'],
                'frame_hash_sequence_sha256':hashlib.sha256(json.dumps(observed['frame_sha256']).encode()).hexdigest()}
            observations.append(observed)
        assert observations[0]['cpu34']==observations[1]['cpu34']
        assert observations[0]['frame_sha256']==observations[1]['frame_sha256']
    assert not cleanup['exists_after']
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--published',action='store_true');args=parser.parse_args()
    report={'table':consistency()}
    if args.published:report['published']=published()
    print('PASS',json.dumps(report)[:2000])
    return 0


if __name__=='__main__':raise SystemExit(main())
