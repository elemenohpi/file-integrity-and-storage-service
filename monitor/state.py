# state.py -- course staff file, do not modify.
#
# The shared, thread-safe state the whole monitor fills in and reads from:
# log-derived events, job tracking, docker samples, hostile event results.
# Everything here degrades gracefully: a missing or changed log line just
# means that one metric stays empty, never a crash.

import threading

from metrics import mean, percentile

EXEC_NODES = ["exec1", "exec2", "exec3"]
ALL_NODES = ["gateway", "scheduler", "storage", "exec1", "exec2", "exec3"]


class JobRecord:
    __slots__ = ("local_id", "user", "submit_sim_ms", "baseline_job", "script",
                 "expect", "state", "done_sim_ms", "latency_ms", "correct",
                 "total_lines", "ambiguous", "output", "lost", "lost_sim_ms")

    def __init__(self, local_id, user, submit_sim_ms, script, expect):
        self.local_id = local_id
        self.user = user
        self.submit_sim_ms = submit_sim_ms
        self.baseline_job = None
        self.script = script
        self.expect = expect or []
        self.state = "waiting"   # waiting|done|lost
        self.done_sim_ms = None
        self.latency_ms = None
        self.correct = 0
        self.total_lines = len(expect) if expect else 0
        self.ambiguous = 0      # 'check' lines excluded: the file could have
                                 # changed while this job was queued/running
        self.output = ""
        self.lost = False
        self.lost_sim_ms = None


