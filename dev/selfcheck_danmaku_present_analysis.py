"""Offline tests for final-display PresentMon analysis; no GUI or ETW required."""
import copy
import csv
import json
import subprocess
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev.benchmarks.analyze_danmaku_present import analyze, analyze_dxgi, compare_resources, sha256
from dev.benchmarks.benchmark_video_danmaku_render import (
    DisplayStatisticsRecorder, ResourceSampler, benchmark_window_state, build_report,
    counter_delta, drop_stage_counters, input_plan, input_plan_summary, memory_trend,
    planned_offer, report_paths, stats, verify_abba_reports)


class PresentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.csv = Path(self.temp.name) / "capture.csv"
        self.metadata = Path(self.temp.name) / "capture.json"
        self.evidence = {"screen_hz": 60, "display_mode_changed_during_capture": False,
                         "warmup_seconds": 10, "capture_seconds": 120, "wall_seconds": 120,
                         "final_display_capture_boundary_status": "raw_qpc_pending_analysis",
                         "capture_qpc": {"frequency": 60000000, "warmup_start": 60000000,
                                         "start": 660000000, "end": 7860000000},
                         "presentmon_readiness": {"status": "observed", "process_id": 42,
                                                  "observed_qpc": 59000000, "row_cpu_start_qpc": 58000000},
                         "swapchain_attribution": {"address": "0x123", "process_id": 42,
                                                   "evidence": "Independent overlay address"}}

    def write(self, durations, metric="DisplayedTime", extra=()):
        with self.csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("ProcessID", "SwapChainAddress", metric, "VidPnSourceId", "LayerIndex", "Dropped", "CPUStartQPC", "DisplayLatency"))
            writer.writerow((42, "0x999", 16, 1, 0, 0, 58000000, 0))
            position = 660000000
            for duration in durations:
                writer.writerow((42, "0x123", duration, 1, 0, 0, round(position), 0))
                if isinstance(duration, (int, float)):
                    position += duration * 60000
            writer.writerows(extra)
        self.evidence["csv_sha256"] = sha256(self.csv)
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")

    def report(self):
        return analyze(self.csv, self.metadata, 60, "0x123", 42)

    def test_formal_display_duration_pass_and_hash_binding(self):
        self.evidence["swapchain_attribution"]["address"] = 291
        self.write([1000 / 60] * 7200)
        report = analyze(self.csv, self.metadata, 60, "0x00000123", 42)
        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["criteria_met"])
        self.assertEqual(report["raw_csv_sha256"], sha256(self.csv))
        self.assertEqual(report["metadata_sha256"], sha256(self.metadata))

    def test_thresholds_and_long_stall_fail_even_if_p99_passes(self):
        self.write([51] + [1000 / 60] * 7200)
        report = self.report()
        self.assertLess(report["p99_ms"], 1.25 * 1000 / 60)
        self.assertEqual(report["over_3T_count"], 1)
        self.assertEqual(report["status"], "fail")
        self.write([26] * 8 + [1000 / 60] * 7200)
        self.assertEqual(self.report()["status"], "fail")
        self.write([21] * 7200)
        self.assertEqual(self.report()["status"], "fail")

    def test_v1_display_field_and_exact_process_swapchain_filter(self):
        self.write([1000 / 60] * 7200, "MsBetweenDisplayChange",
                   [(42, "0x456", 200, 1, 0, 0), (43, "0x123", 200, 1, 0, 0),
                    (42, "0x123", 200, 1, 0, 1), (42, "0x123", "NA", 1, 0, 0)])
        report = self.report()
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["displayed_intervals"], 7200)
        self.assertEqual(report["discarded_rows"], 2)

    def test_invalid_rate_and_duration_are_rejected(self):
        for hz, seconds in ((0, 120), (float("nan"), 120), (60, -1), (60, float("inf"))):
            with self.assertRaises(ValueError):
                analyze(self.csv, self.metadata, hz, "0x123", 42, seconds)

    def test_present_cadence_never_substitutes_for_display_field(self):
        self.write([16] * 7200, "FrameTime")
        with self.assertRaises(ValueError):
            self.report()

    def test_missing_attribution_wrong_refresh_short_capture_are_unverified(self):
        self.evidence["swapchain_attribution"] = {}
        self.evidence["screen_hz"] = 144
        self.write([1000 / 60] * 30)
        report = self.report()
        self.assertEqual(report["status"], "unverified")
        self.assertGreaterEqual(len(report["unverified_reasons"]), 3)

    def test_multi_display_and_csv_hash_mismatch_are_unverified(self):
        self.write([1000 / 60] * 7200, extra=[(42, "0x123", 16, 2, 0, 0, 660000000, 0)])
        self.assertEqual(self.report()["status"], "unverified")
        with self.csv.open("a", encoding="utf-8") as handle:
            handle.write("42,0x123,16,1,0,0\n")
        self.assertIn("CSV hash is missing or differs from capture metadata", self.report()["unverified_reasons"])

    def test_missing_hash_and_114_seconds_cannot_pass(self):
        self.write([1000 / 60] * 6840)
        self.assertEqual(self.report()["status"], "unverified")
        self.write([1000 / 60] * 7200)
        del self.evidence["csv_sha256"]
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
        self.assertEqual(self.report()["status"], "unverified")

    def test_warmup_measured_window_and_display_boundaries_are_required(self):
        for key, value in (("warmup_seconds", 2), ("wall_seconds", 119),
                           ("capture_seconds", 119), ("presentmon_readiness", {})):
            original = self.evidence[key]
            self.evidence[key] = value
            self.write([1000 / 60] * 7200)
            self.assertEqual(self.report()["status"], "unverified", key)
            self.evidence[key] = original

    def test_raw_qpc_boundaries_cannot_be_self_attested(self):
        self.evidence["final_display_capture_boundary_status"] = "verified"
        self.evidence.pop("capture_qpc")
        self.write([1000 / 60] * 7200)
        self.assertEqual(self.report()["status"], "unverified")

    def test_raw_qpc_gap_missing_tail_and_readiness_are_unverified(self):
        self.write([1000 / 60] * 7200)
        with self.csv.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        for omitted in (1, 4000, len(rows) - 1):
            with self.csv.open("w", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(row for index, row in enumerate(rows) if index != omitted)
            self.evidence["csv_sha256"] = sha256(self.csv)
            self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
            self.assertEqual(self.report()["status"], "unverified", omitted)

    def test_frames_after_window_do_not_affect_thresholds(self):
        self.write([1000 / 60] * 7200 + [1000])
        self.assertEqual(self.report()["status"], "pass")
        self.assertEqual(self.report()["over_3T_count"], 0)

    def test_boundary_stall_keeps_full_duration_for_threshold(self):
        self.write([51] + [1000 / 60] * 7200)
        self.evidence["capture_qpc"]["start"] += 60000 * 50
        self.evidence["capture_qpc"]["end"] += 60000 * 50
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
        self.assertEqual(self.report()["status"], "fail")
        self.assertEqual(self.report()["max_ms"], 51)

    def test_missing_display_latency_and_qpc_cannot_pass(self):
        self.write([1000 / 60] * 7200)
        original = self.csv.read_text(encoding="utf-8")
        for name in ("CPUStartQPC", "DisplayLatency"):
            self.csv.write_text(original.replace(name, "Unknown"), encoding="utf-8")
            self.evidence["csv_sha256"] = sha256(self.csv)
            self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
            self.assertEqual(self.report()["status"], "unverified")

    def test_external_csv_binding_preserves_original_metadata(self):
        self.evidence["external_presentmon_csv"] = True
        self.write([1000 / 60] * 7200)
        self.evidence.pop("csv_sha256")
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
        original_hash = sha256(self.metadata)
        bound = self.metadata.with_name("bound.json")
        command = [sys.executable, str(Path(__file__).parent / "benchmarks/analyze_danmaku_present.py"),
                   str(self.csv), "--metadata", str(self.metadata), "--bind-external-csv", str(bound),
                   "--hz", "60", "--process-id", "42", "--swapchain", "0x123"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sha256(self.metadata), original_hash)
        evidence = json.loads(bound.read_text(encoding="utf-8"))
        self.assertEqual(evidence["original_metadata_sha256"], original_hash)
        self.assertEqual(evidence["csv_sha256"], sha256(self.csv))
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 2)

    def test_nonfinite_metadata_is_not_evidence(self):
        for key in ("warmup_seconds", "wall_seconds", "capture_seconds", "screen_hz"):
            original = self.evidence[key]
            self.evidence[key] = float("nan")
            self.write([1000 / 60] * 7200)
            self.assertEqual(self.report()["status"], "unverified", key)
            self.evidence[key] = original


class DxgiStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name) / "display.jsonl"
        self.metadata = Path(self.temp.name) / "metadata.json"
        self.evidence = {"pid": 42, "screen_hz": 60, "display_mode_changed_during_capture": False,
                         "capture_seconds": 120, "wall_seconds": 120, "warmup_seconds": 10,
                         "capture_qpc": {"frequency": 60000000, "warmup_start": 60000000,
                                         "start": 660000000, "end": 7860000000},
                         "display_statistics_status": "observed", "display_statistics_errors": [],
                         "display_statistics_lost_count": 0,
                         "native_binary": {"path": "loaded/native.pyd", "sha256": "a" * 64},
                         "swapchain_attribution": {"address": "0x123", "process_id": 42, "evidence": "native host"}}
        self.records = []
        for index in range(7204):
            offset = 5 + index % 2
            display = 659000000 + index * 1000000
            self.records.append({"record_sequence": index + 1, "observed_qpc": display + offset * 1000000 + 1000,
                                 "hresult": 0, "present_count": 100 + index,
                                 "present_refresh_count": 1000 + index, "sync_refresh_count": 1000 + index + offset,
                                 "sync_qpc": display + offset * 1000000, "last_present_count": 900000 + index,
                                 "phase": "permit", "moving": True, "active_count": 80, "frame_kind": "content",
                                 "swap_chain_address": 291, "hwnd": 1234})

    def write(self, records=None, lost=0):
        records = self.records if records is None else records
        page = {"process_id": 42, "qpc_frequency": 60000000, "swap_chain_address": 291,
                "samples": records, "lost_count": lost}
        self.raw.write_text(json.dumps(page) + "\n", encoding="utf-8")
        self.evidence["display_statistics_sha256"] = sha256(self.raw)
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")

    def report(self):
        return analyze_dxgi(self.raw, self.metadata, 60, "0x123", 42)

    def test_sync_anchor_is_corrected_by_refresh_delta_not_used_as_display_time(self):
        self.write()
        report = self.report()
        self.assertEqual(report["status"], "pass", report["unverified_reasons"])
        self.assertEqual(report["displayed_intervals"], 7200)
        self.assertAlmostEqual(report["displayed_seconds"], 120)
        self.assertAlmostEqual(report["max_ms"], 1000 / 60)

    def test_duplicate_present_count_allows_new_sync_anchor_but_detects_conflict(self):
        duplicate = dict(self.records[100])
        duplicate["sync_refresh_count"] += 1
        duplicate["sync_qpc"] += 1000000
        duplicate["observed_qpc"] += 1000000
        records = self.records[:101] + [duplicate] + self.records[101:]
        for index, sample in enumerate(records):
            sample["record_sequence"] = index + 1
        self.write(records)
        self.assertEqual(self.report()["status"], "pass")
        self.assertEqual(self.report()["duplicate_count"], 1)
        duplicate["present_refresh_count"] += 1
        self.write(records)
        self.assertEqual(self.report()["status"], "unverified")
        self.assertEqual(self.report()["duplicate_conflict_count"], 1)

    def test_missing_present_id_is_observed_gap_not_a_fabricated_long_frame(self):
        records = self.records[:400] + self.records[401:]
        for index, sample in enumerate(records):
            sample["record_sequence"] = index + 1
        self.write(records)
        report = self.report()
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["observed_present_gap_count"], 1)
        self.assertAlmostEqual(report["observed_present_gaps"][0]["observed_gap_ms"], 2 * 1000 / 60)
        self.assertEqual(report["over_1_5T_count"], 0)
        self.assertEqual(report["displayed_seconds"], 0)

    def test_disjoint_zero_motion_clear_and_foreign_chain_are_unverified(self):
        for field, value in (("hresult", 0x887A000B), ("present_count", 0), ("sync_qpc", 0),
                             ("moving", False), ("frame_kind", "clear"), ("swap_chain_address", 999)):
            records = copy.deepcopy(self.records)
            records[400][field] = value
            self.write(records)
            self.assertEqual(self.report()["status"], "unverified", field)

    def test_ring_overflow_hash_mismatch_and_missing_tail_are_unverified(self):
        self.write(lost=1)
        self.assertEqual(self.report()["status"], "unverified")
        self.write(self.records[:7000])
        self.assertEqual(self.report()["status"], "unverified")
        self.write()
        self.raw.write_text(self.raw.read_text(encoding="utf-8") + " ", encoding="utf-8")
        self.assertEqual(self.report()["status"], "unverified")

    def test_adjacent_present_with_five_refresh_hold_fails_thresholds(self):
        for sample in self.records[400:]:
            sample["present_refresh_count"] += 4
            sample["sync_refresh_count"] += 4
            sample["sync_qpc"] += 4000000
            sample["observed_qpc"] += 4000000
        self.write()
        report = self.report()
        self.assertEqual(report["status"], "fail", report["unverified_reasons"])
        self.assertEqual(report["over_3T_count"], 1)
        self.assertAlmostEqual(report["max_ms"], 5 * 1000 / 60)

    def test_initial_clear_outside_resource_window_is_excluded(self):
        initial = dict(self.records[0], record_sequence=0, present_count=99, present_refresh_count=999,
                       sync_refresh_count=999, sync_qpc=658000000, observed_qpc=658000001,
                       moving=False, active_count=0, frame_kind="initial")
        records = [initial] + self.records
        for index, sample in enumerate(records):
            sample["record_sequence"] = index + 1
        self.write(records)
        self.assertEqual(self.report()["status"], "pass")

    def test_empty_uninitialized_warmup_page_is_ignored_but_capture_page_chain_is_checked(self):
        self.write()
        empty = {"process_id": 42, "qpc_frequency": 60000000, "swap_chain_address": 0,
                 "poll_qpc": 60000001, "samples": [], "lost_count": 0}
        original = self.raw.read_text(encoding="utf-8")
        self.raw.write_text(json.dumps(empty) + "\n" + original, encoding="utf-8")
        self.evidence["display_statistics_sha256"] = sha256(self.raw)
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
        self.assertEqual(self.report()["status"], "pass")
        page = json.loads(original)
        page["swap_chain_address"] = 999
        self.raw.write_text(json.dumps(page) + "\n", encoding="utf-8")
        self.evidence["display_statistics_sha256"] = sha256(self.raw)
        self.metadata.write_text(json.dumps(self.evidence), encoding="utf-8")
        self.assertIn("DXGI page swap chain attribution mismatch", self.report()["unverified_reasons"])

    def test_always_on_top_argument_is_opt_in(self):
        from dev.benchmarks.benchmark_video_danmaku_render import parse_args
        with patch.object(sys, "argv", ["benchmark", "--backend", "native"]):
            self.assertFalse(parse_args().always_on_top)
            self.assertEqual(parse_args().lane_preflight, 1)
        with patch.object(sys, "argv", ["benchmark", "--backend", "native", "--always-on-top"]):
            self.assertTrue(parse_args().always_on_top)
        with patch.object(sys, "argv", ["benchmark", "--backend", "native", "--lane-preflight", "0"]):
            self.assertEqual(parse_args().lane_preflight, 0)
            self.assertEqual(parse_args().lane_preflight_refresh, 1)

    def test_recorder_drains_pages_using_last_returned_sequence(self):
        class Host:
            def __init__(self):
                self.cursors = []

            def display_statistics(self, after, maximum):
                self.cursors.append(after)
                self.maximum = maximum
                return {"samples": [{"record_sequence": after + 1}], "lost_count": 0, "latest_sequence": 2}

        host = Host()
        recorder = DisplayStatisticsRecorder(host, self.raw)
        with patch("dev.benchmarks.benchmark_video_danmaku_render.qpc_clock", return_value=(100, 60000000)):
            recorder.sample()
        recorder.close()
        self.assertEqual(host.cursors, [0, 1])
        self.assertEqual(host.maximum, 8192)
        self.assertEqual(len(self.raw.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(recorder.summary()["display_statistics_status"], "observed")


class CollectorContractTests(unittest.TestCase):
    def test_collector_is_fixed_target_and_read_shareable(self):
        script = (Path(__file__).parent / "benchmarks/collect_danmaku_etw.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("[ValidateSet('DDMDanmakuBench-20261024.exe')]", script)
        self.assertIn("[IO.FileShare]::ReadWrite", script)
        self.assertIn("$csv.AutoFlush = $true", script)
        self.assertIn("--output_stdout --qpc_time --v2_metrics", script)
        self.assertIn("$process.StandardError.ReadToEndAsync()", script)
        self.assertIn("$process.StandardOutput.ReadLine()", script)
        self.assertIn("[IO.FileMode]::CreateNew", script)
        self.assertIn("Get-FileHash -LiteralPath $tool", script)
        self.assertNotIn("--stop_existing_session", script)
        self.assertNotIn("--terminate_existing_session", script)

    @unittest.skipUnless(sys.platform == "win32", "PowerShell collector guardrails")
    def test_collector_rejects_unrelated_process_and_outside_output(self):
        script = Path(__file__).parent / "benchmarks/collect_danmaku_etw.ps1"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "outside.csv"
            for process in ("python.exe", "DDMDanmakuBench-20261024.exe"):
                result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
                                         "-File", str(script), "-OutputCsv", str(output),
                                         "-ProcessName", process, "-Seconds", "1"], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(output.exists())


class ResourceTests(unittest.TestCase):
    def test_report_counts_complete_plan_without_claiming_display_acceptance(self):
        class Args:
            lane_preflight = 1
            lane_preflight_refresh = 1
        class Screen:
            def name(self): return "DISPLAY2"
            def refreshRate(self): return 60
            def size(self):
                class Size:
                    def width(self): return 3840
                    def height(self): return 2160
                return Size()
            def devicePixelRatio(self): return 1.5
            def geometry(self): return "geometry"
        plan = input_plan(1, "high")
        start = {"counters": {"offered": 1, "admitted": 2}, "lane_preflight_offered": 3}
        end = {"counters": {"offered": 5, "admitted": 7}, "lane_preflight_offered": 8}
        report = build_report(args=Args(), plan_summary=input_plan_summary(plan),
                              counters={"offered": 32, "queued": 20, "rejected": 12},
                              offer_lag={"count": 1, "max_seconds": 0.02},
                              status_start=start, status_end=end,
                              native_counts={"offered": 4, "admitted": 5},
                              screen=Screen(), screen_start=("DISPLAY2", 60, "geometry"),
                              mode_changed=False, resource_samples="samples.jsonl")
        self.assertEqual(report["status"], "unverified")
        self.assertEqual(report["input_actual"]["offered"], 32)
        self.assertEqual(report["input_actual"]["events_per_tile"], 8)
        self.assertEqual(report["input_plan"]["offered"], 32)
        self.assertEqual(report["input_lag"]["count"], 1)
        self.assertEqual(report["counter_delta"]["counters.admitted"], 5)
        self.assertFalse(report["display_mode_changed_during_capture"])

    def test_benchmark_disables_hover_network_entry_without_mutating_defaults(self):
        defaults = {"auto_update": True, "preview_on_hover": True, "video_danmaku_size": 24}
        original = defaults.copy()
        state = benchmark_window_state(defaults)
        self.assertFalse(state["settings"]["preview_on_hover"])
        self.assertFalse(state["settings"]["auto_update"])
        self.assertEqual(state["plugins_enabled"], [])
        self.assertEqual(state["settings"]["video_danmaku_size"], 24)
        self.assertEqual(defaults, original)
        state["plugins_enabled"].append("modified")
        state["settings"]["preview_on_hover"] = True
        fresh = benchmark_window_state(defaults)
        self.assertFalse(fresh["settings"]["preview_on_hover"])
        self.assertEqual(fresh["plugins_enabled"], [])

    def test_overlapping_failures_remain_separate_and_replacements_unknown(self):
        stages = drop_stage_counters(1, {"dropped_prepare": 3, "lane_preflight_offered": 4,
                                        "lane_preflight_rejected": 2, "lane_preflight_refreshed": 4,
                                        "counters": {"dropped_queue": 5}},
                                    {"dropped_prepare": 6, "lane_preflight_offered": 11,
                                     "lane_preflight_rejected": 9, "lane_preflight_refreshed": 11,
                                     "counters": {"dropped_queue": 7}})
        self.assertEqual(stages["add_event_rejected"], 1)
        self.assertEqual(stages["prepare_failures_including_native_queue_rejections"], 3)
        self.assertEqual(stages["lane_preflight_offered"], 7)
        self.assertEqual(stages["lane_preflight_rejected"], 7)
        self.assertEqual(stages["lane_preflight_refreshed"], 7)
        self.assertEqual(stages["native_submission_failures"], {"dropped_queue": 2})
        self.assertIsNone(stages["replacement_failures"])

    def test_formal_input_plan_is_deterministic_and_counts_boundary(self):
        plan = input_plan(2, "high")
        repeat = input_plan(2, "high")
        self.assertEqual(plan, repeat)
        self.assertEqual(plan[0], {"due": 0.0, "sequence": 1, "kind": "long", "color": "#ff8844"})
        self.assertEqual(plan[-1]["sequence"], len(plan))
        self.assertEqual(len(plan), 16)
        summary = input_plan_summary(plan)
        self.assertEqual(summary["offered"], 64)
        self.assertEqual(summary["sequence_start"], 1)
        self.assertEqual(summary["sequence_end"], 16)
        self.assertEqual(summary["exact_duration_seconds"], 2)
        self.assertEqual(summary["sha256"], input_plan_summary(repeat)["sha256"])
        self.assertEqual(input_plan(1, "burst")[0]["sequence"], 1)
        self.assertEqual(len(input_plan(1, "burst")), 50)
        self.assertEqual(input_plan_summary(input_plan(1, "burst"))["exact_duration_seconds"], 5)

    def test_counter_delta_includes_all_native_and_preflight_fields(self):
        start = {"counters": {"offered": 2, "admitted": 1},
                 "prepare_offered": 4, "lane_preflight_offered": 5,
                 "lane_preflight_rejected": 3}
        end = {"counters": {"offered": 9, "admitted": 6, "dropped_lanes": 2},
               "prepare_offered": 11, "lane_preflight_offered": 15,
               "lane_preflight_rejected": 8, "lane_preflight_refreshed": 6}
        result = counter_delta(start, end)
        self.assertEqual(result["counters.offered"], 7)
        self.assertEqual(result["counters.admitted"], 5)
        self.assertEqual(result["counters.dropped_lanes"], 2)
        self.assertEqual(result["prepare_offered"], 7)
        self.assertEqual(result["lane_preflight_offered"], 10)
        self.assertEqual(result["lane_preflight_rejected"], 5)
        self.assertEqual(result["lane_preflight_refreshed"], 6)
        self.assertEqual(result["prepare_queued"], 0)
        self.assertEqual(result["dropped_prepare"], 0)

    def test_planned_offer_resets_at_capture_boundary_and_never_duplicates(self):
        plan = input_plan(2, "burst")
        state = {"index": 0, "lag": {"count": 0, "max_seconds": 0.0}, "next_due": 20.0}
        first = planned_offer(20.0, state, 20.015, plan)
        second = planned_offer(20.0, state, 20.02, plan)
        self.assertIs(first, plan[0])
        self.assertIs(second, plan[1])
        self.assertEqual(state["index"], 2)
        self.assertAlmostEqual(state["lag"]["max_seconds"], 0.02)
        self.assertEqual(state["lag"]["count"], 2)
        self.assertEqual(state["next_due"], 20.0)

    def test_abba_verifier_accepts_four_fresh_matching_children_and_rejects_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            base = {"source_commit": "fixed", "source_code_sha256": "source",
                    "backend": "native", "video": "mixed", "density": "high",
                    "source_dirty": [], "native_binary": {"sha256": "binary"},
                    "python": "3.13", "qt_version": "6.9.3",
                    "video_rates": [30, 60, 30, 60],
                    "source_video_sha256": {"mixed": "videos"},
                    "screen_hz": 60, "screen_size": [3840, 2160], "screen_dpr": 1.5,
                    "sample_scale": 2, "render_quality": {"sample_scale": 2},
                    "input_plan": {"offered": 480, "sha256": "plan"},
                    "input_actual": {"offered": 480}, "repeat": 1,
                    "warmup_seconds": 10, "capture_seconds": 120,
                    "window_always_on_top": True,
                    "display_mode_changed_during_capture": False,
                    "measurement_schema": 3}
            arms = (("control", 1, 0), ("enabled", 2, 1),
                    ("enabled", 3, 1), ("control", 4, 0))
            paths = []
            for index, (arm, arm_id, enabled) in enumerate(arms):
                path = output / f"{index}.json"
                report = dict(base, worker_arm=arm, arm_id=arm_id,
                              lane_preflight=enabled, lane_preflight_refresh=1,
                              pid=900000000 + index,
                              worker_environment={"lane_preflight": bool(enabled),
                                                  "lane_preflight_refresh": True,
                                                  "pid": 900000000 + index})
                path.write_text(json.dumps(report), encoding="utf-8")
                paths.append(path)
            with patch("dev.benchmarks.benchmark_video_danmaku_render.process_alive",
                       return_value=False):
                self.assertEqual(verify_abba_reports(paths)["status"], "comparable")
            drift = json.loads(paths[-1].read_text(encoding="utf-8"))
            drift["screen_hz"] = 120
            paths[-1].write_text(json.dumps(drift), encoding="utf-8")
            with patch("dev.benchmarks.benchmark_video_danmaku_render.process_alive",
                       return_value=False):
                verifier = verify_abba_reports(paths)
            self.assertEqual(verifier["status"], "unverified")
            self.assertIn("Unmatched/missing ABBA screen_hz", verifier["errors"])
            self.assertEqual(len(report_paths(output)), 4)

    def test_abba_verifier_rejects_binary_and_source_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            base = {"source_commit": "fixed", "source_code_sha256": "source",
                    "source_dirty": [], "native_binary": {"sha256": "binary"},
                    "python": "3.13", "qt_version": "6.9.3", "backend": "native",
                    "video": "mixed", "video_rates": [30, 60, 30, 60], "density": "high",
                    "source_video_sha256": {"mixed": "videos"},
                    "screen_hz": 60, "screen_size": [3840, 2160], "screen_dpr": 1.5,
                    "sample_scale": 2, "render_quality": {"sample_scale": 2},
                    "input_plan": {"offered": 480, "sha256": "plan"},
                    "input_actual": {"offered": 480}, "repeat": 1,
                    "warmup_seconds": 10, "capture_seconds": 120,
                    "window_always_on_top": True,
                    "display_mode_changed_during_capture": False,
                    "measurement_schema": 3}
            arms = (("control", 1, 0), ("enabled", 2, 1),
                    ("enabled", 3, 1), ("control", 4, 0))
            paths = []
            for index, (arm, arm_id, enabled) in enumerate(arms):
                path = output / f"{index}.json"
                report = dict(base, worker_arm=arm, arm_id=arm_id,
                              lane_preflight=enabled, lane_preflight_refresh=1,
                              pid=910000000 + index,
                              worker_environment={"lane_preflight": bool(enabled),
                                                  "lane_preflight_refresh": True,
                                                  "pid": 910000000 + index})
                path.write_text(json.dumps(report), encoding="utf-8")
                paths.append(path)
            drift = json.loads(paths[-1].read_text(encoding="utf-8"))
            drift["native_binary"] = {"sha256": "different"}
            drift["source_dirty"] = [" M ddm/native_danmaku.py"]
            paths[-1].write_text(json.dumps(drift), encoding="utf-8")
            with patch("dev.benchmarks.benchmark_video_danmaku_render.process_alive",
                       return_value=False):
                verifier = verify_abba_reports(paths)
            self.assertEqual(verifier["status"], "unverified")
            self.assertIn("Unmatched/missing ABBA native_binary", verifier["errors"])
            self.assertIn("ABBA arms were not captured from a clean relevant source tree",
                          verifier["errors"])
            self.assertIn("ABBA native binary hashes differ", verifier["errors"])

    def test_repeat_orchestration_evidence_is_not_a_benchmark_report(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "repeat-attempts.json").write_text("{}", encoding="utf-8")
            (output / "capture-analysis.json").write_text("{}", encoding="utf-8")
            report = output / "capture.json"
            report.write_text("{}", encoding="utf-8")
            self.assertEqual(report_paths(output), [report])

    @unittest.skipUnless(sys.platform == "win32", "Win32 process memory API")
    def test_real_current_process_memory_without_gui(self):
        sampler = ResourceSampler()
        try:
            first = sampler.sample(0)
            second = sampler.sample(1)
            sampler.reset()
            repeated = sampler.sample(0)
        finally:
            sampler.close()
        self.assertGreater(first["working_set_bytes"], 0)
        self.assertGreater(first["private_bytes"], 0)
        self.assertGreaterEqual(second["process_cpu_seconds"], first["process_cpu_seconds"])
        self.assertIsNone(repeated["process_cpu_percent_one_core"])
        self.assertIn(second["dwm_cpu_status"], ("available", "unverified"))
        if second["dwm_cpu_status"] == "unverified":
            self.assertTrue(second["dwm_cpu_reason"])

    def test_memory_slope_and_bounded_cadence(self):
        from collections import deque
        samples = [{"elapsed_seconds": index, "bytes": 100 + index * 10} for index in range(10)]
        result = memory_trend(samples, "bytes")
        self.assertEqual(result["tail_80_percent_bytes_per_second"], 10)
        self.assertEqual(result["peak_bytes"], 190)
        self.assertEqual(stats(deque((0, 1000000, 2000000), maxlen=3))["p50_ms"], 1)

    def test_resource_comparison_rejects_different_admission_and_quality(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            samples = root / "samples.jsonl"
            samples.write_text("".join(json.dumps({"elapsed_seconds": index}) + "\n" for index in range(120)), encoding="utf-8")
            baseline = {"source_commit": "fixed", "source_code_sha256": "fixed-dirty-source", "video": "mixed", "video_rates": [30, 60, 30, 60],
                "density": "high", "render_quality": {"sample_scale": 2}, "screen_hz": 144,
                "screen_dpr": 1.5, "screen_size": [2560, 1440], "source_video_sha256": {},
                "offered": 100, "admitted": 90, "capture_seconds": 120, "wall_seconds": 120, "warmup_seconds": 10,
                "display_mode_changed_during_capture": False, "video_visibility_status": "verified by reviewer",
                "resource_samples": str(samples), "resource_samples_sha256": sha256(samples),
                "process_cpu_percent_one_core": 20, "image_bytes_peak": 100}
            candidate: dict[str, Any] = dict(baseline, process_cpu_percent_one_core=10)
            left, right = root / "baseline.json", root / "candidate.json"
            left.write_text(json.dumps(baseline), encoding="utf-8")
            right.write_text(json.dumps(candidate), encoding="utf-8")
            self.assertEqual(compare_resources(left, right)["status"], "comparable")
            samples.write_text("{}\n", encoding="utf-8")
            baseline["resource_samples_sha256"] = candidate["resource_samples_sha256"] = sha256(samples)
            left.write_text(json.dumps(baseline), encoding="utf-8")
            right.write_text(json.dumps(candidate), encoding="utf-8")
            self.assertIn("baseline resource samples do not cover the capture window", compare_resources(left, right)["unverified_reasons"])
            candidate = baseline.copy()
            candidate["process_cpu_percent_one_core"] = 10
            candidate["admitted"] = 70
            candidate["render_quality"] = {"sample_scale": 1}
            right.write_text(json.dumps(candidate), encoding="utf-8")
            report = compare_resources(left, right)
            self.assertEqual(report["status"], "unverified")
            self.assertIn("Unmatched or missing admitted", report["unverified_reasons"])
            self.assertIn("Unmatched or missing render_quality", report["unverified_reasons"])


if __name__ == "__main__":
    unittest.main()
