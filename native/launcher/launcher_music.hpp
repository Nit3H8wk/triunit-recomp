#pragma once

#include <windows.h>
#include <mfapi.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#include <wrl/client.h>
#include <xaudio2.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <memory>
#include <stdexcept>
#include <vector>

namespace mklauncher {
class MenuMusic {
public:
    explicit MenuMusic(const std::filesystem::path& path) {
        const auto format = decode(path);
        const auto frames = UINT32(pcm_.size() / format.nChannels);
        const auto overlap = std::min<UINT32>(8 * format.nSamplesPerSec, frames / 4);
        crossfade(format.nChannels, frames, overlap);

        check(XAudio2Create(engine_.GetAddressOf(), 0, XAUDIO2_DEFAULT_PROCESSOR), "audio engine");
        IXAudio2MasteringVoice* master = nullptr;
        check(engine_->CreateMasteringVoice(&master, XAUDIO2_DEFAULT_CHANNELS, XAUDIO2_DEFAULT_SAMPLERATE,
                                            0, nullptr, nullptr, AudioCategory_GameMedia), "output device");
        master_.reset(master);
        IXAudio2SourceVoice* source = nullptr;
        check(engine_->CreateSourceVoice(&source, &format), "music voice");
        voice_.reset(source);
        check(voice_->SetVolume(0), "initial gain");
        XAUDIO2_BUFFER buffer{};
        buffer.AudioBytes = UINT32(pcm_.size() * sizeof(pcm_[0]));
        buffer.pAudioData = reinterpret_cast<const BYTE*>(pcm_.data());
        // The tail already contains the intro up to this point.
        buffer.LoopBegin = overlap;
        buffer.LoopLength = frames - overlap;
        buffer.LoopCount = XAUDIO2_LOOP_INFINITE;
        check(voice_->SubmitSourceBuffer(&buffer), "music loop");
    }

    void duck() noexcept {
        if (playing_) duckUntil_ = GetTickCount64() + 320;
    }

    void pause() noexcept {
        if (!playing_) return;
        voice_->SetVolume(0);
        voice_->Stop();
        playing_ = false;
        fade_ = volume_ = 0;
        duckGain_ = 1;
        duckUntil_ = 0;
    }

    bool update(int level) noexcept {
        if (!voice_) return false;
        const float target = float(level) / 100.f;
        const auto now = GetTickCount64();
        auto elapsed = float(now - updated_);
        updated_ = now;
        if (!playing_) {
            if (target == 0) return false;
            if (FAILED(voice_->Start())) {
                voice_.reset();
                return false;
            }
            playing_ = true;
            elapsed = 0;
        }

        fade_ += std::clamp(target - fade_, -elapsed / 160.f, elapsed / 440.f);
        if (target == 0 && fade_ == 0) {
            pause();
            return false;
        }
        // Keep the short coin transient clear, then bring the music bed back gently.
        duckGain_ = std::clamp(duckGain_ + elapsed / (now < duckUntil_ ? -65.f : 550.f), .60f, 1.f);
        // .85 x +4.24 dB: the common loudness L3 = -23.62 LUFS of the games (F5, audio-measure.json); peak -5.9 dBTP.
        const float gain = 1.386f * fade_ * duckGain_;
        if (gain != volume_) {
            voice_->SetVolume(gain);
            volume_ = gain;
        }
        return target == 0;
    }

private:
    struct DestroyVoice {
        void operator()(IXAudio2Voice* voice) const noexcept { voice->DestroyVoice(); }
    };
    Microsoft::WRL::ComPtr<IXAudio2> engine_;
    std::unique_ptr<IXAudio2MasteringVoice, DestroyVoice> master_;
    std::vector<int16_t> pcm_;
    std::unique_ptr<IXAudio2SourceVoice, DestroyVoice> voice_;
    ULONGLONG updated_ = GetTickCount64(), duckUntil_ = 0;
    bool playing_ = false;
    float fade_ = 0, volume_ = 0, duckGain_ = 1;

    static void check(HRESULT hr, const char* step) {
        if (FAILED(hr)) throw std::runtime_error(step);
    }

