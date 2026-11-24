#!/usr/bin/env python3
# monitor.py -- course staff file, do not modify.
#
# Entry point. Waits for the gateway, starts the log tailers and the docker
# sampler, plays the sequence named by $SEQUENCE, periodically writes
# checkpoints.csv / jobs.csv / hostile.csv, and serves the dashboard on
# :8080 for as long as the container runs.

import datetime
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import csvio
import dashboard
import dockerstats
import fisclient
import jobs as jobs_mod
import logtail
import sequence
import users
from metrics import Clock, mean
from state import ALL_NODES, EXEC_NODES, State

TS_INTERVAL_MS = 20 * 1000          # one dashboard point per 20 simulated seconds
TS_WINDOW_MS = 2 * 60 * 1000        # each point covers the last 2 simulated minutes
CKPT_INTERVAL_MS = 5 * 60 * 1000    # one checkpoint row per 5 simulated minutes

RUNS_DIR = "/runs"
SEQ_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sequences")


def log(msg):
    print(f"[monitor] {msg}", flush=True)


def wait_for_gateway(state, max_real_s=60):
    """Retry a login for one account until the gateway answers, or give up
    after about max_real_s real seconds. Keeps state.startup_* updated so
    the dashboard shows the same thing the monitor log says."""
    acct = users.ACCOUNTS["alice"]
    deadline = time.monotonic() + max_real_s
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        rc, out, err, ms = fisclient.login("alice", acct["password"])
        if rc == 0:
            with state.lock:
                state.startup_ok = True
                state.startup_message = "gateway reachable"
            return True
        with state.lock:
            state.startup_message = f"waiting for the gateway to answer (attempt {attempt})..."
        time.sleep(1.0)
    msg = f"the gateway never answered a login after {max_real_s:.0f}s; starting anyway"
    with state.lock:
        state.startup_ok = False
        state.startup_message = msg
    log(msg)
    return False


def make_run_dir(sequence_name):
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = os.path.join(RUNS_DIR, f"{sequence_name}-{stamp}")
    os.makedirs(run_dir, exist_ok=True)
    return run_dir


def get_docker_client():
    try:
        import docker
        return docker.from_env()
    except Exception as exc:
        log(f"docker client unavailable: {exc}")
        return None


def outside_stats():
    try:
        with urllib.request.urlopen("http://outside:8081/stats", timeout=3) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def network_bytes_window(state, t0, t1):
    """Bytes sent and received by all nodes between t0 and t1. Docker gives a
    counter per node, so the result is the counter of the last sample before
    t1 minus the counter of the last sample before t0. The counter of a node
    starts again from zero when the node restarts."""
    with state.lock:
        samples = [s for s in state.docker_samples if s["sim_ms"] < t1]
    total = 0
    for node in ALL_NODES:
        start = None
        end = None
        for s in samples:
            c = s["containers"].get(node, {})
            if c.get("net_rx") is None:
                continue
            counter = c.get("net_rx", 0) + c.get("net_tx", 0)
            if s["sim_ms"] < t0:
                start = counter
            else:
                if start is None:
                    start = 0 if t0 <= 0 else counter
                if counter < start:      # the node restarted
                    start = 0
                end = counter
        if start is not None and end is not None:
            total += max(0, end - start)
    return total


def payload_bytes_window(state, t0, t1):
    with state.lock:
        up = sum(b for (t, u, m, b, ok) in state.upload_lat if t0 <= t < t1 and ok)
        down = sum(b for (t, u, m, b, ok) in state.request_lat if t0 <= t < t1 and ok)
    return up + down


def cpu_mem_window(state, t0, t1):
    with state.lock:
        samples = [s for s in state.docker_samples if t0 <= s["sim_ms"] < t1]
    out = {}
    for node in ALL_NODES:
        cpus = [s["containers"].get(node, {}).get("cpu_pct") for s in samples]
        cpus = [c for c in cpus if c is not None]
        mems = [s["containers"].get(node, {}).get("mem_used") for s in samples]
        mems = [m for m in mems if m is not None]
        out[node] = {
            "cpu": mean(cpus),
            "mem_mb": (mean(mems) / (1024.0 * 1024.0)) if mems else None,
        }
    return out


def work_pct_latest(state):
    with state.lock:
        if not state.docker_samples:
            return {}
        last = state.docker_samples[-1]
    return {n: last["containers"].get(n, {}).get("work_pct") for n in EXEC_NODES}


