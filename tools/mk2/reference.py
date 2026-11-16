"""Finite, read-only MAME/native observations; no state import into either executor."""
from pathlib import Path
import json
import hashlib
import os
import struct
from functools import cache

REFERENCE_LOG_LIMIT_BYTES = 2048 * 1024 * 1024

POINTS = {"prefix": 0xff811150, "status": 0xff811180, "branch": 0xff8111c0,
          "sound": 0xffa4b860, "scan": 0xffa4b9c0, "checked": 0xffa4bc10,
          "record": 0xffa4c040, "stored": 0xffa4c070,
          "routine": 0xffa4cb50, "restored": 0xffa4c090, "returned": 0xff8111f0,
          "board_entry": 0xffa5fa20, "board_configured": 0xffa5c180, "board_ready": 0xffa5c200,
          "dsw_read": 0xffa5c230, "dsw_branch": 0xffa5c270, "dsw_taken": 0xffa5fc40,
          "reset_entry": 0xff811220, "ram_clear_entry": 0xff814e80,
          "timer_first": 0xff814e80, "timer_second": 0xff814e80, "ram_midpoint": 0xff814e80,
          "ram_cleared": 0xff814ea0,
          "after_clear": 0xff8112b0, "powerup_ready": 0xffa5a000,
          "video_palette_entry": 0xffa5b160, "video_palette_ready": 0xffa5a150,
          "video_vram_entry": 0xffa59f00, "video_vram_mid": 0xffa59f00,
          "video_vram_last": 0xffa59f00, "video_vram_cleared": 0xffa59f20,
          "video_ready": 0xffa5a190,
          "text_center_entry": 0xffa593b0, "text_centered": 0xffa5a200,
          "text_renderer_entry": 0xffa590c0, "text_first_glyph": 0xffa592b0,
          "text_last_glyph": 0xffa592b0, "text_rendered": 0xffa5a2a0,
          "text_cmos_checked": 0xffa5a2d0, "text_ready": 0xffa5a2e0}
FACTORY_POINTS = {"factory_entry": 0xffa4cb90, "factory_audit_ready": 0xffa4cc00,
    "factory_defaults_written": 0xffa4ccf0, "factory_checksum_written": 0xffa4cd10,
    "factory_revision_written": 0xffa4ce20, "ranking_entry": 0xffa284c0,
    "ranking_cleared": 0xffa27890, "ranking_insert_entry": 0xffa27b00,
    "ranking_entries_ready": 0xffa286e0, "ranking_checksum_ready": 0xffa28700,
    "ranking_return": 0xffa4ce70, "factory_return": 0xffa5a310,
    "audits_entry": 0xffa4c140, "audits_first": 0xffa4be80, "audits_last": 0xffa4be80,
    "factory_ready": 0xffa5a340}
POST_FACTORY_POINTS = {"post_check_entry": 0xffa4c1f0, "post_defaults_checked": 0xffa4c210,
    "post_revision_entry": 0xffa4c850, "post_revision_checked": 0xffa4c240,
    "post_cmos_checked": 0xffa5a380, "post_status_centered": 0xffa5a630,
    "post_status_rendered": 0xffa5a7f0, "post_audit_checked": 0xffa536b0,
    "post_audit_ready": 0xffa5a820, "post_dsw_ready": 0xffa5a840,
    "post_coinage_centered": 0xffa5aa30, "post_coinage_rendered": 0xffa5aad0,
    "post_inputs_read": 0xffa5ab00, "post_factory_ready": 0xffa5ac90}
SOUND_COMMAND_POINTS = {"sound_command_entry": 0xffa3aed0, "sound_command_saved": 0xffa13bc0,
    "sound_command_high_written": 0xffa13c90, "sound_command_high_polled": 0xffa13ce0,
    "sound_command_low_written": 0xffa13d60, "sound_command_low_polled": 0xffa13db0,
    "sound_command_ready": 0xffa5acc0}
INPUT_WAIT_POINTS = {"input_wait_centered": 0xffa5ad30, "input_wait_ready": 0xffa592b0}
INPUT_POLL_POINTS = {"input_poll_rendered": 0xffa5add0, "input_poll_prepared": 0xffa5aef0,
    "input_poll_unmapped_write": 0xffa5af20, "input_poll_secondary": 0xffa5afd0, "input_poll_ready": 0xffa5aef0}
POINTS.update(FACTORY_POINTS)
POINTS.update(POST_FACTORY_POINTS)
POINTS.update(SOUND_COMMAND_POINTS)
POINTS.update(INPUT_WAIT_POINTS)
INPUT_IDLE_POINTS = {"input_idle_pre_sport": 0xffa5aef0, "input_idle_post_sport": 0xffa5aef0, "input_idle_ready": 0xffa5aef0}
INPUT_IDLE_CYCLE = 460021
INPUT_IDLE_BUS_COUNT = (INPUT_IDLE_CYCLE - 407967) // 34 * 9
POINTS.update(INPUT_POLL_POINTS)
POINTS.update(INPUT_IDLE_POINTS)
SPORT_WRAP_CYCLE = 506023
SPORT_WRAP_BUS_COUNT = (SPORT_WRAP_CYCLE - INPUT_IDLE_CYCLE) // 34 * 9
SPORT_WRAP_POINTS = {name: 0xffa5aef0 for name in ("sport_wrap_pre_callback", "sport_wrap_post_callback", "sport_wrap_ready")}
POINTS.update(SPORT_WRAP_POINTS)
POINT_CONDITIONS = {"timer_first": "a2==7b10", "timer_second": "a2==7a8c", "ram_midpoint": "a2==4000",
                    "video_vram_entry": "b4==10000", "video_vram_mid": "b4==8000", "video_vram_last": "b4==1",
                    "text_first_glyph": "a0==ffa401c8&&(st&2000000)==0",
                    "text_last_glyph": "a0==ffa40220&&(st&2000000)==0"}
POINT_CONDITIONS.update({name: f"totalcycles>={305359:x}" for name in FACTORY_POINTS})
POINT_CONDITIONS.update(ranking_insert_entry=f"totalcycles>={305359:x}&&a8==ffa28790",
                        audits_first=f"totalcycles>={305359:x}&&a0==1",
                        audits_last=f"totalcycles>={305359:x}&&a0==2c")
POINT_CONDITIONS.update({name: f"totalcycles>={379387:x}" for name in POST_FACTORY_POINTS})
POINT_CONDITIONS.update({name: f"totalcycles>={399187:x}" for name in SOUND_COMMAND_POINTS})
POINT_CONDITIONS.update({name: f"totalcycles>={399321:x}" for name in INPUT_WAIT_POINTS})
POINT_CONDITIONS.update(input_wait_ready=f"totalcycles=={400774:x}")
POINT_CONDITIONS.update({name: f"totalcycles>={400774:x}" for name in INPUT_POLL_POINTS})
POINT_CONDITIONS.update(input_poll_prepared=f"totalcycles=={407933:x}", input_poll_ready=f"totalcycles=={407967:x}")
POINT_CONDITIONS.update(input_idle_pre_sport=f"totalcycles=={451589:x}",
                        input_idle_post_sport=f"totalcycles=={451623:x}",
                        input_idle_ready=f"totalcycles=={INPUT_IDLE_CYCLE:x}")
POINT_CONDITIONS.update(sport_wrap_pre_callback=f"totalcycles=={499563:x}",
                        sport_wrap_post_callback=f"totalcycles=={499597:x}",
                        sport_wrap_ready=f"totalcycles=={SPORT_WRAP_CYCLE:x}")
BUTTON_EXIT_CYCLE = 780256
BUTTON_EXIT_BUS_COUNT = 148464
BUTTON_EXIT_POINTS = {
    "button_exit_pressed": (0xffa5aef0, 506023), "button_exit_changed": (0xffa5b130, 571254),
    "button_exit_reset_before": (0xffa13ec0, 571275), "button_exit_held": (0xffa13ef0, 571278),
    "button_exit_release_before": (0xffa13f50, 583284), "button_exit_released": (0xffa13f80, 583287),
    "button_exit_board_reloaded": (0xff814f10, 583518), "button_exit_gfx_configured": (0xff814f30, 583554),
    "button_exit_pitches": (0xff814f60, 583589), "button_exit_clear_entry": (0xff80f290, 583629),
    "button_exit_clear_mid": (0xff80f290, 681933), "button_exit_clear_last": (0xff80f290, 780234),
    "button_exit_cleared": (0xff80f2b0, 780238), "button_exit_ready": (0xff815090, BUTTON_EXIT_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in BUTTON_EXIT_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in BUTTON_EXIT_POINTS.items()})
VIDEO_IRQ_CYCLE = 816384
VIDEO_IRQ_BUS_COUNT = 6255
VIDEO_IRQ_POINTS = {
    "video_irq_enabled": (0xff815170, 780270), "video_irq_dip": (0xff8158f0, 780287),
    "video_irq_lists": (0xff80df40, 780587), "video_irq_buffers": (0xff808310, 781660),
    "video_irq_returned": (0xff811360, 792746), "video_irq_handshake": (0xff815300, 809267),
    "video_irq_eint": (0xff8114c0, 815654), "video_irq_entered": (0xff816370, 815673),
    "video_irq_reti": (0xff816e90, 816373), "video_irq_ready": (0xff8114d0, VIDEO_IRQ_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in VIDEO_IRQ_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in VIDEO_IRQ_POINTS.items()})
STARTUP_CYCLE = 818697
STARTUP_BUS_COUNT = 337
STARTUP_POINTS = {
    "startup_ranking_sum": (0xffa28440, 818142), "startup_ranking_read": (0xffa28470, 818289),
    "startup_ranking_valid": (0xffa284b0, 818292), "startup_ranking_ready": (0xff811500, 818299),
    "startup_service_ready": (0xff811570, 818584), "startup_task_entry": (0xff80e280, 818599),
    "startup_task_saved": (0xff80e3d0, 818633), "startup_task_queued": (0xff80e420, 818664),
    "startup_ready": (0xff811710, STARTUP_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in STARTUP_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in STARTUP_POINTS.items()})
DISPATCHER_CYCLE = 846457
DISPATCHER_BUS_COUNT = 8420
DISPATCHER_POINTS = {
    "dispatcher_entered": (0xff80dae0, 818701), "dispatcher_task": (0xff843030, 818975),
    "dispatcher_task_initialized": (0xff847660, 832307), "dispatcher_yield_call": (0xff847bb0, 846419),
    "dispatcher_yield_entry": (0xff80dcc0, 846423), "dispatcher_ready": (0xff80dd30, DISPATCHER_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in DISPATCHER_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in DISPATCHER_POINTS.items()})
TASK_RESUME_CYCLE = 1146279
TASK_RESUME_BUS_COUNT = 99699
TASK_RESUME_POINTS = {
    "task_resume_dispatcher": (0xff80dae0, 846795),
    "task_resume_irq1_entered": (0xff816370, 913998), "task_resume_irq1_reti": (0xff816e90, 915567),
    "task_resume_irq2_entered": (0xff816370, 1028224), "task_resume_irq2_reti": (0xff816e90, 1029294),
    "task_resume_irq3_entered": (0xff816370, 1142489), "task_resume_irq3_reti": (0xff816e90, 1143552),
    "task_resume_resumed": (0xff847be0, 1143822), "task_resume_yield_entry": (0xff80dcc0, 1146245),
    "task_resume_ready": (0xff80dd30, TASK_RESUME_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in TASK_RESUME_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in TASK_RESUME_POINTS.items()})
TASK_QUEUE_CYCLE = 1159587
TASK_QUEUE_BUS_COUNT = 507
TASK_QUEUE_POINTS = {
    "task_queue_selected1": (0xff80dd50, 1146283), "task_queue_task1": (0xff80fe50, 1146325),
    "task_queue_yield1": (0xff80dcc0, 1147865), "task_queue_saved1": (0xff80dd30, 1147899),
    "task_queue_selected2": (0xff80dd50, 1147903), "task_queue_task2": (0xff80fe50, 1147945),
    "task_queue_yield2": (0xff80dcc0, 1153709), "task_queue_saved2": (0xff80dd30, 1153743),
    "task_queue_selected3": (0xff80dd50, 1153747), "task_queue_task3": (0xff80fe50, 1153789),
    "task_queue_yield3": (0xff80dcc0, 1159553), "task_queue_ready": (0xff80dd30, TASK_QUEUE_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in TASK_QUEUE_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in TASK_QUEUE_POINTS.items()})
POINT_CONDITIONS.update(task_queue_task2=f"totalcycles>={TASK_RESUME_CYCLE:x}&&a13==106b150",
                        task_queue_task3=f"totalcycles>={TASK_RESUME_CYCLE:x}&&a13==106aa60")
TASK_QUEUE_IMAGE_SIZES = (("main_ram", 262144), ("cmos", 8192), ("palette_ram", 32768), ("vram", 524288),
                        ("board_io", 28), ("display", 2), ("dma_registers", 18), ("shiftreg", 4096))
TASK_PALETTE_CYCLE = 1258434
TASK_PALETTE_BUS_COUNT = 29307
TASK_PALETTE_POINTS = {
    "task_palette_selected1": (0xff80dd50, 1159591), "task_palette_yield1": (0xff80dcc0, 1161173),
    "task_palette_saved1": (0xff80dd30, 1161207), "task_palette_selected2": (0xff80dd50, 1161211),
    "task_palette_yield2": (0xff80dcc0, 1167017), "task_palette_saved2": (0xff80dd30, 1167051),
    "task_palette_selected3": (0xff80dd50, 1167055), "task_palette_yield3": (0xff80dcc0, 1172861),
    "task_palette_saved3": (0xff80dd30, 1172895), "task_palette_traversed": (0xff80de10, 1172900),
    "task_palette_dispatcher": (0xff80dae0, 1173097), "task_palette_irq_entered": (0xff816370, 1256742),
    "task_palette_ready": (0xff816a30, TASK_PALETTE_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in TASK_PALETTE_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in TASK_PALETTE_POINTS.items()})
TASK_DRAW_CYCLE = 1261260
TASK_DRAW_BUS_COUNT = 523
TASK_DRAW_POINTS = {
    "task_draw_dma_entry": (0xff8044f0, 1259215), "task_draw_trap": (0xff8045d0, 1259231),
    "task_draw_dma_started": (0xff804640, 1259256), "task_draw_trap_reti": (0xff8046d0, 1259267),
    "task_draw_reti": (0xff816e90, 1259530), "task_draw_returned": (0xff807e60, 1259541),
    "task_draw_dispatcher": (0xff80dd30, 1259632), "task_draw_selected1": (0xff80dd50, 1259636),
    "task_draw_selected2": (0xff80dd50, 1259651),
    "task_draw_dma_busy": (0xff810250, 1260496), "task_draw_dma_completed": (0xff810260, 1260517),
    "task_draw_yield": (0xff80dcc0, 1261226),
    "task_draw_ready": (0xff80dd30, TASK_DRAW_CYCLE)}
POINTS.update({name: pc for name, (pc, _) in TASK_DRAW_POINTS.items()})
POINT_CONDITIONS.update({name: f"totalcycles=={cycle:x}" for name, (_, cycle) in TASK_DRAW_POINTS.items()})
BUTTON_DSP_POINTS = tuple("button_exit_" + name for name in
                          ("reset_before", "held", "release_before", "released", "board_reloaded", "ready"))
DSP_IMAGE_SIZES = (("dsp_pm", 1024), ("dsp_dm", 512), ("dsp_control", 32),
                   ("dsp_external_pm", 2048), ("dsp_external_dm", 2048), ("dsp_device", 17))
BOARD_WRITE_COUNT = 34
POWERUP_WRITE_COUNT = 32772
POWERUP_FETCH = {0xffa5fc90: (48, 16), 0xffa5fcc0: (48, 16),
                 0xff811290: (16, 32), 0xff814e90: (16, 32), 0xff811310: (48, 32)}
VIDEO_WRITE_COUNT = 65556
VIDEO_FETCH = {pc + 48: (48, 16) for pc in (0xffa5a020, 0xffa5a050, 0xffa5a0a0, 0xffa5a0d0,
                 0xffa5b170, 0xffa5b1a0, 0xffa5b270, 0xffa5b2a0, 0xffa5b2d0, 0xffa5b300)}
VIDEO_FETCH.update({0xffa5b250: (16, 16), 0xffa59f10: (16, 32)})
BOARD_FETCH_BITS = {pc: 48 for pc in (0xff811030, 0xffa5fac0, 0xffa5faf0, 0xffa5fb20,
                                      0xffa5fb70, 0xffa5c1d0, 0xffa5c200)}
BOARD_FETCH_BITS[0xffa5fc10] = 16
RETURN_RAM_KEYS = ("routine_ram", "restored_ram", "returned_ram")
BOOT_WORDS = 376
DSP_PCS = list(dict.fromkeys([0, *range(0x22, 0x49), 4, *range(0x16e, 0x177),
                             *range(0x8, 0x25), *range(0xf4, 0xf9), *range(0x3e8, 0x3f6), *range(0x800, 0x8ae)]))
DSP_PCS = list(dict.fromkeys(DSP_PCS + list(range(0x1aa)) + list(range(0xa7e, 0xaff))))
DSP_PCS += [*range(0x394, 0x39c), *range(0x39d, 0x3b2), *range(0x3b3, 0x3b6), *range(0x3bf, 0x3da), *range(0x3e2, 0x3e8)]
# Original first-task sound-command handler path, observed independently through its return.
DSP_PCS += [0x3b2, 0x3b7, 0x3b8, 0x3b9, 0x3ba, 0x3bb, 0x3bc, 0x3bd, 0x3be]
# Executed command/voice path through the second yield; PM and DM aliases observed independently.
DSP_PCS += [
    *range(0x1aa, 0x1ca), *range(0x1ce, 0x1d6), *range(0x1e7, 0x228), *range(0x237, 0x23a),
    *range(0x2af, 0x2b5), *range(0x2ba, 0x2ca), *range(0x2d4, 0x2da), 0x2e7, 0x311, 0x317,
    *range(0x328, 0x32f), *range(0x332, 0x358), *range(0x35e, 0x394), *range(0x8ae, 0x8d7),
    *range(0x8db, 0x900), *range(0x901, 0x970), *range(0x978, 0x998), *range(0x99f, 0x9b6),
    *range(0x9be, 0x9c7), *range(0x9f7, 0xa24), *range(0xa27, 0xa3c), *range(0xa45, 0xa61),
    *range(0xa63, 0xa7e),
]
# Original voice tail reached after the fifth yield; authenticated independently against U2.
DSP_PCS += list(range(0x998, 0x99f))
DSP_PCS = list(dict.fromkeys(DSP_PCS + [int(pc,16)
    for filename in ('coin_pair_dsp_path.json','start_release_dsp_path.json','selection_dsp_path.json','first_fight_dsp_path.json')
    for pc in json.loads(Path(__file__).with_name(filename).read_text(encoding='utf-8'))['pcs']]))

PM_READ_PCS = (0x38, 0x834, 0x83a, 0x840, 0x846, 0x84c, 0x852)
DCS_DEVICE_FIELDS = ("sounddata_bank", "ireg", "ireg_base", "incs", "size", "channels", "timer_enable",
                     "timer_scale", "timer_period", "timers_fired", "timer_start_count", "timer_start_cycles",
                     "timer_ignore", "progflags", "dac_enabled", "dac_bufin", "dac_bufout")
DSP_REGISTERS = ["pc", "totalcycles", "ar", "si", "px", "cntr", "astat", "sstat", "mstat",
                 "imask", "icntl", "pcsp", "cntrsp", "loopsp", "statsp", "irq2"]
DSP_REGISTERS += [f"{reg}{n}" for reg in ("i", "m", "l") for n in range(8)]
CORE = ["ax0", "ax1", "ay0", "ay1", "ar", "af", "mx0", "mx1", "my0", "my1",
        "mr0", "mr1", "mr2", "mf", "si", "se", "sb", "sr0", "sr1"]
DSP_REGISTERS += [reg for reg in CORE if reg not in ("ar", "si")] + [reg + "_sec" for reg in CORE]
RAM_ADDRESSES = sorted([0x0105bb10, 0x010b95a0, *range(0x010ffdd0, 0x010ffff0, 32)])
STORED_RAM_ADDRESSES = sorted([0x0105bb10, 0x010b95a0, *range(0x010ffd90, 0x010ffff0, 32)])
SOUND_RAM_ADDRESSES = [a for a in RAM_ADDRESSES if a < 0x010ffdd0 or a >= 0x010ffed0]
TEXT_GLYPH_POINTS = {0xffa401c8: "text_first_glyph", 0xffa40220: "text_last_glyph"}
TEXT_READ_COUNT, TEXT_WRITE_COUNT, TEXT_PIXBLT_COUNT = 1424, 1013, 16
TEXT_READ_FETCH = {pc + 16: pc for pc in (0xffa593e0, 0xffa59450, 0xffa59460,
    0xffa59180, 0xffa591f0, 0xffa59200, 0xffa59280, 0xffa592b0, 0xffa4d320,
    0xffa4d310, 0xffa4cac0, 0xffa4d360, 0xffa4d410, 0xffa4d530, 0xffa4c410, 0xffa4c240)}
TEXT_READ_FETCH.update({pc + 32: pc for pc in (0xffa4caa0, 0xffa4d510, 0xffa4c3f0)})
TEXT_WRITE_FETCH = {pc + 16: pc for pc in (0xffa592b0, 0xffa5a2a0, 0xffa4c1f0,
    0xffa4c270, 0xffa4ca70, 0xffa4c2f0, 0xffa4d3c0, 0xffa4c3b0, 0xffa4d440, 0xffa4d4b0)}
TEXT_WRITE_FETCH.update({pc + 32: pc for pc in (0xffa4c250, 0xffa4ca30, 0xffa4d420)})
TEXT_WRITE_FETCH[0xffa59150] = 0xffa59120
FACTORY_BUS_COUNT = 23755
POST_FACTORY_BUS_COUNT, POST_FACTORY_PIXBLT_COUNT = 6542, 74
SOUND_COMMAND_BUS_COUNT = 37
INPUT_WAIT_BUS_COUNT, INPUT_WAIT_PIXBLT_COUNT = 340, 2
INPUT_POLL_BUS_COUNT, INPUT_POLL_PIXBLT_COUNT = 2828, 56


@cache
def factory_fetch_bits(opcode):
    exact = {0x01c0: 16, 0x01e0: 16, 0x0960: 16, 0x098f: 32, 0x09af: 32, 0x099f: 32, 0x09bf: 32,
             0x0d3f: 16, 0x0d5f: 16, 0x0fa0: 16}
    if opcode in exact: return exact[opcode]
    if opcode & 0xffe0 in (0x0580, 0x05a0, 0x05e0, 0x0780, 0x07a0, 0x07e0): return 48
    if opcode & 0xfe00 in (0x8000, 0x8600, 0x8c00, 0x8e00, 0x9200, 0x9400, 0x9600, 0x9800, 0xa200): return 16
    raise ValueError(f"Unknown factory bus opcode {opcode:04x}")


def video_irq_fetch_bits(opcode, write):
    if opcode == 0x05c0: return 80 if write else 48
    if opcode in (0x8201, 0x8202, 0x820d, 0x8222, 0x8ba0, 0x9020, 0x9023, 0x9043, 0x91c1, 0x9a43, 0xa022, 0xa023, 0xa182, 0x0d60, 0x0940): return 16
    if opcode in (0xb041, 0xb422, 0x0982): return 32
    return factory_fetch_bits(opcode)


class _ProgramOpcodeLengths(dict):
    """Exact lengths of the reached L3.1 opcode classes (checked against the pinned offline decoder).

    Only program-ROM locators and lengths are versioned (dispatcher_opcode_locators.json); the opcodes are read from
    the user's program image on first use and accepted only when the SHA-256 of the (opcode, bits) pairs matches.
    """
    def _load(self):
        if dict.__len__(self): return
        locators = json.loads(Path(__file__).with_name("dispatcher_opcode_locators.json").read_text(encoding="utf-8"))
        manifest = json.loads(Path(__file__).with_name("roms-l31.json").read_text(encoding="utf-8"))
        if locators["program_sha256"] != manifest["program_sha256"]: raise ValueError("Opcode locators name another program")
        opcode = factory_opcode_reader(factory_program_image(Path(__file__).resolve().parents[2] / "roms/mk2", manifest))
        table = {opcode(int(pc, 16)): int(bits) for bits, pcs in locators["bits"].items() for pc in pcs}
        pairs = b"".join(int(v).to_bytes(8, "little") for item in sorted(table.items()) for v in item)
        if hashlib.sha256(pairs).hexdigest() != locators["sha256"]:
            raise ValueError("Dispatcher opcode classes differ from the authenticated program ROM")
        dict.update(self, table)

    def __contains__(self, key): self._load(); return dict.__contains__(self, key)
    def __getitem__(self, key): self._load(); return dict.__getitem__(self, key)
    def __iter__(self): self._load(); return dict.__iter__(self)
    def __len__(self): self._load(); return dict.__len__(self)
    def get(self, key, default=None): self._load(); return dict.get(self, key, default)
    def items(self): self._load(); return dict.items(self)
    def keys(self): self._load(); return dict.keys(self)


