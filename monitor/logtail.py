# logtail.py -- course staff file, do not modify.
#
# Tails /logs/<node>.log (appended to by every node) from wherever it is
# when the run starts. Parses the "key=value key=value ..." lines into the
# shared State. A log line the monitor does not recognize, or a field that
# is missing, is simply skipped -- a student's redesign of the logging is
# expected and must not crash the monitor.

import glob
import os
import threading
import time

LOG_DIR = "/logs"


def _parse_kv(text):
    fields = {}
    for part in text.split(" "):
        if "=" in part:
            k, v = part.split("=", 1)
            fields[k] = v
    return fields


def _to_int(fields, key, default=None):
    try:
        return int(fields.get(key, default))
    except (TypeError, ValueError):
        return default


def _to_sim_ms(state, fields, key, default=None):
    """The durations in the logs are real milliseconds. The monitor shows
    every delay in simulated time, so they are multiplied by the speed."""
    value = _to_int(fields, key, default)
    if value is None:
        return None
    return value * state.clock.speed


def _handle_line(state, node, fields):
    event = fields.get("event")
    ts = _to_int(fields, "ts")
    if ts is None:
        return
    sim_ms = state.clock.sim_ms_for_epoch(ts)

    if event == "call":
        to = fields.get("to", "?")
        type_ = fields.get("type", "?")
        ms = _to_sim_ms(state, fields, "ms")
        ok = fields.get("ok") == "1"
        if ms is not None:
            state.add_call(sim_ms, to, type_, ms, ok)

    elif event == "request" and node == "gateway":
        type_ = fields.get("type", "?")
        result = fields.get("result", "?")
        ms = _to_sim_ms(state, fields, "ms")
        if ms is not None:
            state.add_gateway_request(sim_ms, type_, result, ms)

    elif event == "storage" and node == "storage":
        op = fields.get("op", "?")
        area = fields.get("area", "?")
        ms = _to_sim_ms(state, fields, "ms")
        ok = fields.get("result") == "OK"
        if ms is not None:
            state.add_storage_op(sim_ms, op, area, ms, ok)

    elif event == "job_submitted" and node == "scheduler":
        job = _to_int(fields, "job")
        user = fields.get("user", "?")
        queue = _to_int(fields, "queue", 0)
        if job is not None:
            state.add_sched_submitted(sim_ms, job, user, queue)

    elif event == "job_started" and node == "scheduler":
        job = _to_int(fields, "job")
        exec_ = fields.get("exec", "?")
        wait_ms = _to_sim_ms(state, fields, "wait_ms", 0)
        queue = _to_int(fields, "queue", 0)
        if job is not None:
            state.add_sched_started(sim_ms, job, exec_, wait_ms, queue)

    elif event == "job_done" and node == "scheduler":
        job = _to_int(fields, "job")
        exec_ = fields.get("exec", "?")
        run_ms = _to_sim_ms(state, fields, "run_ms", 0)
        if job is not None:
            state.add_sched_done(sim_ms, job, exec_, run_ms)

    elif event == "node_failed" and node == "scheduler":
        exec_ = fields.get("exec", "?")
        state.add_node_failed(sim_ms, exec_)


def _tail_one(path, node, state, stop_flag):
    try:
        f = open(path, "r", errors="replace")
        f.seek(0, os.SEEK_END)
    except OSError:
        return
    with f:
        while not stop_flag["stop"]:
            line = f.readline()
            if not line:
                time.sleep(0.3)
                continue
            line = line.strip()
            if not line:
                continue
            fields = _parse_kv(line)
            try:
                _handle_line(state, node, fields)
            except Exception:
                pass  # a broken/changed log line must never crash the monitor


def start_tailers(state, stop_flag):
    """Starts one tailing thread per existing /logs/<node>.log, plus a
    watcher thread that picks up logs for nodes that appear later."""
    known = set()

    def watcher():
        while not stop_flag["stop"]:
            for path in glob.glob(os.path.join(LOG_DIR, "*.log")):
                node = os.path.basename(path)[:-4]
                if node not in known:
                    known.add(node)
                    t = threading.Thread(target=_tail_one, args=(path, node, state, stop_flag),
                                          daemon=True)
                    t.start()
            time.sleep(2.0)

    threading.Thread(target=watcher, daemon=True).start()
