#include "../mk2/mk2_video.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void require(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
template<class F> void rejects(F action) {
    bool rejected = false;
    try { action(); } catch (const std::runtime_error&) { rejected = true; }
    require(rejected, "invalid video access accepted");
}
}

int main() {
    try {
        {
            mk2::BootVideo sprite;
            mk2::BoardBootControls control;
            auto setup = [&](unsigned x, unsigned y, unsigned width) {
                sprite.dma_registers.fill(0); sprite.dma_palette = 0x7f23;
                auto& r = sprite.dma_registers;
                r[4] = uint16_t(x); r[5] = uint16_t(y);
                r[6] = uint16_t(width); r[7] = 1;
                r[13] = 511; r[17] = 1023;
                std::fill(sprite.vram.begin(), sprite.vram.end(), uint16_t(0x1234));
                control.io[18] = 0x0402;
            };
            setup(4, 5, 3);
            {
                setup(8,2,3);sprite.dma_registers[7]=2;
                std::vector<uint8_t> packed(8);unsigned bit=0;
                const auto append=[&](unsigned value,unsigned count) {
                    for(unsigned n=0;n<count;++n,++bit)packed[bit/8]|=uint8_t(((value>>n)&1)<<(bit&7));
                };
                append(0,8);append(1,4);append(0,4);append(3,4);
                append(0,8);append(4,4);append(5,4);append(6,4);
                auto expected=sprite.vram;
                expected[2*512+8]=0x7f01;expected[2*512+6]=0x7f03;
                expected[512+8]=0x7f04;expected[512+7]=0x7f05;expected[512+6]=0x7f06;
                require(sprite.StartDma(0xc0b2,control,packed)==6 && sprite.vram==expected &&
                        control.dma_command==0xc0b2 && control.io[18]==0x0400,
                        "two-player C0B2: 4bpp row headers, both flips, transparent zero and packed half-byte row");
            }
            {
                setup(8,2,3);sprite.dma_registers[7]=2;sprite.dma_registers[9]=0x95;
                std::vector<uint8_t> packed(9);unsigned bit=0;
                const auto append=[&](unsigned value,unsigned count) {
                    for(unsigned n=0;n<count;++n,++bit)packed[bit/8]|=uint8_t(((value>>n)&1)<<(bit&7));
                };
                append(0,8);append(1,6);append(0,6);append(3,6);
                append(0,8);append(4,6);append(5,6);append(6,6);
                auto expected=sprite.vram;
                for(auto offset:{2*512+8,2*512+6,512+8,512+7,512+6})expected[offset]=0x7f95;
                require(sprite.StartDma(0xe5b8,control,packed)==6 && sprite.vram==expected &&
                        control.dma_command==0xe5b8 && control.io[18]==0x0400,
                        "fighter E5B8: 6bpp packed headers, both flips, transparent zero and constant nonzero color");
            }
            setup(4,5,5);sprite.dma_registers[0]=0x0101;sprite.dma_registers[9]=0xa595;
            {
                auto expected=sprite.vram;expected[5*512+4]=expected[5*512+6]=0x7f95;
                require(sprite.StartDma(0xe048,control,{0x81,0,0x0c,4,0})==5 &&
                        sprite.vram==expected && control.dma_command==0xe048 && control.io[18]==0x0400,
                        "attract E048: uncompressed 6bpp nonzero color, transparent zero, dual edge skips and exact DMA cost");
            }
            setup(4, 5, 3);
            require(sprite.StartDma(0xe002, control, {0x40,0xf0,0x03,0}) == 3 &&
                    sprite.vram[5*512+4] == 0x1234 && sprite.vram[5*512+5] == 0x7f01 &&
                    sprite.vram[5*512+6] == 0x7f3f && control.dma_command == 0xe002 &&
                    control.io[18] == 0x0400, "6bpp transparency and DMA INT1 clear");
            setup(5, 3, 7);
            sprite.StartDma(0xe482, control, {0x11,0x01,0x20,0x0c,0});
            require(sprite.vram[3*512+5] == 0x1234 && sprite.vram[3*512+6] == 0x7f01 &&
                    sprite.vram[3*512+7] == 0x1234 && sprite.vram[3*512+8] == 0x7f02 &&
                    sprite.vram[3*512+9] == 0x7f03 && sprite.vram[3*512+10] == 0x1234,
                    "6bpp packed pre/post skips and transparent pixel");
            setup(8, 2, 3); sprite.dma_registers[16] = 7;
            sprite.StartDma(0xee92, control, {0,0x81,0x30,0});
            require(sprite.vram[2*512+8] == 0x7f01 && sprite.vram[2*512+7] == 0x7f02 &&
                    sprite.vram[2*512+6] == 0x1234, "flipped DMA clips the left pixel");
            setup(8, 2, 3);
            sprite.StartDma(0xe092, control, {1,0x81,0});
            require(sprite.vram[2*512+8] == 0x1234 && sprite.vram[2*512+7] == 0x7f01 &&
                    sprite.vram[2*512+6] == 0x7f02 && sprite.vram[2*512+5] == 0x1234,
                    "original release E092 keeps packed preskip, X flip and pixel values");
            setup(3, 1, 3); sprite.dma_registers[9] = 0x87;
            sprite.StartDma(0x9008, control, {5,0});
            require(sprite.vram[512+3] == 0x7f87 && sprite.vram[512+4] == 0x1234 &&
                    sprite.vram[512+5] == 0x7f87, "1bpp nonzero pixels use the color register");
            setup(4, 5, 3); sprite.dma_registers[10] = 0x80;
            const auto before = sprite.vram;
            const auto command = control.dma_command;
            rejects([&] { sprite.StartDma(0xe002, control, {0x40,0xf0,0x03,0}); });
            require(sprite.vram == before && control.dma_command == command && control.io[18] == 0x0402,
                    "unsupported scaling rejects before drawing or latch mutation");
            sprite.dma_registers[10] = 0;
            bool truncated = false;
            try { sprite.StartDma(0xe002, control, {0x40}); }
            catch (const std::out_of_range&) { truncated = true; }
            require(truncated && sprite.vram == before && control.dma_command == command &&
                    control.io[18] == 0x0402, "truncated ROM rejects before partial rendering");
            setup(8,2,7);sprite.dma_registers[7]=5;
            sprite.dma_registers[10]=sprite.dma_registers[11]=1213;
            std::vector<uint8_t> zoom(64,0x41);
            auto expected=sprite.vram;expected[2*512+8]=0x7f01;expected[2*512+9]=0x7f01;
            expected[3*512+8]=0x7f01;expected[3*512+9]=0x7f01;
            require(sprite.StartDma(0xe002,control,zoom)==1 && sprite.vram==expected,
                    "stage E002 uses the exact 1213 scale without quantization");
        }
        mk2::BootVideo video;
        mk2::BoardBootControls board;
        video.WritePalette(0x01800000, 0x81ab);
        video.WritePalette(0x01800000, 0x2300, 0xff00);
        require(video.ReadPalette(0x01800000) == 0x23ab,
                "palette masked write preserves the other byte");
        video.WritePalette(0x0187fff0, 0xffff);
        video.WritePalette(0x0187fff0, 0, 0);
        require(video.palette_ram.back() == 0xffff,
                "palette stores raw xRGB555 high bit and honors zero mask");
        rejects([&] { video.WritePalette(0x01880000, 1); });
        rejects([&] { video.ReadPalette(0x01800001); });
        board.io[18] = 0x0402;
        video.WriteDma(1, 0x1200, board);
        video.WriteDma(1, 0x0034, board, 0x00ff);
        require(video.ReadDma(0, board) == 0x1234 && video.ReadDma(1, board) == 0x1234 &&
                board.io[18] == 0x0400, "DMA command read alias and INT1 clear");
        board.io[18] |= 2;
        video.WriteDma(1, 0, board, 0);
        require(board.dma_command == 0x1234 && board.io[18] == 0x0400,
                "zero-mask command still clears INT1 without changing the command");
        rejects([&] { video.WriteDma(1, 0x8000, board); });
        require(board.dma_command == 0x1234, "DMA start rejected before mutation");
        video.WriteDma(2, 0x1234, board);
        require(video.ReadDma(2, board) == 0x1234, "DMA source register retains physical word");
        video.WriteDma(8, 0xabcd, board);
        video.WriteDma(8, 0x1200, board, 0xff00);
        require(video.ReadDma(8, board) == 0x12cd, "DMA palette byte lanes");
        video.WriteDma(15, 0x30, board);
        video.WriteDma(12, 0x1357, board);
        video.WriteDma(13, 0x2468, board);
        video.WriteDma(15, 0x10, board);
        video.WriteDma(12, 0xab00, board, 0xff00);
        video.WriteDma(12, 0x00cd, board, 0x00ff);
        video.WriteDma(13, 0x5678, board);
        const auto dma = video.DmaRegisters(board);
        require(dma[12] == 0x1357 && dma[13] == 0x2468 && dma[16] == 0xabcd &&
                dma[17] == 0x5678 && dma[15] == 0x10 && dma[8] == 0x12cd &&
                dma[1] == board.dma_command && dma[0] == 0,
                "DMA clip writes select a bank and preserve byte lanes and physical registers");
        require(video.ReadDma(12, board) == 0x1357 && video.ReadDma(13, board) == 0x2468,
                "DMA reads retain the original asymmetric unbanked mapping");
        rejects([&] { video.WriteDma(16, 1, board); });
        {
            mk2::BootVideo sprite;
            mk2::BoardBootControls sprite_board;
            sprite.dma_registers[4] = 1; sprite.dma_registers[5] = 2;
            sprite.dma_registers[6] = 20; sprite.dma_registers[7] = 2;
            sprite.dma_palette = 0x7f23;
            sprite.dma_registers[10] = sprite.dma_registers[11] = 0x100;
            sprite.dma_registers[12] = 0; sprite.dma_registers[13] = 511;
            sprite.dma_registers[16] = 0; sprite.dma_registers[17] = 1023;
            std::vector<uint8_t> graphics{0x11, 0x20, 0x43, 0x65, 0x87, 0xa9, 0x21, 0xb2, 0x0c, 0};
            std::fill(sprite.vram.begin(), sprite.vram.end(), uint16_t(0x1234));
            require(sprite.StartDma(0xc382, sprite_board, graphics) == 40,
                    "original DMA completion counts full dimensions, including skipped pixels");
            require(sprite.vram[2 * 512 + 8] == 0x1234 && sprite.vram[2 * 512 + 9] == 0x1234 &&
                    sprite.vram[2 * 512 + 10] == 0x7f02 && sprite.vram[3 * 512 + 17] == 0x7f0b &&
                    sprite.vram[3 * 512 + 18] == 0x7f0c && sprite_board.dma_command == 0xc382,
                    "4bpp ROM nibbles, preskip8, postskip1, transparency and successive packed rows");
            const auto before = sprite.vram;
            rejects([&] { sprite.StartDma(0xc383, sprite_board, graphics); });
            require(sprite.vram == before && sprite_board.dma_command == 0xc382,
                    "unobserved drawing mode rejects without changing pixels or DMA latches");
            std::fill(sprite.vram.begin(), sprite.vram.end(), uint16_t(0x1234));
            sprite.dma_registers[12] = 3;
            sprite.dma_registers[16] = sprite.dma_registers[17] = 18;
            sprite.StartDma(0xc382, sprite_board, graphics);
            require(sprite.vram[2 * 512 + 10] == 0x1234 && sprite.vram[3 * 512 + 17] == 0x1234 &&
                    sprite.vram[3 * 512 + 18] == 0x7f0c,
                    "clipped rows still advance their packed ROM source and horizontal clipping preserves neighbors");
        }
        board.WriteVideoControl(0x20);
        video.WriteVram(0, 0x3412, board);
        require(video.vram[0] == 0xcd12 && video.vram[1] == 0x1234 &&
                video.ReadVram(0, board) == 0x3412,
                "data bank writes two pixels with corresponding DMA palette bytes");
        video.WriteVram(0, 0x5678, board, 0x00ff);
        require(video.vram[0] == 0xcd78 && video.vram[1] == 0x1234,
                "data-bank low byte preserves adjacent pixel");
        video.WriteVram(0, 0x9abc, board, 0xff00);
        require(video.vram[0] == 0xcd78 && video.vram[1] == 0x129a,
                "data-bank high byte preserves first pixel");
        board.WriteVideoControl(0);
        require(video.ReadVram(0, board) == 0x12cd, "color-bank reads pixel high bytes");
        video.WriteVram(0, 0x3456, board, 0x00ff);
        require(video.vram[0] == 0x5678 && video.vram[1] == 0x129a,
                "color-bank low byte changes only first pixel palette");
        video.WriteVram(0, 0x789a, board, 0xff00);
        require(video.vram[0] == 0x5678 && video.vram[1] == 0x789a,
                "color-bank high byte changes only second pixel palette");
        video.WriteVram(0, 0, board, 0);
        require(video.ReadVram(0, board) == 0x7856, "VRAM zero mask preserves both pixels");
        board.WriteVideoControl(0x20);
        video.WriteVram(0x003ffff0, 0xabcd, board);
        require(video.vram[524286] == 0xcdcd && video.vram.back() == 0x12ab,
                "final CPU VRAM word reaches final two physical pixels");
        rejects([&] { video.WriteVram(0x00400000, 0, board); });
        rejects([&] { video.ReadVram(1, board); });
        board.io[8] = 0xf010; board.io[5] = 20; board.io[6] = 274;
        board.io[7] = 288; board.io[9] = 0xfffc; board.io[10] = 274;
        board.io[18] = 0;
        board.AdvanceScanlines(274);
        require(board.vcount == 273 && board.display_address == 0xf020 &&
                board.active_updates == 254 && board.io[18] == 0,
                "last active line precedes display reload");
        board.AdvanceScanlines(275);
        require(board.vcount == 274 && board.display_address == 0xfffc && board.io[18] == 0x0400,
                "vblank start reloads display address and asserts display pending");
        board.WriteIo(18, 0);
        board.AdvanceScanlines(290);
        require(board.vcount == 0 && board.display_address == 0xfffc && board.io[18] == 0,
                "scanline wraps after VTOTAL and cleared display pending stays clear");
        board.AdvanceScanlines(737);
        require(board.vcount == 158 && board.display_address == 0xf74c &&
                board.active_updates == 647 && board.io[18] == 0x0400,
                "third frame continues original display update and display IRQ");
        board.AdvanceScanlines(995);
        require(board.vcount == 127 && board.display_address == 0xf93c &&
                board.active_updates == 870 && board.io[18] == 0x0400,
                "post-factory status preserves the unchanged fourth-frame scanline calendar");
        board.AdvanceScanlines(996);
        require(board.vcount == 128 && board.display_address == 0xf92c &&
                board.active_updates == 871 && board.io[18] == 0x0400,
                "sound command return advances the next original scanline without horizontal reconfiguration");
        board.AdvanceScanlines(999);
        require(board.vcount == 131 && board.display_address == 0xf8fc &&
                board.active_updates == 874 && board.io[18] == 0x0400,
                "warning text prefix preserves the next three original scanlines");
        board.AdvanceScanlines(1018);
        require(board.vcount == 150 && board.display_address == 0xf7cc &&
                board.active_updates == 893 && board.io[18] == 0x0400,
                "completed prompt and first input poll preserve the original scanline calendar");
        board.AdvanceScanlines(1149);
        require(board.vcount == 281 && board.display_address == 0xfffc,
                "first SPORT horizon preserves the complete scanline calendar");
        board.AdvanceScanlines(1266);
        require(board.vcount == 109 && board.display_address == 0xfa5c,
                "second SPORT horizon preserves the original display phase");
        board.AdvanceScanlines(2051);
        require(board.scanline_events == 2051 && board.vcount == 27,
                "first display IRQ horizon retains the original scanline period");
        board.AdvanceScanlines(2057);
        require(board.scanline_events == 2057 && board.vcount == 33,
                "ranking/service checks and first task enqueue retain six original callbacks");
        board.io[1] = 21; board.io[3] = 252;
        require(board.HorizontalCount(0) == 21 && board.HorizontalCount(1) == 21 &&
                board.HorizontalCount(2) == 22 && board.HorizontalCount(395) == 21 &&
                board.HorizontalCount(819274) == 140,
                "horizontal count rounds fractional pixels then scales and offsets original beam position");
        board.io[1] = 1;
        require(board.HorizontalCount(394) == 253,
                "horizontal count preserves exact total before strict greater-than wrap");
        board.io[1] = 2;
        require(board.HorizontalCount(394) == 1,
                "horizontal count wraps only values beyond total");
        board.io[1] = 21;
        require(board.HorizontalCount(790) == 20 && board.HorizontalCount(791) == 21,
                "horizontal beam wraps fractional 506-pixel lines without accumulating drift");
        board.io[3] = 253;
        rejects([&] { board.HorizontalCount(819274); });
        board.io[3] = 252;
        board.io[1] = 0x2d;
        require(board.HorizontalCount(1173059) == 0x98,
                "post-traversal original HCNT read retains its measured beam position");
        require(board.HorizontalCount(1273375) == 92 && board.HorizontalCount(1387282) == 128,
                "larger cooperative batch retains both independently observed HCNT reads");
        const std::array<std::array<uint64_t,2>,13> larger_beam{{
            {2186664,167},{2300899,160},{2415141,158},{2529429,185},
            {2643669,182},{2757904,175},{2872144,172},{2986377,164},
            {3100653,184},{3201878,200},{3315917,68},{3436054,43},{3544177,173}}};
        for (const auto& sample : larger_beam)
            require(board.HorizontalCount(sample[0]) == sample[1],
                    "larger interval beam reads match independent MAME observations");
        rejects([&] { board.HorizontalCount(3658092); });
        board.AdvanceScanlines(2127);
        require(board.scanline_events == 2127 && board.vcount == 103,
                "first cooperative yield retains all seventy original scanline callbacks");
        board.AdvanceScanlines(2919);
        require(board.scanline_events == 2919 && board.vcount == 28,
                "fifth task yield retains the original complete scanline calendar");
        board.AdvanceScanlines(3169);
        require(board.scanline_events == 3169 && board.vcount == 278,
                "palette queue drain retains all scanline callbacks through its original display IRQ");
        board.AdvanceScanlines(3176);
        require(board.scanline_events == 3176 && board.vcount == 285,
                "loaded drawing and following task preserve seven additional physical scanlines");
        board.AdvanceScanlines(7795);
        require(board.scanline_events == 7795 && board.vcount == 280,
                "larger endpoint preserves every physical scanline through measured VCOUNT280");
        board.AdvanceScanlines(8374);
        require(board.scanline_events == 8374 && board.vcount == 281,
                "coin queue retains every original scanline through its measured boundary");
        board.AdvanceScanlines(9239);
        require(board.scanline_events == 9239 && board.vcount == 279,
                "coin accounting preserves the released-input scanline frontier");
        rejects([&] { board.AdvanceScanlines(9240); });
        require(board.scanline_events == 9239 && board.vcount == 279,
                "next unsupported scanline rejects before clock mutation");
        rejects([&] { board.AdvanceScanlines(994); });
        std::cout << "mk2 video contracts passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