DISPATCHER_INSTRUCTION_BITS = _ProgramOpcodeLengths()


def dispatcher_fetch_bits(opcode, write):
    if opcode not in DISPATCHER_INSTRUCTION_BITS:
        raise ValueError(f"Unknown dispatcher bus opcode {opcode:04x}")
    if opcode == 0x05c0: return 80 if write else 48
    # CALL pushes its return PC before fetching its displacement/address parameters.
    if opcode in (0x0d3f, 0x0d5f): return 16
    return DISPATCHER_INSTRUCTION_BITS[opcode]


def dispatcher_bus_row(pc, address, value, cycle, size, source, write, opcode_reader):
    opcode = opcode_reader(source)
    if opcode not in DISPATCHER_INSTRUCTION_BITS:
        raise ValueError(f"Unknown dispatcher bus opcode {opcode:04x}")
    bits = DISPATCHER_INSTRUCTION_BITS[opcode]
    delta = (pc - source) & 0xffffffff
    if not write and source <= address < source + bits:
        stage = (16 if address == source or opcode in (0x0d3f, 0x0d5f, 0x0d82, 0x0d89, 0xc000, 0xc080) else
                 32 if opcode == 0xbaa8 and address == source + 16 else
                 48 if opcode == 0x05c0 and address < source + 48 else bits)
        if delta != stage or value != opcode_reader(address):
            raise ValueError("Unauthenticated dispatcher instruction fetch lane")
        return None
    if delta != dispatcher_fetch_bits(opcode, write):
        raise ValueError(f"Unexpected dispatcher fetched PC {pc:08x} for CURPC {source:08x}, opcode {opcode:04x}")
    return [119 if write else 114, source, address, value, cycle, size]


def factory_program_image(directory, manifest):
    lanes = sorted((r for r in manifest["roms"] if r["region"] == "maincpu"), key=lambda r: r["offset_bytes"])
    if len(lanes) != 2 or [r["offset_bytes"] for r in lanes] != [0, 1]:
        raise ValueError("Invalid factory program lanes")
    image = bytearray(0x100000)
    for lane in lanes:
        name = lane["path"]
        if Path(name).name != name or any(c in name for c in "/\\:") or lane["stride_bytes"] != 2:
            raise ValueError("Invalid factory program lane")
        data = (directory / name).read_bytes()
        if len(data) != 0x80000 or hashlib.sha256(data).hexdigest() != lane["sha256"]:
            raise ValueError("Factory program lane SHA-256 or size mismatch")
        image[lane["offset_bytes"]::2] = data
    if hashlib.sha256(image).hexdigest() != manifest["program_sha256"]:
        raise ValueError("Factory program image SHA-256 mismatch")
    return bytes(image)


