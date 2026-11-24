# csvio.py -- course staff file, do not modify.
#
# Writes the CSV files a student can read without documentation, plus
# summary.json.

import csv
import json
import os

CHECKPOINT_HEADER = [
    "sim_minute", "jobs_submitted_window", "jobs_completed_window", "jobs_lost_window",
    "jobs_submitted_total", "jobs_completed_total", "jobs_lost_total", "jobs_pending",
    "throughput_jobs_per_sim_minute",
    "job_latency_p50_ms", "job_latency_p95_ms", "job_latency_mean_ms",
    "queue_wait_mean_ms", "run_time_mean_ms",
    "queue_len_max", "queue_len_mean",
    "verdict_accuracy_pct",
    "upload_latency_p50_ms", "upload_latency_p95_ms",
    "request_latency_p50_ms", "request_latency_p95_ms",
    "storage_time_mean_ms", "storage_time_p95_ms",
    "call_rtt_mean_ms", "call_rtt_p95_ms",
    "request_failures_window",
    "network_bytes_total_window", "overhead_ratio_window",
    "cpu_pct_mean_gateway", "cpu_pct_mean_scheduler", "cpu_pct_mean_storage",
    "cpu_pct_mean_exec1", "cpu_pct_mean_exec2", "cpu_pct_mean_exec3",
    "mem_mb_mean_gateway", "mem_mb_mean_scheduler", "mem_mb_mean_storage",
    "mem_mb_mean_exec1", "mem_mb_mean_exec2", "mem_mb_mean_exec3",
    "work_pct_exec1", "work_pct_exec2", "work_pct_exec3",
    "restarts_total",
]

JOBS_HEADER = ["local_job_id", "baseline_job_number", "user", "submit_sim_ms",
               "state", "latency_ms", "verdicts_correct", "verdicts_total",
               "verdicts_ambiguous"]

HOSTILE_HEADER = ["sim_ms", "sequence_time_s", "kind", "description", "outcome", "evidence"]


def write_header_if_new(path, header):
    if not os.path.exists(path):
        with open(path, "w", newline="\n", encoding="utf-8") as f:
            csv.writer(f).writerow(header)


def start_files(run_dir):
    """Create the three CSV files with their header lines, so that every
    run folder holds the same files even when one of them stays empty."""
    write_header_if_new(os.path.join(run_dir, "checkpoints.csv"), CHECKPOINT_HEADER)
    write_header_if_new(os.path.join(run_dir, "jobs.csv"), JOBS_HEADER)
    write_header_if_new(os.path.join(run_dir, "hostile.csv"), HOSTILE_HEADER)


def append_row(path, header, row):
    write_header_if_new(path, header)
    with open(path, "a", newline="\n", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def checkpoint_row(run_dir, sim_minute, window_stats, cumulative, cpu_mem, work_pct,
                    net_total_window, overhead_ratio, restarts_total):
    def g(d, k):
        v = d.get(k)
        return "" if v is None else round(v, 3) if isinstance(v, float) else v

    storage_all_mean = [v["mean"] for v in window_stats["storage_by_op"].values() if v["mean"] is not None]
    storage_all_p95 = [v["p95"] for v in window_stats["storage_by_op"].values() if v["p95"] is not None]
    call_all_mean = [v["mean"] for v in window_stats["call_by_dest"].values() if v["mean"] is not None]
    call_all_p95 = [v["p95"] for v in window_stats["call_by_dest"].values() if v["p95"] is not None]

    def avg(v):
        return sum(v) / len(v) if v else ""

    row = [
        round(sim_minute, 2),
        window_stats["jobs_submitted"], window_stats["jobs_completed"], window_stats["jobs_lost"],
        cumulative["jobs_submitted"], cumulative["jobs_completed"], cumulative["jobs_lost"],
        cumulative["jobs_pending"],
        g(window_stats, "throughput_per_min"),
        g(window_stats, "latency_p50"), g(window_stats, "latency_p95"), g(window_stats, "latency_mean"),
        g(window_stats, "queue_wait_mean"), g(window_stats, "run_time_mean"),
        g(window_stats, "queue_len_max"), g(window_stats, "queue_len_mean"),
        g(window_stats, "accuracy_pct"),
        g(window_stats, "upload_p50"), g(window_stats, "upload_p95"),
        g(window_stats, "request_p50"), g(window_stats, "request_p95"),
        avg(storage_all_mean), avg(storage_all_p95),
        avg(call_all_mean), avg(call_all_p95),
        window_stats["request_failures"],
        net_total_window, g({"r": overhead_ratio}, "r"),
    ]
    for n in ["gateway", "scheduler", "storage", "exec1", "exec2", "exec3"]:
        row.append(g(cpu_mem.get(n, {}), "cpu"))
    for n in ["gateway", "scheduler", "storage", "exec1", "exec2", "exec3"]:
        row.append(g(cpu_mem.get(n, {}), "mem_mb"))
    for n in ["exec1", "exec2", "exec3"]:
        row.append(g(work_pct, n))
    row.append(restarts_total)

    append_row(os.path.join(run_dir, "checkpoints.csv"), CHECKPOINT_HEADER, row)
    return row


def write_job_row(run_dir, rec):
    row = [rec.local_id, rec.baseline_job, rec.user, round(rec.submit_sim_ms, 1),
           rec.state, round(rec.latency_ms, 1) if rec.latency_ms is not None else "",
           rec.correct, rec.total_lines, rec.ambiguous]
    append_row(os.path.join(run_dir, "jobs.csv"), JOBS_HEADER, row)


def write_hostile_row(run_dir, entry):
    row = [round(entry["t_sim"], 1), entry.get("t_event", ""), entry["kind"],
           entry["description"], entry["outcome"], entry["evidence"]]
    append_row(os.path.join(run_dir, "hostile.csv"), HOSTILE_HEADER, row)


def write_summary(run_dir, summary):
    with open(os.path.join(run_dir, "summary.json"), "w", newline="\n", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
