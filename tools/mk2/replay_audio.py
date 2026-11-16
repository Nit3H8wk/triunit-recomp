"""Full DAC/speaker/PCM comparison in bounded memory; raw files stay in case scratch."""
import hashlib
import json
import struct
from tools.mk2 import dac_reference


def native_source(text):
    marker='mk2::Scanout scanout;uint64_t samples=0;float peak=0;'
    assert text.count(marker)==1
    text=text.replace(marker,marker+'''
        uint64_t source_count=0,speaker_count=0,pcm_count=0;
        std::ofstream source_file(output/"native-source.bin",std::ios::binary);
        std::ofstream speaker_file(output/"native-speaker.bin",std::ios::binary);
        std::ofstream pcm_file(output/"native-pcm16.bin",std::ios::binary);
        if(!source_file || !speaker_file || !pcm_file)throw std::runtime_error("Replay audio output unavailable");
        mk5audio::WilliamsResampler resampler(31250);
        mk2::DcsAudio audio([&](const int16_t* p,size_t count){
            pcm_file.write(reinterpret_cast<const char*>(p),count*sizeof(*p));pcm_count+=count;
        });''')
    marker='[&](uint64_t,const float* pcm,size_t count){'
    assert text.count(marker)==1
    text=text.replace(marker,'''[&](uint64_t first,const float* pcm,size_t count){
            if(first!=source_count)throw std::runtime_error("Replay absolute DAC sample gap/overlap");
            source_file.write(reinterpret_cast<const char*>(pcm),count*sizeof(*pcm));
            audio.Feed(first,pcm,count);
            for(size_t n=0;n<count;++n){
                resampler.Push(pcm[n]);++source_count;
                while(speaker_count*31250<=(source_count-1)*48000){
                    const float value=resampler.Sample(speaker_count++);
                    speaker_file.write(reinterpret_cast<const char*>(&value),sizeof(value));
                }
            }''')
    marker='        std::cout<<"{\\\"passed\\\":true,\\\"gameplay_qualified\\\":false,\\\"cycles\\\":"<<s.cycles'
    assert text.count(marker)==1
    text=text.replace(marker,'''        if(!source_count || speaker_count!=(source_count-1)*48000/31250+1 || pcm_count!=speaker_count ||
           audio.SourceSamples()!=source_count || audio.OutputSamples()!=speaker_count)
            throw std::runtime_error("Replay complete audio cardinality differs; DAC "+std::to_string(source_count)+
                "; speaker "+std::to_string(speaker_count)+"; PCM "+std::to_string(pcm_count));
        source_file.close();speaker_file.close();pcm_file.close();
        if(!source_file || !speaker_file || !pcm_file)throw std::runtime_error("Replay audio close failed");
'''+marker)
    return text


def original_lua(lua,cycles):
    template=dac_reference.LUA
    assert template.count('local dac=assert')==1 and template.count('mk2_audio_stop_subscription')==1
    body='local dac=assert'+template.split('local dac=assert',1)[1].split('mk2_audio_stop_subscription',1)[0]
    assert body.count('first==1875 and #blocks==3')==1
    body=body.replace('first==1875 and #blocks==3','first==7500 and #blocks==12')
    stop='replay_audio_stop'+template.split('mk2_audio_stop_subscription',1)[1]
    stop=stop.replace('    tap:remove();assert(frame)\n','').replace('assert(source_end==6251)',f'assert(source_end=={cycles*16//2000000*625+1})')
    stop=stop.replace('ipairs(events)','ipairs({})')
    return lua+'\nlocal machine=m\n'+body+stop


class SampleMismatch(ValueError):
    def __init__(self, stream, sample_index, native, original):
        super().__init__(f'{stream} differs at sample {sample_index}')
        self.difference = {'stream': stream, 'sample_index': sample_index,
                           'native_bits_le': native.hex(), 'original_bits_le': original.hex()}


def require_equal_samples(native, original, width, offset, stream):
    if len(native) != len(original) or len(native) % width:
        raise ValueError(f'{stream}: incomplete sample block')
    if native != original:
        start = next(n for n in range(0, len(native), width)
                     if native[n:n+width] != original[n:n+width])
        raise SampleMismatch(stream, offset + start // width, native[start:start+width], original[start:start+width])


def compare_float_files(actual,expected,count,label):
    if actual.stat().st_size!=count*4 or expected.stat().st_size!=count*4:
        raise ValueError(label+': incomplete/extra samples')
    digest=hashlib.sha256();nonzero=0;offset=0
    with actual.open('rb')as a,expected.open('rb')as b:
        while True:
            left=a.read(65536);right=b.read(65536)
            require_equal_samples(left,right,4,offset,label)
            if not left:break
            digest.update(left);nonzero+=sum(v!=0 for v, in struct.iter_unpack('<f',left));offset+=len(left)//4
    if offset!=count:raise ValueError(label+': observed sample count differs')
    return {'samples_compared':count,'unequal_float32_bits':0,'nonzero_samples':nonzero,'sha256':digest.hexdigest()}


def compare_pcm_file(actual,speaker,count):
    if actual.stat().st_size!=count*2 or speaker.stat().st_size!=count*4:raise ValueError('Incomplete PCM/speaker data')
    digest=hashlib.sha256();offset=0
    with actual.open('rb')as a,speaker.open('rb')as b:
        while True:
            floats=b.read(65536)
            if not floats:break
            expected=b''.join(struct.pack('<h',max(-32768,min(32767,int(v*32768))))for v, in struct.iter_unpack('<f',floats))
            left=a.read(len(expected))
            require_equal_samples(left,expected,2,offset,'PCM16')
            digest.update(left);offset+=len(left)//2
        if offset!=count or a.read(1):raise ValueError('PCM16 observed sample count differs')
    return {'samples_compared':count,'unequal_samples':0,'sha256':digest.hexdigest()}


def compare(native,original,cycles):
    blocks=cycles*16//2000000;meta=json.loads((original/'audio-meta.json').read_text())
    dac=[[n*2000000,48000 if n<13 else 31250,961 if n==1 else 960 if n<13 else 626 if n==13 else 625]for n in range(1,blocks+1)]
    speaker=[[n*2000000,961 if n==1 else 960]for n in range(1,blocks+1)]
    if meta['dac_blocks']!=dac or meta['speaker_blocks']!=speaker:raise ValueError('Missing/extra/mistimed factory CMOS audio block')
    r={'scope':'All DAC31250/speaker48000 float32 bits and PCM16; every block timestamp/cardinality/rate checked, factory phase7500/12; no normalization.'}
    r['DAC']=compare_float_files(native/'native-source.bin',original/'reference-dac.bin',blocks*625+1,'DAC31250')
    r['speaker']=compare_float_files(native/'native-speaker.bin',original/'reference-speaker.bin',blocks*960+1,'speaker48000')
    r['PCM16']=compare_pcm_file(native/'native-pcm16.bin',original/'reference-speaker.bin',blocks*960+1)
    if not r['DAC']['nonzero_samples']or not r['speaker']['nonzero_samples']:raise ValueError('Unobserved nonzero audio')
    r['passed']=True;return r
