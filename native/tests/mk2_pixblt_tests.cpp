#include "../mk2/mk2_pixblt.hpp"
#include <algorithm>
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "unsupported PIXBLT accepted");
}
mk2::ResetTrace fixture(unsigned x = 1, unsigned width = 2) {
    mk2::ResetTrace state;
    state.next_pc = 0xffa592b0; state.cycles = 1000; state.status = 0x50000008;
    state.board.io[8] = 0xf010; state.board.io[11] = 0x2c;
    state.board.io[20] = 19; state.board.io[21] = 8;
    state.board.WriteVideoControl(0x20);
    state.b[0] = 0xff800000; state.b[1] = 8; state.b[2] = (2 << 16) | x;
    state.b[3] = 4096; state.b[7] = (8 << 16) | width; state.b[9] = 0x0505;
    return state;
}
mk2::Program program() {
    mk2::Program source;
    source.bytes.resize(0x100000);
    source.bytes[(0xffa592b0 - 0xff800000) / 8] = 0xa0;
    source.bytes[(0xffa592b0 - 0xff800000) / 8 + 1] = 0x0f;
    for (unsigned row = 0; row < 8; ++row) source.bytes[row] = row & 1 ? 2 : 1;
    return source;
}
}

int main() {
    try {
        auto source = program();
        auto state = fixture();
        mk2::BootVideo video;
        video.dma_palette = 0xabcd;
        std::fill(video.vram.begin(), video.vram.end(), 0x7777);
        mk2::BitmapTextBlit blit;
        const auto first = blit.Step(source, video, state, 3);
        require(first.cycles == 3 && !first.completed && state.next_pc == 0xffa592b0 &&
                state.status == 0x52000008 && state.b[0] == 0xff800000 && state.b[2] == 0x00020001,
                "first partial slice sets P and restarts without updating source or destination");
        require(first.accesses.size() == 40, "eight rows preserve all source and partial-word bus accesses");
        require(first.accesses[0].kind == 'r' && first.accesses[0].address_bit == 0xff800000 &&
                first.accesses[0].value == 0x0201 && first.accesses[1].kind == 'r' &&
                first.accesses[1].address_bit == 0x2000 && first.accesses[1].value == 0x7777 &&
                first.accesses[2].kind == 'w' && first.accesses[2].address_bit == 0x2000 &&
                first.accesses[2].value == 0x0577 && first.accesses[3].kind == 'r' &&
                first.accesses[3].address_bit == 0x2010 && first.accesses[4].kind == 'w' &&
                first.accesses[4].value == 0x7777,
                "word reads precede writes, including a fully transparent partial destination word");
        for (const auto& access : first.accesses)
            require(access.pc == 0xffa592b0 && access.cycle == 1000,
                    "all drawing accesses occur at the first entry before consuming graphics cycles");
        require(video.vram[1024] == 0xcd77 && video.vram[1025] == 0xab05 &&
                video.vram[1026] == 0xcd77 && video.vram[1027] == 0xab77 &&
                video.vram[1537] == 0xab77 && video.vram[1538] == 0xcd05,
                "partial and transparent stores preserve CPU data but rewrite both palette bytes");
        const auto drawn = video.vram;
        auto changed = state;
        ++changed.b[0];
        rejects([&] { blit.Step(source, video, changed, 1); });
        require(video.vram == drawn && changed.status == state.status,
                "unsupported register changes during P restart have no drawing side effects");
        const auto second = blit.Step(source, video, state, 4);
        require(second.cycles == 4 && !second.completed && second.accesses.empty() && video.vram == drawn,
                "P restart consumes time without repeating any bus access");
        const auto final = blit.Step(source, video, state, 1000);
        require(final.cycles == 81 && final.completed && final.accesses.empty() &&
                state.next_pc == 0xffa592c0 && state.status == 0x50000008 &&
                state.b[0] == 0xff800040 && state.b[2] == 0x000a0001 && state.cycles == 1000,
                "only completion advances B0 and B2.Y and clears P; caller owns CPU cycle accounting");
        auto full_state = fixture(0, 8);
        full_state.b[0] += 8; full_state.b[9] = 0x1200;
        mk2::BootVideo full_video;
        std::fill(full_video.vram.begin(), full_video.vram.end(), 0x7777);
        std::fill(source.bytes.begin(), source.bytes.begin() + 10, 0xff);
        mk2::BitmapTextBlit full;
        const auto full_result = full.Step(source, full_video, full_state, 200);
        require(full_result.completed && full_result.cycles == 168 && full_result.accesses.size() == 76,
                "full words use transparent replace timing and retain terminal source prefetch");
        require(full_result.accesses[8].kind == 'r' && full_result.accesses[8].address_bit == 0xff800010 &&
                full_result.accesses[9].kind == 'w' && full_result.accesses[9].address_bit == 0x2030,
                "source boundary prefetch occurs before the last destination word write");
        require(full_video.vram[1024] == 0x0077 && full_video.vram[1025] == 0x0012,
                "transparency tests the selected color byte and does not replicate COLOR1");
        auto background_state = fixture(0, 2);
        background_state.b[8] = 0x1234; background_state.b[9] = 0;
        mk2::BootVideo background_video;
        std::fill(background_video.vram.begin(), background_video.vram.end(), 0x7777);
        auto background_source = program();
        mk2::BitmapTextBlit background;
        const auto background_result = background.Step(background_source, background_video, background_state, 40);
        require(background_result.completed && background_result.cycles == 40 &&
                background_video.vram[1024] == 0x0077 && background_video.vram[1025] == 0x0012,
                "COLOR0 selects background bytes and exact cycle budget completes without an extra restart");
        auto wide_state = fixture(237, 10);
        wide_state.cycles = 397269; wide_state.b[1] = 16; wide_state.b[2] = (110 << 16) | 237;
        mk2::BootVideo wide_video;
        std::fill(wide_video.vram.begin(), wide_video.vram.end(), 0x7777);
        std::fill(source.bytes.begin(), source.bytes.begin() + 16, 0xff);
        mk2::BitmapTextBlit wide;
        const auto wide_first = wide.Step(source, wide_video, wide_state, 20);
        require(wide_first.cycles == 20 && !wide_first.completed && wide_first.accesses.size() == 104 &&
                wide_state.status == 0x52000008 && wide_state.next_pc == 0xffa592b0 &&
                wide_state.b[0] == 0xff800000 && wide_state.b[2] == 0x006e00ed,
                "ten-pixel M with sixteen-bit source pitch draws once and restarts at the measured slice");
        require(wide_first.accesses[0].address_bit == 0xff800000 &&
                wide_first.accesses[2].kind == 'w' && wide_first.accesses[2].address_bit == 0x6e760 &&
                wide_first.accesses[2].value == 0x0577 && wide_first.accesses[12].kind == 'w' &&
                wide_first.accesses[12].address_bit == 0x6e7b0 && wide_first.accesses[12].value == 0x7705 &&
                wide_first.accesses[13].kind == 'r' && wide_first.accesses[13].address_bit == 0xff800010,
                "M rows contain one source word and six ordered destination RMW pairs including both partial words");
        const auto wide_final = wide.Step(source, wide_video, wide_state, 1000);
        require(wide_final.cycles == 228 && wide_final.completed && wide_final.accesses.empty() &&
                wide_state.b[0] == 0xff800080 && wide_state.b[2] == 0x007600ed &&
                wide_state.status == 0x50000008 && wide_state.next_pc == 0xffa592c0,
                "M completes after 248 total cycles with original pointer and flag effects");
        auto wrong_pitch = fixture(237, 10);
        mk2::BitmapTextBlit wrong_pitch_blit;
        rejects([&] { wrong_pitch_blit.Step(source, wide_video, wrong_pitch, 1); });
        for (unsigned mutation = 0; mutation < 8; ++mutation) {
            auto bad = fixture();
            if (mutation == 0) bad.board.io[21] = 16;
            if (mutation == 1) bad.board.io[11] = 0;
            if (mutation == 2) bad.board.io[22] = 1;
            if (mutation == 3) bad.board.io[8] |= 0x0800;
            if (mutation == 4) bad.board.io[20] = 18;
            if (mutation == 5) bad.b[0] = 0xfffffff8;
            if (mutation == 6) bad.b[2] = 0xffff0001;
            if (mutation == 7) bad.b[7] = 0;
            mk2::BootVideo rejected_video;
            mk2::BitmapTextBlit rejected_blit;
            const auto before_b = bad.b;
            const auto before_status = bad.status;
            rejects([&] { rejected_blit.Step(source, rejected_video, bad, 1); });
            require(bad.b == before_b && bad.status == before_status &&
                    std::all_of(rejected_video.vram.begin(), rejected_video.vram.end(), [](uint16_t p) { return p == 0; }),
                    "unsupported mode or unmapped range is rejected before register and VRAM mutation");
        }
        auto invalid_state = fixture(); mk2::BitmapTextBlit invalid;
        rejects([&] { invalid.Step(source, video, invalid_state, 0); });
        invalid_state.status |= 1u << 25;
        rejects([&] { invalid.Step(source, video, invalid_state, 1); });
        std::cout << "mk2 PIXBLT contracts passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
