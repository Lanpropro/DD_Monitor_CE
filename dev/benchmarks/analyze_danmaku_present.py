"""Analyze final display durations from official PresentMon 1.x/2.x CSV fields."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def address_key(value):
    if isinstance(value, int):
        return value
    try:
        return int(str(value), 16)
    except ValueError:
        return str(value).lower()


def display_boundary_evidence(metadata, segments, process_id):
    window = metadata.get("capture_qpc", {})
    readiness = metadata.get("presentmon_readiness", {})
    frequency, start, end, warmup = (window.get(key) for key in ("frequency", "start", "end", "warmup_start"))
    values = (frequency, start, end, warmup, readiness.get("observed_qpc"), readiness.get("row_cpu_start_qpc"))
    if (not all(isinstance(value, int) and value > 0 for value in values)
            or not warmup <= start < end or frequency <= 0
            or readiness.get("status") != "observed" or readiness.get("process_id") != process_id
            or not readiness["row_cpu_start_qpc"] <= readiness["observed_qpc"] <= warmup):
        return [], 0, "Missing raw-QPC capture window or pre-warmup collector readiness"
    if (start - warmup) / frequency < metadata.get("warmup_seconds", 10) - .01:
        return [], 0, "Raw-QPC warmup is shorter than configured warmup"
    if (end - start) / frequency < metadata.get("capture_seconds", 120):
        return [], 0, "Raw-QPC resource window is shorter than configured capture"
    selected = [(a, b, duration) for a, b, duration in segments if a < end and b > start]
    if not selected:
        return [], 0, "No final-display intervals overlap the raw-QPC resource window"
    ordered = sorted(selected)
    # PresentMon serializes millisecond metrics with limited decimal precision.
    tolerance = frequency * .00005
    covered = start
    for a, b, _ in ordered:
        if a > covered + tolerance:
            return [item[2] for item in selected], 0, "Final-display intervals do not continuously cover the resource window"
        covered = max(covered, b)
    if ordered[0][0] > start or covered < end:
        return [item[2] for item in selected], 0, "Final-display CSV does not bracket both resource boundaries"
    return [item[2] for item in selected], (end - start) / frequency, None


def analyze(csv_path: Path, metadata_path: Path, hz: float, swapchain: str,
            process_id: int, min_seconds: float = 120) -> dict:
    if not math.isfinite(hz) or hz <= 0 or not math.isfinite(min_seconds) or min_seconds <= 0:
        raise ValueError("Refresh rate must be positive and finite")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = reader.fieldnames or []
        metric = next((name for name in ("DisplayedTime", "MsBetweenDisplayChange") if name in fields), None)
        if metric is None or not {"ProcessID", "SwapChainAddress"}.issubset(fields):
            raise ValueError("CSV needs ProcessID, SwapChainAddress and a final display duration field")
        intervals = []
        discarded = 0
        sources = set()
        segments = []
        source_segments = []
        readiness_row_found = False
        qpc_frequency = metadata.get("capture_qpc", {}).get("frequency")
        for row in reader:
            if (row.get("ProcessID") == str(process_id)
                    and row.get("CPUStartQPC") == str(metadata.get("presentmon_readiness", {}).get("row_cpu_start_qpc"))
                    and row.get("DisplayedTime") not in (None, "", "NA")):
                try:
                    readiness_row_found |= float(row["DisplayedTime"]) > 0
                except (ValueError, TypeError):
                    pass
            if int(row["ProcessID"]) != process_id or address_key(row["SwapChainAddress"]) != address_key(swapchain):
                continue
            if row.get("Dropped", "0").strip().lower() in ("1", "true"):
                discarded += 1
                continue
            try:
                duration = float(row[metric])
            except (ValueError, TypeError):
                discarded += 1
                continue
            if not math.isfinite(duration) or duration <= 0:
                discarded += 1
                continue
            intervals.append(duration)
            if metric == "DisplayedTime" and isinstance(qpc_frequency, int) and qpc_frequency > 0:
                try:
                    cpu_start = int(row["CPUStartQPC"])
                    latency = float(row["DisplayLatency"])
                    if math.isfinite(latency) and latency >= 0:
                        displayed_start = cpu_start + latency * qpc_frequency / 1000
                        displayed_end = displayed_start + duration * qpc_frequency / 1000
                        segments.append((displayed_start, displayed_end, duration))
                        source_segments.append((displayed_start, displayed_end,
                                                (row.get("VidPnSourceId"), row.get("LayerIndex"))))
                except (KeyError, TypeError, ValueError):
                    pass
            sources.add((row.get("VidPnSourceId"), row.get("LayerIndex")))
    reasons = []
    if not metadata.get("csv_sha256") or metadata["csv_sha256"] != sha256(csv_path):
        reasons.append("CSV hash is missing or differs from capture metadata")
    if not intervals:
        reasons.append("No displayed frames for the selected process and swap chain")
    window = metadata.get("capture_qpc", {})
    if source_segments and all(finite_number(window.get(key)) for key in ("start", "end")):
        sources = {source for a, b, source in source_segments if a < window["end"] and b > window["start"]}
    if len(sources) > 1:
        reasons.append("Selected swap chain spans multiple display sources/layers")
    evidence = metadata.get("swapchain_attribution", {})
    if (address_key(evidence.get("address", "")) != address_key(swapchain)
            or not evidence.get("evidence") or evidence.get("process_id") != process_id):
        reasons.append("Missing independent native overlay swap chain attribution")
    screen_hz = metadata.get("screen_hz")
    if not finite_number(screen_hz) or abs(float(screen_hz) - hz) > 1:
        reasons.append("Capture metadata does not confirm the requested actual screen refresh rate")
    if metadata.get("display_mode_changed_during_capture") is not False:
        reasons.append("Stable display mode during capture is unconfirmed")
    raw_displayed_seconds = sum(intervals) / 1000
    selected, observed_seconds, boundary_reason = display_boundary_evidence(metadata, segments, process_id)
    if not readiness_row_found:
        reasons.append("Pre-warmup readiness row is absent from finalized CSV")
    if boundary_reason:
        reasons.append(boundary_reason)
    if selected:
        intervals = selected
    if boundary_reason:
        observed_seconds = 0
    if observed_seconds + 1e-6 < min_seconds or min_seconds < 120:
        reasons.append("Formal capture requires at least 120 seconds of displayed duration")
    if not finite_number(metadata.get("warmup_seconds")) or metadata["warmup_seconds"] < 10:
        reasons.append("Formal capture requires at least 10 seconds of warmup")
    if any(not finite_number(metadata.get(key)) or metadata[key] < min_seconds
           for key in ("capture_seconds", "wall_seconds")):
        reasons.append("Formal capture requires a complete measured resource capture window")
    if not segments:
        reasons.append("Final display boundaries require CPUStartQPC and DisplayLatency; present/CPU cadence is insufficient")
    ordered = sorted(intervals)
    period = 1000 / hz
    p99 = ordered[max(0, math.ceil(len(ordered) * .99) - 1)] if ordered else None
    over_15 = sum(value > 1.5 * period for value in intervals)
    over_3 = sum(value > 3 * period for value in intervals)
    criteria = p99 is not None and p99 <= 1.25 * period and over_15 / len(intervals) <= .001 and over_3 == 0
    return {"status": "unverified" if reasons else ("pass" if criteria else "fail"),
            "unverified_reasons": reasons, "criteria_met": criteria,
            "metric": metric, "hz": hz, "period_ms": period,
            "displayed_intervals": len(intervals), "discarded_rows": discarded,
            "displayed_seconds": observed_seconds, "raw_displayed_seconds": raw_displayed_seconds,
            "final_display_capture_boundary_status": "verified" if not boundary_reason and readiness_row_found else "unverified",
            "p99_ms": p99,
            "over_1_5T_count": over_15,
            "over_1_5T_fraction": over_15 / len(intervals) if intervals else None,
            "over_3T_count": over_3, "max_ms": max(intervals, default=None),
            "process_id": process_id, "swapchain": swapchain,
            "display_sources_layers": sorted(sources, key=str),
            "raw_csv": str(csv_path.resolve()), "raw_csv_sha256": sha256(csv_path),
            "metadata": str(metadata_path.resolve()), "metadata_sha256": sha256(metadata_path),
            "scope": "One capture only; three repeats and baseline/resource comparison remain required"}


def signed_refresh_delta(current, previous):
    return ((current - previous + (1 << 31)) % (1 << 32)) - (1 << 31)


def analyze_dxgi(statistics_path: Path, metadata_path: Path, hz: float, swapchain: str,
                 process_id: int, min_seconds: float = 120) -> dict:
    if not math.isfinite(hz) or hz <= 0 or not math.isfinite(min_seconds) or min_seconds <= 0:
        raise ValueError("Refresh rate and minimum duration must be positive and finite")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    window = metadata.get("capture_qpc", {})
    frequency, start, end, warmup = (window.get(key) for key in ("frequency", "start", "end", "warmup_start"))
    if not all(isinstance(value, int) and value > 0 for value in (frequency, start, end, warmup)) or not warmup <= start < end:
        raise ValueError("DXGI analysis requires a valid raw-QPC resource capture window")
    reasons = []
    if metadata.get("display_statistics_sha256") != sha256(statistics_path):
        reasons.append("DXGI statistics hash is missing or differs from capture metadata")
    if metadata.get("display_statistics_status") != "observed" or metadata.get("display_statistics_errors"):
        reasons.append("Native display statistics recorder did not complete without errors")
    if metadata.get("display_statistics_lost_count", 0):
        reasons.append("Native display statistics recorder lost records")
    evidence = metadata.get("swapchain_attribution", {})
    if (address_key(evidence.get("address", "")) != address_key(swapchain)
            or evidence.get("process_id") != process_id or not evidence.get("evidence")):
        reasons.append("Missing independent native overlay swap chain attribution")
    binary = metadata.get("native_binary") or {}
    if not binary.get("path") or len(str(binary.get("sha256", ""))) != 64:
        reasons.append("Missing actual loaded native binary path/hash")
    if metadata.get("pid") != process_id:
        reasons.append("Capture metadata PID differs from requested process")
    actual_hz = metadata.get("screen_hz")
    if not finite_number(actual_hz) or abs(actual_hz - hz) > 1:
        reasons.append("Capture metadata does not confirm the requested actual screen refresh rate")
    if metadata.get("display_mode_changed_during_capture") is not False:
        reasons.append("Stable display mode during capture is unconfirmed")
    if (not finite_number(metadata.get("warmup_seconds")) or metadata["warmup_seconds"] < 10
            or (start - warmup) / frequency < 10):
        reasons.append("Formal capture requires at least 10 seconds of measured warmup")
    if (min_seconds < 120 or (end - start) / frequency < min_seconds
            or any(not finite_number(metadata.get(key)) or metadata[key] < min_seconds
                   for key in ("capture_seconds", "wall_seconds"))):
        reasons.append("Formal capture requires a complete measured resource window of at least 120 seconds")
    period = 1000 / hz
    frames = []
    duplicate_count = 0
    duplicate_conflicts = 0
    invalid_capture_samples = 0
    lost_records = 0
    previous_sequence = 0
    identities = set()
    with statistics_path.open(encoding="utf-8-sig") as handle:
        for line in handle:
            try:
                page = json.loads(line)
                if page.get("process_id") != process_id or page.get("qpc_frequency") != frequency:
                    reasons.append("DXGI page process or QPC frequency mismatch")
                capture_samples = [sample for sample in page.get("samples", [])
                                   if finite_number(sample.get("observed_qpc")) and start <= sample["observed_qpc"] <= end]
                if capture_samples and address_key(page.get("swap_chain_address", "")) != address_key(swapchain):
                    reasons.append("DXGI page swap chain attribution mismatch")
                lost_records += page.get("lost_count", 0)
                for sample in page["samples"]:
                    sequence = sample["record_sequence"]
                    observed = sample["observed_qpc"]
                    if not isinstance(sequence, int) or sequence <= previous_sequence:
                        reasons.append("DXGI raw record sequence is not strictly increasing")
                    elif previous_sequence and sequence != previous_sequence + 1:
                        reasons.append("DXGI raw record sequence has an unexplained gap")
                    previous_sequence = sequence
                    in_capture = start <= observed <= end
                    if address_key(sample.get("swap_chain_address", "")) != address_key(swapchain):
                        reasons.append("DXGI sample swap chain attribution mismatch")
                        continue
                    identities.add(sample.get("hwnd"))
                    values = [sample.get(key) for key in ("present_count", "present_refresh_count", "sync_refresh_count", "sync_qpc")]
                    if sample.get("hresult") != 0 or not all(isinstance(value, int) and value > 0 for value in values):
                        invalid_capture_samples += in_capture
                        continue
                    count, refresh, sync_refresh, sync_qpc = values
                    display_qpc = sync_qpc + signed_refresh_delta(refresh, sync_refresh) * frequency / hz
                    if display_qpc > observed + frequency / hz / 4:
                        invalid_capture_samples += in_capture
                        continue
                    moving = sample.get("moving") is True and sample.get("frame_kind") == "content" and sample.get("active_count", 0) > 0
                    if in_capture and not moving:
                        invalid_capture_samples += 1
                    frame = {"count": count, "refresh": refresh, "display_qpc": display_qpc, "moving": moving,
                             "kind": sample.get("frame_kind"), "active": sample.get("active_count"), "observed_qpc": observed}
                    if frames and frames[-1]["count"] == count:
                        duplicate_count += 1
                        previous = frames[-1]
                        if (any(previous[key] != frame[key] for key in ("refresh", "moving", "kind", "active"))
                                or abs(previous["display_qpc"] - display_qpc) > frequency / hz / 4):
                            if start <= display_qpc <= end or in_capture:
                                duplicate_conflicts += 1
                        continue
                    frames.append(frame)
            except (KeyError, TypeError, ValueError):
                reasons.append("Malformed DXGI raw statistics page")
    if lost_records:
        reasons.append("Native display statistics ring overflow lost raw records")
    if len(identities) != 1 or not next(iter(identities), None):
        reasons.append("DXGI samples do not identify one nonzero overlay HWND")
    if invalid_capture_samples:
        reasons.append("Capture contains failed/disjoint/zero statistics or unconfirmed moving content")
    if duplicate_conflicts:
        reasons.append("Duplicate displayed PresentCount has conflicting timing or content metadata")
    segments = []
    observed_gaps = []
    gap_count = 0
    for previous, current in zip(frames, frames[1:]):
        a, b = previous["display_qpc"], current["display_qpc"]
        if a >= end or b <= start:
            continue
        count_delta = (current["count"] - previous["count"]) % (1 << 32)
        refresh_delta = signed_refresh_delta(current["refresh"], previous["refresh"])
        if count_delta != 1:
            gap_count += 1
            if len(observed_gaps) < 128:
                observed_gaps.append({"previous_present_count": previous["count"], "present_count": current["count"],
                                      "present_count_delta": count_delta, "observed_gap_ms": (b - a) / frequency * 1000})
            continue
        if b <= a or refresh_delta <= 0:
            reasons.append("Displayed frame time or refresh count is not strictly increasing")
            continue
        if not previous["moving"]:
            reasons.append("Resource window includes initial/clear/unconfirmed-motion displayed content")
            continue
        segments.append((a, b, (b - a) / frequency * 1000))
    if gap_count:
        reasons.append("Displayed PresentCount jumps leave intermediate frame display times unobserved")
    ordered_segments = sorted(segments)
    covered = start
    for a, b, _ in ordered_segments:
        if a > covered + 1:
            reasons.append("Moving-content DXGI intervals do not continuously cover the resource window")
        covered = max(covered, b)
    boundary_verified = bool(ordered_segments and ordered_segments[0][0] <= start and covered >= end)
    if not boundary_verified:
        reasons.append("Moving-content DXGI evidence does not bracket both resource boundaries")
    intervals = [duration for _, _, duration in segments]
    ordered = sorted(intervals)
    p99 = ordered[max(0, math.ceil(len(ordered) * .99) - 1)] if ordered else None
    over_15 = sum(value > 1.5 * period for value in intervals)
    over_3 = sum(value > 3 * period for value in intervals)
    criteria = p99 is not None and p99 <= 1.25 * period and over_15 / len(intervals) <= .001 and over_3 == 0
    reasons = list(dict.fromkeys(reasons))
    return {"status": "unverified" if reasons else "pass" if criteria else "fail",
            "unverified_reasons": reasons, "criteria_met": criteria, "metric": "DXGI per-swapchain displayed frame intervals",
            "hz": hz, "period_ms": period, "displayed_intervals": len(intervals), "p99_ms": p99,
            "over_1_5T_count": over_15, "over_1_5T_fraction": over_15 / len(intervals) if intervals else None,
            "over_3T_count": over_3, "max_ms": max(intervals, default=None),
            "displayed_seconds": (end - start) / frequency if boundary_verified and not gap_count else 0,
            "duplicate_count": duplicate_count, "duplicate_conflict_count": duplicate_conflicts,
            "invalid_capture_samples": invalid_capture_samples, "lost_records": lost_records,
            "observed_present_gap_count": gap_count, "observed_present_gaps": observed_gaps,
            "final_display_capture_boundary_status": "verified" if boundary_verified and not gap_count else "unverified",
            "process_id": process_id, "swapchain": swapchain, "hwnd": list(identities),
            "raw_statistics": str(statistics_path.resolve()), "raw_statistics_sha256": sha256(statistics_path),
            "metadata": str(metadata_path.resolve()), "metadata_sha256": sha256(metadata_path),
            "timing_basis": "SyncQPCTime + signed32(PresentRefreshCount - SyncRefreshCount) * QPCFrequency / actualHz; adjacent unique PresentCount only",
            "scope": "One capture only; three repeats and baseline/resource/image-quality comparison remain required"}


def compare_resources(baseline_path: Path, candidate_path: Path) -> dict:
    baseline, candidate = [json.loads(path.read_text(encoding="utf-8-sig")) for path in (baseline_path, candidate_path)]
    reasons = []
    for key in ("source_commit", "source_code_sha256", "video", "video_rates", "density", "render_quality",
                "screen_hz", "screen_dpr", "screen_size", "source_video_sha256", "offered", "admitted", "capture_seconds"):
        if baseline.get(key) is None or baseline.get(key) != candidate.get(key):
            reasons.append(f"Unmatched or missing {key}")
    for label, report in (("baseline", baseline), ("candidate", candidate)):
        if report.get("capture_seconds", 0) < 120 or report.get("warmup_seconds", 0) < 10:
            reasons.append(f"{label} is a short capture")
        if report.get("wall_seconds", 0) < report.get("capture_seconds", 120):
            reasons.append(f"{label} measured capture window is incomplete")
        if report.get("display_mode_changed_during_capture") is not False:
            reasons.append(f"{label} has unconfirmed stable display mode")
        if not str(report.get("video_visibility_status", "")).startswith("verified"):
            reasons.append(f"{label} has no unobscured-video pixel evidence")
        samples_path = Path(report.get("resource_samples") or "")
        if not samples_path.is_file() or report.get("resource_samples_sha256") != sha256(samples_path):
            reasons.append(f"{label} resource sample hash is missing or mismatched")
        else:
            try:
                samples = [json.loads(line) for line in samples_path.read_text(encoding="utf-8-sig").splitlines()]
                times = [sample["elapsed_seconds"] for sample in samples]
                valid = (len(times) >= 2 and all(math.isfinite(t) and t >= 0 for t in times)
                         and all(a < b for a, b in zip(times, times[1:]))
                         and times[0] <= 2 and times[-1] >= report.get("capture_seconds", 120) - 2
                         and all(b - a <= 2.5 for a, b in zip(times, times[1:])))
            except (ValueError, TypeError, KeyError):
                valid = False
            if not valid:
                reasons.append(f"{label} resource samples do not cover the capture window")
    deltas = {}
    for metric in ("process_cpu_percent_one_core", "image_bytes_peak"):
        before, after = baseline.get(metric), candidate.get(metric)
        deltas[metric] = {"baseline": before, "candidate": after,
                         "delta": after - before if before is not None and after is not None else None}
    for metric in ("working_set_trend", "private_bytes_trend"):
        deltas[metric] = {"baseline": baseline.get(metric), "candidate": candidate.get(metric)}
    return {"status": "unverified" if reasons else "comparable",
        "unverified_reasons": reasons, "resource_deltas": deltas,
        "baseline_sha256": sha256(baseline_path), "candidate_sha256": sha256(candidate_path),
        "measurement": "Descriptive same-load resource comparison; final display/GPU acceptance and three-repeat variability remain separate"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path, nargs="?")
    parser.add_argument("--compare-resources", type=Path, nargs=2, metavar=("BASELINE", "CANDIDATE"))
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--dxgi-statistics", type=Path, help="Native per-chain DXGI display-statistics JSONL")
    parser.add_argument("--bind-external-csv", type=Path, metavar="METADATA_COPY",
                        help="Bind finalized external CSV hash into a new metadata copy before analysis")
    parser.add_argument("--hz", type=float)
    parser.add_argument("--swapchain")
    parser.add_argument("--process-id", type=int)
    parser.add_argument("--min-seconds", default=120, type=float)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.compare_resources:
        report = compare_resources(*args.compare_resources)
    elif args.dxgi_statistics:
        if any(value is None for value in (args.metadata, args.hz, args.swapchain, args.process_id)):
            parser.error("DXGI analysis requires --metadata, --hz, --swapchain and --process-id")
        report = analyze_dxgi(args.dxgi_statistics, args.metadata, args.hz, args.swapchain, args.process_id, args.min_seconds)
    else:
        if not args.csv or any(value is None for value in (args.metadata, args.hz, args.swapchain, args.process_id)):
            parser.error("Display analysis requires CSV, --metadata, --hz, --swapchain and --process-id")
        if args.bind_external_csv:
            if args.bind_external_csv.resolve() == args.metadata.resolve() or args.bind_external_csv.exists():
                parser.error("External CSV binding must write a new metadata copy")
            metadata = json.loads(args.metadata.read_text(encoding="utf-8-sig"))
            if not metadata.get("external_presentmon_csv"):
                parser.error("Only an external-collector report can be rebound")
            metadata.update(csv_sha256=sha256(args.csv), original_metadata_sha256=sha256(args.metadata),
                            original_metadata=str(args.metadata.resolve()), presentmon_csv=str(args.csv.resolve()))
            args.bind_external_csv.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            args.metadata = args.bind_external_csv
        report = analyze(args.csv, args.metadata, args.hz, args.swapchain, args.process_id, args.min_seconds)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return_code = {"pass": 0, "comparable": 0, "fail": 1, "unverified": 2}[report["status"]]
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