def node_status_latest(state):
    with state.lock:
        if not state.docker_samples:
            return {}
        last = state.docker_samples[-1]
    return {n: last["containers"].get(n, {}).get("status") for n in ALL_NODES}


def make_timeseries_point(state, t0, t1):
    ws = state.window_stats(t0, t1)
    cm = cpu_mem_window(state, t0, t1)
    net_total = network_bytes_window(state, t0, t1)
    payload = payload_bytes_window(state, t0, t1)
    overhead = (net_total / payload) if payload > 0 else None
    return {
        "t_min": round(t1 / 60000.0, 3),
        "jobs_submitted": len(state.jobs),
        "jobs_completed": sum(1 for j in state.job_snapshot() if j.state == "done"),
        "jobs_lost": sum(1 for j in state.job_snapshot() if j.lost),
        "jobs_pending": sum(1 for j in state.job_snapshot() if j.state == "waiting"),
        "throughput_per_min": ws["throughput_per_min"],
        "latency_p50": ws["latency_p50"], "latency_p95": ws["latency_p95"],
        "queue_wait_mean": ws["queue_wait_mean"], "run_time_mean": ws["run_time_mean"],
        "queue_len_max": ws["queue_len_max"], "queue_len_mean": ws["queue_len_mean"],
        "accuracy_pct": ws["accuracy_pct"],
        "upload_p50": ws["upload_p50"], "upload_p95": ws["upload_p95"],
        "request_p50": ws["request_p50"], "request_p95": ws["request_p95"],
        "storage_by_op": ws["storage_by_op"], "call_by_dest": ws["call_by_dest"],
        "per_node_jobs": ws["per_node_jobs"],
        "cpu": {n: cm[n]["cpu"] for n in ALL_NODES},
        "mem_mb": {n: cm[n]["mem_mb"] for n in ALL_NODES},
        "work_pct": work_pct_latest(state),
        "node_status": node_status_latest(state),
        "network_bytes_window": net_total,
        "overhead_ratio": overhead,
    }


def run_aggregator(state, run_dir, stop_flag, settle_event):
    last_ts_ms = 0.0
    last_ckpt_ms = 0.0
    while not stop_flag["stop"]:
        now_ms = state.clock.sim_ms()

        if now_ms - last_ts_ms >= TS_INTERVAL_MS:
            try:
                point = make_timeseries_point(state, max(0, now_ms - TS_WINDOW_MS), now_ms)
                with state.lock:
                    state.timeseries.append(point)
                    if len(state.timeseries) > 2000:
                        state.timeseries = state.timeseries[-2000:]
            except Exception as exc:
                log(f"timeseries point failed: {exc}")
            last_ts_ms = now_ms

        if now_ms - last_ckpt_ms >= CKPT_INTERVAL_MS or (settle_event.is_set() and now_ms > last_ckpt_ms):
            try:
                with state.lock:   # no job may finish between the clock read and the count
                    now_ms = state.clock.sim_ms()
                    write_checkpoint(state, run_dir, last_ckpt_ms, now_ms)
            except Exception as exc:
                log(f"checkpoint failed: {exc}")
            last_ckpt_ms = now_ms

        if settle_event.is_set():
            break
        time.sleep(1.0)


def write_checkpoint(state, run_dir, t0, t1):
    ws = state.window_stats(t0, t1)
    jobs_all = state.job_snapshot()
    cumulative = {
        "jobs_submitted": len(jobs_all),
        "jobs_completed": sum(1 for j in jobs_all if j.state == "done"),
        "jobs_lost": sum(1 for j in jobs_all if j.lost),
        "jobs_pending": sum(1 for j in jobs_all if j.state == "waiting"),
    }
    cpu_mem = cpu_mem_window(state, t0, t1)
    work_pct = work_pct_latest(state)
    net_total = network_bytes_window(state, t0, t1)
    payload = payload_bytes_window(state, t0, t1)
    overhead = (net_total / payload) if payload > 0 else None
    restarts_total = sum(state.node_restarts.values())

    csvio.checkpoint_row(run_dir, t1 / 60000.0, ws, cumulative, cpu_mem, work_pct,
                          net_total, overhead, restarts_total)


def write_new_job_rows(state, run_dir, written_ids):
    for j in state.job_snapshot():
        if j.local_id in written_ids:
            continue
        if j.state in ("done", "lost"):
            csvio.write_job_row(run_dir, j)
            written_ids.add(j.local_id)


def write_new_hostile_rows(state, run_dir, written_count):
    with state.lock:
        entries = list(state.hostile_events)
    for entry in entries[written_count[0]:]:
        csvio.write_hostile_row(run_dir, entry)
    written_count[0] = len(entries)


