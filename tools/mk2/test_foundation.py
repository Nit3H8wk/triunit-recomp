"""ROM manifest boundary tests without proprietary ROM data."""
import hashlib
import importlib.util
import os
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("mk2_run", HERE / "run.py")
mk2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mk2)


class ManifestTests(unittest.TestCase):
    def test_first_sport_transfer_reads_real_half_buffer_without_cpu_accesses(self):
        source = r'''
#include "native/mk2/mk2_adsp.hpp"
#include <stdexcept>
void check(bool ok) { if (!ok) throw std::runtime_error("SPORT half-buffer contract"); }
int main() {
    mk2::DcsLink link;
    mk2::AdspBoot dsp(std::vector<uint32_t>(376), link);
    dsp.sport_enabled = true; dsp.sport_ireg = 7; dsp.sport_base = 0x400;
    dsp.dac_enabled_ = true;
    dsp.imask = 0x20; dsp.sport_size = 480; dsp.sport_incs = 1; dsp.i[7] = 0x400; dsp.l[7] = 480;
    for (unsigned n = 0; n < 480; ++n)
        dsp.external_pm[0x400+n] = (uint32_t(uint16_t(0x8000+n)) << 8) | 0x5a;
    const auto memory = dsp.external_pm;
    dsp.SportTransfer(7225490);
    check(dsp.i[7] == 0x4f0 && dsp.sport_base == 0x400 && dsp.sport_pcm.size() == 240);
    check(dsp.sport_transfers == std::vector<std::vector<uint64_t>>{{7225490,0,0,7,0x400,0x4f0,240}});
    for (unsigned n = 0; n < 240; ++n) check(dsp.sport_pcm[n] == int16_t(0x8000+n));
    check(dsp.external_pm == memory && dsp.trace.empty() && dsp.accesses.empty());
    check(dsp.DeviceState()[15] == 240 && dsp.DeviceState()[16] == 0);
    auto guarded = dsp.Registers();
    dsp.imask = 0x24;
    bool unmasked_rejected = false;
    try { dsp.SportTransfer(7993490); } catch (const std::runtime_error&) { unmasked_rejected = true; }
    check(unmasked_rejected && dsp.sport_pcm.size() == 240 && dsp.i[7] == 0x4f0);
    dsp.imask = 0x20;
    check(dsp.Registers() == guarded);
    dsp.SportTransfer(7993490);
    check(dsp.i[7] == 0x400 && dsp.sport_pcm.size() == 480);
    check(dsp.sport_transfers[1] == std::vector<uint64_t>{7993490,0,0,7,0x4f0,0x400,240});
    for (unsigned n = 0; n < 480; ++n) check(dsp.sport_pcm[n] == int16_t(0x8000+n));
    check(dsp.external_pm == memory && dsp.trace.empty() && dsp.accesses.empty());
    check(dsp.sport_irq1_asserted && dsp.sport_irq1_latched);
    dsp.ClearSportIrq1(7993500);
    check(!dsp.sport_irq1_asserted && dsp.sport_irq1_latched);
    check(dsp.sport_irq1_events == std::vector<std::vector<uint64_t>>{{7993490,0,0,1},{7993500,0,0,0}});
    check(dsp.sport_dma_positions == std::vector<uint64_t>{0,0} && dsp.sport_dma_position == 0);
    check(dsp.DeviceState()[16] == 240);
    dsp.DacUpdate(8000000);
    check(dsp.DeviceState()[15] == 480 && dsp.DeviceState()[16] == 243);
    const auto dac_state = dsp.DeviceState();
    bool backward_rejected = false;
    try { dsp.DacUpdate(7999999); } catch (const std::runtime_error&) { backward_rejected = true; }
    check(backward_rejected && dsp.DeviceState() == dac_state);
    auto before = dsp.Registers();
    bool rejected = false;
    dsp.SportTransfer(8761490);
    check(dsp.i[7] == 0x4f0 && dsp.sport_pcm.size() == 720 &&
          dsp.DeviceState()[15] == 720 && dsp.DeviceState()[16] == 480);
    for (unsigned n = 0; n < 240; ++n) check(dsp.sport_pcm[480+n] == dsp.sport_pcm[n]);
    const auto dac_memory = dsp.DacBuffer(720);
    dsp.pm[600] = 0x123456; dsp.dm[7] = 0xbeef; dsp.external_pm[777] = 0xaabbcc;
    dsp.ar = 0xabcd; dsp.se = 0xfff1; dsp.cntr = 187; dsp.astat = 0x95; dsp.mstat = 8;
    dsp.alternate_.ar = 0x5678; dsp.i[0] = 0x123; dsp.m[0] = -1;
    const auto warm = dsp.Registers();
    dsp.ReloadBoard();
    check(dsp.Registers() == warm && dsp.sport_irq1_latched &&
          dsp.DeviceState() == std::vector<uint64_t>{0,0,0x400,0,0,1,0,1,0,0,0,0,0,0,1,720,480});
    dsp.ResetCore();
    check(dsp.pc == 0 && dsp.cycles == 0 && dsp.imask == 0 && dsp.mstat == 0 &&
          !dsp.sport_irq1_asserted && !dsp.sport_irq1_latched && dsp.ar == 0xabcd &&
          dsp.alternate_.ar == 0x5678 && dsp.se == 0xfff1 && dsp.cntr == 187 &&
          dsp.astat == 0x95 && dsp.i[0] == 0x123 && dsp.m[0] == -1 &&
          dsp.pm[600] == 0x123456 && dsp.dm[7] == 0xbeef && dsp.external_pm[777] == 0xaabbcc);
    dsp.instruction_ticks_ = 9332610;
    dsp.trace.push_back(dsp.Registers());
    dsp.WriteControl(0x3fff, 0x10);
    check(dsp.DeviceState()[14] == 0 && dsp.DeviceState()[15] == 0 && dsp.DeviceState()[16] == 0 &&
          dsp.dac_write_sample_ == 2917 && dsp.dac_last_ticks_ == 9332610 &&
          dsp.DacBuffer(720) == dac_memory && dsp.sport_pcm.size() == 720 && dsp.sport_timer_cancelled);
    before = dsp.Registers();
    try { dsp.SportTransfer(9529490); } catch (const std::runtime_error&) { rejected = true; }
    check(rejected && dsp.Registers() == before && dsp.sport_pcm.size() == 720);
    mk2::DcsBootMachine machine(std::vector<uint32_t>(376));
    auto& d = machine.dsp;
    d.sport_enabled = true; d.sport_ireg = 7; d.sport_base = 0x400;
    d.dac_enabled_ = true;
    d.sport_size = d.l[7] = 480; d.sport_incs = 1; d.i[7] = 0x400;
    d.imask = 0x20; d.SportTransfer(7225490);
    d.rebooted_ = true; d.pc = 0x130; d.cycles = 158526;
    d.pm[0x130] = 0x0d02a3; d.pm[0x131] = 0x26e20f; d.ay0 = 0x4f0;
    machine.last_main_ = 499563; machine.dsp_ticks_ = 7993480;
    machine.next_sound_ticks_ = 8000000; machine.next_scanline_ticks_ = 7994800; machine.sport_deadline_ticks_ = 7993490;
    machine.MainInstruction(499597);
    check(d.cycles == 158528 && d.pc == 0x132 && d.i[7] == 0x400 &&
          !d.sport_irq1_asserted && d.sport_irq1_latched && d.trace.size() == 2 &&
          d.trace[0][0] == 0x130 && d.trace[1][0] == 0x131 && d.trace[1][23] == 0x400);
    check(d.sport_irq1_events == std::vector<std::vector<uint64_t>>{
          {7993490,0x131,158527,1},{7993500,0x132,158528,0}});
    check(d.pc_sp == 0 && d.stat_sp == 0 && d.imask == 0x20);

    // Signed extremes distinguish physical float32 conversion from silent ROM samples.
    mk2::DcsLink float_link;
    mk2::AdspBoot float_dsp(std::vector<uint32_t>(376), float_link);
    float_dsp.sport_enabled = float_dsp.dac_enabled_ = true;
    float_dsp.sport_ireg = 7; float_dsp.sport_base = float_dsp.i[7] = 0x400;
    float_dsp.sport_size = float_dsp.l[7] = 480; float_dsp.sport_incs = 1; float_dsp.imask = 0x20;
    const std::array<int16_t,5> samples{-32768,-1,0,1,32767};
    const std::array<uint32_t,5> words{0xbf800100,0xb8000100,0,0x38000100,0x3f800000};
    for (unsigned n = 0; n < 480; ++n)
        float_dsp.external_pm[0x400+n] = (uint32_t(uint16_t(samples[n%5])) << 8) | 0x5a;
    float_dsp.SportTransfer(7225490); float_dsp.SportTransfer(7993490);
    float_dsp.ClearSportIrq1(7993500); float_dsp.SportTransfer(8761490);
    const auto physical = float_dsp.DacBuffer(720);
    for (unsigned n = 0; n < 720; ++n) check(physical[n] == words[n%5]);

}
'''
        with mk2.quality.scratch_tree() as (scratch, cleanup):
            path = scratch / "sport.cpp"
            path.write_text(source, encoding="utf-8")
            executable = scratch / "sport.exe"
            compiler = mk2.quality.DEFAULT_CC
            env = {"PATH": str(compiler.parent) + os.pathsep + os.environ.get("PATH", "")}
            build = mk2.quality.command([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-Werror", "-fno-access-control",
                "-I" + str(mk2.ROOT), "-I" + str(mk2.ROOT / "native/include"), path,
                mk2.ROOT / "native/mk2/mk2_adsp.cpp", mk2.ROOT / "native/mk2/mk2_dcs.cpp",
                mk2.ROOT / "native/src/mk5_program.cpp", "-lbcrypt", "-o", executable], scratch, env=env)
            self.assertTrue(build["passed"], build.get("stdout", ""))
            result = mk2.quality.command([executable], scratch, env=env)
            self.assertTrue(result["passed"], result.get("stdout", ""))
        self.assertFalse(cleanup["exists_after"])

    def test_event_receipt_keeps_only_ordered_count_and_hash(self):
        events = [[112, 0x39, 4, 0x1816ef, 24], [100, 0x40, 5, 0xff, 25]]
        summary = mk2.event_summary(events)
        self.assertEqual(summary["ordered_events"], 2)
        self.assertEqual(summary["events_sha256"], hashlib.sha256(
            b'[[112,57,4,1578735,24],[100,64,5,255,25]]').hexdigest())
        self.assertNotEqual(summary, mk2.event_summary(events[::-1]))
        events[-1][-1] += 1
        self.assertNotEqual(summary, mk2.event_summary(events))
        self.assertEqual(set(summary), {"ordered_events", "events_sha256", "events_encoding"})

    def test_rom_check_cannot_claim_sanitized_execution(self):
        for sanitizer in ("address", "undefined"):
            with self.subTest(sanitizer=sanitizer), self.assertRaisesRegex(ValueError, "does not execute"):
                mk2.run("check", HERE / "missing-roms", sanitizer=sanitizer)

    def test_manifest_keeps_mk2_revision_and_all_regions(self):
        self.assertTrue(hasattr(mk2, "read_manifest"), "MK2 manifest loader is missing")
        manifest = mk2.read_manifest()
        self.assertEqual(manifest["revision"], "L3.1")
        self.assertEqual(len(manifest["roms"]), 20)
        self.assertEqual({r["region"] for r in manifest["roms"]}, {"maincpu", "dcs", "video"})

    def test_missing_wrong_size_and_changed_byte_are_rejected(self):
        self.assertTrue(hasattr(mk2, "verify_roms"), "MK2 ROM verification is missing")
        fixture = {"roms": [{"path": "sample", "size": 4,
                              "sha256": hashlib.sha256(b"ROM!").hexdigest()}]}
        with mk2.quality.scratch_tree() as (scratch, cleanup):
            with self.assertRaisesRegex(ValueError, "missing"):
                mk2.verify_roms(scratch, fixture)
            (scratch / "sample").write_bytes(b"R")
            with self.assertRaisesRegex(ValueError, "size"):
                mk2.verify_roms(scratch, fixture)
            (scratch / "sample").write_bytes(b"ROM?")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                mk2.verify_roms(scratch, fixture)
            (scratch / "sample").write_bytes(b"ROM!")
            self.assertEqual(mk2.verify_roms(scratch, fixture)["verified"], 1)
        self.assertFalse(cleanup["exists_after"])

    def test_manifest_cannot_escape_rom_directory(self):
        self.assertTrue(hasattr(mk2, "verify_roms"), "MK2 ROM verification is missing")
        for path in ("../outside", "C:/outside", "nested/../../outside", "nested\\outside"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "path"):
                mk2.verify_roms(HERE, {"roms": [{"path": path}]})


if __name__ == "__main__":
    unittest.main()
