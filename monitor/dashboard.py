# dashboard.py -- course staff file, do not modify.
#
# The dashboard's HTTP server: GET /api/state (JSON), static files from
# static/, and CSV downloads of the current run. Standard library only,
# threaded so a slow request never blocks the event-firing threads.

import json
import mimetypes
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from metrics import mean, percentile
from state import ALL_NODES, EXEC_NODES

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


def build_state_json(state, outside_stats_fn=None):
    with state.lock:
        sim_ms = state.clock.sim_ms()
        if state.finished and state.finished_sim_ms is not None:
            sim_ms = state.finished_sim_ms   # the clock of a finished run stands still
        jobs = list(state.jobs.values())
        hostile = list(state.hostile_events)
        timeseries = list(state.timeseries[-400:])
        started = list(state.sched_started)
        docker_samples = state.docker_samples[-1:] if state.docker_samples else []
        restarts = dict(state.node_restarts)
        running = state.running
        finished = state.finished
        seq_name = state.sequence_name
        speed = state.clock.speed
        total_events = state.sequence_total_events
        fired_events = state.sequence_fired_events
        startup_ok = state.startup_ok
        startup_message = state.startup_message

    submitted = len(jobs)
    completed = [j for j in jobs if j.state == "done"]
    lost = [j for j in jobs if j.lost]
    correct = sum(j.correct for j in completed)
    total_lines = sum(j.total_lines for j in completed)
    ambiguous_lines = sum(j.ambiguous for j in completed)
    accuracy = (100.0 * correct / total_lines) if total_lines else None
    latencies = [j.latency_ms for j in completed if j.latency_ms is not None]

    fairness = {}
    for j in jobs:
        if j.latency_ms is not None:
            fairness.setdefault(j.user, []).append(j.latency_ms)
    fairness_summary = {u: round(mean(v), 1) for u, v in fairness.items() if v}

    # jobs each execution node has started since the run began
    per_node_total = {n: 0 for n in EXEC_NODES}
    for row in started:
        if row[2] in per_node_total:
            per_node_total[row[2]] += 1

    nodes = {}
    if docker_samples:
        for name, info in docker_samples[0]["containers"].items():
            nodes[name] = info
    for n in ALL_NODES:
        nodes.setdefault(n, {})
        nodes[n]["restarts"] = restarts.get(n, nodes[n].get("restarts", 0))

    outside = outside_stats_fn() if outside_stats_fn else None

    return {
        "sequence": seq_name,
        "speed": speed,
        "sim_seconds": round(sim_ms / 1000.0, 1),
        "sim_minutes": round(sim_ms / 60000.0, 2),
        "running": running,
        "finished": finished,
        "startup_ok": startup_ok,
        "startup_message": startup_message,
        "sequence_progress": {"fired": fired_events, "total": total_events},
        "totals": {
            "jobs_submitted": submitted,
            "jobs_completed": len(completed),
            "jobs_lost": len(lost),
            "accuracy_pct": round(accuracy, 1) if accuracy is not None else None,
            "verdicts_ambiguous": ambiguous_lines,
            "latency_p50_ms": percentile(latencies, 50),
            "latency_p95_ms": percentile(latencies, 95),
        },
        "timeseries": timeseries,
        "per_node_total": per_node_total,
        "nodes": nodes,
        "fairness": fairness_summary,
        "hostile": hostile,
        "has_hostile": len(hostile) > 0,
        "outside": outside,
        "generated_at": time.time(),
    }


class Handler(BaseHTTPRequestHandler):
    state = None
    run_dir = None
    outside_stats_fn = None

    def log_message(self, fmt, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type=None):
        if not os.path.isfile(path):
            self.send_response(404)
            self.end_headers()
            return
        if content_type is None:
            content_type, _ = mimetypes.guess_type(path)
            content_type = content_type or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/state":
                self._send_json(build_state_json(self.state, self.outside_stats_fn))
                return
            if path.startswith("/download/"):
                name = os.path.basename(path[len("/download/"):])
                self._send_file(os.path.join(self.run_dir, name), "text/csv")
                return
            if path.startswith("/runs/"):
                # compare-with-earlier-run support: list or fetch another run's checkpoints.csv
                rest = path[len("/runs/"):]
                base = os.path.dirname(self.run_dir)
                full = os.path.normpath(os.path.join(base, rest))
                if os.path.commonpath([os.path.abspath(full), os.path.abspath(base)]) != os.path.abspath(base):
                    self.send_response(403)
                    self.end_headers()
                    return
                self._send_file(full, "text/csv")
                return
            if path == "/api/runs":
                base = os.path.dirname(self.run_dir)
                names = []
                try:
                    names = sorted(d for d in os.listdir(base)
                                    if os.path.isdir(os.path.join(base, d)))
                except OSError:
                    pass
                self._send_json({"runs": names, "current": os.path.basename(self.run_dir)})
                return

            if path == "/":
                path = "/index.html"
            full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
            if os.path.commonpath([os.path.abspath(full), os.path.abspath(STATIC_DIR)]) != os.path.abspath(STATIC_DIR):
                self.send_response(403)
                self.end_headers()
                return
            self._send_file(full)
        except Exception:
            self.send_response(500)
            self.end_headers()


def start_server(state, run_dir, outside_stats_fn, port=8080):
    Handler.state = state
    Handler.run_dir = run_dir
    Handler.outside_stats_fn = staticmethod(outside_stats_fn) if outside_stats_fn else None
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    import threading
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server