    WAVEFORMATEX decode(const std::filesystem::path& path) {
        using Microsoft::WRL::ComPtr;
        check(MFStartup(MF_VERSION, MFSTARTUP_LITE), "Media Foundation");
        struct Shutdown { ~Shutdown() { MFShutdown(); } } shutdown;
        ComPtr<IMFSourceReader> reader;
        check(MFCreateSourceReaderFromURL(path.c_str(), nullptr, reader.GetAddressOf()), "open MP3");
        constexpr DWORD audio = MF_SOURCE_READER_FIRST_AUDIO_STREAM;
        check(reader->SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS, FALSE), "select audio stream");
        check(reader->SetStreamSelection(audio, TRUE), "select audio stream");
        ComPtr<IMFMediaType> type;
        check(MFCreateMediaType(type.GetAddressOf()), "audio type");
        check(type->SetGUID(MF_MT_MAJOR_TYPE, MFMediaType_Audio), "audio type");
        check(type->SetGUID(MF_MT_SUBTYPE, MFAudioFormat_PCM), "PCM format");
        check(reader->SetCurrentMediaType(audio, nullptr, type.Get()), "MP3 decoder");
        check(reader->GetCurrentMediaType(audio, type.ReleaseAndGetAddressOf()), "decoded format");
        UINT32 rate = 0, channels = 0, bits = 0;
        check(type->GetUINT32(MF_MT_AUDIO_SAMPLES_PER_SECOND, &rate), "sample rate");
        check(type->GetUINT32(MF_MT_AUDIO_NUM_CHANNELS, &channels), "channel count");
        check(type->GetUINT32(MF_MT_AUDIO_BITS_PER_SAMPLE, &bits), "sample width");
        if (bits != 16 || channels < 1 || channels > 2 || rate < 8000 || rate > 48000)
            throw std::runtime_error("unsupported MP3 format");
        const auto alignment = WORD(channels * sizeof(int16_t));

        constexpr size_t maxSamples = 64 * 1024 * 1024 / sizeof(int16_t);
        for (;;) {
            DWORD flags = 0;
            ComPtr<IMFSample> sample;
            check(reader->ReadSample(audio, 0, nullptr, &flags, nullptr, sample.GetAddressOf()), "decode MP3");
            if (flags & (MF_SOURCE_READERF_ERROR | MF_SOURCE_READERF_CURRENTMEDIATYPECHANGED))
                throw std::runtime_error("MP3 stream changed");
            if (sample) {
                ComPtr<IMFMediaBuffer> buffer;
                check(sample->ConvertToContiguousBuffer(buffer.GetAddressOf()), "decoded buffer");
                BYTE* data = nullptr;
                DWORD bytes = 0;
                check(buffer->Lock(&data, nullptr, &bytes), "decoded samples");
                struct Unlock { IMFMediaBuffer* buffer; ~Unlock() { buffer->Unlock(); } } unlock{buffer.Get()};
                const auto count = bytes / sizeof(int16_t);
                if (bytes % alignment || count > maxSamples - pcm_.size())
                    throw std::runtime_error("invalid or oversized decoded MP3");
                if (count) {
                    const auto offset = pcm_.size();
                    pcm_.resize(offset + count);
                    std::memcpy(pcm_.data() + offset, data, bytes);
                }
            }
            if (flags & MF_SOURCE_READERF_ENDOFSTREAM) break;
        }
        if (pcm_.empty()) throw std::runtime_error("empty MP3");
        return {WAVE_FORMAT_PCM, WORD(channels), rate, rate * alignment, alignment, WORD(bits), 0};
    }

    void crossfade(UINT32 channels, UINT32 frames, UINT32 overlap) {
        const auto tail = (frames - overlap) * channels;
        for (UINT32 frame = 0; frame < overlap; ++frame) {
            const float angle = 1.570796327f * float(frame) / float(overlap);
            const float out = std::cos(angle), in = std::sin(angle);
            for (UINT32 channel = 0; channel < channels; ++channel) {
                const auto i = frame * channels + channel;
                pcm_[tail + i] = int16_t(std::clamp(out * pcm_[tail + i] + in * pcm_[i], -32768.f, 32767.f));
            }
        }
    }
};
}