class State:
    def __init__(self, clock, sequence_name, run_dir):
        self.clock = clock
        self.sequence_name = sequence_name
        self.run_dir = run_dir
        self.lock = threading.RLock()

        self.running = True
        self.finished = False
        self.finished_sim_ms = None   # simulated time at which the run finished
        self.sequence_total_events = 0
        self.sequence_fired_events = 0
        self.startup_ok = None     # None while waiting, then True/False
        self.startup_message = "waiting for the gateway..."

        self._next_job_id = 1
        self.jobs = {}  # local_id -> JobRecord

        # raw, timestamped samples (sim_ms, ...); every "ms" value in them is
        # a duration in simulated milliseconds
        self.calls = []            # (sim_ms, to, type, ms, ok)
        self.storage_ops = []      # (sim_ms, op, area, ms, ok)
        self.gateway_requests = [] # (sim_ms, type, result, ms)
        self.sched_submitted = []  # (sim_ms, job, user, queue)
        self.sched_started = []    # (sim_ms, job, exec, wait_ms, queue)
        self.sched_done = []       # (sim_ms, job, exec, run_ms)
        self.node_failed = []      # (sim_ms, exec)
        self.upload_lat = []       # (sim_ms, user, ms, bytes, ok)
        self.request_lat = []      # (sim_ms, user, ms, bytes, ok)
        self.uploads_named = []    # (sim_ms, user, name) -- successful uploads only,
                                    # used to detect timing-ambiguous verdicts

        self.payload_bytes_up = 0
        self.payload_bytes_down = 0

        self.docker_samples = []   # list of dict, newest last
        self.node_restarts = {n: 0 for n in ALL_NODES}

        self.hostile_events = []   # list of dict

        self.checkpoints = []      # list of dict rows (mirrors checkpoints.csv)
        self.timeseries = []       # finer-grained points for the dashboard

    # ---- jobs -----------------------------------------------------------

    def new_job(self, user, script, expect):
        with self.lock:
            jid = self._next_job_id
            self._next_job_id += 1
            rec = JobRecord(jid, user, self.clock.sim_ms(), script, expect)
            self.jobs[jid] = rec
            return rec

    def mark_lost(self, rec):
        with self.lock:
            if rec.state == "done" or rec.lost:
                return
            rec.state = "lost"
            rec.lost = True
            rec.lost_sim_ms = self.clock.sim_ms()

    def job_snapshot(self):
        with self.lock:
            return list(self.jobs.values())

    # ---- log-derived events ----------------------------------------------

    def add_call(self, sim_ms, to, type_, ms, ok):
        with self.lock:
            self.calls.append((sim_ms, to, type_, ms, ok))

    def add_storage_op(self, sim_ms, op, area, ms, ok):
        with self.lock:
            self.storage_ops.append((sim_ms, op, area, ms, ok))

    def add_gateway_request(self, sim_ms, type_, result, ms):
        with self.lock:
            self.gateway_requests.append((sim_ms, type_, result, ms))

    def add_sched_submitted(self, sim_ms, job, user, queue):
        with self.lock:
            self.sched_submitted.append((sim_ms, job, user, queue))

    def add_sched_started(self, sim_ms, job, exec_, wait_ms, queue):
        with self.lock:
            self.sched_started.append((sim_ms, job, exec_, wait_ms, queue))

    def add_sched_done(self, sim_ms, job, exec_, run_ms):
        with self.lock:
            self.sched_done.append((sim_ms, job, exec_, run_ms))

    def add_node_failed(self, sim_ms, exec_):
        with self.lock:
            self.node_failed.append((sim_ms, exec_))

    def add_upload_lat(self, sim_ms, user, ms, nbytes, ok, name=None):
        with self.lock:
            self.upload_lat.append((sim_ms, user, ms, nbytes, ok))
            if ok:
                self.payload_bytes_up += nbytes
                if name:
                    self.uploads_named.append((sim_ms, user, name))

    def add_request_lat(self, sim_ms, user, ms, nbytes, ok):
        with self.lock:
            self.request_lat.append((sim_ms, user, ms, nbytes, ok))
            if ok:
                self.payload_bytes_down += nbytes

    def add_docker_sample(self, sim_ms, containers):
        with self.lock:
            self.docker_samples.append({"sim_ms": sim_ms, "containers": containers})
            if len(self.docker_samples) > 4000:
                self.docker_samples = self.docker_samples[-4000:]

    def add_hostile(self, entry):
        with self.lock:
            self.hostile_events.append(entry)

    # ---- windowed aggregation --------------------------------------------

    def _in_window(self, rows, t0, t1, idx=0):
        return [r for r in rows if t0 <= r[idx] < t1]

    def job_latencies_in_window(self, t0, t1, users=None):
        out = []
        with self.lock:
            for j in self.jobs.values():
                if j.latency_ms is None:
                    continue
                if not (t0 <= j.submit_sim_ms < t1):
                    continue
                if users is not None and j.user not in users:
                    continue
                out.append(j.latency_ms)
        return out

    def job_waits_in_window(self, t0, t1, now, users=None):
        """How long each job submitted in [t0, t1) has taken, as seen at the
        simulated time now: its latency if it is done, otherwise the time it
        has waited so far."""
        out = []
        with self.lock:
            for j in self.jobs.values():
                if not (t0 <= j.submit_sim_ms < t1):
                    continue
                if users is not None and j.user not in users:
                    continue
                if j.baseline_job is None:
                    continue
                if j.latency_ms is not None and j.done_sim_ms <= now:
                    out.append(j.latency_ms)
                else:
                    out.append(max(0.0, now - j.submit_sim_ms))
        return out

    def window_stats(self, t0, t1):
        """Everything needed for one checkpoint row or one dashboard point,
        computed over [t0, t1) of simulated ms. A job belongs to the window
        in which it was submitted for the submitted count, and to the window
        in which it finished (or was declared lost) for everything else, so a
        job that waited for a long time shows up when its result arrives."""
        with self.lock:
            calls = self._in_window(self.calls, t0, t1)
            sops = self._in_window(self.storage_ops, t0, t1)
            greqs = self._in_window(self.gateway_requests, t0, t1)
            started = self._in_window(self.sched_started, t0, t1)
            done = self._in_window(self.sched_done, t0, t1)
            submitted_rows = self._in_window(self.sched_submitted, t0, t1)
            node_failed = self._in_window(self.node_failed, t0, t1)
            uploads = self._in_window(self.upload_lat, t0, t1)
            requests = self._in_window(self.request_lat, t0, t1)

            jobs_all = list(self.jobs.values())

        jobs_submitted = [j for j in jobs_all if t0 <= j.submit_sim_ms < t1]
        jobs_completed = [j for j in jobs_all if j.state == "done" and
                          j.done_sim_ms is not None and t0 <= j.done_sim_ms < t1]
        jobs_lost = [j for j in jobs_all if j.lost and
                     j.lost_sim_ms is not None and t0 <= j.lost_sim_ms < t1]

        latencies = [j.latency_ms for j in jobs_completed if j.latency_ms is not None]
        wait_ms_list = [w for (_, _, _, w, _) in started]
        run_ms_list = [r for (_, _, _, r) in done]
        queue_list = [q for (_, _, _, _, q) in started] + [q for (_, _, _, q) in submitted_rows]

        correct = sum(j.correct for j in jobs_completed)
        total_lines = sum(j.total_lines for j in jobs_completed)
        accuracy = (100.0 * correct / total_lines) if total_lines else None

        per_node_jobs = {n: 0 for n in EXEC_NODES}
        for (_, _, exec_, _, _) in started:
            if exec_ in per_node_jobs:
                per_node_jobs[exec_] += 1

        call_by_dest = {}
        for (_, to, _, ms, ok) in calls:
            call_by_dest.setdefault(to, []).append(ms)

        storage_by_op = {}
        for (_, op, area, ms, ok) in sops:
            storage_by_op.setdefault(op, []).append(ms)

        request_failures = sum(1 for (_, t, result, _) in greqs if result != "OK")

        upload_ms = [m for (_, _, m, _, ok) in uploads if ok]
        request_ms = [m for (_, _, m, _, ok) in requests if ok]
        window_minutes = max((t1 - t0) / 60000.0, 1e-9)

        return {
            "t0": t0, "t1": t1,
            "jobs_submitted": len(jobs_submitted),
            "jobs_completed": len(jobs_completed),
            "jobs_lost": len(jobs_lost),
            "throughput_per_min": len(jobs_completed) / window_minutes,
            "latency_p50": percentile(latencies, 50),
            "latency_p95": percentile(latencies, 95),
            "latency_mean": mean(latencies),
            "queue_wait_mean": mean(wait_ms_list),
            "run_time_mean": mean(run_ms_list),
            "queue_len_max": max(queue_list) if queue_list else None,
            "queue_len_mean": mean(queue_list),
            "accuracy_pct": accuracy,
            "upload_p50": percentile(upload_ms, 50),
            "upload_p95": percentile(upload_ms, 95),
            "request_p50": percentile(request_ms, 50),
            "request_p95": percentile(request_ms, 95),
            "storage_by_op": {op: {"mean": mean(v), "p95": percentile(v, 95)}
                               for op, v in storage_by_op.items()},
            "call_by_dest": {dest: {"mean": mean(v), "p95": percentile(v, 95)}
                               for dest, v in call_by_dest.items()},
            "request_failures": request_failures,
            "node_failed_count": len(node_failed),
            "per_node_jobs": per_node_jobs,
        }
