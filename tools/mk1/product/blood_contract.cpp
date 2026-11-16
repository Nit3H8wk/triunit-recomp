#include "mk5_scanout.hpp"
#include "mk5_task_body.hpp"
#include <algorithm>
#include <array>
#include <iostream>
#include <set>
#include <stdexcept>

namespace {
void need(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}
uint16_t word(const Mk5MemoryBuffers& memory, uint32_t address) {
    return memory.ram.at((address - 0x01000000) / 16);
}
uint32_t pointer(const Mk5MemoryBuffers& memory, uint32_t address) {
    return word(memory, address) | (uint32_t(word(memory, address + 16)) << 16);
}
void check_landed_sprite(const VerifiedMk5Program& program, const VerifiedMk5GlyphBank& graphics) {
    Mk5MemoryBuffers memory;
    ResetTrace cpu{};
    Mk5IrqEpoch epoch{};
    cpu.a[15] = 0x01000200;
    epoch.io[3] = epoch.io[7] = 1;
    epoch.io[8] = 0x6000;
    epoch.quanta_to_next_scanline = 1;
    Mk5IrqController irq(program, cpu, memory, epoch);
    BootDiState di;
    Mk5LiveVideo video(graphics, cpu, memory, irq, di, &program);
    auto set = [&](uint32_t bit, uint16_t value) { memory.ram[(bit - 0x01000000) / 16] = value; };
    constexpr uint32_t object = 0x01001000;
    cpu.a[8] = object;
    cpu.a[13] = (254u << 16) | 400;
    set(0x01051190, 2);
    set(0x010517c0, 230);
    set(object + 0x90, 100);
    set(object + 0xb0, 220);
    set(object + 0x190, 0xfffa);
    // RGB and transparent padding, independently decoded from frame FFFA5FE0 and palette FFEA7C00.
    constexpr const char* expected[] = {
        "467d870dc449d21e90f1d1a0377786b23232812985faf269ca2deb64ba7c7591",
        "1a61f98776fdbbb24c89c930a0f22c74ce738defc0eed8bcc9f515bc0c910107"
    };
    for (unsigned flip = 0; flip < 2; ++flip) {
        video.ObserveBlood(0xffc9f010, cpu);
        set(object + 0xd0, 0x52);
        set(object + 0xe0, 0xe002 | (flip << 4));
        set(object + 0x180, 0x5f20);
        video.ObserveBlood(0xffc88860, cpu);
        video.ObserveBlood(0xffc7a700, cpu);
        need(video.BloodPixel(230 * 512 + 100) == 0, "the splash plays normally before retention");
        set(object + 0xd0, 0);
        set(object + 0x180, 0x5fe0);
        video.ObserveBlood(0xffde7ad0, cpu);
        video.ObserveBlood(0xffc7a700, cpu);
        std::vector<uint8_t> pixels;
        for (unsigned y = 216; y < 235; ++y) {
            for (unsigned x = 96; x < 139; ++x) {
                const auto rgb = video.BloodPixel(y * 512 + x);
                for (unsigned shift : {16u, 8u, 0u}) pixels.push_back(uint8_t(rgb >> shift));
            }
        }
        need(Sha256(pixels) == expected[flip], "the whole landed sprite matches original pixels and transparency");
    }
}
struct Sample {
    uint64_t frame, cycles;
    uint16_t arena;
    int camera_x, camera_y;
    bool has_decal;
    std::vector<uint16_t> ram, vram, palette;
    std::vector<uint32_t> raster;
};

std::array<Sample, 4> play(const VerifiedMk5Program& program, const VerifiedMk5GlyphBank& graphics,
                            const std::vector<uint16_t>& cmos, bool remastered, uint16_t dsw = 0xfeff,
                            bool challenge = false) {
    Mk5MemoryBuffers memory;
    Mk5BoardState board;
    board.cmos = cmos;
    auto& cpu = board.check.cpu;
    Mk5IrqController irq(program, cpu, memory);
    BootDiState di;
    const BootDiInputs released{0xffffffff, (uint32_t(dsw) << 16) | 0xffffu};
    Mk5TaskBodyRunner runner(program, board, memory, irq, di);
    Mk5BootInputs power_on;
    power_on.ports = released;
    power_on.pending = 0x400;
    power_on.next_line = 1;
    power_on.quanta_to_next = 6325;
    need(runner.Boot(power_on).stop == TaskBodyStop::TaskEntry, "generated power-on reaches the first task");
    need(word(memory, 0x01052890) == ((dsw & 0x8000) == 0) &&
         word(memory, 0x010528a0) == ((dsw & 0x4000) == 0), "original boot applies the DIP flags");
    TaskBodyInputs in;
    in.dsw = in.main_dsw = dsw;
    in.sound_status = 0x80;
    in.quiet_di = released;
    runner.Run(in);
    runner.AttachVideo(graphics, remastered);
    Mk5Scanout screen(irq, memory, remastered ? &runner.Video() : nullptr);
    in.active_di = released;
    auto step = [&] { return runner.ContinueMain(in, 64); };
    auto resumable = [](const TaskBodyResult& out) {
        return out.stop == TaskBodyStop::Budget || out.stop == TaskBodyStop::DiLimit;
    };
    in.stop_after_decompression = true;
    TaskBodyResult out;
    for (unsigned call = 0; call < 100; ++call) {
        out = step();
        if (!resumable(out)) break;
    }
    need(out.stop == TaskBodyStop::DecompressorComplete, "original startup reaches gameplay");
    in.stop_after_decompression = false;
    in.instruction_budget = 10000;
    auto advance = [&](unsigned frames, uint32_t pressed = 0) {
        in.active_di = BootDiInputs{released.in01 ^ pressed, released.in2_dsw};
        const auto target = screen.frames() + frames;
        for (unsigned calls = 0; screen.frames() < target && calls < 100 + frames * 250; ++calls) {
            need(resumable(step()), "original replay reaches the requested frame");
            runner.CompactDiagnostics();
        }
        need(screen.frames() == target, "replay samples each requested frame");
    };
    auto join = [&](unsigned coin, unsigned start, unsigned confirm) {
        for (unsigned n = 0; n < 2; ++n) { advance(4, 1u << coin); advance(20); }
        advance(4, 1u << start);
        advance(160);
        advance(4, 1u << confirm);
        advance(720);
    };
    auto mode = [&] { return word(memory, 0x01051190); };
    auto round = [&] { return word(memory, 0x010518c0); };
    auto life = [&](uint32_t base) { return int16_t(word(memory, base)) - int16_t(word(memory, base + 16)); };
    auto local = [&] { return mode() == 2 && word(memory, 0x01051200) == 1 && word(memory, 0x010514e0) == 1; };
    auto approach = [&](unsigned frames) {
        const auto x1 = int16_t(word(memory, pointer(memory, 0x01051230) + 0x90));
        const auto x2 = int16_t(word(memory, pointer(memory, 0x01051510) + 0x90));
        advance(frames, x1 < x2 ? (1u << 3) | (1u << 10) : (1u << 2) | (1u << 11));
    };
    auto sample = [&] {
        bool has_decal = false;
        if (remastered) {
            for (size_t pixel = 0; pixel < memory.vram.size(); ++pixel) {
                if (!runner.Video().BloodPixel(pixel)) continue;
                has_decal = true;
                break;
            }
        }
        return Sample{screen.frames(), cpu.reference_cycles, word(memory, 0x01051820),
                      int16_t(word(memory, 0x0104f880)), int16_t(word(memory, 0x0104f660)),
                      has_decal,
                      memory.ram, memory.vram, memory.palette, screen.pixels()};
    };
    advance(30);
    join(16, 18, 4);
    Sample previous_fight{};
    if (challenge) {
        // The first CPU blood landing is visible here before the fighters cover it.
        advance(184);
        previous_fight = sample();
        advance(216);
    }
    join(17, 21, 12);
    if (!local() && mode() == 4) { advance(4, 1u << 4); advance(720); }
    need(local() && round() == 1, "local round 1");
    if (challenge) {
        // Revisit the part of the floor that was visible before the challenge.
        advance(140, (1u << 2) | (1u << 10));
        advance(20);
        const auto next_fight = sample();
        need(next_fight.camera_x <= 160, "the new camera revisits the old blood landing near x=167");
        return {std::move(previous_fight), next_fight, {}, {}};
    }
    approach(36);
    advance(60);
    advance(12, 1u << 1);
    const auto before = sample();
    advance(4, (1u << 1) | (1u << 4));
    advance(180);
    const auto after = sample();
    if (dsw != 0xfeff) return {before, after, {}, {}};
    auto win_round = [&] {
        for (unsigned n = 0; n < 12 && local() && life(0x010515e0) > 0; ++n) {
            approach(24);
            advance(12);
            advance(4, 1u << 28);
            advance(100);
        }
        need(life(0x010515e0) <= 0, "legal attacks knock out P2");
    };
    win_round();
    for (unsigned n = 0; n < 300 && !(local() && round() == 2); ++n) advance(4);
    need(local() && round() == 2 && life(0x010515e0) > 0, "local round 2");
    const auto next_round = sample();
    win_round();
    auto cpu_fight = [&] {
        return mode() == 2 && word(memory, 0x01051200) == 1 && word(memory, 0x010514e0) == 0 &&
               life(0x01051300) > 0 && life(0x010515e0) > 0;
    };
    for (unsigned n = 0; n < 750 && !cpu_fight(); ++n) advance(4);
    need(cpu_fight() && word(memory, 0x010519d0) == 1, "another fight starts against the CPU");
    return {before, after, next_round, sample()};
}
}