def factory_opcode_reader(image):
    if len(image) != 0x100000: raise ValueError("Incomplete factory program image")

    @cache
    def opcode(pc):
        if not 0xff800000 <= pc <= 0xfffffff0 or pc & 15:
            raise ValueError("Factory opcode PC outside program ROM")
        return struct.unpack_from("<H", image, (pc - 0xff800000) // 8)[0]
    return opcode


def validate_dispatcher_native_data(native, directory, manifest, *, phase="dispatcher"):
    if phase not in ("dispatcher", "task_resume", "task_queue", "task_palette", "task_draw"): raise ValueError("Unknown native data phase")
    opcode_reader = factory_opcode_reader(factory_program_image(directory, manifest))
    reads, rom_reads = 0, 0
    for row in native[phase + "_bus"]:
        if len(row) != 6 or row[0] not in (114, 119) or row[-1] != 16:
            raise ValueError("Malformed native dispatcher data lane")
        if row[0] != 114: continue
        _, source, address, _, _, _ = row
        opcode = opcode_reader(source)
        if opcode not in DISPATCHER_INSTRUCTION_BITS:
            raise ValueError(f"Unknown dispatcher bus opcode {opcode:04x}")
        if source <= address < source + DISPATCHER_INSTRUCTION_BITS[opcode]:
            raise ValueError("Native dispatcher data self-reads current instruction; fetch subtraction is ambiguous")
        reads += 1
        if address >= 0xff800000: rom_reads += 1
    return {"data_read_lanes": reads, "rom_data_read_lanes": rom_reads, "self_overlapping_reads": 0}


def cpu_snapshot(fields):
    if len(fields) != 34: raise ValueError("Incomplete CPU snapshot")
    return {"pc": int(fields[0], 16), "status": int(fields[1], 16), "cycles": int(fields[2]),
            "a": [int(v, 16) for v in fields[3:19]], "b": [int(v, 16) for v in fields[19:34]]}


SPORT_PACKETS = ((7225490, 0x136, 0x138, 81726, 0x400, 0x4f0),
                 (7993490, 0x131, 0x130, 158526, 0x4f0, 0x400),
                 (8761490, 0x137, 0x136, 235326, 0x400, 0x4f0))
SPORT_SAMPLES = len(SPORT_PACKETS) * 240
TASK_RESUME_SPORT_PACKETS = ((13552570, 0x136, 0x138, 81726, 0x400, 0x4f0),
                            (14320570, 0x131, 0x130, 158526, 0x4f0, 0x400),
                            (15088570, 0x138, 0x137, 235326, 0x400, 0x4f0),
                            (15856570, 0x131, 0x130, 312126, 0x4f0, 0x400),
                            (16624570, 0x137, 0x136, 388926, 0x400, 0x4f0),
                            (17392570, 0x131, 0x130, 465726, 0x4f0, 0x400),
                            (18160570, 0x136, 0x138, 542526, 0x400, 0x4f0))
TASK_RESUME_SAMPLES = len(TASK_RESUME_SPORT_PACKETS) * 240
TASK_PALETTE_SPORT_PACKETS = ((18928570, 0x132, 0x131, 619326, 0x4f0, 0x400),
                             (19696570, 0x138, 0x137, 696126, 0x400, 0x4f0))
TASK_PALETTE_SAMPLES = len(TASK_PALETTE_SPORT_PACKETS) * 240
DSP_IRQ_HOOKS = tuple((pc, cycle + pc - 0x131) for cycle in (158527, 312127, 465727)
                      for pc in (0x131, 0x132)) + ((0x132, 619327), (0x130, 619328))


def sport_dma_observations(raw, dma_rows, positions, *, phase="sport"):
    if phase not in ("sport", "task_resume", "task_palette"): raise ValueError("Unknown SPORT phase")
    packets = {"sport": SPORT_PACKETS, "task_resume": TASK_RESUME_SPORT_PACKETS, "task_palette": TASK_PALETTE_SPORT_PACKETS}[phase]
    samples = len(packets) * 240
    prefix = phase
    if (len(raw) != samples or len(dma_rows) != samples or not isinstance(positions, list) or
            len(positions) != len(packets) or any(not isinstance(v, int) or v < 0 for v in positions) or
            positions != sorted(positions)):
        raise ValueError("Incomplete or malformed SPORT DMA watchpoint provenance")
    for packet, (tick, pc, previous, cycle, first, after) in enumerate(packets):
        for index in range(240):
            offset = packet * 240 + index
            row, lua = raw[offset], dma_rows[offset]
            if (len(row) != 5 or row[:3] != [114, previous, first + index] or row[4] != cycle or
                    lua != (tick, pc, first + index, row[3])):
                raise ValueError("SPORT DMA Lua/watchpoint observations differ")
    return {prefix + "_dma_reads": [[row[0], row[1], raw[index][4], row[2], row[3]] for index, row in enumerate(dma_rows)],
            prefix + "_pcm": [row[3] if row[3] < 0x8000 else row[3] - 0x10000 for row in dma_rows],
            **({prefix + "_transfers": [[tick, pc, cycle+1, 7, first, after, 240]
                                        for tick, pc, _, cycle, first, after in packets]} if phase == "task_palette" else {})}


def native_dac_buffer(pcm):
    # Pinned dmadac.h stores float samples scaled by float(1 / int16_max).
    scale = struct.unpack("<f", struct.pack("<f", 1 / 32767))[0]
    return [struct.unpack("<I", struct.pack("<f", sample * scale))[0] for sample in pcm]


def native_sport_dma_reads(native, *, phase="sport"):
    if phase not in ("sport", "task_resume", "task_palette"): raise ValueError("Unknown SPORT phase")
    packets = {"sport": SPORT_PACKETS, "task_resume": TASK_RESUME_SPORT_PACKETS, "task_palette": TASK_PALETTE_SPORT_PACKETS}[phase]
    prefix = phase
    events, pcm, trace = native.get(prefix + "_transfers", []), native.get(prefix + "_pcm", []), native.get("dsp_trace", [])
    counts = native.get("task_queue_event_counts") if phase == "task_palette" else native.get("dispatcher_event_counts")
    if phase == "task_palette" and counts is None: raise ValueError("Missing native task-queue instruction boundary")
    if counts is not None and len(counts) != 8: raise ValueError("Incomplete native historical dispatcher event counts")
    boundary = counts[0] if counts is not None else len(trace)
    if not isinstance(boundary, int) or not 0 < boundary <= len(trace): raise ValueError("Invalid native historical dispatcher instruction boundary")
    if phase == "task_resume" and "task_queue_event_counts" in native:
        end = native["task_queue_event_counts"]
        if len(end) != 8 or not isinstance(end[0], int) or not boundary <= end[0] <= len(trace):
            raise ValueError("Invalid native task-queue instruction boundary")
        trace = trace[boundary:end[0]]
    else: trace = trace[boundary:] if phase in ("task_resume", "task_palette") else trace[:boundary]
    if len(events) != len(packets) or any(len(event) != 7 for event in events) or len(pcm) != len(packets) * 240:
        raise ValueError("Incomplete native SPORT transfer")
    result = []
    i7 = DSP_REGISTERS.index("i7")
    for packet, (event, expected) in enumerate(zip(events, packets)):
        tick, pc, cycle, register, first, after, count = event
        etick, epc, previous, cached, efirst, eafter = expected
        if event != [etick, epc, cached + 1, 7, efirst, eafter, 240]:
            raise ValueError("Unsupported native SPORT transfer")
        hooks = [index for index, row in enumerate(trace) if row[0] == pc and row[1] == cycle and row[i7] == after]
        if len(hooks) != 1 or hooks[0] == 0:
            raise ValueError("Missing native SPORT instruction boundaries")
        before = trace[hooks[0] - 1]
        if before[0] != previous or before[1] != cached or before[i7] != first:
            raise ValueError("Native SPORT transfer does not bracket the original instruction boundaries")
        result.extend([[tick, pc, before[1], first + index, sample & 0xffff]
                       for index, sample in enumerate(pcm[packet * 240:(packet + 1) * 240])])
    return result


def compare_dsp(native, observed, *, instruction_trace=True):
    if "sport_dma_reads" not in native:
        try: native = dict(native, sport_dma_reads=native_sport_dma_reads(native))
        except ValueError as error: return {"passed": False, "first_difference": str(error)}
    if "task_resume_dma_reads" not in native:
        try: native = dict(native, task_resume_dma_reads=native_sport_dma_reads(native, phase="task_resume"))
        except ValueError as error: return {"passed": False, "first_difference": str(error)}
    if "task_palette_dma_reads" not in native:
        try: native = dict(native, task_palette_dma_reads=native_sport_dma_reads(native, phase="task_palette"))
        except ValueError as error: return {"passed": False, "first_difference": str(error)}
    sizes = {"dsp_points": len(POINTS), "ram": len(RAM_ADDRESSES), "cmos_reads": 22, "cmos_writes": 12, "cmos": 8192,
             "checked_ram": len(RAM_ADDRESSES), "stored_ram": len(STORED_RAM_ADDRESSES),
             "sound_ram": len(SOUND_RAM_ADDRESSES),
             **{key: len(STORED_RAM_ADDRESSES) for key in RETURN_RAM_KEYS},
             "dsp_pm": 1024, "dsp_dm": 512, "dsp_control": 32,
             "post_factory_dsp_pm": 1024, "post_factory_dsp_dm": 512, "post_factory_dsp_control": 32,
             "sound_command_dsp_pm": 1024, "sound_command_dsp_dm": 512, "sound_command_dsp_control": 32,
             "input_wait_dsp_pm": 1024, "input_wait_dsp_dm": 512, "input_wait_dsp_control": 32,
             "dsp_external_pm": 2048, "dsp_external_dm": 2048, "dsp_device": len(DCS_DEVICE_FIELDS),
             "input_wait_dsp_external_pm": 2048, "input_wait_dsp_external_dm": 2048,
             "input_wait_dsp_device": len(DCS_DEVICE_FIELDS),
             "input_poll_dsp_pm": 1024, "input_poll_dsp_dm": 512, "input_poll_dsp_control": 32,
             "input_poll_dsp_external_pm": 2048, "input_poll_dsp_external_dm": 2048,
             "input_poll_dsp_device": len(DCS_DEVICE_FIELDS), "sport_pcm": SPORT_SAMPLES,
             "sport_dma_reads": SPORT_SAMPLES, "sport_dac_buffer": SPORT_SAMPLES,
             "sport_wrap_dac_buffer": 480, "sport_wrap_irq1_state": 2,
             "sport_irq1_state": 2, "sport_irq1_events": 2, "sport_dma_positions": len(SPORT_PACKETS),
             "input_events": 4, "button_exit_irq1_state": 2,
             "button_exit_dac_buffer": SPORT_SAMPLES, "button_exit_event_counts": 8,
             "video_irq_dac_buffer": SPORT_SAMPLES, "video_irq_irq1_state": 2, "video_irq_event_counts": 8,
             "startup_dac_buffer": SPORT_SAMPLES, "startup_irq1_state": 2, "startup_event_counts": 8,
             "dispatcher_dac_buffer": SPORT_SAMPLES, "dispatcher_irq1_state": 2, "dispatcher_event_counts": 8,
             "task_resume_pcm": TASK_RESUME_SAMPLES, "task_resume_dma_reads": TASK_RESUME_SAMPLES,
             "task_resume_dma_positions": len(TASK_RESUME_SPORT_PACKETS), "task_resume_irq1_events": 6, "task_resume_irq1_state": 2,
             "task_resume_dac_buffer": SPORT_SAMPLES + TASK_RESUME_SAMPLES, "task_resume_event_counts": 8,
             "task_queue_irq1_state": 2, "task_queue_dac_buffer": SPORT_SAMPLES + TASK_RESUME_SAMPLES,
             "task_queue_event_counts": 8,
             "task_draw_irq1_state": 2, "task_draw_dac_buffer": 2880, "task_draw_event_counts": 8,
             **{"task_draw_" + key: count for key, count in DSP_IMAGE_SIZES},
             **{"task_draw_" + key: 0 for key in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events")},
             "task_palette_irq1_state": 2, "task_palette_dac_buffer": 2880,
             "task_palette_event_counts": 8, "task_palette_pcm": 480, "task_palette_dma_reads": 480,
             "task_palette_dma_positions": 2, "task_palette_transfers": 2, "task_palette_irq1_events": 2,
             **{"task_palette_" + key: count for key, count in DSP_IMAGE_SIZES},
             **{"task_queue_" + key: 0 for key in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events")},
             **{"task_queue_" + key: count for key, count in DSP_IMAGE_SIZES},
             **{point + "_" + key: count for point in ("sport_wrap", *BUTTON_DSP_POINTS, "video_irq", "startup", "dispatcher") for key, count in DSP_IMAGE_SIZES},
             **{"input_idle_" + key: count for key, count in (("dsp_pm", 1024), ("dsp_dm", 512), ("dsp_control", 32),
                 ("dsp_external_pm", 2048), ("dsp_external_dm", 2048), ("dsp_device", len(DCS_DEVICE_FIELDS)))}}
    for label, result in (("native", native), ("reference", observed)):
        for key, size in sizes.items():
            if key not in result or len(result[key]) != size:
                return {"passed": False, "first_difference": f"{label} incomplete {key}: {len(result.get(key, []))}/{size}"}
        if (any(len(row) != 5 for key in ("sport_dma_reads", "task_resume_dma_reads", "task_palette_dma_reads") for row in result[key]) or
                any(len(row) != 4 for key in ("sport_irq1_events", "task_resume_irq1_events", "task_palette_irq1_events") for row in result[key]) or
                result.get("sport_dma_position") != result["sport_dma_positions"][0] or
                any(value not in (0, 1) for key in ("sport_irq1_state", "sport_wrap_irq1_state", "task_resume_irq1_state", "task_queue_irq1_state", "task_palette_irq1_state", "task_draw_irq1_state") for value in result[key]) or
                any(len(row) != 7 for row in result["task_palette_transfers"]) or
                any(len(row) != 4 for row in result["input_events"])):
            return {"passed": False, "first_difference": label + " malformed SPORT observations"}
        if (not result.get("dsp_trace") or not result.get("dsp_accesses") or "task_queue_dcs_control" not in result or "task_palette_dcs_control" not in result or "task_draw_dcs_control" not in result or
                any(key not in result for key in ("dcs_control", "sport_wrap_dcs_control", "button_exit_dcs_control", "video_irq_dcs_control", "startup_dcs_control", "dispatcher_dcs_control", "task_resume_dcs_control"))):
            return {"passed": False, "first_difference": label + " incomplete DSP observations"}
        if any(len(row) != len(DSP_REGISTERS) for key in ("dsp_trace", "dsp_points") for row in result[key]):
            return {"passed": False, "first_difference": label + " incomplete DSP registers"}
        if [row[0] for row in result["ram"]] != RAM_ADDRESSES:
            return {"passed": False, "first_difference": label + " incomplete main RAM"}
        if [row[0] for row in result["checked_ram"]] != RAM_ADDRESSES:
            return {"passed": False, "first_difference": label + " incomplete checksum-return RAM"}
        if [row[0] for row in result["stored_ram"]] != STORED_RAM_ADDRESSES:
            return {"passed": False, "first_difference": label + " incomplete CMOS-return RAM"}
        for key in RETURN_RAM_KEYS:
            if [row[0] for row in result[key]] != STORED_RAM_ADDRESSES:
                return {"passed": False, "first_difference": label + " incomplete " + key}
        if [row[0] for row in result["sound_ram"]] != SOUND_RAM_ADDRESSES:
            return {"passed": False, "first_difference": label + " incomplete sound-entry RAM"}
    for key in ("dsp_trace", "dsp_points", "dsp_accesses", "ram", "checked_ram", "stored_ram", "sound_ram", "cmos_reads", "cmos_writes", "cmos", "dsp_pm", "dsp_dm", "dsp_control", "post_factory_dsp_pm", "post_factory_dsp_dm", "post_factory_dsp_control", "sound_command_dsp_pm", "sound_command_dsp_dm", "sound_command_dsp_control", "input_wait_dsp_pm", "input_wait_dsp_dm", "input_wait_dsp_control",
                "dsp_external_pm", "dsp_external_dm", "dsp_device", "input_wait_dsp_external_pm",
                "input_wait_dsp_external_dm", "input_wait_dsp_device",
                "input_poll_dsp_pm", "input_poll_dsp_dm", "input_poll_dsp_control",
                "input_poll_dsp_external_pm", "input_poll_dsp_external_dm", "input_poll_dsp_device", "sport_pcm", "sport_dma_reads", "sport_dac_buffer", "sport_dma_positions", "sport_irq1_state", "sport_irq1_events",
                "input_idle_dsp_pm", "input_idle_dsp_dm", "input_idle_dsp_control", "input_idle_dsp_external_pm", "input_idle_dsp_external_dm", "input_idle_dsp_device",
                "sport_wrap_dac_buffer", "sport_wrap_irq1_state", "input_events",
                "button_exit_irq1_state", "button_exit_dac_buffer", "button_exit_event_counts",
                "video_irq_irq1_state", "video_irq_dac_buffer", "video_irq_event_counts",
                "startup_irq1_state", "startup_dac_buffer", "startup_event_counts",
                "dispatcher_irq1_state", "dispatcher_dac_buffer", "dispatcher_event_counts",
                "task_resume_pcm", "task_resume_dma_reads", "task_resume_dma_positions", "task_resume_irq1_events",
                "task_resume_irq1_state", "task_resume_dac_buffer", "task_resume_event_counts",
                "task_draw_irq1_state", "task_draw_dac_buffer", "task_draw_event_counts",
                "task_draw_pcm", "task_draw_dma_reads", "task_draw_dma_positions", "task_draw_transfers", "task_draw_irq1_events",
                *["task_draw_" + key for key, _ in DSP_IMAGE_SIZES],
                "task_palette_irq1_state", "task_palette_dac_buffer", "task_palette_event_counts",
                "task_palette_pcm", "task_palette_dma_reads", "task_palette_dma_positions", "task_palette_transfers", "task_palette_irq1_events",
                *["task_palette_" + key for key, _ in DSP_IMAGE_SIZES],
                "task_queue_irq1_state", "task_queue_dac_buffer", "task_queue_event_counts",
                "task_queue_pcm", "task_queue_dma_reads", "task_queue_dma_positions", "task_queue_transfers", "task_queue_irq1_events",
                *["task_queue_" + key for key, _ in DSP_IMAGE_SIZES],
                *[point + "_" + key for point in ("sport_wrap", *BUTTON_DSP_POINTS, "video_irq", "startup", "dispatcher") for key, _ in DSP_IMAGE_SIZES], *RETURN_RAM_KEYS):
        if key == "dsp_trace" and not instruction_trace: continue
        if len(native[key]) != len(observed[key]):
            return {"passed": False, "first_difference": key + " length"}
        for index, (a, b) in enumerate(zip(native[key], observed[key])):
            # debugcpu caches totalcycles at the last instruction hook for an inactive CPU.
            # The instruction trace compares cycles exactly; concurrent snapshots compare state.
            if key == "dsp_points": a, b = a[:1] + a[2:], b[:1] + b[2:]
            if key in ("button_exit_event_counts", "video_irq_event_counts", "startup_event_counts", "dispatcher_event_counts", "task_resume_event_counts", "task_queue_event_counts", "task_palette_event_counts", "task_draw_event_counts") and index == 0 and not instruction_trace: continue
            if a != b:
                return {"passed": False, "first_difference": f"{key}[{index}]", "native": a, "reference": b}
    if native.get("sport_dma_position") is None or native.get("sport_dma_position") != observed.get("sport_dma_position"):
        return {"passed": False, "first_difference": "sport_dma_position"}
    if native.get("button_exit_sport_deadline_ticks") != 0:
        return {"passed": False, "first_difference": "native historical button SPORT cancellation"}
    if native.get("video_irq_sport_deadline") != 13552570:
        return {"passed": False, "first_difference": "native historical video IRQ SPORT deadline"}
    if native.get("startup_sport_deadline") != 13552570:
        return {"passed": False, "first_difference": "native historical startup SPORT deadline"}
    if native.get("dispatcher_sport_deadline") != 13552570:
        return {"passed": False, "first_difference": "native historical dispatcher SPORT deadline"}
    if native.get("task_resume_sport_deadline") != 18928570:
        return {"passed": False, "first_difference": "native task-resume SPORT deadline"}
    if native.get("task_queue_sport_deadline") != 18928570:
        return {"passed": False, "first_difference": "native task-queue SPORT deadline"}
    if native.get("task_palette_sport_deadline") != 20464570:
        return {"passed": False, "first_difference": "native task-palette SPORT deadline"}
    if native.get("task_draw_sport_deadline") != 20464570:
        return {"passed": False, "first_difference": "native task-draw SPORT deadline"}
    for key in ("task_draw_dcs_control", "task_palette_dcs_control", "task_queue_dcs_control", "dcs_control", "sport_wrap_dcs_control", "button_exit_dcs_control", "video_irq_dcs_control", "startup_dcs_control", "dispatcher_dcs_control", "task_resume_dcs_control"):
        if native[key] != observed[key]: return {"passed": False, "first_difference": key}
    return {"passed": True, "dsp_instruction_boundaries": len(native["dsp_trace"]) if instruction_trace else 0,
            "dsp_instruction_trace_compared": instruction_trace,
            "dsp_fields_per_instruction": len(DSP_REGISTERS),
            "paired_cpu_checkpoints": len(POINTS),
            "ordered_dsp_accesses": len(native["dsp_accesses"]),
            "sport_dma_device_reads": SPORT_SAMPLES, "ordered_dsp_accesses_including_device_dma": len(native["dsp_accesses"]) + SPORT_SAMPLES + TASK_RESUME_SAMPLES + TASK_PALETTE_SAMPLES,
            "sport_dma_position": observed["sport_dma_position"], "sport_callback_tick_100mhz": observed["sport_dma_reads"][0][0],
            "sport_dma_positions": observed["sport_dma_positions"], "sport_callback_ticks_100mhz": [row[0] for row in SPORT_PACKETS],
            "sport_pcm_samples_compared_in_full": SPORT_SAMPLES, "sport_dac_float32_values_compared_in_full": SPORT_SAMPLES,
            "historical_sport_wrap_dac_float32_values_compared_in_full": 480,
            "historical_video_irq_dac_float32_values_compared_in_full": SPORT_SAMPLES,
            "historical_dispatcher_dac_float32_values_compared_in_full": SPORT_SAMPLES,
            "historical_dispatcher_event_counts_compared": 8 if instruction_trace else 7,
            "historical_dispatcher_dsp_image_sizes": dict(DSP_IMAGE_SIZES),
            "task_resume_pcm_samples_compared_in_full": TASK_RESUME_SAMPLES,
            "task_resume_dma_device_reads": TASK_RESUME_SAMPLES,
            "task_resume_dac_float32_values_compared_in_full": SPORT_SAMPLES + TASK_RESUME_SAMPLES,
            "task_draw_dsp_image_sizes": dict(DSP_IMAGE_SIZES),
            "task_draw_dac_float32_values_compared_in_full": 2880,
            "task_draw_new_pcm_samples_compared_in_full": 0, "task_draw_new_dma_device_reads": 0,
            "task_draw_event_counts_compared": 8 if instruction_trace else 7,
            "task_palette_dsp_image_sizes": dict(DSP_IMAGE_SIZES),
            "task_palette_dac_float32_values_compared_in_full": 2880,
            "task_palette_new_pcm_samples_compared_in_full": 480, "task_palette_new_dma_device_reads": 480,
            "task_palette_event_counts_compared": 8 if instruction_trace else 7,
            "task_queue_dsp_image_sizes": dict(DSP_IMAGE_SIZES),
            "task_queue_dac_float32_values_compared_in_full": SPORT_SAMPLES + TASK_RESUME_SAMPLES,
            "task_queue_new_pcm_samples_compared_in_full": 0, "task_queue_new_dma_device_reads": 0,
            "task_queue_event_counts_compared": 8 if instruction_trace else 7,
            "historical_video_irq_event_counts_compared": 8 if instruction_trace else 7,
            "historical_video_irq_dsp_image_sizes": dict(DSP_IMAGE_SIZES),
            "button_dsp_image_checkpoints": list(BUTTON_DSP_POINTS), "physical_input_events": 4,
            "main_ram_values": len(RAM_ADDRESSES),
            "ordered_cmos_reads": len(native["cmos_reads"]),
            "ordered_cmos_enable_and_data_writes": len(native["cmos_writes"]),
            "cmos_words_compared_in_full": 8192,
            "status_routine_ram_values_per_checkpoint": len(STORED_RAM_ADDRESSES),
            "status_routine_ram_checkpoints": len(RETURN_RAM_KEYS),
            "cmos_write_return_ram_values": len(STORED_RAM_ADDRESSES),
            "checksum_return_ram_values": len(RAM_ADDRESSES),
            "sound_entry_ram_values": len(SOUND_RAM_ADDRESSES),
            "program_words_compared_in_full": 1024, "data_words_compared_in_full": 512,
            "control_words_compared_in_full": 32,
            "post_factory_program_words_compared_in_full": 1024,
            "post_factory_data_words_compared_in_full": 512,
            "post_factory_control_words_compared_in_full": 32,
            "sound_command_program_words_compared_in_full": 1024,
            "sound_command_data_words_compared_in_full": 512,
            "sound_command_control_words_compared_in_full": 32,
            "input_wait_program_words_compared_in_full": 1024, "input_wait_data_words_compared_in_full": 512,
            "input_wait_control_words_compared_in_full": 32, "external_program_words_compared_in_full": 2048,
            "external_data_alias_words_compared_in_full": 2048, "dcs_device_fields": len(DCS_DEVICE_FIELDS),
            "input_wait_external_program_words_compared_in_full": 2048,
            "input_wait_external_data_alias_words_compared_in_full": 2048,
            "input_wait_dcs_device_fields": len(DCS_DEVICE_FIELDS),
            "input_poll_program_words_compared_in_full": 1024, "input_poll_data_words_compared_in_full": 512,
            "input_poll_control_words_compared_in_full": 32, "input_poll_external_program_words_compared_in_full": 2048,
            "input_poll_external_data_alias_words_compared_in_full": 2048,
            "input_poll_dcs_device_fields": len(DCS_DEVICE_FIELDS)}


def parse_dsp(text):
    import re
    points, accesses, ram, instructions, cmos_reads = {}, [], [], [], []
    dma_accesses, dma_positions, dma_packets, dma_closed = [], [], [], False
    irq_hooks, serial_opcodes = [], []
    button_counts, video_counts, startup_counts, dispatcher_counts, task_resume_counts = None, None, None, None, None
    task_queue_counts, task_palette_counts, task_draw_counts = None, None, None
    sound_ram, checked_ram, stored_ram, cmos_writes = [], [], [], []
    result, active, registers = {}, None, {}
    return_ram = {key: [] for key in RETURN_RAM_KEYS}
    text_pixblt_dsp, post_pixblt_dsp, input_pixblt_dsp, poll_pixblt_dsp = [], [], [], []
    text_cpu = None

    def finish():
        nonlocal dma_closed
        if active is None: return
        if any(reg not in registers for reg in DSP_REGISTERS):
            raise ValueError("Incomplete ADSP symbol snapshot")
        row = [registers[reg] & (0x3fff if re.fullmatch(r"m[0-7]", reg) else 0xffffffffffffffff)
               for reg in DSP_REGISTERS]
        if active[0] == "MK2_DSP_BEGIN":
            if row[0] == 0x829:
                if (len(active) != 2 or not re.fullmatch(r"[0-9A-Fa-f]{1,6}", active[1]) or
                        int(active[1], 16) not in (0x0d0cb0, 0x806114)):
                    raise ValueError("Missing, duplicate or unknown 0829 opcode observation")
                serial_opcodes.append([row[1], int(active[1], 16)])
            elif len(active) != 1:
                raise ValueError("Unexpected ADSP instruction opcode observation")
            instructions.append(row)
        elif active[0] == "MK2_DSP_IRQ1":
            if "irq1" not in registers: raise ValueError("Missing IRQ1 debugger symbol")
            irq_hooks.append([row[0], row[1], registers["irq1"]])
        elif active[0] == "MK2_DSP_POST_FACTORY_PIXBLT": post_pixblt_dsp.append(row)
        elif active[0] == "MK2_DSP_INPUT_WAIT_PIXBLT": input_pixblt_dsp.append(row)
        elif active[0] == "MK2_DSP_INPUT_POLL_PIXBLT": poll_pixblt_dsp.append(row)
        elif active[0] == "MK2_DSP_TEXT_PIXBLT":
            if text_cpu is None: raise ValueError("ADSP PIXBLT snapshot without CPU boundary")
            text_pixblt_dsp.append(row)
            if not text_cpu["status"] & 0x02000000 and text_cpu["a"][0] in TEXT_GLYPH_POINTS:
                name = TEXT_GLYPH_POINTS[text_cpu["a"][0]]
                if name in points: raise ValueError("Duplicate ADSP glyph boundary")
                points[name] = row
        elif active[0] == "MK2_DSP_POINT":
            if len(active) != 2 or active[1] not in POINTS or active[1] in points:
                raise ValueError("Malformed or duplicate ADSP checkpoint")
            points[active[1]] = row
        else:
            if len(active) != 4 or "curpc" not in registers: raise ValueError("Malformed ADSP access")
            row = [int(active[1],16), registers["curpc"], int(active[2],16),
                   int(active[3],16), registers["totalcycles"]]
            packet_set = (SPORT_PACKETS if dispatcher_counts is None else
                          TASK_RESUME_SPORT_PACKETS if task_queue_counts is None else TASK_PALETTE_SPORT_PACKETS)
            packet_offset = (0 if dispatcher_counts is None else len(SPORT_PACKETS) if task_queue_counts is None else
                             len(SPORT_PACKETS) + len(TASK_RESUME_SPORT_PACKETS))
            packet = next((n + packet_offset for n, (_, pc, previous, cycle, first, _) in enumerate(packet_set)
                           if row[0] == 114 and row[1] == previous and registers["pc"] == pc and
                           row[4] == cycle and first <= row[2] < first + 240), None)
            if packet is not None:
                if not dma_packets or packet != dma_packets[-1]:
                    if packet != len(dma_packets) or dma_packets and len(dma_accesses) != packet * 240:
                        raise ValueError("Non-contiguous SPORT DMA reads")
                    dma_packets.append(packet); dma_positions.append(len(accesses)); dma_closed = False
                if dma_closed: raise ValueError("Non-contiguous SPORT DMA reads")
                dma_accesses.append(row)
            else:
                if dma_accesses: dma_closed = True
                accesses.append(row)


    for line in (text.splitlines() if isinstance(text, str) else text):
        line = line.rstrip("\r\n")
        if line.startswith("MK2_"):
            finish(); active, registers = None, {}
            fields = line.split()
            if fields[0] in ("MK2_DSP_BEGIN", "MK2_DSP_IRQ1", "MK2_DSP_POINT", "MK2_DSP_ACCESS", "MK2_DSP_TEXT_PIXBLT", "MK2_DSP_POST_FACTORY_PIXBLT", "MK2_DSP_INPUT_WAIT_PIXBLT", "MK2_DSP_INPUT_POLL_PIXBLT"):
                active = fields
            elif fields[0] == "MK2_TEXT_PIXBLT": text_cpu = cpu_snapshot(fields[1:])
            elif fields[0] == "MK2_RAM":
                if len(fields) != 3: raise ValueError("Malformed main RAM observation")
                ram.append([int(v,16) for v in fields[1:]])
            elif fields[0] == "MK2_SOUND_RAM":
                if len(fields) != 3: raise ValueError("Malformed sound-entry RAM observation")
                sound_ram.append([int(v,16) for v in fields[1:]])
            elif fields[0][4:].lower() in return_ram:
                if len(fields) != 3: raise ValueError("Malformed routine RAM observation")
                return_ram[fields[0][4:].lower()].append([int(v,16) for v in fields[1:]])
            elif fields[0] == "MK2_STORED_RAM":
                if len(fields) != 3: raise ValueError("Malformed CMOS-return RAM observation")
                stored_ram.append([int(v,16) for v in fields[1:]])
            elif fields[0] == "MK2_CHECKED_RAM":
                if len(fields) != 3: raise ValueError("Malformed checksum-return RAM observation")
                checked_ram.append([int(v,16) for v in fields[1:]])
            elif fields[0] == "MK2_CMOS_WRITE":
                if len(fields) != 5: raise ValueError("Malformed CMOS write observation")
                row = [int(v,16) for v in fields[1:]]
                row[0] = (row[0] - (48 if row[1] == 0x01480000 else 16)) & 0xffffffff
                cmos_writes.append(row)
            elif fields[0] == "MK2_CMOS_READ":
                if len(fields) != 5: raise ValueError("Malformed CMOS read observation")
                row = [int(v,16) for v in fields[1:]]
                row[0] = (row[0] - 16) & 0xffffffff  # MOVB watchpoint after 16-bit fetch.
                cmos_reads.append(row)
            elif fields[0] == "MK2_BUTTON_EXIT_BOUNDARY":
                if button_counts is not None: raise ValueError("Duplicate historical button boundary")
                button_counts = [len(instructions), len(accesses),
                                 sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                 sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                 len(dma_packets), len(dma_positions)]
            elif fields[0] == "MK2_VIDEO_IRQ_BOUNDARY":
                if video_counts is not None: raise ValueError("Duplicate historical video IRQ boundary")
                video_counts = [len(instructions), len(accesses),
                                sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                len(dma_packets), len(dma_positions)]
            elif fields[0] == "MK2_STARTUP_BOUNDARY":
                if startup_counts is not None: raise ValueError("Duplicate historical startup boundary")
                startup_counts = [len(instructions), len(accesses),
                                  sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                  sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                  len(dma_packets), len(dma_positions)]
            elif fields[0] == "MK2_DISPATCHER_BOUNDARY":
                if dispatcher_counts is not None: raise ValueError("Duplicate historical dispatcher boundary")
                dispatcher_counts = [len(instructions), len(accesses),
                                     sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                     sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                     len(dma_packets), len(dma_positions)]
            elif fields[0] == "MK2_TASK_RESUME_BOUNDARY":
                if task_resume_counts is not None: raise ValueError("Duplicate task-resume boundary")
                task_resume_counts = [len(instructions), len(accesses),
                                      sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                      sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                      len(dma_packets), len(dma_positions)]
            elif fields[0] == "MK2_TASK_RESUME_DCS_CONTROL":
                if len(fields) != 2 or "task_resume_dcs_control" in result: raise ValueError("Malformed task-resume DCS control")
                result["task_resume_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_TASK_QUEUE_BOUNDARY":
                if task_queue_counts is not None: raise ValueError("Duplicate task-queue boundary")
                task_queue_counts = [len(instructions), len(accesses),
                                     sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                     sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                     len(dma_packets), len(dma_positions)]
                if task_resume_counts is None or task_queue_counts[4:] != task_resume_counts[4:]:
                    raise ValueError("Unexpected task-queue SPORT observations")
            elif fields[0] == "MK2_TASK_PALETTE_BOUNDARY":
                if len(fields) != 1 or task_palette_counts is not None: raise ValueError("Malformed or duplicate task-palette boundary")
                task_palette_counts = [len(instructions), len(accesses),
                                       sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                       sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                       len(dma_packets), len(dma_positions)]
                if (task_queue_counts is None or
                        [task_palette_counts[i] - task_queue_counts[i] for i in range(4, 8)] != [480, 2, 2, 2]):
                    raise ValueError("Unexpected task-palette SPORT observations")
            elif fields[0] == "MK2_TASK_DRAW_BOUNDARY":
                if len(fields) != 1 or task_draw_counts is not None: raise ValueError("Malformed or duplicate task-draw boundary")
                task_draw_counts = [len(instructions), len(accesses),
                                    sum(row[0] == 100 and row[2] == 0x3fff and row[3] == 0x208 for row in accesses),
                                    sum(word == 0x0d0cb0 for _, word in serial_opcodes), len(dma_accesses), len(irq_hooks),
                                    len(dma_packets), len(dma_positions)]
                if task_palette_counts is None or task_draw_counts[4:] != task_palette_counts[4:]:
                    raise ValueError("Unexpected task-draw SPORT observations")
            elif fields[0] == "MK2_TASK_DRAW_DCS_CONTROL":
                if len(fields) != 2 or "task_draw_dcs_control" in result: raise ValueError("Malformed task-draw DCS control")
                result["task_draw_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_TASK_PALETTE_DCS_CONTROL":
                if len(fields) != 2 or "task_palette_dcs_control" in result: raise ValueError("Malformed task-palette DCS control")
                result["task_palette_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_TASK_QUEUE_DCS_CONTROL":
                if len(fields) != 2 or "task_queue_dcs_control" in result: raise ValueError("Malformed task-queue DCS control")
                result["task_queue_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_DISPATCHER_DCS_CONTROL":
                if len(fields) != 2 or "dispatcher_dcs_control" in result: raise ValueError("Malformed historical dispatcher DCS control")
                result["dispatcher_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_STARTUP_DCS_CONTROL":
                if len(fields) != 2 or "startup_dcs_control" in result: raise ValueError("Malformed historical startup DCS control")
                result["startup_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_VIDEO_IRQ_DCS_CONTROL":
                if len(fields) != 2 or "video_irq_dcs_control" in result: raise ValueError("Malformed historical video IRQ DCS control")
                result["video_irq_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_BUTTON_EXIT_DCS_CONTROL":
                if len(fields) != 2 or "button_exit_dcs_control" in result: raise ValueError("Malformed historical button DCS control")
                result["button_exit_dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_DCS_CONTROL":
                if len(fields) != 2 or "dcs_control" in result: raise ValueError("Malformed DCS control observation")
                result["dcs_control"] = int(fields[1],16)
            elif fields[0] == "MK2_SPORT_WRAP_DCS_CONTROL":
                if len(fields) != 2 or "sport_wrap_dcs_control" in result: raise ValueError("Malformed SPORT-wrap DCS control")
                result["sport_wrap_dcs_control"] = int(fields[1],16)
        elif active is not None:
            match = re.fullmatch(r"([a-z0-9_]+) = ([0-9A-F]+)(?:  \(read-only\))?", line)
            if match:
                key = match[1]
                if key in registers: raise ValueError("Duplicate ADSP symbol")
                registers[key] = int(match[2],16)
    finish()
    if set(points) != set(POINTS) or not instructions or not accesses or "dcs_control" not in result:
        raise ValueError("Incomplete ADSP capture")
    result.update(dsp_0829_opcodes=serial_opcodes, dsp_trace=instructions, dsp_points=[points[name] for name in POINTS],
                  dsp_accesses=accesses, ram=sorted(ram), checked_ram=sorted(checked_ram),
                  sound_ram=sorted(sound_ram), stored_ram=sorted(stored_ram), cmos_reads=cmos_reads, cmos_writes=cmos_writes,
                  text_pixblt_dsp=text_pixblt_dsp, post_factory_pixblt_dsp=post_pixblt_dsp, input_wait_pixblt_dsp=input_pixblt_dsp, input_poll_pixblt_dsp=poll_pixblt_dsp)
    result.update(sport_dma_raw=dma_accesses[:SPORT_SAMPLES], sport_dma_position=dma_positions[0] if dma_positions else None,
                  sport_dma_positions=dma_positions[:len(SPORT_PACKETS)], sport_irq1_hooks=irq_hooks,
                  task_resume_dma_raw=dma_accesses[SPORT_SAMPLES:SPORT_SAMPLES + TASK_RESUME_SAMPLES],
                  task_resume_dma_positions=dma_positions[len(SPORT_PACKETS):len(SPORT_PACKETS) + len(TASK_RESUME_SPORT_PACKETS)])
    if task_palette_counts is not None:
        result.update(task_palette_event_counts=task_palette_counts,
                      task_palette_dma_raw=dma_accesses[SPORT_SAMPLES + TASK_RESUME_SAMPLES:],
                      task_palette_dma_positions=dma_positions[len(SPORT_PACKETS) + len(TASK_RESUME_SPORT_PACKETS):])
    if task_draw_counts is not None:
        result["task_draw_event_counts"] = task_draw_counts
        result.update({"task_draw_" + key: [] for key in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events")})
    if button_counts is not None: result["button_exit_event_counts"] = button_counts
    if video_counts is not None: result["video_irq_event_counts"] = video_counts
    if startup_counts is not None: result["startup_event_counts"] = startup_counts
    if dispatcher_counts is not None: result["dispatcher_event_counts"] = dispatcher_counts
    if task_resume_counts is not None: result["task_resume_event_counts"] = task_resume_counts
    if task_queue_counts is not None:
        result["task_queue_event_counts"] = task_queue_counts
        result.update({"task_queue_" + key: [] for key in ("pcm", "dma_reads", "dma_positions", "transfers", "irq1_events")})
    result.update({key: sorted(rows) for key, rows in return_ram.items()})
    return result

def reject_mame_diagnostic(line):
    if line.lstrip().casefold().startswith(("invalid ", "unknown command", "error", "fatal error", "lua error", "[lua error]")):
        raise ValueError("MAME diagnostic: " + line.strip()[:240])


def parse_log(text, factory_opcode=None):
    checkpoints, writes, board_writes, board_io, board_ram = {}, [], [], {}, []
    inputs, powerup_writes, powerup_io, display, pending = [], [], {}, None, None
    board_dma = None
    video_writes, video_pending, video_io, video_display, video_dma = [], None, {}, None, None
    text_reads, text_writes, text_pixblt, text_io, text_display, text_dma = [], [], [], {}, None, None
    text_bus = []
    phases = {name: {"bus": [], "io": {}, "display": None, "dma": None} for name in ("factory", "post_factory", "sound_command", "input_wait", "input_poll", "input_idle", "sport_wrap", "button_exit", "video_irq", "startup", "dispatcher", "task_resume", "task_queue", "task_palette", "task_draw")}
    post_pixblt, input_pixblt, poll_pixblt, graphics_dma = [], [], [], []
    transport = {phase: [0, 0, 0] for phase in ("dispatcher", "task_resume", "task_queue", "task_palette", "task_draw")}
    for line in (text.splitlines() if isinstance(text, str) else text):
        line = line.rstrip("\r\n")
        reject_mame_diagnostic(line)
        phase = ("task_draw" if line.startswith("MK2_TASK_DRAW_") else
                 "task_palette" if line.startswith("MK2_TASK_PALETTE_") else
                 "task_queue" if line.startswith("MK2_TASK_QUEUE_") else
                 "task_resume" if line.startswith("MK2_TASK_RESUME_") else
                 "dispatcher" if line.startswith("MK2_DISPATCHER_") else
                 "startup" if line.startswith("MK2_STARTUP_") else
                 "video_irq" if line.startswith("MK2_VIDEO_IRQ_") else
                 "button_exit" if line.startswith("MK2_BUTTON_EXIT_") else
                 "sport_wrap" if line.startswith("MK2_SPORT_WRAP_") else
                 "input_idle" if line.startswith("MK2_INPUT_IDLE_") else
                 "input_poll" if line.startswith("MK2_INPUT_POLL_") else
                 "input_wait" if line.startswith("MK2_INPUT_WAIT_") else
                 "sound_command" if line.startswith("MK2_SOUND_COMMAND_") else
                 "post_factory" if line.startswith("MK2_POST_FACTORY_") else "factory")
        if pending is not None and line.startswith("MK2_") and not line.startswith("MK2_POWERUP_WRITE "):
            raise ValueError("Interrupted 32-bit powerup write lanes")
        if video_pending is not None and line.startswith("MK2_") and not line.startswith("MK2_VIDEO_WRITE "):
            raise ValueError("Interrupted 32-bit video write lanes")
        if line.startswith("MK2_CPU "):
            fields = line.split()
            if len(fields) != 36 or fields[1] not in POINTS or fields[1] in checkpoints:
                raise ValueError("Invalid or duplicate MK2 checkpoint")
            checkpoints[fields[1]] = cpu_snapshot(fields[2:])
        elif line.startswith("MK2_TASK_DRAW_GRAPHICS_DMA "):
            fields = line.split()
            if len(fields) != 4: raise ValueError("Malformed task-draw graphics DMA observation")
            row = [int(fields[1]), int(fields[2], 16), int(fields[3], 16)]
            if row[0] not in (1259256, 1260496, 1260517) or any(previous[0] == row[0] for previous in graphics_dma) or any(not 0 <= value <= 0xffff for value in row[1:]):
                raise ValueError("Invalid or duplicate task-draw graphics DMA observation")
            graphics_dma.append(row)
        elif line.startswith("MK2_INPUT_POLL_PIXBLT "):
            cpu = cpu_snapshot(line.split()[1:])
            if cpu["pc"] != 0xffa592b0: raise ValueError("Unexpected input-poll PIXBLT boundary")
            poll_pixblt.append(cpu)
        elif line.startswith("MK2_INPUT_WAIT_PIXBLT "):
            cpu = cpu_snapshot(line.split()[1:])
            if cpu["pc"] != 0xffa592b0: raise ValueError("Unexpected input-wait PIXBLT boundary")
            input_pixblt.append(cpu)
        elif line.startswith("MK2_POST_FACTORY_PIXBLT "):
            cpu = cpu_snapshot(line.split()[1:])
            if cpu["pc"] != 0xffa592b0: raise ValueError("Unexpected post-factory PIXBLT boundary")
            post_pixblt.append(cpu)
        elif line.startswith("MK2_TEXT_PIXBLT "):
            cpu = cpu_snapshot(line.split()[1:])
            if cpu["pc"] != 0xffa592b0: raise ValueError("Unexpected PIXBLT boundary")
            text_pixblt.append(cpu)
            if not cpu["status"] & 0x02000000 and cpu["a"][0] in TEXT_GLYPH_POINTS:
                name = TEXT_GLYPH_POINTS[cpu["a"][0]]
                if name in checkpoints: raise ValueError("Duplicate glyph boundary")
                checkpoints[name] = cpu
        elif line.startswith(("MK2_TEXT_READ ", "MK2_TEXT_WRITE ")):
            fields = line.split()
            if len(fields) != 6: raise ValueError("Invalid text bus observation")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size = int(fields[4]), int(fields[5])
            fetch = TEXT_READ_FETCH if fields[0] == "MK2_TEXT_READ" else TEXT_WRITE_FETCH
            if pc not in fetch or size != 16 or address & 15 or not 0 <= value <= 0xffff:
                raise ValueError("Unexpected text bus instruction, width or value")
            target = text_reads if fields[0] == "MK2_TEXT_READ" else text_writes
            target.append([fetch[pc], address, value, cycle, size])
            text_bus.append([114 if fields[0] == "MK2_TEXT_READ" else 119, *target[-1]])
        elif line.startswith("MK2_TEXT_IO "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid text IO observation")
            index, value = [int(v, 16) for v in fields[1:]]
            if index not in range(28) or index in text_io or not 0 <= value <= 0xffff:
                raise ValueError("Invalid or duplicate text IO observation")
            text_io[index] = value
        elif line.startswith("MK2_TEXT_DISPLAY "):
            fields = line.split()
            if len(fields) != 3 or text_display is not None: raise ValueError("Invalid text display observation")
            text_display = [int(v, 16) for v in fields[1:]]
            if any(not 0 <= v <= 0xffff for v in text_display): raise ValueError("Invalid text display word")
        elif line.startswith("MK2_TEXT_DMA "):
            fields = line.split()
            if len(fields) != 2 or text_dma is not None: raise ValueError("Invalid text DMA observation")
            text_dma = int(fields[1], 16)
            if not 0 <= text_dma <= 0xffff: raise ValueError("Invalid text DMA word")
        elif line.startswith(("MK2_" + phase.upper() + "_READ ", "MK2_" + phase.upper() + "_WRITE ")):
            fields = line.split()
            if len(fields) != 7: raise ValueError("Invalid factory bus observation")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size, source = int(fields[4]), int(fields[5]), int(fields[6], 16)
            if (not 0xff800000 <= source <= 0xfffffff0 or source & 15 or
                    not 0 <= pc <= 0xffffffff or pc & 15 or
                    ((pc - source) & 0xffffffff) not in (16, 32, 48, 64, 80) or
                    size != 16 or not 0 <= address <= 0xfffffff0 or address & 15 or
                    not 0 <= value <= 0xffff):
                raise ValueError("Unexpected factory bus PC, width, address or value")
            if factory_opcode is None: raise ValueError("Missing authenticated factory opcode reader")
            if phase in transport:
                row = dispatcher_bus_row(pc, address, value, cycle, size, source, fields[0].endswith("_WRITE"), factory_opcode)
                transport[phase][0] += 1
                if row is None: transport[phase][1] += 1
                else:
                    phases[phase]["bus"].append(row)
                    if row[0] == 114 and address >= 0xff800000: transport[phase][2] += 1
                continue
            opcode = factory_opcode(source)
            fetch_bits = (dispatcher_fetch_bits(opcode, fields[0].endswith("_WRITE")) if phase == "dispatcher" else
                          video_irq_fetch_bits(opcode, fields[0].endswith("_WRITE")) if phase in ("video_irq", "startup", "dispatcher") else factory_fetch_bits(opcode))
            if ((pc - source) & 0xffffffff) != fetch_bits:
                raise ValueError(f"Unexpected factory fetched PC {pc:08x} for CURPC {source:08x}, opcode {opcode:04x}")
            phases[phase]["bus"].append([114 if fields[0] == "MK2_" + phase.upper() + "_READ" else 119, source, address, value, cycle, size])
        elif line.startswith("MK2_" + phase.upper() + "_IO "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid factory IO observation")
            index, value = [int(v, 16) for v in fields[1:]]
            if index not in range(28) or index in phases[phase]["io"] or not 0 <= value <= 0xffff:
                raise ValueError("Invalid or duplicate factory IO observation")
            phases[phase]["io"][index] = value
        elif line.startswith("MK2_" + phase.upper() + "_DISPLAY "):
            fields = line.split()
            if len(fields) != 3 or phases[phase]["display"] is not None: raise ValueError("Invalid factory display observation")
            phases[phase]["display"] = [int(v, 16) for v in fields[1:]]
            if any(not 0 <= v <= 0xffff for v in phases[phase]["display"]): raise ValueError("Invalid factory display word")
        elif line.startswith("MK2_" + phase.upper() + "_DMA "):
            fields = line.split()
            if len(fields) != 2 or phases[phase]["dma"] is not None: raise ValueError("Invalid factory DMA observation")
            phases[phase]["dma"] = int(fields[1], 16)
            if not 0 <= phases[phase]["dma"] <= 0xffff: raise ValueError("Invalid factory DMA word")
        elif line.startswith("MK2_WRITE "):
            fields = line.split()
            if len(fields) != 5:
                raise ValueError("Invalid MK2 write observation")
            if not 0 <= int(fields[3], 16) <= 0xffff: raise ValueError("Invalid 16-bit write value")
            # TMS watchpoint PC is after fetching the 48-bit MOVE; native stores source PC.
            writes.append({"pc": (int(fields[1], 16) - 48) & 0xffffffff,
                           "address_bit": int(fields[2], 16), "value": int(fields[3], 16),
                           "cycle": int(fields[4])})
        elif line.startswith("MK2_BOARD_WRITE "):
            fields = line.split()
            if len(fields) != 6: raise ValueError("Invalid board write observation")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size = int(fields[4]), int(fields[5])
            if pc not in BOARD_FETCH_BITS or size != 16 or not 0 <= value <= 0xffff:
                raise ValueError("Unexpected board write instruction or width")
            pc = (pc - BOARD_FETCH_BITS[pc]) & 0xffffffff
            if pc == 0xff811000:
                writes.append({"pc": pc, "address_bit": address, "value": value, "cycle": cycle})
            else: board_writes.append([pc, address, value, cycle, size])
        elif line.startswith("MK2_BOARD_IO "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid board IO observation")
            index, value = [int(v, 16) for v in fields[1:]]
            if index not in range(28) or index in board_io or not 0 <= value <= 0xffff:
                raise ValueError("Invalid or duplicate board IO observation")
            board_io[index] = value
        elif line.startswith("MK2_BOARD_RAM "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid board RAM observation")
            board_ram.append([int(v, 16) for v in fields[1:]])
        elif line.startswith("MK2_BOARD_DMA "):
            fields = line.split()
            if len(fields) != 2 or board_dma is not None:
                raise ValueError("Invalid or duplicate board DMA observation")
            board_dma = int(fields[1], 16)
            if not 0 <= board_dma <= 0xffff: raise ValueError("Invalid 16-bit board DMA value")
        elif line.startswith("MK2_INPUT_READ "):
            fields = line.split()
            if len(fields) != 6: raise ValueError("Invalid boot input read")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size = int(fields[4]), int(fields[5])
            if pc != 0xffa5c230 or size != 16 or not 0 <= value <= 0xffff:
                raise ValueError("Unexpected boot input read")
            inputs.append([pc - 48, address, value, cycle, size])
        elif line.startswith("MK2_POWERUP_WRITE "):
            fields = line.split()
            if len(fields) != 6: raise ValueError("Invalid powerup write")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size = int(fields[4]), int(fields[5])
            if pc not in POWERUP_FETCH or size != 16 or not 0 <= value <= 0xffff:
                raise ValueError("Unexpected powerup write")
            fetch, width = POWERUP_FETCH[pc]
            row = [pc - fetch, address, value, cycle, size]
            if width == 16:
                if pending is not None: raise ValueError("Interrupted 32-bit powerup write")
                powerup_writes.append(row)
            elif pending is None: pending = row
            else:
                if (row[0] != pending[0] or row[1] != pending[1] + 16 or row[3] != pending[3]):
                    raise ValueError("Mismatched 32-bit powerup write lanes")
                powerup_writes.append([row[0], pending[1], pending[2] | (value << 16), cycle, 32])
                pending = None
        elif line.startswith("MK2_POWERUP_IO "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid powerup IO observation")
            index, value = [int(v, 16) for v in fields[1:]]
            if index not in range(28) or index in powerup_io or not 0 <= value <= 0xffff:
                raise ValueError("Invalid or duplicate powerup IO observation")
            powerup_io[index] = value
        elif line.startswith("MK2_POWERUP_DISPLAY "):
            fields = line.split()
            if len(fields) != 3 or display is not None: raise ValueError("Invalid powerup display observation")
            display = [int(v, 16) for v in fields[1:]]
            if any(not 0 <= value <= 0xffff for value in display):
                raise ValueError("Invalid 16-bit display value")
        elif line.startswith("MK2_VIDEO_WRITE "):
            fields = line.split()
            if len(fields) != 6: raise ValueError("Invalid video write")
            pc, address, value = [int(v, 16) for v in fields[1:4]]
            cycle, size = int(fields[4]), int(fields[5])
            if pc not in VIDEO_FETCH or size != 16 or not 0 <= value <= 0xffff:
                raise ValueError("Unexpected video write")
            fetch, width = VIDEO_FETCH[pc]
            row = [pc - fetch, address, value, cycle, size]
            if width == 16:
                if video_pending is not None: raise ValueError("Interrupted 32-bit video write")
                video_writes.append(row)
            elif video_pending is None: video_pending = row
            else:
                if row[0] != video_pending[0] or row[1] != video_pending[1] + 16 or row[3] != video_pending[3]:
                    raise ValueError("Mismatched 32-bit video write lanes")
                video_writes.append([row[0], video_pending[1], video_pending[2] | (value << 16), cycle, 32])
                video_pending = None
        elif line.startswith("MK2_VIDEO_IO "):
            fields = line.split()
            if len(fields) != 3: raise ValueError("Invalid video IO observation")
            index, value = [int(v, 16) for v in fields[1:]]
            if index not in range(28) or index in video_io or not 0 <= value <= 0xffff:
                raise ValueError("Invalid or duplicate video IO observation")
            video_io[index] = value
        elif line.startswith("MK2_VIDEO_DISPLAY "):
            fields = line.split()
            if len(fields) != 3 or video_display is not None: raise ValueError("Invalid video display observation")
            video_display = [int(v, 16) for v in fields[1:]]
            if any(not 0 <= value <= 0xffff for value in video_display): raise ValueError("Invalid video display word")
        elif line.startswith("MK2_VIDEO_DMA "):
            fields = line.split()
            if len(fields) != 2 or video_dma is not None: raise ValueError("Invalid video DMA observation")
            video_dma = int(fields[1], 16)
            if not 0 <= video_dma <= 0xffff: raise ValueError("Invalid video DMA word")
    if set(checkpoints) != set(POINTS) or len(writes) != 6:
        raise ValueError("Incomplete MK2 reference capture")
    for name, pc in POINTS.items():
        if checkpoints[name]["pc"] != pc:
            raise ValueError("MK2 checkpoint reached wrong PC")
    if (len(board_writes) != BOARD_WRITE_COUNT or len(board_io) != 28 or board_dma is None or
            sorted(row[0] for row in board_ram) != STORED_RAM_ADDRESSES):
        raise ValueError("Incomplete board reference capture")
    if (len(inputs) != 2 or len(powerup_writes) != POWERUP_WRITE_COUNT or pending is not None or
            len(powerup_io) != 28 or display is None):
        raise ValueError("Incomplete powerup reference capture")
    if (len(video_writes) != VIDEO_WRITE_COUNT or video_pending is not None or len(video_io) != 28 or
            video_display is None or video_dma is None):
        raise ValueError("Incomplete video reference capture")
    if (len(text_reads) != TEXT_READ_COUNT or len(text_writes) != TEXT_WRITE_COUNT or len(text_pixblt) != TEXT_PIXBLT_COUNT or len(text_io) != 28 or
            text_display is None or text_dma is None):
        raise ValueError("Incomplete text reference capture")
    for phase, count in (("factory", FACTORY_BUS_COUNT), ("post_factory", POST_FACTORY_BUS_COUNT),
                         ("sound_command", SOUND_COMMAND_BUS_COUNT), ("input_wait", INPUT_WAIT_BUS_COUNT), ("input_poll", INPUT_POLL_BUS_COUNT), ("input_idle", INPUT_IDLE_BUS_COUNT), ("sport_wrap", SPORT_WRAP_BUS_COUNT), ("video_irq", VIDEO_IRQ_BUS_COUNT), ("startup", STARTUP_BUS_COUNT), ("dispatcher", DISPATCHER_BUS_COUNT), ("task_resume", TASK_RESUME_BUS_COUNT), ("task_queue", TASK_QUEUE_BUS_COUNT), ("task_palette", TASK_PALETTE_BUS_COUNT), ("task_draw", TASK_DRAW_BUS_COUNT)):
        capture = phases[phase]
        if len(capture["bus"]) != count or len(capture["io"]) != 28 or capture["display"] is None or capture["dma"] is None:
            raise ValueError("Incomplete " + phase + " reference capture")
    if len(graphics_dma) != 3: raise ValueError("Incomplete task-draw graphics DMA observations")
    if len(poll_pixblt) != INPUT_POLL_PIXBLT_COUNT: raise ValueError("Incomplete input-poll PIXBLT capture")
    if len(input_pixblt) != INPUT_WAIT_PIXBLT_COUNT: raise ValueError("Incomplete input-wait PIXBLT capture")
    if len(post_pixblt) != POST_FACTORY_PIXBLT_COUNT: raise ValueError("Incomplete post-factory PIXBLT capture")
    return {**{phase + "_" + name: counts[index] for phase, counts in transport.items()
               for index, name in enumerate(("raw_bus_events", "authenticated_fetch_lanes", "rom_data_lanes"))},
            "task_draw_graphics_dma": graphics_dma,
            "checkpoints": checkpoints, "writes": writes, "board_writes": board_writes,
            "board_io": [board_io[i] for i in range(28)], "board_ram": sorted(board_ram),
            "board_dma_command": board_dma, "boot_input_reads": inputs, "powerup_writes": powerup_writes,
            "powerup_board_io": [powerup_io[i] for i in range(28)], "powerup_display": display,
            "video_writes": video_writes, "video_board_io": [video_io[i] for i in range(28)],
            "video_display": video_display, "video_dma_command": video_dma, "text_reads": text_reads,
            "text_writes": text_writes, "text_pixblt": text_pixblt, "text_board_io": [text_io[i] for i in range(28)],
            "text_display": text_display, "text_dma_command": text_dma, "text_bus": text_bus,
            "post_factory_pixblt": post_pixblt, "input_wait_pixblt": input_pixblt, "input_poll_pixblt": poll_pixblt,
            **{key: value for phase, capture in phases.items() for key, value in (
                (phase + "_bus", capture["bus"]), (phase + "_board_io", [capture["io"][i] for i in range(28)]),
                (phase + "_display", capture["display"]), (phase + "_dma_command", capture["dma"]))}}


def compare(native, observed):
    for label, result in (("native", native), ("reference", observed)):
        if (set(result.get("checkpoints", {})) != set(POINTS) or
                len(result.get("writes", [])) != 6 or len(result.get("boot_words", [])) != BOOT_WORDS or
                len(result.get("board_writes", [])) != BOARD_WRITE_COUNT or
                len(result.get("board_io", [])) != 28 or "board_dma_command" not in result or
                len(result.get("board_ram", [])) != len(STORED_RAM_ADDRESSES) or
                any(len(row) != 2 for row in result.get("board_ram", [])) or
                [row[0] for row in result.get("board_ram", [])] != STORED_RAM_ADDRESSES or
                any(len(row) != 5 or row[-1] != 16 for row in result.get("board_writes", []))):
            return {"passed": False, "first_difference": label + " incomplete"}
        for key, size in (("boot_input_reads", 2), ("powerup_writes", POWERUP_WRITE_COUNT),
                          ("main_ram", 65536), ("powerup_board_io", 28), ("powerup_display", 2),
                          ("video_writes", VIDEO_WRITE_COUNT), ("video_board_io", 28), ("video_display", 2),
                          ("video_main_ram", 65536), ("palette_ram", 32768), ("vram", 524288),
                          ("text_main_ram", 65536), ("text_palette_ram", 32768), ("text_vram", 524288),
                          ("text_board_io", 28), ("text_display", 2),
                          ("factory_entry_main_ram", 262144), ("factory_main_ram", 262144),
                          ("factory_cmos", 8192), ("factory_palette_ram", 32768), ("factory_vram", 524288),
                          ("factory_board_io", 28), ("factory_display", 2),
                          ("post_factory_main_ram", 262144), ("post_factory_cmos", 8192),
                          ("post_factory_palette_ram", 32768), ("post_factory_vram", 524288),
                          ("post_factory_board_io", 28), ("post_factory_display", 2),
                          ("sound_command_main_ram", 262144), ("sound_command_cmos", 8192),
                          ("sound_command_palette_ram", 32768), ("sound_command_vram", 524288),
                          ("sound_command_board_io", 28), ("sound_command_display", 2),
                          ("input_wait_main_ram", 262144), ("input_wait_cmos", 8192),
                          ("input_wait_palette_ram", 32768), ("input_wait_vram", 524288),
                          ("input_wait_board_io", 28), ("input_wait_display", 2),
                          ("input_poll_main_ram", 262144), ("input_poll_cmos", 8192),
                          ("input_poll_palette_ram", 32768), ("input_poll_vram", 524288),
                          ("input_poll_board_io", 28), ("input_poll_display", 2),
                          ("input_idle_main_ram", 262144), ("input_idle_cmos", 8192),
                          ("input_idle_palette_ram", 32768), ("input_idle_vram", 524288),
                          ("input_idle_board_io", 28), ("input_idle_display", 2),
                          ("sport_wrap_main_ram", 262144), ("sport_wrap_cmos", 8192),
                          ("sport_wrap_palette_ram", 32768), ("sport_wrap_vram", 524288),
                          ("sport_wrap_board_io", 28), ("sport_wrap_display", 2),
                          ("sport_wrap_dma_registers", 18), ("button_exit_dma_registers", 18),
                          ("button_exit_main_ram", 262144), ("button_exit_cmos", 8192),
                          ("button_exit_palette_ram", 32768), ("button_exit_vram", 524288),
                          ("button_exit_board_io", 28), ("button_exit_display", 2),
                          ("video_irq_main_ram", 262144), ("video_irq_cmos", 8192),
                          ("video_irq_palette_ram", 32768), ("video_irq_vram", 524288),
                          ("video_irq_board_io", 28), ("video_irq_display", 2), ("video_irq_dma_registers", 18),
                          ("startup_main_ram", 262144), ("startup_cmos", 8192),
                          ("startup_palette_ram", 32768), ("startup_vram", 524288),
                          ("startup_board_io", 28), ("startup_display", 2), ("startup_dma_registers", 18),
                          ("dispatcher_main_ram", 262144), ("dispatcher_cmos", 8192),
                          ("dispatcher_palette_ram", 32768), ("dispatcher_vram", 524288),
                          ("dispatcher_board_io", 28), ("dispatcher_display", 2), ("dispatcher_dma_registers", 18),
                          ("dispatcher_shiftreg", 4096),
                          ("task_resume_main_ram", 262144), ("task_resume_cmos", 8192),
                          ("task_resume_palette_ram", 32768), ("task_resume_vram", 524288),
                          ("task_resume_board_io", 28), ("task_resume_display", 2), ("task_resume_dma_registers", 18),
                          ("task_resume_shiftreg", 4096),
                          *[("task_draw_dma_" + boundary + "_" + key, count) for boundary in ("busy", "completed") for key, count in (("vram", 524288), ("registers", 18))],
                          *[(phase + "_" + key, count) for phase in ("task_queue", "task_palette", "task_draw") for key, count in TASK_QUEUE_IMAGE_SIZES]):
            if len(result.get(key, [])) != size:
                return {"passed": False, "first_difference": label + " incomplete " + key}
        if len(result.get("task_draw_graphics_dma", [])) != 3 or any(len(row) != 3 for row in result["task_draw_graphics_dma"]):
            return {"passed": False, "first_difference": label + " incomplete task-draw graphics DMA observations"}
        if any(len(row) != 5 for key in ("boot_input_reads", "powerup_writes", "video_writes") for row in result[key]):
            return {"passed": False, "first_difference": label + " incomplete powerup event"}
        if any(key not in result for key in ("task_draw_dma_command", "task_draw_dma_palette", "task_palette_dma_command", "task_palette_dma_palette", "task_queue_dma_command", "task_queue_dma_palette", "video_dma_command", "dma_palette", "text_dma_command", "text_dma_palette",
                                              "factory_dma_command", "factory_dma_palette", "post_factory_dma_command", "post_factory_dma_palette",
                                              "sound_command_dma_command", "sound_command_dma_palette", "input_wait_dma_command", "input_wait_dma_palette", "input_poll_dma_command", "input_poll_dma_palette", "input_idle_dma_command", "input_idle_dma_palette", "sport_wrap_dma_command", "sport_wrap_dma_palette", "button_exit_dma_command", "button_exit_dma_palette", "video_irq_dma_command", "video_irq_dma_palette", "startup_dma_command", "startup_dma_palette", "dispatcher_dma_command", "dispatcher_dma_palette", "task_resume_dma_command", "task_resume_dma_palette")):
            return {"passed": False, "first_difference": label + " incomplete video latch"}
        for key, count in (("text_reads", TEXT_READ_COUNT), ("text_writes", TEXT_WRITE_COUNT)):
            if (len(result.get(key, [])) != count or
                    any(len(row) != 5 or row[-1] != 16 for row in result[key])):
                return {"passed": False, "first_difference": label + " incomplete " + key}
        if (len(result.get("text_bus", [])) != TEXT_READ_COUNT + TEXT_WRITE_COUNT or
                any(len(row) != 6 or row[0] not in (114, 119) or row[-1] != 16 for row in result["text_bus"])):
            return {"passed": False, "first_difference": label + " incomplete text_bus"}
        for phase, count in (("factory", FACTORY_BUS_COUNT), ("post_factory", POST_FACTORY_BUS_COUNT),
                         ("sound_command", SOUND_COMMAND_BUS_COUNT), ("input_wait", INPUT_WAIT_BUS_COUNT), ("input_poll", INPUT_POLL_BUS_COUNT), ("input_idle", INPUT_IDLE_BUS_COUNT), ("sport_wrap", SPORT_WRAP_BUS_COUNT), ("button_exit", BUTTON_EXIT_BUS_COUNT), ("video_irq", VIDEO_IRQ_BUS_COUNT), ("startup", STARTUP_BUS_COUNT), ("dispatcher", DISPATCHER_BUS_COUNT), ("task_resume", TASK_RESUME_BUS_COUNT), ("task_queue", TASK_QUEUE_BUS_COUNT), ("task_palette", TASK_PALETTE_BUS_COUNT), ("task_draw", TASK_DRAW_BUS_COUNT)):
            key = phase + "_bus"
            if (len(result.get(key, [])) != count or
                    any(len(row) != 6 or row[0] not in (114, 119) or row[-1] != 16 for row in result[key])):
                return {"passed": False, "first_difference": label + " incomplete " + key}
        if (len(result.get("input_poll_pixblt", [])) != INPUT_POLL_PIXBLT_COUNT or
                len(result.get("input_poll_pixblt_dsp", [])) != INPUT_POLL_PIXBLT_COUNT or
                any(len(row) != len(DSP_REGISTERS) for row in result["input_poll_pixblt_dsp"])):
            return {"passed": False, "first_difference": label + " incomplete input-poll PIXBLT snapshots"}
        if (len(result.get("input_wait_pixblt", [])) != INPUT_WAIT_PIXBLT_COUNT or
                len(result.get("input_wait_pixblt_dsp", [])) != INPUT_WAIT_PIXBLT_COUNT or
                any(len(row) != len(DSP_REGISTERS) for row in result["input_wait_pixblt_dsp"])):
            return {"passed": False, "first_difference": label + " incomplete input-wait PIXBLT snapshots"}
        if (len(result.get("post_factory_pixblt", [])) != POST_FACTORY_PIXBLT_COUNT or
                len(result.get("post_factory_pixblt_dsp", [])) != POST_FACTORY_PIXBLT_COUNT or
                any(len(row) != len(DSP_REGISTERS) for row in result["post_factory_pixblt_dsp"])):
            return {"passed": False, "first_difference": label + " incomplete post-factory PIXBLT snapshots"}
        if (len(result.get("text_pixblt", [])) != TEXT_PIXBLT_COUNT or
                len(result.get("text_pixblt_dsp", [])) != len(result["text_pixblt"]) or
                any(len(row) != len(DSP_REGISTERS) for row in result["text_pixblt_dsp"])):
            return {"passed": False, "first_difference": label + " incomplete PIXBLT snapshots"}
        for cpu in [*result["checkpoints"].values(), *result["text_pixblt"], *result["post_factory_pixblt"], *result["input_wait_pixblt"], *result["input_poll_pixblt"]]:
            if (set(cpu) != {"pc", "status", "cycles", "a", "b"} or
                    len(cpu["a"]) != 16 or len(cpu["b"]) != 15):
                return {"passed": False, "first_difference": label + " incomplete registers"}
    if native.get("task_draw_dma_deadline_subticks") != 0:
        return {"passed": False, "first_difference": "native task-draw completed graphics DMA deadline"}
    if native["task_draw_graphics_dma"] != observed["task_draw_graphics_dma"]:
        return {"passed": False, "first_difference": "task_draw_graphics_dma"}
    for name in POINTS:
        for field in ("pc", "status", "cycles", "a", "b"):
            if native["checkpoints"][name][field] != observed["checkpoints"][name][field]:
                return {"passed": False, "first_difference": f"{name}.{field}"}
    for section in ("writes", "boot_words", "board_writes", "board_io", "board_ram", "boot_input_reads",
                    "powerup_writes", "main_ram", "powerup_board_io", "powerup_display", "video_writes",
                    "video_board_io", "video_display", "video_main_ram", "palette_ram", "vram", "text_reads", "text_writes",
                    "text_pixblt", "text_main_ram", "text_palette_ram", "text_vram", "text_board_io", "text_display", "text_bus",
                    "factory_bus", "factory_entry_main_ram", "factory_main_ram", "factory_cmos", "factory_palette_ram",
                    "factory_vram", "factory_board_io", "factory_display", "post_factory_bus", "post_factory_main_ram",
                    "post_factory_cmos", "post_factory_palette_ram", "post_factory_vram", "post_factory_board_io",
                    "post_factory_display", "post_factory_pixblt", "sound_command_bus", "sound_command_main_ram",
                    "sound_command_cmos", "sound_command_palette_ram", "sound_command_vram",
                    "sound_command_board_io", "sound_command_display", "input_wait_bus", "input_wait_main_ram",
                    "input_wait_cmos", "input_wait_palette_ram", "input_wait_vram", "input_wait_board_io",
                    "input_wait_display", "input_wait_pixblt", "input_poll_bus", "input_poll_main_ram",
                    "input_poll_cmos", "input_poll_palette_ram", "input_poll_vram", "input_poll_board_io",
                    "input_poll_display", "input_poll_pixblt", "input_idle_bus", "input_idle_main_ram",
                    "input_idle_cmos", "input_idle_palette_ram", "input_idle_vram", "input_idle_board_io", "input_idle_display", "sport_wrap_bus", "sport_wrap_main_ram", "sport_wrap_cmos",
                    "sport_wrap_palette_ram", "sport_wrap_vram", "sport_wrap_board_io", "sport_wrap_display",
                    "sport_wrap_dma_registers", "button_exit_dma_registers",
                    "button_exit_bus", "button_exit_main_ram", "button_exit_cmos", "button_exit_palette_ram",
                    "button_exit_vram", "button_exit_board_io", "button_exit_display",
                    "video_irq_bus", "video_irq_main_ram", "video_irq_cmos", "video_irq_palette_ram",
                    "video_irq_vram", "video_irq_board_io", "video_irq_display", "video_irq_dma_registers",
                    "startup_bus", "startup_main_ram", "startup_cmos", "startup_palette_ram",
                    "startup_vram", "startup_board_io", "startup_display", "startup_dma_registers",
                    "dispatcher_bus", "dispatcher_main_ram", "dispatcher_cmos", "dispatcher_palette_ram",
                    "dispatcher_vram", "dispatcher_board_io", "dispatcher_display", "dispatcher_dma_registers", "dispatcher_shiftreg",
                    "task_resume_bus", "task_resume_main_ram", "task_resume_cmos", "task_resume_palette_ram", "task_resume_vram",
                    "task_resume_board_io", "task_resume_display", "task_resume_dma_registers", "task_resume_shiftreg",
                    *["task_draw_dma_" + boundary + "_" + key for boundary in ("busy", "completed") for key in ("vram", "registers")],
                    "task_queue_bus", "task_palette_bus", "task_draw_bus", *[phase + "_" + key for phase in ("task_queue", "task_palette", "task_draw") for key, _ in TASK_QUEUE_IMAGE_SIZES]):
        if len(native[section]) != len(observed[section]):
            return {"passed": False, "first_difference": section + " length"}
        if native[section] == observed[section]: continue
        for index, (left, right) in enumerate(zip(native[section], observed[section])):
            if left != right:
                return {"passed": False, "first_difference": f"{section}[{index}]"}
    if native["board_dma_command"] != observed["board_dma_command"]:
        return {"passed": False, "first_difference": "board_dma_command"}
    for key in ("task_draw_dma_command", "task_draw_dma_palette", "task_palette_dma_command", "task_palette_dma_palette", "task_queue_dma_command", "task_queue_dma_palette", "video_dma_command", "dma_palette", "text_dma_command", "text_dma_palette", "factory_dma_command", "factory_dma_palette", "post_factory_dma_command", "post_factory_dma_palette", "sound_command_dma_command", "sound_command_dma_palette", "input_wait_dma_command", "input_wait_dma_palette", "input_poll_dma_command", "input_poll_dma_palette", "input_idle_dma_command", "input_idle_dma_palette", "sport_wrap_dma_command", "sport_wrap_dma_palette", "button_exit_dma_command", "button_exit_dma_palette", "video_irq_dma_command", "video_irq_dma_palette", "startup_dma_command", "startup_dma_palette", "dispatcher_dma_command", "dispatcher_dma_palette", "task_resume_dma_command", "task_resume_dma_palette"):
        if native[key] != observed[key]: return {"passed": False, "first_difference": key}
    for key in ("text_pixblt_dsp", "post_factory_pixblt_dsp", "input_wait_pixblt_dsp", "input_poll_pixblt_dsp"):
        for index, (a, b) in enumerate(zip(native[key], observed[key])):
            if a[:1] + a[2:] != b[:1] + b[2:]:
                return {"passed": False, "first_difference": f"{key}[{index}]"}
    return {"passed": True, "cpu_checkpoints": len(POINTS), "registers_per_checkpoint": 31,
            "ordered_writes": 6, "boot_words_compared_in_full": BOOT_WORDS,
            "ordered_board_writes": BOARD_WRITE_COUNT, "board_io_words": 28,
            "board_ram_values": len(STORED_RAM_ADDRESSES), "board_dma_command_readback": True,
            "ordered_boot_input_reads": 2, "ordered_powerup_writes": POWERUP_WRITE_COUNT,
            "clear_dword_writes": 32768, "cleared_ram_words_compared_in_full": 65536,
            "powerup_io_words": 28, "powerup_display_fields": 2,
            "ordered_video_writes": VIDEO_WRITE_COUNT, "cpu_vram_dword_writes": 65536,
            "video_main_ram_words_compared_in_full": 65536, "palette_words_compared_in_full": 32768,
            "raw_vram_words_compared_in_full": 524288, "video_io_words": 28, "video_display_fields": 2,
            "ordered_text_reads": len(native["text_reads"]), "ordered_text_writes": len(native["text_writes"]),
            "interleaved_text_bus_accesses": len(native["text_bus"]),
            "text_pixblt_boundaries": len(native["text_pixblt"]), "text_main_ram_words_compared_in_full": 65536,
            "text_palette_words_compared_in_full": 32768, "text_raw_vram_words_compared_in_full": 524288,
            "interleaved_factory_bus_accesses": FACTORY_BUS_COUNT,
            "factory_entry_main_ram_words_compared_in_full": 262144, "factory_main_ram_words_compared_in_full": 262144,
            "factory_cmos_words_compared_in_full": 8192, "factory_palette_words_compared_in_full": 32768,
            "factory_raw_vram_words_compared_in_full": 524288,
            "interleaved_post_factory_bus_accesses": POST_FACTORY_BUS_COUNT,
            "interleaved_sound_command_bus_accesses": SOUND_COMMAND_BUS_COUNT,
            "interleaved_input_idle_bus_accesses": INPUT_IDLE_BUS_COUNT,
            "interleaved_sport_wrap_bus_accesses": SPORT_WRAP_BUS_COUNT,
            "interleaved_button_exit_bus_accesses": BUTTON_EXIT_BUS_COUNT,
            "interleaved_video_irq_bus_accesses": VIDEO_IRQ_BUS_COUNT,
            "interleaved_startup_bus_accesses": STARTUP_BUS_COUNT,
            "interleaved_dispatcher_bus_accesses": DISPATCHER_BUS_COUNT,
            "interleaved_task_resume_bus_accesses": TASK_RESUME_BUS_COUNT,
            "interleaved_task_queue_bus_accesses": TASK_QUEUE_BUS_COUNT,
            "task_draw_graphics_dma_checkpoints": 3,
            "task_draw_graphics_dma_intermediate_vram_words_per_checkpoint": 524288,
            "task_draw_graphics_dma_intermediate_registers_per_checkpoint": 18,
            "interleaved_task_draw_bus_accesses": TASK_DRAW_BUS_COUNT,
            "task_draw_image_values_compared_in_full": dict(TASK_QUEUE_IMAGE_SIZES),
            "interleaved_task_palette_bus_accesses": TASK_PALETTE_BUS_COUNT,
            "task_palette_image_values_compared_in_full": dict(TASK_QUEUE_IMAGE_SIZES),
            "task_queue_image_values_compared_in_full": dict(TASK_QUEUE_IMAGE_SIZES),
            "dispatcher_main_ram_words_compared_in_full": 262144, "dispatcher_cmos_words_compared_in_full": 8192,
            "dispatcher_palette_words_compared_in_full": 32768, "dispatcher_vram_words_compared_in_full": 524288,
            "dispatcher_physical_dma_registers_compared": 18,
            "dispatcher_shiftreg_words_compared_in_full": 4096,
            "task_resume_main_ram_words_compared_in_full": 262144, "task_resume_cmos_words_compared_in_full": 8192,
            "task_resume_palette_words_compared_in_full": 32768, "task_resume_vram_words_compared_in_full": 524288,
            "task_resume_physical_dma_registers_compared": 18,
            "task_resume_shiftreg_words_compared_in_full": 4096,
            "startup_main_ram_words_compared_in_full": 262144, "startup_cmos_words_compared_in_full": 8192,
            "startup_palette_words_compared_in_full": 32768, "startup_vram_words_compared_in_full": 524288,
            "video_irq_main_ram_words_compared_in_full": 262144, "video_irq_cmos_words_compared_in_full": 8192,
            "video_irq_palette_words_compared_in_full": 32768, "video_irq_vram_words_compared_in_full": 524288,
            "button_exit_main_ram_words_compared_in_full": 262144, "button_exit_cmos_words_compared_in_full": 8192,
            "button_exit_palette_words_compared_in_full": 32768, "button_exit_vram_words_compared_in_full": 524288,
            "button_exit_physical_dma_registers_compared": 18, "historical_sport_wrap_physical_dma_registers_compared": 18,
            "sport_wrap_main_ram_words_compared_in_full": 262144, "sport_wrap_cmos_words_compared_in_full": 8192,
            "sport_wrap_palette_words_compared_in_full": 32768, "sport_wrap_vram_words_compared_in_full": 524288,
            "input_idle_main_ram_words_compared_in_full": 262144, "input_idle_cmos_words_compared_in_full": 8192,
            "input_idle_palette_words_compared_in_full": 32768, "input_idle_vram_words_compared_in_full": 524288,
            "interleaved_input_poll_bus_accesses": INPUT_POLL_BUS_COUNT, "input_poll_pixblt_boundaries": INPUT_POLL_PIXBLT_COUNT,
            "input_poll_main_ram_words_compared_in_full": 262144, "input_poll_cmos_words_compared_in_full": 8192,
            "input_poll_palette_words_compared_in_full": 32768, "input_poll_vram_words_compared_in_full": 524288,
            "interleaved_input_wait_bus_accesses": INPUT_WAIT_BUS_COUNT, "input_wait_pixblt_boundaries": INPUT_WAIT_PIXBLT_COUNT,
            "input_wait_main_ram_words_compared_in_full": 262144, "input_wait_cmos_words_compared_in_full": 8192,
            "input_wait_palette_words_compared_in_full": 32768, "input_wait_vram_words_compared_in_full": 524288,
            "sound_command_main_ram_words_compared_in_full": 262144,
            "sound_command_cmos_words_compared_in_full": 8192,
            "sound_command_palette_words_compared_in_full": 32768,
            "sound_command_vram_words_compared_in_full": 524288,
            "post_factory_pixblt_boundaries": POST_FACTORY_PIXBLT_COUNT,
            "post_factory_main_ram_words_compared_in_full": 262144, "post_factory_cmos_words_compared_in_full": 8192,
            "post_factory_palette_words_compared_in_full": 32768, "post_factory_raw_vram_words_compared_in_full": 524288}


def capture(scratch, executable, directory, manifest):
    result = None
    try:
        result = _capture(scratch, executable, directory, manifest)
        return result
    finally:
        # The debugger only transports symbol snapshots through this transient log.
        (scratch / "debug.log").unlink(missing_ok=True)
        if result is not None: result[1]["debug_log_removed_before_return"] = True


def _capture(scratch, executable, directory, manifest):
    from tools.quality import run as quality

    factory_program = factory_program_image(directory, manifest)
    factory_opcode = factory_opcode_reader(factory_program)

    video_script = '''local machine = manager.machine
local main = machine.devices[":maincpu"]
local video = assert(machine.devices[":video"])
local input_port = assert(machine.ioport.ports[":IN0"])
local button = assert(input_port.fields["P1 High Punch"])
assert(button.mask == 0x10)
local input_events, requested, previous_port = {}, 0, input_port:read()
local input_tap = main.spaces["program"]:install_read_tap(0x01a80000, 0x01a8000f, "mk2-legal-input", function()
    local pc = main.state["PC"].value
    local tick = math.floor(machine.time:as_double() * 100000000 + 0.5)
    if pc == 0xffa5aef0 and tick == 8096368 then
        assert(requested == 0 and #input_events == 0)
        requested = 1
    elseif pc == 0xffa5b130 and tick == 9140064 then
        assert(requested == 1 and #input_events == 2)
        requested = 0
    else return end
    button:set_value(requested)
    input_events[#input_events + 1] = {tick, requested, input_port:read(), 0}
end)
local input_frame_subscription = emu.add_machine_frame_notifier(function()
    local value = input_port:read()
    if value ~= previous_port then
        input_events[#input_events + 1] = {math.floor(machine.time:as_double() * 100000000 + 0.5), requested, value, 1}
        previous_port = value
    end
end)
local function bind(device, suffix)
    local found
    for name, index in pairs(device.items) do
        if name == suffix or name:sub(-#suffix - 1) == "/" .. suffix then
            assert(not found, "Ambiguous video saved item " .. suffix)
            found = emu.item(index)
        end
    end
    return assert(found, "Missing video saved item " .. suffix)
end
local shiftreg = bind(main, "m_shiftreg")
assert(shiftreg.size == 2 and shiftreg.count == 4096)
local vram, dma = bind(video, "m_local_videoram"), bind(video, "m_dma_register")
assert(vram.size == 2 and vram.count == 524288 and dma.size == 2 and dma.count == 18)
local dcs, dac = assert(machine.devices[":dcs"]), assert(machine.devices[":dcs:dac"])
local device_fields = {"sounddata_bank", "ireg", "ireg_base", "incs", "size", "channels", "timer_enable",
    "timer_scale", "timer_period", "timers_fired", "timer_start_count", "timer_start_cycles", "timer_ignore", "progflags"}
local device_items = {}
for _, name in ipairs(device_fields) do device_items[#device_items + 1] = bind(dcs, "m_" .. name) end
for _, name in ipairs({"enabled", "bufin", "bufout"}) do device_items[#device_items + 1] = bind(dac, "m_" .. name) end
for _, item in ipairs(device_items) do assert(item.count == 1) end
local dac_buffer = bind(dac, "m_buffer")
assert(dac_buffer.size == 4 and dac_buffer.count == 32768)
local dma_rows = {}
local dma_tap = machine.devices[":dcs:dcs"].spaces["data"]:install_read_tap(0x400, 0x5df, "mk2-sport-dma", function(offset, data)
    -- Debugger memory saves also invoke read taps; only running-device reads belong here.
    if machine.debugger.execution_state ~= "run" then return end
    local pc = machine.devices[":dcs:dcs"].state["PC"].value
    if (pc == 0x136 or pc == 0x131 or pc == 0x132 or pc == 0x137 or pc == 0x138) and machine.time:as_double() > 0.07 then
        local tick = math.floor(machine.time:as_double() * 100000000 + 0.5)
        dma_rows[#dma_rows + 1] = {tick, pc, offset, data}
    end
end)
local irq_state, irq_latch = bind(machine.devices[":dcs:dcs"], "m_irq_state"), bind(machine.devices[":dcs:dcs"], "m_irq_latch")
local irq_rows = {}
local irq_tap = main.spaces["program"]:install_read_tap(0x01a80000, 0x01a8000f, "mk2-irq1-hook", function()
    local dsp = machine.devices[":dcs:dcs"]
    local tick, pc = math.floor(machine.time:as_double() * 100000000 + 0.5), dsp.state["PC"].value
    if ((tick == 7993490 or tick == 14320570 or tick == 15856570 or tick == 17392570) and pc == 0x131) or
       ((tick == 7993500 or tick == 14320580 or tick == 15856580 or tick == 17392580) and pc == 0x132) or
       (tick == 18928570 and pc == 0x132) or (tick == 18928580 and pc == 0x130) then
        irq_rows[#irq_rows + 1] = {tick, pc, irq_state:read(1), irq_latch:read(1)}
    end
end)
local captured = {}
local targets = {[0xffa5a190] = "", [0xffa5a2e0] = "text_", [0xffa5a340] = "factory_", [0xffa5ac90] = "post_factory_", [0xffa5acc0] = "sound_command_", [0xffa592b0] = "input_wait_", [0xffa5aef0] = "input_poll_", [0xff815090] = "button_exit_", [0xff8114d0] = "video_irq_", [0xff811710] = "startup_", [0xff80dd30] = "dispatcher_", [0xff816a30] = "task_palette_", [0xff810250] = "task_draw_dma_busy_", [0xff810260] = "task_draw_dma_completed_"}
local dsp_targets = {[0xffa13ec0] = "button_exit_reset_before_", [0xffa13ef0] = "button_exit_held_",
    [0xffa13f50] = "button_exit_release_before_", [0xffa13f80] = "button_exit_released_",
    [0xff814f10] = "button_exit_board_reloaded_", [0xff815090] = "button_exit_ready_", [0xff8114d0] = "video_irq_ready_", [0xff811710] = "startup_ready_", [0xff80dd30] = "dispatcher_ready_", [0xff816a30] = "task_palette_ready_"}
local tap = main.spaces["program"]:install_read_tap(0x01a80010, 0x01a8001f, "mk2-final-raw-video", function()
    local pc = main.state["PC"].value
    local dsp_prefix = dsp_targets[pc]
    if dsp_prefix == "dispatcher_ready_" and captured[dsp_prefix] then dsp_prefix = "task_resume_ready_" end
    if dsp_prefix == "task_resume_ready_" and captured[dsp_prefix] then dsp_prefix = "task_queue_ready_" end
    if dsp_prefix == "task_queue_ready_" and captured[dsp_prefix] and captured["task_palette_"] then dsp_prefix = "task_draw_ready_" end
    if dsp_prefix and not captured[dsp_prefix] then
        local file = assert(io.open(dsp_prefix .. "device.bin", "wb"))
        for _, item in ipairs(device_items) do assert(file:write(string.pack("<I8", assert(item:read(0))))) end
        file:close()
        captured[dsp_prefix] = true
    end
    local prefix = targets[pc]
    if prefix == "dispatcher_" and captured[prefix] then prefix = "task_resume_" end
    if prefix == "task_resume_" and captured[prefix] then prefix = "task_queue_" end
    if prefix == "task_queue_" and captured[prefix] and captured["task_palette_"] then prefix = "task_draw_" end
    if prefix == "input_poll_" and captured[prefix] then prefix = "input_idle_" end
    if prefix == "input_idle_" and captured[prefix] then prefix = "sport_wrap_" end
    if not prefix or captured[prefix] then return end
    if prefix == "dispatcher_" or prefix == "task_resume_" or prefix == "task_queue_" or prefix == "task_palette_" or prefix == "task_draw_" then
        local file = assert(io.open(prefix .. "shiftreg.bin", "wb"))
        for index = 0, 4095 do assert(file:write(string.pack("<I2", assert(shiftreg:read(index))))) end
        file:close()
    end
    local output = assert(io.open(prefix .. "vram.bin", "wb"))
    for first = 0, vram.count - 1, 4096 do
        local words = {}
        for i = first, first + 4095 do words[#words + 1] = string.pack("<I2", assert(vram:read(i))) end
        assert(output:write(table.concat(words)))
    end
    output:close()
    local latch = assert(io.open(prefix .. "video-latch.bin", "wb"))
    assert(latch:write(string.pack("<I2", assert(dma:read(8)))))
    latch:close()
    if prefix == "sport_wrap_" or prefix == "button_exit_" or prefix == "video_irq_" or prefix == "startup_" or prefix == "dispatcher_" or prefix == "task_resume_" or prefix == "task_queue_" or prefix == "task_palette_" or prefix == "task_draw_" or prefix == "task_draw_dma_busy_" or prefix == "task_draw_dma_completed_" then
        local dma_file = assert(io.open(prefix .. "dma-registers.bin", "wb"))
        for index = 0, 17 do assert(dma_file:write(string.pack("<I2", assert(dma:read(index))))) end
        dma_file:close()
    end
    if prefix == "input_wait_" or prefix == "input_poll_" or prefix == "input_idle_" or prefix == "sport_wrap_" then
        local device_file = assert(io.open(prefix .. "device.bin", "wb"))
        for _, item in ipairs(device_items) do assert(device_file:write(string.pack("<I8", assert(item:read(0))))) end
        device_file:close()
    end
    if prefix == "sport_wrap_" then
        local irq_file = assert(io.open("sport_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        for _, row in ipairs(irq_rows) do assert(irq_file:write(string.pack("<I8I8I8I8", table.unpack(row)))) end
        irq_file:close()
        assert(device_items[#device_items - 1]:read(0) == 480, "Expected both SPORT transfers")
        local pcm_file = assert(io.open("sport_wrap_dac.bin", "wb"))
        for index = 0, 479 do assert(pcm_file:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        pcm_file:close()
        assert(#dma_rows == 480, "Expected both SPORT DMA packets")
    end
    if prefix == "video_irq_" or prefix == "startup_" or prefix == "dispatcher_" then
        local final_dac = assert(io.open(prefix == "video_irq_" and "video_irq_dac.bin" or prefix == "startup_" and "startup_dac.bin" or "final_dac.bin", "wb"))
        for index = 0, 719 do assert(final_dac:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        final_dac:close()
        local irq_file = assert(io.open(prefix == "video_irq_" and "video_irq_irq.bin" or prefix == "startup_" and "startup_irq.bin" or "sport_irq_final.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        irq_file:close()
    end
    if prefix == "task_resume_" then
        assert(device_items[15]:read(0) == 1 and device_items[16]:read(0) == 1680 and device_items[17]:read(0) == 1440,
               "Expected independently observed DAC reset/consumption cursors")
        local final_dac = assert(io.open("task_resume_dac.bin", "wb"))
        for index = 0, 2399 do assert(final_dac:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        final_dac:close()
        local irq_file = assert(io.open("task_resume_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        assert(#irq_rows == 8, "Expected historical and task-resume SPORT IRQ1 observations")
        for index = 3, #irq_rows do assert(irq_file:write(string.pack("<I8I8I8I8", table.unpack(irq_rows[index])))) end
        irq_file:close()
        assert(#dma_rows == 2400, "Expected historical and task-resume SPORT DMA packets")
        local dma_file = assert(io.open("task_resume_dma.bin", "wb"))
        for index = 721, #dma_rows do assert(dma_file:write(string.pack("<I8I8I8I8", table.unpack(dma_rows[index])))) end
        dma_file:close()
    end
    if prefix == "task_queue_" then
        assert(captured["task_resume_"] and #dma_rows == 2400 and #irq_rows == 8,
               "Unexpected task-queue SPORT observations")
        assert(device_items[15]:read(0) == 1 and device_items[16]:read(0) == 1680 and device_items[17]:read(0) == 1440,
               "Unexpected task-queue DAC cursors")
        local final_dac = assert(io.open("task_queue_dac.bin", "wb"))
        for index = 0, 2399 do assert(final_dac:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        final_dac:close()
        local irq_file = assert(io.open("task_queue_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        irq_file:close()
    end
    if prefix == "task_palette_" then
        assert(captured["task_queue_"] and #dma_rows == 2880 and #irq_rows == 10,
               "Unexpected task-palette SPORT observations")
        assert(device_items[15]:read(0) == 1 and device_items[16]:read(0) == 2160 and device_items[17]:read(0) == 2015,
               "Unexpected task-palette DAC cursors")
        local final_dac = assert(io.open("task_palette_dac.bin", "wb"))
        for index = 0, 2879 do assert(final_dac:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        final_dac:close()
        local irq_file = assert(io.open("task_palette_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        for index = 9, #irq_rows do assert(irq_file:write(string.pack("<I8I8I8I8", table.unpack(irq_rows[index])))) end
        irq_file:close()
        local dma_file = assert(io.open("task_palette_dma.bin", "wb"))
        for index = 2401, #dma_rows do assert(dma_file:write(string.pack("<I8I8I8I8", table.unpack(dma_rows[index])))) end
        dma_file:close()
    end
    if prefix == "task_draw_" then
        assert(captured["task_palette_"] and #dma_rows == 2880 and #irq_rows == 10,
               "Unexpected task-draw SPORT observations")
        assert(device_items[15]:read(0) == 1 and device_items[16]:read(0) == 2160 and device_items[17]:read(0) == 2015,
               "Unexpected task-draw DAC cursors")
        local final_dac = assert(io.open("task_draw_dac.bin", "wb"))
        for index = 0, 2879 do assert(final_dac:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        final_dac:close()
        local irq_file = assert(io.open("task_draw_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        irq_file:close()
    end
    if prefix == "button_exit_" then
        local irq_file = assert(io.open("button_exit_irq.bin", "wb"))
        assert(irq_file:write(string.pack("<I8I8", irq_state:read(1), irq_latch:read(1))))
        irq_file:close()
        local pcm_file = assert(io.open("sport_dac.bin", "wb"))
        for index = 0, 719 do assert(pcm_file:write(string.pack("<I4", assert(dac_buffer:read(index))))) end
        pcm_file:close()
        assert(#dma_rows == 720, "Expected three SPORT DMA packets")
        local dma_file = assert(io.open("sport_dma.bin", "wb"))
        for _, row in ipairs(dma_rows) do assert(dma_file:write(string.pack("<I8I8I8I8", table.unpack(row)))) end
        dma_file:close()
        assert(#input_events == 4 and requested == 0 and input_port:read() == 0xffff)
        local input_file = assert(io.open("input_events.bin", "wb"))
        for _, row in ipairs(input_events) do assert(input_file:write(string.pack("<I8I8I8I8", table.unpack(row)))) end
        input_file:close()
    end
    captured[prefix] = true
end)
mk2_video_stop_subscription = emu.add_machine_stop_notifier(function()
    tap:remove(); dma_tap:remove(); irq_tap:remove(); input_tap:remove()
    assert(input_frame_subscription)
end)
'''
    (scratch / "video.lua").write_text(video_script, encoding="ascii")

    roms = scratch / "mk2"
    roms.mkdir()
    for rom in manifest["roms"]:
        name = rom["upstream_name"]
        if Path(name).name != name or "/" in name or "\\" in name or ":" in name:
            raise ValueError("Invalid reference ROM name")
        # Same-volume, read-only use: removing these hard links preserves the ROM sources.
        os.link(directory / rom["path"], roms / name)
    lines = ["focus :maincpu", "observe :dcs:dcs"]
    # A0..A9/B0..B9 without a leading zero resolve as visible main-CPU register symbols.
    for pc in DSP_PCS:
        condition = "&&".join(f"totalcycles!={cycle:x}" for hook_pc, cycle in DSP_IRQ_HOOKS if hook_pc == pc) or "1"
        # 0829 is reused after a PM-bank reload; only the observed TX1 opcode is a serial event.
        header = 'printf "MK2_DSP_BEGIN %X\\n",:dcs:dcs.pd@829' if pc == 0x829 else 'printf "MK2_DSP_BEGIN\\n"'
        lines.append(f'bpset {pc:04x}:dcs:dcs,{condition},{{{header};symlist :dcs:dcs;g}}')
    for address, size, mode, space, kind, condition in ((0, 0x2000, 'w', 'program', 'p', '1'),
                                            (0, 0x4000, 'w', 'data', 'd', 'wpaddr<3fe0'),
                                            (0x3fe0, 32, 'w', 'data', 'd', '1'),
                                            (0, 0x4000, 'r', 'data', 'r', 'wpaddr!=39fc'),
                                            (0x39fc, 1, 'r', 'data', 'r', '1'),
                                            (0, 0x2000, 'r', 'program', 'q',
                                             '(' + '||'.join(f'curpc=={pc:x}' for pc in PM_READ_PCS) + ')&&wpaddr==i5')):
        lines.append(f'wpset {address:x}:dcs:dcs:{space},{size:x},{mode},{condition},{{'
                     f'printf "MK2_DSP_ACCESS {ord(kind):X} %X %X\\n",wpaddr,wpdata;symlist :dcs:dcs;g}}')
    for address in (0x0105bb10, 0x01d01030, 0x010b95a0):
        lines.append(f'wpset {address:x},10,w,totalcycles<829,{{printf "MK2_WRITE %08X %08X %04X %d\\n",'
                     'pc,wpaddr,wpdata,totalcycles;g}')
    for address, size in ((0x01b00000, 0x20), (0x01f00000, 0x20),
                          (0x01a80010, 0x10), (0xc0000000, 0x200)):
        lines.append(f'wpset {address:x}:maincpu,{size:x},w,totalcycles<829,{{printf "MK2_BOARD_WRITE '
                     '%X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}')
    lines.append('wpset 1600030:maincpu,20,r,1,{printf "MK2_INPUT_READ %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}')
    for address, size in ((0x01000000, 0x100000), (0x01b00000, 0x20), (0x01f00000, 0x20)):
        lines.append(f'wpset {address:x}:maincpu,{size:x},w,totalcycles>=829&&totalcycles<{100455:x},{{printf "MK2_POWERUP_WRITE '
                     '%X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}')
    # Multiple mapped-range observers duplicate the control callback in MAME 0.280; one bus observer does not.
    lines.append(f'wpset 0:maincpu,ffffffff,w,totalcycles>={100455:x},{{printf "MK2_VIDEO_WRITE '
                 '%X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}')
    lines.append('wpset 1400f00,60,r,1,{printf "MK2_CMOS_READ %X %X %X %X\\n",'
                 'pc,wpaddr,b@wpaddr,totalcycles;g}')
    for address, size in ((0x01480000, 16), (0x01400f00, 0x60)):
        lines.append(f'wpset {address:x},{size:x},w,1,{{printf "MK2_CMOS_WRITE %X %X %X %X\\n",pc,wpaddr,wpdata,totalcycles;g}}')
    registers = [f"a{i}" for i in range(15)] + ["sp"] + [f"b{i}" for i in range(15)]
    index = len(DSP_PCS)
    for name, address in POINTS.items():
        if name in TEXT_GLYPH_POINTS.values() or name == "button_exit_pressed": continue
        index += 1
        fmt = f"MK2_CPU {name} %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
        action = f'bpdisable {index:x};printf "{fmt}",pc,st,totalcycles,' + ",".join(registers)
        if name == "prefix":
            action += ";save boot.bin,0:dcs:dcs,178"
        action += f';printf "MK2_DSP_POINT {name}\\n";symlist :dcs:dcs'
        if name in ("task_draw_dma_started", "task_draw_dma_busy", "task_draw_dma_completed"):
            action += ';printf "MK2_TASK_DRAW_GRAPHICS_DMA %d %X %X\\n",totalcycles,w@1a80010,w@c0000120'
        if name in BUTTON_DSP_POINTS:
            action += ';printf "%X\\n",w@1a80010'
            action += f';save {name}_pm.bin,0:dcs:dcs,400;saved {name}_dm.bin,3800:dcs:dcs,200;saved {name}_control.bin,3fe0:dcs:dcs,20;save {name}_external_pm.bin,800:dcs:dcs,800;saved {name}_external_dm.bin,0:dcs:dcs,800'
        if name == "sound":
            for ram_address in SOUND_RAM_ADDRESSES:
                action += f';printf "MK2_SOUND_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
        if name == "checked":
            for ram_address in RAM_ADDRESSES:
                action += f';printf "MK2_CHECKED_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
        if name == "record":
            for ram_address in RAM_ADDRESSES:
                action += f';printf "MK2_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
        if name == "stored":
            for ram_address in STORED_RAM_ADDRESSES:
                action += f';printf "MK2_STORED_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
        if name + "_ram" in RETURN_RAM_KEYS:
            for ram_address in STORED_RAM_ADDRESSES:
                action += f';printf "MK2_{name.upper()}_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
        if name == "board_ready":
            for i in range(28):
                action += f';printf "MK2_BOARD_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            for ram_address in STORED_RAM_ADDRESSES:
                action += f';printf "MK2_BOARD_RAM {ram_address:X} %X\\n",d@{ram_address:x}'
            action += ';printf "MK2_BOARD_DMA %X\\n",w@1a80010'
        if name == "powerup_ready":
            for i in range(28):
                action += f';printf "MK2_POWERUP_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_POWERUP_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';save main_ram.bin,1000000,100000'
            # These eleven main-CPU observers have reached their complete checkpoints; DSP observers remain active.
            action += ';wpclear 7,8,9,a,b,c,d,e,f,10,11'
        if name == "video_ready":
            for i in range(28):
                action += f';printf "MK2_VIDEO_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_VIDEO_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_VIDEO_DMA %X\\n",w@1a80010'
            action += ";save video_main_ram.bin,1000000,100000;save palette.bin,1800000,80000"
            action += ';wpclear 12,13,14,15'
            action += ';wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ffa401c0&&wpaddr<=ffa40220)||(wpaddr>=ffa56000&&wpaddr<ffa59000),{printf "MK2_TEXT_READ %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_TEXT_WRITE %X %X %X %d %d\\n",pc,wpaddr,wpdata,totalcycles,wpsize;g}'
        if name == "text_ready":
            for i in range(28):
                action += f';printf "MK2_TEXT_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_TEXT_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_TEXT_DMA %X\\n",w@1a80010'
            action += ";save text_main_ram.bin,1000000,100000;save text_palette.bin,1800000,80000;save cmos.bin,1400000,20000;save factory_entry_main_ram.bin,1000000,400000"
            action += ';wpclear 16,17'
            action += ';wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ffa401c0&&wpaddr<=ffa40220)||(wpaddr>=ffa4cf20&&wpaddr<ffa4d2a0)||(wpaddr>=ffa28730&&wpaddr<ffa28cd0),{printf "MK2_FACTORY_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_FACTORY_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
        if name == "factory_ready":
            for i in range(28):
                action += f';printf "MK2_FACTORY_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_FACTORY_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_FACTORY_DMA %X\\n",w@1a80010'
            action += ";save factory_main_ram.bin,1000000,400000;save factory_cmos.bin,1400000,20000;save factory_palette.bin,1800000,80000"
            action += ';wpclear 18,19'
            action += ';wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ffa401c0&&wpaddr<=ffa40220)||(wpaddr>=ffa56000&&wpaddr<ffa59000)||(wpaddr>=ffa6a6c0&&wpaddr<ffa6a760)||(wpaddr>=ffa6a8b0&&wpaddr<ffa6aa00),{printf "MK2_POST_FACTORY_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_POST_FACTORY_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
        if name == "post_factory_ready":
            for i in range(28):
                action += f';printf "MK2_POST_FACTORY_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_POST_FACTORY_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_POST_FACTORY_DMA %X\\n",w@1a80010'
            # Replace only the completed phase's CPU observers; IRQ2 still uses the DSP observers.
            action += ';wpclear 1a,1b;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000,{printf "MK2_SOUND_COMMAND_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_SOUND_COMMAND_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ";save post_factory_main_ram.bin,1000000,400000;save post_factory_cmos.bin,1400000,20000;save post_factory_palette.bin,1800000,80000;save post_factory_pm.bin,0:dcs:dcs,400;saved post_factory_dm.bin,3800:dcs:dcs,200;saved post_factory_control.bin,3fe0:dcs:dcs,20;g"
        elif name == "sound_command_ready":
            for i in range(28):
                action += f';printf "MK2_SOUND_COMMAND_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_SOUND_COMMAND_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_SOUND_COMMAND_DMA %X\\n",w@1a80010'
            action += ';wpclear 1c,1d'
            action += ';wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ffa56000&&wpaddr<ffa59000)||(wpaddr>=ffa6a760&&wpaddr<ffa6a8b0),{printf "MK2_INPUT_WAIT_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_INPUT_WAIT_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ";save sound_command_main_ram.bin,1000000,400000;save sound_command_cmos.bin,1400000,20000;save sound_command_palette.bin,1800000,80000;save sound_command_pm.bin,0:dcs:dcs,400;saved sound_command_dm.bin,3800:dcs:dcs,200;saved sound_command_control.bin,3fe0:dcs:dcs,20;g"
        elif name == "input_wait_ready":
            for i in range(28):
                action += f';printf "MK2_INPUT_WAIT_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_INPUT_WAIT_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_INPUT_WAIT_DMA %X\\n",w@1a80010'
            action += ';wpclear 1e,1f'
            action += ';wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ffa56000&&wpaddr<ffa59000)||(wpaddr>=ffa6a760&&wpaddr<ffa6a8b0),{printf "MK2_INPUT_POLL_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_INPUT_POLL_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ";save input_wait_main_ram.bin,1000000,400000;save input_wait_cmos.bin,1400000,20000;save input_wait_palette.bin,1800000,80000;save input_wait_pm.bin,0:dcs:dcs,400;saved input_wait_dm.bin,3800:dcs:dcs,200;saved input_wait_control.bin,3fe0:dcs:dcs,20;save input_wait_external_pm.bin,800:dcs:dcs,800;saved input_wait_external_dm.bin,0:dcs:dcs,800"
            # The old endpoint is also the new first PIXBLT entry; one breakpoint owns both observations.
            first_fmt = "MK2_INPUT_POLL_PIXBLT %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
            action += f';printf "{first_fmt}",pc,st,totalcycles,' + ",".join(registers)
            action += ';printf "MK2_DSP_INPUT_POLL_PIXBLT\\n";symlist :dcs:dcs;g'
        elif name == "input_poll_ready":
            for i in range(28):
                action += f';printf "MK2_INPUT_POLL_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_INPUT_POLL_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_INPUT_POLL_DMA %X\\n",w@1a80010'
            action += ";save input_poll_main_ram.bin,1000000,400000;save input_poll_cmos.bin,1400000,20000;save input_poll_palette.bin,1800000,80000;save input_poll_pm.bin,0:dcs:dcs,400;saved input_poll_dm.bin,3800:dcs:dcs,200;saved input_poll_control.bin,3fe0:dcs:dcs,20;save input_poll_external_pm.bin,800:dcs:dcs,800;saved input_poll_external_dm.bin,0:dcs:dcs,800"
            action += ';wpclear 20,21;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000,{printf "MK2_INPUT_IDLE_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_INPUT_IDLE_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
        elif name == "input_idle_ready":
            for i in range(28):
                action += f';printf "MK2_INPUT_IDLE_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_INPUT_IDLE_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_INPUT_IDLE_DMA %X\\n",w@1a80010'
            action += ";save input_idle_main_ram.bin,1000000,400000;save input_idle_cmos.bin,1400000,20000;save input_idle_palette.bin,1800000,80000;save input_idle_pm.bin,0:dcs:dcs,400;saved input_idle_dm.bin,3800:dcs:dcs,200;saved input_idle_control.bin,3fe0:dcs:dcs,20;save input_idle_external_pm.bin,800:dcs:dcs,800;saved input_idle_external_dm.bin,0:dcs:dcs,800"
            action += ';wpclear 22,23;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000,{printf "MK2_SPORT_WRAP_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_SPORT_WRAP_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'

        elif name == "sport_wrap_ready":
            for i in range(28):
                action += f';printf "MK2_SPORT_WRAP_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_SPORT_WRAP_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_SPORT_WRAP_DMA %X\\n",w@1a80010'
            action += ';printf "MK2_SPORT_WRAP_DCS_CONTROL %X\\n",w@1d00000<<4'
            action += ";save sport_wrap_main_ram.bin,1000000,400000;save sport_wrap_cmos.bin,1400000,20000;save sport_wrap_palette.bin,1800000,80000;save sport_wrap_pm.bin,0:dcs:dcs,400;saved sport_wrap_dm.bin,3800:dcs:dcs,200;saved sport_wrap_control.bin,3fe0:dcs:dcs,20;save sport_wrap_external_pm.bin,800:dcs:dcs,800;saved sport_wrap_external_dm.bin,0:dcs:dcs,800"
            action += ';wpclear 24,25;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ff815c50&&wpaddr<ff815e10),{printf "MK2_BUTTON_EXIT_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_BUTTON_EXIT_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            pressed_fmt = "MK2_CPU button_exit_pressed %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
            action += f';printf "{pressed_fmt}",pc,st,totalcycles,' + ",".join(registers)
            action += ';printf "MK2_DSP_POINT button_exit_pressed\\n";symlist :dcs:dcs;printf "%X\\n",w@1a80000;g'
        elif name == "button_exit_changed":
            action += ';printf "%X\\n",w@1a80000;g'
        elif name == "button_exit_ready":
            for i in range(28):
                action += f';printf "MK2_BUTTON_EXIT_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += ';printf "MK2_BUTTON_EXIT_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += ';printf "MK2_BUTTON_EXIT_DMA %X\\n",w@1a80010'
            action += ';printf "MK2_BUTTON_EXIT_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_BUTTON_EXIT_BOUNDARY\\n"'
            action += ";save button_exit_main_ram.bin,1000000,400000;save button_exit_cmos.bin,1400000,20000;save button_exit_palette.bin,1800000,80000"
            action += ';wpclear 26,27;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000||(wpaddr>=ff808b30&&wpaddr<ff8090b0)||(wpaddr>=ffafe5a0&&wpaddr<ffafe9b0)||(wpaddr>=fffffea0&&wpaddr<fffffec0),{printf "MK2_VIDEO_IRQ_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
            action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_VIDEO_IRQ_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
        elif name in ("video_irq_ready", "startup_ready", "dispatcher_ready", "task_resume_ready", "task_queue_ready", "task_palette_ready", "task_draw_ready"):
            phase = name.removesuffix("_ready")
            for i in range(28):
                action += f';printf "MK2_{phase.upper()}_IO {i:X} %X\\n",w@{0xc0000000 + i*16:x}'
            action += f';printf "MK2_{phase.upper()}_DISPLAY %X %X\\n",w@c00001d0,w@c00001e0'
            action += f';printf "MK2_{phase.upper()}_DMA %X\\n",w@1a80010'
            action += f";save {phase}_main_ram.bin,1000000,400000;save {phase}_cmos.bin,1400000,20000;save {phase}_palette.bin,1800000,80000"
            if name == "video_irq_ready":
                action += ';printf "MK2_VIDEO_IRQ_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_VIDEO_IRQ_BOUNDARY\\n"'
                action += ";save video_irq_pm.bin,0:dcs:dcs,400;saved video_irq_dm.bin,3800:dcs:dcs,200;saved video_irq_control.bin,3fe0:dcs:dcs,20;save video_irq_external_pm.bin,800:dcs:dcs,800;saved video_irq_external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 28,29;wpset 0:maincpu,ffffffff,r,wpaddr<ff800000,{printf "MK2_STARTUP_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_STARTUP_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            elif name == "startup_ready":
                action += ';printf "MK2_STARTUP_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_STARTUP_BOUNDARY\\n"'
                action += ";save startup_pm.bin,0:dcs:dcs,400;saved startup_dm.bin,3800:dcs:dcs,200;saved startup_control.bin,3fe0:dcs:dcs,20;save startup_external_pm.bin,800:dcs:dcs,800;saved startup_external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 2a,2b;wpset 0:maincpu,ffffffff,r,1,{printf "MK2_DISPATCHER_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_DISPATCHER_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            elif name == "dispatcher_ready":
                action += ';printf "MK2_DISPATCHER_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_DISPATCHER_BOUNDARY\\n"'
                action += ";save dispatcher_pm.bin,0:dcs:dcs,400;saved dispatcher_dm.bin,3800:dcs:dcs,200;saved dispatcher_control.bin,3fe0:dcs:dcs,20;save dispatcher_external_pm.bin,800:dcs:dcs,800;saved dispatcher_external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 2c,2d;wpset 0:maincpu,ffffffff,r,1,{printf "MK2_TASK_RESUME_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_TASK_RESUME_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            elif name == "task_resume_ready":
                action += ';printf "MK2_TASK_RESUME_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_TASK_RESUME_BOUNDARY\\n"'
                action += ';printf "MK2_DCS_CONTROL %X\\n",w@1d00000<<4'
                action += ";save pm.bin,0:dcs:dcs,400;saved dm.bin,3800:dcs:dcs,200;saved control.bin,3fe0:dcs:dcs,20;save external_pm.bin,800:dcs:dcs,800;saved external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 2e,2f;wpset 0:maincpu,ffffffff,r,1,{printf "MK2_TASK_QUEUE_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_TASK_QUEUE_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            elif name == "task_queue_ready":
                action += ';printf "MK2_TASK_QUEUE_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_TASK_QUEUE_BOUNDARY\\n"'
                action += ";save task_queue_pm.bin,0:dcs:dcs,400;saved task_queue_dm.bin,3800:dcs:dcs,200;saved task_queue_control.bin,3fe0:dcs:dcs,20;save task_queue_external_pm.bin,800:dcs:dcs,800;saved task_queue_external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 30,31;wpset 0:maincpu,ffffffff,r,1,{printf "MK2_TASK_PALETTE_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_TASK_PALETTE_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            elif name == "task_palette_ready":
                action += ';printf "MK2_TASK_PALETTE_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_TASK_PALETTE_BOUNDARY\\n"'
                action += ";save task_palette_pm.bin,0:dcs:dcs,400;saved task_palette_dm.bin,3800:dcs:dcs,200;saved task_palette_control.bin,3fe0:dcs:dcs,20;save task_palette_external_pm.bin,800:dcs:dcs,800;saved task_palette_external_dm.bin,0:dcs:dcs,800"
                action += ';wpclear 32,33;wpset 0:maincpu,ffffffff,r,1,{printf "MK2_TASK_DRAW_READ %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g}'
                action += ';wpset 0:maincpu,ffffffff,w,1,{printf "MK2_TASK_DRAW_WRITE %X %X %X %d %d %X\\n",pc,wpaddr,wpdata,totalcycles,wpsize,curpc;g};g'
            else:
                action += ';printf "MK2_TASK_DRAW_DCS_CONTROL %X\\n",w@1d00000<<4;printf "MK2_TASK_DRAW_BOUNDARY\\n"'
                # quit schedules exit; the current CPU slice can still run. End observation here.
                action += ';wpclear'
                action += ";save task_draw_pm.bin,0:dcs:dcs,400;saved task_draw_dm.bin,3800:dcs:dcs,200;saved task_draw_control.bin,3fe0:dcs:dcs,20;save task_draw_external_pm.bin,800:dcs:dcs,800;saved task_draw_external_dm.bin,0:dcs:dcs,800;quit"
        else: action += ";g"
        lines.append(f"bpset {address:x},{POINT_CONDITIONS.get(name, '1')},{{{action}}}")
    fmt = "MK2_TEXT_PIXBLT %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
    lines.append(f'bpset ffa592b0,totalcycles<5c9fb,{{printf "{fmt}",pc,st,totalcycles,' + ",".join(registers) +
                 ';printf "MK2_DSP_TEXT_PIXBLT\\n";symlist :dcs:dcs;g}')
    fmt = "MK2_POST_FACTORY_PIXBLT %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
    lines.append(f'bpset ffa592b0,totalcycles>={379387:x}&&totalcycles<{399321:x},{{printf "{fmt}",pc,st,totalcycles,' + ",".join(registers) +
                 ';printf "MK2_DSP_POST_FACTORY_PIXBLT\\n";symlist :dcs:dcs;g}')
    fmt = "MK2_INPUT_WAIT_PIXBLT %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
    lines.append(f'bpset ffa592b0,totalcycles>={399321:x}&&totalcycles<{400774:x},{{printf "{fmt}",pc,st,totalcycles,' + ",".join(registers) +
                 ';printf "MK2_DSP_INPUT_WAIT_PIXBLT\\n";symlist :dcs:dcs;g}')
    fmt = "MK2_INPUT_POLL_PIXBLT %08X %08X %d " + " ".join(["%08X"] * 31) + "\\n"
    lines.append(f'bpset ffa592b0,totalcycles>{400774:x},{{printf "{fmt}",pc,st,totalcycles,' + ",".join(registers) +
                 ';printf "MK2_DSP_INPUT_POLL_PIXBLT\\n";symlist :dcs:dcs;g}')
    for pc, cycle in DSP_IRQ_HOOKS:
        lines.append(f'bpset {pc:04x}:dcs:dcs,totalcycles=={cycle:x},{{printf "MK2_DSP_BEGIN\\n";symlist :dcs:dcs;printf "MK2_DSP_IRQ1\\n";symlist :dcs:dcs;printf "%X\\n",w@1a80000;g}}')
    lines.append("go")
    script = "\n".join(lines) + "\n"
    (scratch / "reset.cmd").write_text(script, encoding="ascii")
    args = [executable, "mk2", "-noreadconfig", "-nowriteconfig", "-rompath", scratch,
            "-video", "none", "-sound", "none", "-nothrottle", "-skip_gameinfo", "-noplugins",
            "-debug", "-debugger", "windows", "-debuglog", "-debugscript", "reset.cmd",
            "-autoboot_delay", "0", "-autoboot_script", "video.lua",
            "-nvram_directory", scratch / "nvram", "-cfg_directory", scratch / "cfg",
            "-snapshot_directory", scratch / "snap", "-homepath", scratch / "home", "-seconds_to_run", "1"]
    execution = quality.command(args, scratch, timeout=2400, cwd=scratch)
    for line in execution.get("stdout", "").splitlines(): reject_mame_diagnostic(line)
    if not execution["passed"]:
        log = scratch / "debug.log"
        tail = log.read_text(encoding="utf-8")[-5000:] if log.exists() and log.stat().st_size < 262144 else ""
        raise RuntimeError("MAME reference execution failed (timed_out=" + str(execution.get("timed_out")) + "): " +
                           execution.get("stdout", "")[-1000:] + tail)
    log_path, boot_path = scratch / "debug.log", scratch / "boot.bin"
    if not log_path.is_file() or log_path.stat().st_size > REFERENCE_LOG_LIMIT_BYTES:
        raise ValueError("Missing or oversized reference log")
    if not boot_path.is_file() or boot_path.stat().st_size != BOOT_WORDS * 4:
        raise ValueError("Missing or incomplete ADSP boot observation")
    with log_path.open(encoding="utf-8") as stream:
        version = stream.readline().strip()
    with log_path.open(encoding="utf-8") as stream:
        observed = parse_log(stream, factory_opcode)
    boot = boot_path.read_bytes()
    observed["boot_words"] = list(struct.unpack("<376I", boot))
    with log_path.open(encoding="utf-8") as stream:
        observed.update(parse_dsp(stream))
    dma_path = scratch / "sport_dma.bin"
    if not dma_path.is_file() or dma_path.stat().st_size != SPORT_SAMPLES * 32:
        raise ValueError("Incomplete SPORT DMA read tap")
    dma_rows = list(struct.iter_unpack("<QQQQ", dma_path.read_bytes()))
    observed.update(sport_dma_observations(observed.pop("sport_dma_raw"), dma_rows, observed["sport_dma_positions"]))
    task_dma_path = scratch / "task_resume_dma.bin"
    if not task_dma_path.is_file() or task_dma_path.stat().st_size != TASK_RESUME_SAMPLES * 32:
        raise ValueError("Incomplete task-resume SPORT DMA read tap")
    task_dma_rows = list(struct.iter_unpack("<QQQQ", task_dma_path.read_bytes()))
    observed.update(sport_dma_observations(observed.pop("task_resume_dma_raw"), task_dma_rows, observed["task_resume_dma_positions"], phase="task_resume"))
    palette_dma_path = scratch / "task_palette_dma.bin"
    if not palette_dma_path.is_file() or palette_dma_path.stat().st_size != TASK_PALETTE_SAMPLES * 32:
        raise ValueError("Incomplete task-palette SPORT DMA read tap")
    palette_dma_rows = list(struct.iter_unpack("<QQQQ", palette_dma_path.read_bytes()))
    observed.update(sport_dma_observations(observed.pop("task_palette_dma_raw"), palette_dma_rows,
                                         observed["task_palette_dma_positions"], phase="task_palette"))
    for field, filename, count, code in (("cmos", "cmos.bin", 8192, "H"), ("dsp_pm", "pm.bin", 1024, "I"), ("dsp_dm", "dm.bin", 512, "H"),
                                          ("dsp_control", "control.bin", 32, "H"), ("main_ram", "main_ram.bin", 65536, "H"),
                                          ("post_factory_dsp_pm", "post_factory_pm.bin", 1024, "I"),
                                          ("post_factory_dsp_dm", "post_factory_dm.bin", 512, "H"),
                                          ("post_factory_dsp_control", "post_factory_control.bin", 32, "H"),
                                          ("sound_command_dsp_pm", "sound_command_pm.bin", 1024, "I"),
                                          ("sound_command_dsp_dm", "sound_command_dm.bin", 512, "H"),
                                          ("sound_command_dsp_control", "sound_command_control.bin", 32, "H"),
                                          ("input_wait_dsp_pm", "input_wait_pm.bin", 1024, "I"),
                                          ("input_wait_dsp_dm", "input_wait_dm.bin", 512, "H"),
                                          ("input_wait_dsp_control", "input_wait_control.bin", 32, "H"),
                                          ("input_wait_dsp_external_pm", "input_wait_external_pm.bin", 2048, "I"),
                                          ("input_wait_dsp_external_dm", "input_wait_external_dm.bin", 2048, "H"),
                                          ("input_wait_dsp_device", "input_wait_device.bin", len(DCS_DEVICE_FIELDS), "Q"),
                                          ("dsp_external_pm", "external_pm.bin", 2048, "I"),
                                          ("dsp_external_dm", "external_dm.bin", 2048, "H"),
                                          ("dsp_device", "task_resume_ready_device.bin", len(DCS_DEVICE_FIELDS), "Q"),
                                          ("input_poll_dsp_pm", "input_poll_pm.bin", 1024, "I"),
                                          ("input_poll_dsp_dm", "input_poll_dm.bin", 512, "H"),
                                          ("input_poll_dsp_control", "input_poll_control.bin", 32, "H"),
                                          ("input_poll_dsp_external_pm", "input_poll_external_pm.bin", 2048, "I"),
                                          ("input_poll_dsp_external_dm", "input_poll_external_dm.bin", 2048, "H"),
                                          ("input_poll_dsp_device", "input_poll_device.bin", len(DCS_DEVICE_FIELDS), "Q"),
                                          ("video_main_ram", "video_main_ram.bin", 65536, "H"),
                                          ("palette_ram", "palette.bin", 32768, "H"), ("vram", "vram.bin", 524288, "H"),
                                          ("text_main_ram", "text_main_ram.bin", 65536, "H"),
                                          ("text_palette_ram", "text_palette.bin", 32768, "H"), ("text_vram", "text_vram.bin", 524288, "H"),
                                          ("factory_entry_main_ram", "factory_entry_main_ram.bin", 262144, "H"),
                                          ("factory_main_ram", "factory_main_ram.bin", 262144, "H"), ("factory_cmos", "factory_cmos.bin", 8192, "H"),
                                          ("factory_palette_ram", "factory_palette.bin", 32768, "H"), ("factory_vram", "factory_vram.bin", 524288, "H"),
                                          ("post_factory_main_ram", "post_factory_main_ram.bin", 262144, "H"),
                                          ("post_factory_cmos", "post_factory_cmos.bin", 8192, "H"),
                                          ("post_factory_palette_ram", "post_factory_palette.bin", 32768, "H"),
                                          ("post_factory_vram", "post_factory_vram.bin", 524288, "H"),
                                          ("sound_command_main_ram", "sound_command_main_ram.bin", 262144, "H"),
                                          ("sound_command_cmos", "sound_command_cmos.bin", 8192, "H"),
                                          ("sound_command_palette_ram", "sound_command_palette.bin", 32768, "H"),
                                          ("sound_command_vram", "sound_command_vram.bin", 524288, "H"),
                                          ("input_wait_main_ram", "input_wait_main_ram.bin", 262144, "H"),
                                          ("input_wait_cmos", "input_wait_cmos.bin", 8192, "H"),
                                          ("input_wait_palette_ram", "input_wait_palette.bin", 32768, "H"),
                                          ("input_wait_vram", "input_wait_vram.bin", 524288, "H"),
                                          ("input_poll_main_ram", "input_poll_main_ram.bin", 262144, "H"),
                                          ("input_poll_cmos", "input_poll_cmos.bin", 8192, "H"),
                                          ("input_poll_palette_ram", "input_poll_palette.bin", 32768, "H"),
                                          ("input_poll_vram", "input_poll_vram.bin", 524288, "H"),
                                          ("input_idle_main_ram", "input_idle_main_ram.bin", 262144, "H"),
                                          ("input_idle_cmos", "input_idle_cmos.bin", 8192, "H"),
                                          ("input_idle_palette_ram", "input_idle_palette.bin", 32768, "H"),
                                          ("input_idle_vram", "input_idle_vram.bin", 524288, "H"),
                                          ("sport_dac_buffer", "final_dac.bin", SPORT_SAMPLES, "I"),
                                          ("dispatcher_dac_buffer", "final_dac.bin", SPORT_SAMPLES, "I"),
                                          ("dispatcher_irq1_state", "sport_irq_final.bin", 2, "Q"),
                                          ("startup_dac_buffer", "startup_dac.bin", SPORT_SAMPLES, "I"),
                                          ("startup_irq1_state", "startup_irq.bin", 2, "Q"),
                                          ("button_exit_dac_buffer", "sport_dac.bin", SPORT_SAMPLES, "I"),
                                          ("sport_wrap_dac_buffer", "sport_wrap_dac.bin", 480, "I"),
                                          ("sport_wrap_dma_registers", "sport_wrap_dma-registers.bin", 18, "H"),
                                          ("button_exit_dma_registers", "button_exit_dma-registers.bin", 18, "H"),
                                          ("video_irq_dma_registers", "video_irq_dma-registers.bin", 18, "H"),
                                          ("startup_dma_registers", "startup_dma-registers.bin", 18, "H"),
                                          ("dispatcher_dma_registers", "dispatcher_dma-registers.bin", 18, "H"),
                                          ("task_resume_dma_registers", "task_resume_dma-registers.bin", 18, "H"),
                                          ("dispatcher_shiftreg", "dispatcher_shiftreg.bin", 4096, "H"),
                                          ("task_resume_shiftreg", "task_resume_shiftreg.bin", 4096, "H"),
                                          ("task_resume_dac_buffer", "task_resume_dac.bin", SPORT_SAMPLES + TASK_RESUME_SAMPLES, "I"),
                                          ("task_queue_dac_buffer", "task_queue_dac.bin", SPORT_SAMPLES + TASK_RESUME_SAMPLES, "I"),
                                          ("task_palette_dac_buffer", "task_palette_dac.bin", 2880, "I"),
                                          *[("task_draw_dma_" + boundary + "_" + field, "task_draw_dma_" + boundary + "_" + filename + ".bin", count, "H")
                                            for boundary in ("busy", "completed") for field, filename, count in (("vram", "vram", 524288), ("registers", "dma-registers", 18))],
                                          ("task_draw_dac_buffer", "task_draw_dac.bin", 2880, "I"),
                                          ("task_draw_irq1_state", "task_draw_irq.bin", 2, "Q"),
                                          ("task_draw_dma_registers", "task_draw_dma-registers.bin", 18, "H"),
                                          ("task_draw_shiftreg", "task_draw_shiftreg.bin", 4096, "H"),
                                          ("task_queue_irq1_state", "task_queue_irq.bin", 2, "Q"),
                                          ("task_queue_dma_registers", "task_queue_dma-registers.bin", 18, "H"),
                                          ("task_queue_shiftreg", "task_queue_shiftreg.bin", 4096, "H"),
                                          ("task_palette_dma_registers", "task_palette_dma-registers.bin", 18, "H"),
                                          ("task_palette_shiftreg", "task_palette_shiftreg.bin", 4096, "H"),
                                          ("video_irq_dac_buffer", "video_irq_dac.bin", SPORT_SAMPLES, "I"),
                                          *[(point + "_" + field, point + ("_ready_" if point in ("video_irq", "startup", "dispatcher", "task_queue", "task_palette", "task_draw") and filename == "device" else "_") + filename + ".bin", count, code)
                                            for point in ("sport_wrap", *BUTTON_DSP_POINTS, "video_irq", "startup", "dispatcher", "task_queue", "task_palette", "task_draw") for field, filename, count, code in (
                                              ("dsp_pm", "pm", 1024, "I"), ("dsp_dm", "dm", 512, "H"), ("dsp_control", "control", 32, "H"),
                                              ("dsp_external_pm", "external_pm", 2048, "I"), ("dsp_external_dm", "external_dm", 2048, "H"),
                                              ("dsp_device", "device", len(DCS_DEVICE_FIELDS), "Q"))],
                                          *[("input_idle_" + field, "input_idle_" + filename + ".bin", count, code) for field, filename, count, code in (
                                              ("dsp_pm", "pm", 1024, "I"), ("dsp_dm", "dm", 512, "H"), ("dsp_control", "control", 32, "H"),
                                              ("dsp_external_pm", "external_pm", 2048, "I"), ("dsp_external_dm", "external_dm", 2048, "H"),
                                              ("dsp_device", "device", len(DCS_DEVICE_FIELDS), "Q"))],
                                          *[(phase + "_" + field, phase + "_" + filename + ".bin", count, "H")
                                            for phase in ("sport_wrap", "button_exit", "video_irq", "startup", "dispatcher", "task_resume", "task_queue", "task_palette", "task_draw") for field, filename, count in (
                                              ("main_ram", "main_ram", 262144), ("cmos", "cmos", 8192), ("palette_ram", "palette", 32768), ("vram", "vram", 524288))]):
        path = scratch / filename
        size = count * struct.calcsize(code)
        if not path.is_file() or path.stat().st_size != size: raise ValueError("Incomplete " + field)
        observed[field] = list(struct.unpack(f"<{count}{code}", path.read_bytes()))
    latch = scratch / "video-latch.bin"
    if not latch.is_file() or latch.stat().st_size != 2: raise ValueError("Incomplete raw video latch")
    observed["dma_palette"] = struct.unpack("<H", latch.read_bytes())[0]
    text_latch = scratch / "text_video-latch.bin"
    if not text_latch.is_file() or text_latch.stat().st_size != 2: raise ValueError("Incomplete raw text video latch")
    observed["text_dma_palette"] = struct.unpack("<H", text_latch.read_bytes())[0]
    factory_latch = scratch / "factory_video-latch.bin"
    if not factory_latch.is_file() or factory_latch.stat().st_size != 2: raise ValueError("Incomplete raw factory video latch")
    observed["factory_dma_palette"] = struct.unpack("<H", factory_latch.read_bytes())[0]
    post_latch = scratch / "post_factory_video-latch.bin"
    if not post_latch.is_file() or post_latch.stat().st_size != 2: raise ValueError("Incomplete raw post-factory video latch")
    observed["post_factory_dma_palette"] = struct.unpack("<H", post_latch.read_bytes())[0]
    sound_latch = scratch / "sound_command_video-latch.bin"
    if not sound_latch.is_file() or sound_latch.stat().st_size != 2: raise ValueError("Incomplete sound-command video latch")
    observed["sound_command_dma_palette"] = struct.unpack("<H", sound_latch.read_bytes())[0]
    input_latch = scratch / "input_wait_video-latch.bin"
    if not input_latch.is_file() or input_latch.stat().st_size != 2: raise ValueError("Incomplete input-wait video latch")
    observed["input_wait_dma_palette"] = struct.unpack("<H", input_latch.read_bytes())[0]
    poll_latch = scratch / "input_poll_video-latch.bin"
    if not poll_latch.is_file() or poll_latch.stat().st_size != 2: raise ValueError("Incomplete input-poll video latch")
    observed["input_poll_dma_palette"] = struct.unpack("<H", poll_latch.read_bytes())[0]
    idle_latch = scratch / "input_idle_video-latch.bin"
    if not idle_latch.is_file() or idle_latch.stat().st_size != 2: raise ValueError("Incomplete raw idle video latch")
    observed["input_idle_dma_palette"] = struct.unpack("<H", idle_latch.read_bytes())[0]
    wrap_latch = scratch / "sport_wrap_video-latch.bin"
    if not wrap_latch.is_file() or wrap_latch.stat().st_size != 2: raise ValueError("Incomplete SPORT wrap video latch")
    observed["sport_wrap_dma_palette"] = struct.unpack("<H", wrap_latch.read_bytes())[0]
    button_latch = scratch / "button_exit_video-latch.bin"
    if not button_latch.is_file() or button_latch.stat().st_size != 2: raise ValueError("Incomplete button-exit video latch")
    observed["button_exit_dma_palette"] = struct.unpack("<H", button_latch.read_bytes())[0]
    observed["video_irq_dma_palette"] = struct.unpack("<H", (scratch / "video_irq_video-latch.bin").read_bytes())[0]
    startup_latch = scratch / "startup_video-latch.bin"
    if not startup_latch.is_file() or startup_latch.stat().st_size != 2: raise ValueError("Incomplete startup video latch")
    observed["startup_dma_palette"] = struct.unpack("<H", startup_latch.read_bytes())[0]
    task_resume_latch = scratch / "task_resume_video-latch.bin"
    if not task_resume_latch.is_file() or task_resume_latch.stat().st_size != 2: raise ValueError("Incomplete task-resume video latch")
    observed["task_resume_dma_palette"] = struct.unpack("<H", task_resume_latch.read_bytes())[0]
    task_draw_latch = scratch / "task_draw_video-latch.bin"
    if not task_draw_latch.is_file() or task_draw_latch.stat().st_size != 2: raise ValueError("Incomplete task-draw video latch")
    observed["task_draw_dma_palette"] = struct.unpack("<H", task_draw_latch.read_bytes())[0]
    task_palette_latch = scratch / "task_palette_video-latch.bin"
    if not task_palette_latch.is_file() or task_palette_latch.stat().st_size != 2: raise ValueError("Incomplete task-palette video latch")
    observed["task_palette_dma_palette"] = struct.unpack("<H", task_palette_latch.read_bytes())[0]
    task_queue_latch = scratch / "task_queue_video-latch.bin"
    if not task_queue_latch.is_file() or task_queue_latch.stat().st_size != 2: raise ValueError("Incomplete task-queue video latch")
    observed["task_queue_dma_palette"] = struct.unpack("<H", task_queue_latch.read_bytes())[0]
    dispatcher_latch = scratch / "dispatcher_video-latch.bin"
    if not dispatcher_latch.is_file() or dispatcher_latch.stat().st_size != 2: raise ValueError("Incomplete dispatcher video latch")
    observed["dispatcher_dma_palette"] = struct.unpack("<H", dispatcher_latch.read_bytes())[0]
    input_path = scratch / "input_events.bin"
    if not input_path.is_file() or input_path.stat().st_size != 4 * 32: raise ValueError("Incomplete physical input events")
    observed["input_events"] = [list(row) for row in struct.iter_unpack("<4Q", input_path.read_bytes())]
    irq_path = scratch / "sport_irq.bin"
    if not irq_path.is_file() or irq_path.stat().st_size != 80: raise ValueError("Incomplete SPORT IRQ1 observations")
    irq_values = struct.unpack("<10Q", irq_path.read_bytes())
    observed["sport_wrap_irq1_state"] = list(irq_values[:2])
    button_irq_path = scratch / "button_exit_irq.bin"
    if not button_irq_path.is_file() or button_irq_path.stat().st_size != 16: raise ValueError("Incomplete historical button IRQ1 state")
    observed["button_exit_irq1_state"] = list(struct.unpack("<2Q", button_irq_path.read_bytes()))
    video_irq_path = scratch / "video_irq_irq.bin"
    if not video_irq_path.is_file() or video_irq_path.stat().st_size != 16: raise ValueError("Incomplete historical video IRQ1 state")
    observed["video_irq_irq1_state"] = list(struct.unpack("<2Q", video_irq_path.read_bytes()))
    final_irq_path = scratch / "sport_irq_final.bin"
    if not final_irq_path.is_file() or final_irq_path.stat().st_size != 16: raise ValueError("Incomplete final IRQ1 state")
    observed["sport_irq1_state"] = list(struct.unpack("<2Q", final_irq_path.read_bytes()))
    hooks = observed.pop("sport_irq1_hooks")
    if len(hooks) != 10: raise ValueError("Incomplete SPORT IRQ1 instruction hooks")
    observed["sport_irq1_events"] = []
    for index, hook in enumerate(hooks[:2]):
        tick, pc, state, latch = irq_values[2 + index * 4:6 + index * 4]
        if hook[0] != pc or hook[2] != state or latch != 1:
            raise ValueError("SPORT IRQ1 Lua/debugger observations differ")
        observed["sport_irq1_events"].append([tick, pc, hook[1], state])
    task_irq_path = scratch / "task_resume_irq.bin"
    if not task_irq_path.is_file() or task_irq_path.stat().st_size != 208: raise ValueError("Incomplete task-resume SPORT IRQ1 observations")
    task_irq_values = struct.unpack("<26Q", task_irq_path.read_bytes())
    observed["task_resume_irq1_state"] = list(task_irq_values[:2])
    observed["task_resume_irq1_events"] = []
    for index, hook in enumerate(hooks[2:8]):
        tick, pc, state, latch = task_irq_values[2 + index * 4:6 + index * 4]
        if hook[0] != pc or hook[2] != state or latch != 1:
            raise ValueError("Task-resume SPORT IRQ1 Lua/debugger observations differ")
        observed["task_resume_irq1_events"].append([tick, pc, hook[1], state])
    palette_irq_path = scratch / "task_palette_irq.bin"
    if not palette_irq_path.is_file() or palette_irq_path.stat().st_size != 80: raise ValueError("Incomplete task-palette SPORT IRQ1 observations")
    palette_irq_values = struct.unpack("<10Q", palette_irq_path.read_bytes())
    observed["task_palette_irq1_state"] = list(palette_irq_values[:2])
    observed["task_palette_irq1_events"] = []
    for index, hook in enumerate(hooks[8:]):
        tick, pc, state, latch = palette_irq_values[2 + index * 4:6 + index * 4]
        if hook[0] != pc or hook[2] != state or latch != 1:
            raise ValueError("Task-palette SPORT IRQ1 Lua/debugger observations differ")
        observed["task_palette_irq1_events"].append([tick, pc, hook[1], state])
    metadata = {"executable": str(executable), "sha256": quality.sha(executable),
                "version": version, "execution": quality.compact(execution),
                "script_sha256": hashlib.sha256(script.encode("ascii")).hexdigest(),
                "debug_log_sha256": quality.sha(log_path), "debug_log_bytes": log_path.stat().st_size,
                "debug_log_ceiling_bytes": REFERENCE_LOG_LIMIT_BYTES,
                "mame_debugger_and_lua_diagnostic_scan_passed": True,
                "boot_sha256": hashlib.sha256(boot).hexdigest(),
                "boot_bytes_compared": len(boot), "write_pc_convention": "watchpoint after 48-bit MOVE fetch"}
    metadata["dsp_0829_opcode_observations"] = observed["dsp_0829_opcodes"]
    metadata["dsp_0829_opcode_counts"] = {f"{opcode:06x}": sum(word == opcode for _, word in observed["dsp_0829_opcodes"])
                                         for opcode in (0x0d0cb0, 0x806114)}
    metadata["dsp_serial_tx_transport"] = "Every 0829 breakpoint reads the 24-bit PM word through explicit :dcs:dcs.pd@829 with debugger side effects disabled. Only observed 0d0cb0 counts as TX1; observed 806114 is the authenticated bank-reloaded AY0=DM0611 instruction. Missing, duplicate header words and unknown opcodes reject; all 76 instruction fields remain unchanged."
    metadata["historical_button_deadline"] = "Native cancellation guard only; no independent internal MAME deadline readback. Historical controls, IRQ state, physical DAC and event-prefix counts are compared. Full from-reset DSP instruction trace is mandatory for the final gate."
    metadata["task_resume_endpoint"] = {"pc": "ff80dd30", "cycles": TASK_RESUME_CYCLE, "data_bus_events": TASK_RESUME_BUS_COUNT}
    metadata["task_draw_endpoint"] = {"pc": f"{POINTS['task_draw_ready']:08x}", "cycles": TASK_DRAW_CYCLE,
                                      "instructions": 754, "data_bus_events": TASK_DRAW_BUS_COUNT}
    for name in ("raw_bus_events", "authenticated_fetch_lanes", "rom_data_lanes"):
        metadata["task_draw_" + name] = observed["task_draw_" + name]
    metadata["task_draw_read_transport"] = "Every physical aligned data lane remains ordered, including ROM reads; only authenticated instruction/operand fetch lanes at their exact original stage are removed. No native data lane is filtered."
    metadata["task_draw_audio_scope"] = "Historical task_palette audio is frozen independently; the new phase requires present empty PCM, DMA, transfer and IRQ vectors, all2880 physical float32 DAC slots, final device state and cumulative event-prefix counts. Deadline20464570 is a native guard without independent MAME deadline readback."
    for boundary in ("busy", "completed"):
        for field, filename in (("vram", "vram"), ("registers", "dma-registers")):
            path = scratch / ("task_draw_dma_" + boundary + "_" + filename + ".bin")
            metadata["task_draw_dma_" + boundary + "_" + field + "_sha256"] = quality.sha(path)
            metadata["task_draw_dma_" + boundary + "_" + field + "_bytes_compared"] = path.stat().st_size
    metadata["task_draw_graphics_dma"] = observed["task_draw_graphics_dma"]
    metadata["task_draw_graphics_dma_scope"] = "Original4bpp C382 sprite256x19: busy command/INTPEND observations at1259256 and1260496, followed by4382/INT1=2 at1260517. Completion is independently bracketed by instruction boundaries; the internal MAME timer deadline is not read. All rawVRAM and18 physical registers compare independently. Final native graphics deadline0 is a separate native guard."
    metadata["task_draw_dac_sha256"] = quality.sha(scratch / "task_draw_dac.bin")
    metadata["task_draw_dac_bytes_compared"] = 2880 * 4
    metadata["task_draw_irq1_sha256"] = quality.sha(scratch / "task_draw_irq.bin")
    metadata["task_palette_endpoint"] = {"pc": "ff816a30", "cycles": TASK_PALETTE_CYCLE,
                                         "instructions": 21971, "data_bus_events": TASK_PALETTE_BUS_COUNT}
    for name in ("raw_bus_events", "authenticated_fetch_lanes", "rom_data_lanes"):
        metadata["task_palette_" + name] = observed["task_palette_" + name]
    metadata["task_palette_read_transport"] = "Every physical aligned data lane, including ROM reads, remains ordered; only authenticated opcode/operand words at exact original fetch stages are removed from MAME transport. No native data lane is filtered."
    metadata["task_queue_endpoint"] = {"pc": "ff80dd30", "cycles": TASK_QUEUE_CYCLE,
                                       "instructions": 3342, "data_bus_events": TASK_QUEUE_BUS_COUNT}
    for name in ("raw_bus_events", "authenticated_fetch_lanes", "rom_data_lanes"):
        metadata["task_queue_" + name] = observed["task_queue_" + name]
    metadata["task_queue_read_transport"] = "Every physical aligned read/write, including ROM data, is preserved in order. Only exact authenticated opcode words at the original fetch stages are removed from MAME transport; no native data lane is filtered."
    metadata["task_palette_audio_scope"] = "Two independently measured callbacks at ticks18928570/19696570 add480 PCM/DMA samples, with exact PC/CURPC/cached cycles. IRQ1 on/off at PCs132/130 retains619327/619328. All2880 physical float32 DAC slots compare independently, with enabled1/bufin2160/bufout2015; slots are not a concatenation of PCM packets. Deadline20464570 is a native schedule guard without independent internal MAME deadline readback."
    metadata["task_palette_pcm_samples_compared"] = TASK_PALETTE_SAMPLES
    metadata["task_palette_pcm_sha256"] = hashlib.sha256(struct.pack(f"<{TASK_PALETTE_SAMPLES}h", *observed["task_palette_pcm"])).hexdigest()
    metadata["task_palette_pcm_nonzero"] = sum(sample != 0 for sample in observed["task_palette_pcm"])
    metadata["task_palette_dma_sha256"] = quality.sha(palette_dma_path)
    metadata["task_palette_irq1_sha256"] = quality.sha(palette_irq_path)
    metadata["task_palette_dac_sha256"] = quality.sha(scratch / "task_palette_dac.bin")
    metadata["task_palette_dac_bytes_compared"] = 2880 * 4
    metadata["task_queue_audio_scope"] = "The endpoint Lua tap retains 2400 historical DMA reads and eight historical IRQ observations, with DAC enabled=1, bufin=1680, bufout=1440. All 2400 physical float32 DAC slots and complete DSP/device images compare again. New PCM/DMA/transfers/IRQ vectors are explicitly empty. Native deadline18928570 remains a schedule guard without independent MAME deadline readback."
    metadata["task_resume_deadline"] = "Native next SPORT guard18928570 is derived from the original schedule; no independent internal MAME deadline readback. Seven actual callback packets, IRQ1 pairs, complete DSP state and physical DAC slots/cursors compare independently."
    for name in ("raw_bus_events", "authenticated_fetch_lanes", "rom_data_lanes"):
        metadata["task_resume_" + name] = observed["task_resume_" + name]
    metadata["task_resume_read_transport"] = "All physical aligned reads and writes including ROM; exact authenticated instruction words, opcode lengths and fetch stages exclude only instruction fetch lanes. No native lane is filtered."
    metadata["task_resume_irq_bus_clock"] = "Asynchronous interrupt entry precedes the next debugger instruction hook. Its six bus lanes retain the preceding hook's CURPC and cached totalcycles (for example913952); the actual guest clock (913982 before entry),16-cycle entry and checkpoint cycles are unchanged. Lane timestamps are debugger observations, not a measurement of physical per-lane microcycles."
    metadata["dispatcher_raw_bus_events"] = observed["dispatcher_raw_bus_events"]
    metadata["dispatcher_authenticated_fetch_lanes"] = observed["dispatcher_authenticated_fetch_lanes"]
    metadata["dispatcher_rom_data_lanes"] = observed["dispatcher_rom_data_lanes"]
    metadata["dispatcher_read_transport"] = "All physical aligned reads, including executable ROM; excluded instruction lanes require authenticated opcode length, exact ROM word and fetched-PC stage. CALL stack pushes occur before parameter fetch; every remaining data lane compares in order."
    metadata["dispatcher_endpoint"] = {"pc": "ff80dd30", "cycles": DISPATCHER_CYCLE, "data_bus_events": DISPATCHER_BUS_COUNT}
    metadata["startup_endpoint"] = {"pc": "ff811710", "cycles": STARTUP_CYCLE, "data_bus_events": STARTUP_BUS_COUNT}
    metadata["historical_video_irq_deadline"] = "Native prior deadline guard13552570 only; MAME internal deadline has no independent readback. All six historical DSP images, controls, IRQ1, DAC720 and event counts are mandatory."
    metadata["startup_read_transport"] = "Physical data reads below ff800000 with authenticated opcode provenance and every aligned lane. Original ranking135 low-byte checksum and stored LE checksum compare equal; normal service-DIP branch and nonempty task allocation execute. Stops before dispatcher CALL ff80dae0. No repair branch is qualified by this stage."
    metadata["video_irq_endpoint"] = {"pc": "ff8114d0", "cycles": VIDEO_IRQ_CYCLE, "data_bus_events": VIDEO_IRQ_BUS_COUNT}
    metadata["cmos_sha256"] = quality.sha(scratch / "cmos.bin")
    metadata["cmos_bytes_compared"] = 16384
    metadata["cmos_write_pc_convention"] = "48-bit absolute MOVB enable; 16-bit indirect MOVB data; read-modify-write read before data write"
    metadata["inactive_dsp_cycles"] = "Excluded from concurrent snapshots: debugger caches the previous hook; all instruction trace cycles compared exactly."
    metadata["board_write_width"] = "wpsize=16 bits; aligned original WFIELD16 writes imply mem_mask=ffff."
    metadata["board_write_pc_convention"] = "16-bit indirect MOVE loop; 48-bit absolute MOVE elsewhere."
    metadata["board_readbacks"] = "IO indices 0..27 and DMA command; excludes dynamic IO indices 28..31. INTPEND is the original read interface. T-unit video control is write-only; its latch and derived banks are not independently read back."
    metadata["powerup_write_transport"] = "Original 32-bit writes are paired only from consecutive low/high 16-bit bus events with equal PC/cycle and adjacent addresses; every lane is validated."
    metadata["cleared_ram_bytes_compared"] = 131072
    metadata["cleared_ram_range_bits"] = {"start": 0x01000000, "end_exclusive": 0x01100000}
    metadata["transient_debug_log_limit_bytes"] = REFERENCE_LOG_LIMIT_BYTES
    metadata["dsp_instruction_transport"] = "All 76 symbols through explicit-device symlist, avoiding the debugger visible-CPU context; indispensable transient log is removed before capture returns."
    metadata["raw_video_transport"] = "Read-only Lua saved-item reads at DMA debugger reads in PCs ffa5a190, ffa5a2e0, ffa5a340, ffa5ac90, ffa5acc0, ffa592b0, successive historical endpoint reads at ffa5aef0 for cycles407967/460021/506023 and finalff815090/c780256. Preserves historical video and latch images."
    metadata["video_script_sha256"] = hashlib.sha256(video_script.encode("ascii")).hexdigest()
    metadata["raw_vram_sha256"] = quality.sha(scratch / "vram.bin")
    metadata["raw_vram_bytes_compared"] = 1048576
    metadata["palette_bytes_compared"] = 65536
    metadata["video_main_ram_bytes_compared"] = 131072
    metadata["video_write_transport"] = "One main-CPU bus observer; 32-bit CPU VRAM writes require consecutive, same-PC/cycle, adjacent low/high 16-bit lanes. No event deduplication."
    metadata["glyph_checkpoint_transport"] = "First/last fixed glyph checkpoints are the identical observed P=0, A0=ffa401c8/ffa40220 records from the single all-entry PIXBLT CPU/ADSP hook."
    metadata["text_raw_vram_sha256"] = quality.sha(scratch / "text_vram.bin")
    metadata["text_raw_vram_bytes_compared"] = 1048576
    metadata["text_read_transport"] = "Physical aligned word reads in main RAM/CMOS/IO below ff800000, string ffa401c0..ffa40220 and glyph tables/descriptors/bitmaps ffa56000..ffa58fff. Instruction/operand fetches are outside this data-read scope."
    metadata["text_bus_cycles"] = "Debugger totalcycles caches the instruction-hook boundary, including every MMTM/MMFM word; native records that same boundary, with original instruction costs charged separately."
    metadata["text_bus_width"] = "All observations are physical aligned 16-bit words, including neighboring bits fetched by MOVB and both lanes of original 32-bit operations; no lane or byte is discarded."
    metadata["factory_bus_transport"] = "CURPC is observed directly as original instruction provenance. The separately observed post-fetch PC is checked exactly against the opcode in the authenticated L3.1 program image, including CALL push-before-parameter behavior; unknown opcode classes fail. CURPC is never replaced by post-fetch PC. All raw word reads/writes, including CMOS and enable-gate RMW reads, retain interleaved order and cached instruction-hook cycles."
    metadata["factory_opcode_image_sha256"] = hashlib.sha256(factory_program).hexdigest()
    metadata["factory_read_transport"] = "Physical data reads below ff800000, revision string ffa401c0..ffa40220, defaults ffa4cf20..ffa4d29f and ranking data ffa28730..ffa28ccf. Instruction/operand fetches are outside this read scope."
    metadata["factory_entry_main_ram_bytes_compared"] = 524288
    metadata["factory_main_ram_bytes_compared"] = 524288
    metadata["factory_cmos_bytes_compared"] = 16384
    metadata["factory_cmos_sha256"] = quality.sha(scratch / "factory_cmos.bin")
    metadata["factory_raw_vram_bytes_compared"] = 1048576
    metadata["factory_raw_vram_sha256"] = quality.sha(scratch / "factory_vram.bin")
    metadata["post_factory_read_transport"] = "Physical data reads below ff800000, revision string ffa401c0..ffa40220, font tables/descriptors/bitmaps ffa56000..ffa58fff, and messages ffa6a6c0..ffa6a75f and ffa6a8b0..ffa6a9ff; instruction and operand fetches excluded. Source CURPC and exact authenticated opcode fetch validation use the same transport as factory."
    metadata["post_factory_pixblt_transport"] = "Every initial entry and P-flag restart at original PIXBLT PC ffa592b0 has all 31 CPU registers and 76 concurrent ADSP fields."
    for key in ("pm", "dm", "control"):
        path = scratch / ("post_factory_" + key + ".bin")
        metadata["post_factory_dsp_" + key + "_sha256"] = quality.sha(path)
        metadata["post_factory_dsp_" + key + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("post_factory_" + filename + ".bin")
        metadata["post_factory_" + key + "_sha256"] = quality.sha(path)
        metadata["post_factory_" + key + "_bytes_compared"] = path.stat().st_size
    metadata["sound_command_read_transport"] = "Physical data reads below ff800000; instruction and operand fetches excluded. CURPC, exact authenticated opcode fetch and interleaved cached-cycle observations use the same transport as factory."
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("sound_command_" + filename + ".bin")
        metadata["sound_command_" + key + "_sha256"] = quality.sha(path)
        metadata["sound_command_" + key + "_bytes_compared"] = path.stat().st_size
    metadata["input_wait_read_transport"] = "Physical data reads below ff800000, font tables/descriptors/bitmaps ffa56000..ffa58fff, and original prompt ffa6a760..ffa6a8af. Only the first two glyphs execute; the third glyph is an explicit pre-instruction checkpoint. Instruction/operand fetches excluded. No input handling or wait shortening."
    metadata["input_wait_pixblt_transport"] = "Every initial entry and P-flag restart at original PIXBLT PC ffa592b0 compares all 31 CPU registers and 76 concurrent ADSP fields."
    for key in ("pm", "dm", "control"):
        path = scratch / ("sound_command_" + key + ".bin")
        metadata["sound_command_dsp_" + key + "_sha256"] = quality.sha(path)
        metadata["sound_command_dsp_" + key + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("input_wait_" + filename + ".bin")
        metadata["input_wait_" + key + "_sha256"] = quality.sha(path)
        metadata["input_wait_" + key + "_bytes_compared"] = path.stat().st_size
    metadata["input_poll_read_transport"] = "Continuation from the third initial PIXBLT entry, preserving aligned physical data reads below ff800000, font tables/descriptors/bitmaps ffa56000..ffa58fff and original prompt ffa6a760..ffa6a8af. Includes both lanes of IN0/IN2 reads and the original unmapped write; no input injection."
    metadata["dsp_bus_transport"] = "All logical DM reads/writes and PM CPU writes, plus PM data reads at CURPC38/834/83a/840/846/84c/852 with address I5. PM instruction fetches excluded; direct boot copies are memory reloads, not CPU write events. Values use the watchpoint data; CURPC/cycles come from explicit ADSP symlist."
    metadata["input_poll_pixblt_transport"] = "The old input_wait endpoint at cycle 400774 is also the initial third-glyph PIXBLT observation in the same breakpoint action. Later initial entries and P-flag resumptions use one hook with cycles>400774; each has all 31 CPU registers and 76 concurrent ADSP fields."
    metadata["dsp_core_reset_transport"] = "The trace compares raw per-core totalcycles before SYSCONTROL 0208 and from zero after the deferred bank 1 reboot; the host scheduler clock remains monotonic. No offset is added to the observed core clock."
    metadata["signed_adsp_symbols"] = "Parser preserves all observed 64-bit symbol values without normalization. The native observation adapter applies the pinned device_state_entry value widths: MR2/SE low 8 bits, SB low 5 bits, both banks, while core 16-bit arithmetic storage remains intact. DAG modifier symbols use their original 14-bit representation."
    metadata["dcs_device_fields"] = list(DCS_DEVICE_FIELDS)
    metadata["task_resume_sport_transport"] = "Seven independently observed 240-sample packets after DCS reset:1680 PCM/DMA samples with exact Lua/watchpoint tick, current PC, previous CURPC, cached cycle, address and value. Historical720 samples remain independent. Physical DAC slots0..2399 compare in full; reset restarts device cursors (bufin1680/bufout1440), so these slots are not a concatenation of historical and new packets."
    metadata["task_resume_pcm_bytes_compared"] = TASK_RESUME_SAMPLES * 2
    metadata["task_resume_dac_bytes_compared"] = (SPORT_SAMPLES + TASK_RESUME_SAMPLES) * 4
    metadata["task_resume_pcm_sha256"] = hashlib.sha256(struct.pack(f"<{TASK_RESUME_SAMPLES}h", *observed["task_resume_pcm"])).hexdigest()
    metadata["task_resume_dac_sha256"] = quality.sha(scratch / "task_resume_dac.bin")
    metadata["task_resume_dma_sha256"] = quality.sha(task_dma_path)
    metadata["task_resume_irq1_sha256"] = quality.sha(task_irq_path)
    metadata["sport_pcm_transport"] = "Three 240-sample signed PCM packets and all720 physical final DAC float32 values compare in full, independently of queue pointers and the preserved480-value historical sport_wrap DAC image. Reset/disable does not erase historical PCM observations. No PCM file is retained."
    metadata["sport_dma_transport"] = "Three separate240-word DMA packets retain CPU insertion positions. Independent Lua taps compare tick/currentPC/address/value; debugger snapshots retain previousCURPC/cachedcycles138/81726,130/158526,136/235326. Instruction trace cycles remain exact."
    metadata["sport_irq1_transport"] = "Independent read-only Lua saved-item taps at original instruction hooks observe assert tick7993490/PC131 and clear tick7993500/PC132; all debugger core cycles, levels and final latch compare exactly. IMASK20 masks IRQ1; no ISR executes."
    metadata["sport_irq1_sha256"] = quality.sha(irq_path)
    metadata["sport_dma_sha256"] = quality.sha(dma_path)
    metadata["sport_pcm_sha256"] = hashlib.sha256(struct.pack(f"<{SPORT_SAMPLES}h", *observed["sport_pcm"])).hexdigest()
    metadata["sport_pcm_bytes_compared"] = SPORT_SAMPLES * 2
    metadata["sport_dac_bytes_compared"] = SPORT_SAMPLES * 4
    metadata["sport_dac_sha256"] = quality.sha(scratch / "sport_dac.bin")
    metadata["sport_dac_source_sha256"] = quality.sha(quality.ROOT / "docs/investigation/decoder-research/upstream/dmadac.h")
    metadata["symbol_value_source_sha256"] = quality.sha(quality.ROOT / "docs/investigation/decoder-research/upstream/distate.cpp")
    metadata["sport_dac_source"] = "https://github.com/mamedev/mame/blob/4f9dcc832cc0089de2451696320f671e87da79f4/src/devices/sound/dmadac.h"
    for field, filename in (("dsp_external_pm", "external_pm"), ("dsp_external_dm", "external_dm"),
                            ("dsp_device", "task_resume_ready_device"),
                            *[(point + "_" + field, point + ("_ready_" if point in ("video_irq", "startup", "dispatcher") and filename == "device" else "_") + filename)
                              for point in ("sport_wrap", *BUTTON_DSP_POINTS, "video_irq", "startup", "dispatcher") for field, filename in (
                                  ("dsp_pm", "pm"), ("dsp_dm", "dm"), ("dsp_control", "control"),
                                  ("dsp_external_pm", "external_pm"), ("dsp_external_dm", "external_dm"), ("dsp_device", "device"))],
                            *[("input_idle_" + field, "input_idle_" + name) for field, name in (("dsp_pm", "pm"), ("dsp_dm", "dm"), ("dsp_control", "control"), ("dsp_external_pm", "external_pm"), ("dsp_external_dm", "external_dm"), ("dsp_device", "device"))], ("input_poll_dsp_pm", "input_poll_pm"),
                            ("input_poll_dsp_dm", "input_poll_dm"), ("input_poll_dsp_control", "input_poll_control"),
                            ("input_poll_dsp_external_pm", "input_poll_external_pm"),
                            ("input_poll_dsp_external_dm", "input_poll_external_dm"),
                            ("input_poll_dsp_device", "input_poll_device"), ("input_wait_dsp_pm", "input_wait_pm"),
                            ("input_wait_dsp_dm", "input_wait_dm"), ("input_wait_dsp_control", "input_wait_control"),
                            ("input_wait_dsp_external_pm", "input_wait_external_pm"),
                            ("input_wait_dsp_external_dm", "input_wait_external_dm"),
                            ("input_wait_dsp_device", "input_wait_device")):
        path = scratch / (filename + ".bin")
        metadata[field + "_sha256"] = quality.sha(path)
        metadata[field + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("input_poll_" + filename + ".bin")
        metadata["input_poll_" + key + "_sha256"] = quality.sha(path)
        metadata["input_poll_" + key + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("input_idle_" + filename + ".bin")
        metadata["input_idle_" + key + "_sha256"] = quality.sha(path)
        metadata["input_idle_" + key + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("sport_wrap_" + filename + ".bin")
        metadata["sport_wrap_" + key + "_sha256"] = quality.sha(path)
        metadata["sport_wrap_" + key + "_bytes_compared"] = path.stat().st_size
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("raw_vram", "vram")):
        path = scratch / ("button_exit_" + filename + ".bin")
        metadata["button_exit_" + key + "_sha256"] = quality.sha(path)
        metadata["button_exit_" + key + "_bytes_compared"] = path.stat().st_size
    metadata["input_events_sha256"] = quality.sha(input_path)
    metadata["input_transport"] = "Original P1HighPunch IN0mask0010 active-low ioport_field:set_value(1/0) requests8096368/9140064; MAME frame_update applies at ticks9139625/10967550. Independent frame notifier reads actual port; CPU bus compares realffef low lane and unchanged IN1 high lane. No RAM,PC or read-tap return replacement."
    metadata["button_exit_read_transport"] = "All physical aligned data words belowff800000 plus original IO tableff815c50..ff815e0f; instruction/operand fetches excluded. Authenticated fetchedPC/CURPC opcode validation, order and cached cycles preserved."
    metadata["sport_wrap_dac_sha256"] = quality.sha(scratch / "sport_wrap_dac.bin")
    metadata["sport_irq1_final_sha256"] = quality.sha(final_irq_path)
    for key, filename in (("main_ram", "main_ram"), ("cmos", "cmos"), ("palette_ram", "palette"), ("vram", "vram"),
                          ("dsp_pm", "pm"), ("dsp_dm", "dm"), ("dsp_control", "control"),
                          ("dsp_external_pm", "external_pm"), ("dsp_external_dm", "external_dm"),
                          ("dsp_device", "ready_device"), ("shiftreg", "shiftreg")):
        for phase in ("task_palette", "task_draw"):
            path = scratch / (phase + "_" + filename + ".bin")
            metadata[phase + "_" + key + "_sha256"] = quality.sha(path)
            metadata[phase + "_" + key + "_bytes_compared"] = path.stat().st_size
    for phase in ("sport_wrap", "button_exit", "video_irq", "startup", "dispatcher", "task_resume", "task_palette", "task_draw"):
        metadata[phase + "_dma_registers_sha256"] = quality.sha(scratch / (phase + "_dma-registers.bin"))
        metadata[phase + "_dma_registers_words_compared"] = 18
    for phase in ("dispatcher", "task_resume"):
        path = scratch / (phase + "_shiftreg.bin")
        metadata[phase + "_shiftreg_sha256"] = quality.sha(path)
        metadata[phase + "_shiftreg_bytes_compared"] = path.stat().st_size
    return observed, metadata