def main():
    speed = float(os.environ.get("SIM_SPEED", "10"))
    sequence_name = os.environ.get("SEQUENCE", "normal")
    seq_path = os.path.join(SEQ_DIR, f"{sequence_name}.jsonl")

    clock = Clock(speed)
    run_dir = make_run_dir(sequence_name)
    csvio.start_files(run_dir)
    log(f"run directory: {run_dir}")

    state = State(clock, sequence_name, run_dir)

    # Start the dashboard immediately so the start-up wait (and any failure
    # of it) is visible in a browser from the very first second.
    server = dashboard.start_server(state, run_dir, outside_stats, port=8080)
    log("dashboard listening on :8080")

    log(f"waiting for the gateway (speed={speed}, sequence={sequence_name})...")
    wait_for_gateway(state)
    clock.start()
    log(f"simulated clock started (startup_ok={state.startup_ok})")

    stop_flag = {"stop": False}
    logtail.start_tailers(state, stop_flag)
    dockerstats.start_sampler(state, stop_flag)

    docker_client = get_docker_client()

    header, events = sequence.load_sequence(seq_path)
    log(f"loaded sequence '{header.get('name')}' with {len(events)} events")
    event_threads = sequence.play_sequence(state, events, docker_client)

    settle_event = __import__("threading").Event()
    agg_thread = __import__("threading").Thread(
        target=run_aggregator, args=(state, run_dir, stop_flag, settle_event), daemon=True)
    agg_thread.start()

    written_job_ids = set()
    written_hostile_count = [0]

    max_event_t = max((e["t"] for e in events), default=0.0)
    # After the last event, give its jobs the ten simulated minutes that a
    # job has before it counts as lost, and a little more.
    settle_deadline_sim_ms = max_event_t * 1000.0 + 11 * 60 * 1000

    while True:
        write_new_job_rows(state, run_dir, written_job_ids)
        write_new_hostile_rows(state, run_dir, written_hostile_count)

        with state.lock:
            fired = state.sequence_fired_events >= state.sequence_total_events
        now_ms = state.clock.sim_ms()
        if fired and now_ms >= settle_deadline_sim_ms:
            break
        pending = any(j.state == "waiting" for j in state.job_snapshot())
        if fired and not pending and all(not t.is_alive() for t in event_threads):
            break
        time.sleep(2.0)

    # A job that is still pending when the run ends counts as lost.
    for j in state.job_snapshot():
        if j.state == "waiting":
            state.mark_lost(j)

    write_new_job_rows(state, run_dir, written_job_ids)
    write_new_hostile_rows(state, run_dir, written_hostile_count)

    with state.lock:
        state.running = False
        state.finished = True
        state.finished_sim_ms = state.clock.sim_ms()
    settle_event.set()
    time.sleep(2.0)  # let the aggregator write the final checkpoint

    jobs_all = state.job_snapshot()
    latencies = [j.latency_ms for j in jobs_all if j.latency_ms is not None]
    from metrics import percentile
    summary = {
        "sequence": sequence_name,
        "speed": speed,
        "sim_minutes_total": round(state.finished_sim_ms / 60000.0, 2),
        "jobs_submitted": len(jobs_all),
        "jobs_completed": sum(1 for j in jobs_all if j.state == "done"),
        "jobs_lost": sum(1 for j in jobs_all if j.lost),
        "verdicts_correct": sum(j.correct for j in jobs_all),
        "verdicts_total": sum(j.total_lines for j in jobs_all),
        "verdicts_ambiguous": sum(j.ambiguous for j in jobs_all),
        "latency_p50_ms": percentile(latencies, 50),
        "latency_p95_ms": percentile(latencies, 95),
        "latency_mean_ms": mean(latencies),
        "hostile_events": list(state.hostile_events),
        "node_restarts": dict(state.node_restarts),
        "finished_at": datetime.datetime.now().isoformat(),
    }
    csvio.write_summary(run_dir, summary)
    log(f"run finished: {summary['jobs_completed']}/{summary['jobs_submitted']} jobs completed, "
        f"{summary['jobs_lost']} lost")

    # Keep serving the dashboard indefinitely.
    log("serving the dashboard; the run has finished")
    while True:
        write_new_job_rows(state, run_dir, written_job_ids)
        write_new_hostile_rows(state, run_dir, written_hostile_count)
        time.sleep(5.0)


if __name__ == "__main__":
    main()