int main(int argc, char** argv) try {
    need(argc == 3, "expected the project and contract output directories");
    const std::filesystem::path root(argv[1]);
    const auto program = LoadMk5Program(root / "roms/mk1");
    const auto graphics = LoadMk5GlyphBank(root / "roms/mk1");
    check_landed_sprite(program, graphics);
    const auto cmos = LoadMk5CmosSnapshot(root / "generated/mk1" / program.sha256 / "factory-default-control-input.bin");   // setup seed
    const auto original = play(program, graphics, cmos, false);
    const auto remastered = play(program, graphics, cmos, true);
    std::array<std::set<std::pair<int,int>>, 4> changed;
    for (size_t i = 0; i < changed.size(); ++i) {
        const auto& a = original[i];
        const auto& b = remastered[i];
        need(a.frame == b.frame && a.cycles == b.cycles && a.ram == b.ram &&
             a.vram == b.vram && a.palette == b.palette, "presentation leaves the arcade state intact");
        need(a.raster.size() == 400 * 254 && a.raster.size() == b.raster.size(), "complete arcade rasters");
        for (size_t p = 0; p < a.raster.size(); ++p) {
            if (a.raster[p] == b.raster[p]) continue;
            const int y = int(p / 400) + a.camera_y;
            need(y >= 260 && y <= 290, "changed pixels stay on the arena floor");
            changed[i].emplace(int(p % 400) + a.camera_x, y);
        }
    }
    need(changed[0].empty(), "clean arena before any hit");
    need(!changed[1].empty(), "landed blood leaves visible stains after the uppercut");
    need(original[1].arena == original[2].arena && std::any_of(changed[2].begin(), changed[2].end(),
         [&](const auto& point) { return changed[1].count(point); }), "blood survives round 2 at the same world position");
    need(changed[3].empty(), "the next fight starts with a clean arena");
    const auto blood_off = play(program, graphics, cmos, true, 0xbeff);
    need(!blood_off[1].has_decal, "the Blood DIP suppresses stains");
    const auto violence_off = play(program, graphics, cmos, true, 0x7eff);
    need(violence_off[1].has_decal, "standard blood still lands with only Violence off");
    const auto same_arena = play(program, graphics, cmos, true, 0xfeff, true);
    need(same_arena[0].arena == same_arena[1].arena, "P2 challenge reuses the same arena");
    need(same_arena[0].has_decal, "the CPU fight has stains before the P2 challenge");
    need(!same_arena[1].has_decal, "P2 challenge clears the stains from that arena");
    std::cout << "PASS MK1 remastered blood, changed pixels";
    for (const auto& pixels : changed) std::cout << ' ' << pixels.size();
    std::cout << '\n';
    return 0;
} catch (const std::exception& e) {
    std::cerr << "FAIL MK1 remastered blood: " << e.what() << '\n';
    return 1;
}
