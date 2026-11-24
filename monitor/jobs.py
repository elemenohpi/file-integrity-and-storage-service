# jobs.py -- course staff file, do not modify.
#
# Submits scripts through the real "fis" client and tracks them to
# completion (or loss), filling in the JobRecord the dashboard and the CSV
# files read from.

import threading
import time

import fisclient


def parse_job_number(stdout):
    for tok in stdout.split():
        if tok.isdigit():
            return int(tok)
    return None


def _script_commands(script_lines):
    """[(command, name), ...] for each non-empty script line, matching the
    "<command> <name>" format execnode.cpp parses."""
    out = []
    for line in script_lines or []:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        cmd = parts[0]
        name = parts[1].strip() if len(parts) > 1 else ""
        out.append((cmd, name))
    return out


def _windows_overlap(a0, a1, b0, b1):
    return a0 <= b1 and b0 <= a1


def score_verdicts(state, rec):
    """Compare the job's output against the expected verdict lines.

    A "check" line's verdict depends on the file's content *at the moment
    the job actually ran* on its exec node, not at submit time. Jobs can sit
    queued for minutes, so if the checked name was re-uploaded by the same
    account, or touched by an employee add/modify/remove job, any time
    between this job's submit and its done, the "wrong" verdict may simply
    be the server being correct about a file that changed mid-flight. Such
    lines are excluded from the accuracy count and reported separately as
    "ambiguous" rather than scored as wrong.
    """
    out_lines = [l.strip() for l in (rec.output or "").splitlines() if l.strip()]
    check_names = {name for (cmd, name) in _script_commands(rec.script) if cmd == "check"}

    window0 = rec.submit_sim_ms
    window1 = rec.done_sim_ms if rec.done_sim_ms is not None else rec.submit_sim_ms

    with state.lock:
        uploads = list(state.uploads_named)
        other_jobs = [j for j in state.jobs.values() if j is not rec]

    def is_ambiguous(name):
        for (t, u, n) in uploads:
            if n == name and u == rec.user and window0 <= t <= window1:
                return True
        for j in other_jobs:
            if j.done_sim_ms is None:
                continue
            touches = any(c in ("add", "modify", "remove") and n == name
                           for (c, n) in _script_commands(j.script))
            if touches and _windows_overlap(window0, window1, j.submit_sim_ms, j.done_sim_ms):
                return True
        return False

    correct = 0
    total = 0
    ambiguous = 0
    for i, exp in enumerate(rec.expect or []):
        exp_name = exp.split(":", 1)[0].strip() if ":" in exp else None
        got = out_lines[i] if i < len(out_lines) else None
        if exp_name in check_names and is_ambiguous(exp_name):
            ambiguous += 1
            continue
        total += 1
        if got == exp:
            correct += 1
    return correct, total, ambiguous


def submit_only(state, user, script_lines, expect_lines=None):
    rec = state.new_job(user, script_lines, expect_lines or [])
    script_path = fisclient.write_script(user, script_lines)
    rc, out, err, ms = fisclient.submit(user, script_path)
    if rc != 0:
        state.mark_lost(rec)
        return rec
    baseline_job = parse_job_number(out)
    rec.baseline_job = baseline_job
    if baseline_job is None:
        state.mark_lost(rec)
    return rec


def track_until_done(state, rec, timeout_sim_ms=600000, poll_sim_s=2.0):
    if rec.state == "lost" or rec.baseline_job is None:
        return rec
    deadline_sim_ms = rec.submit_sim_ms + timeout_sim_ms
    while True:
        if rec.state == "lost":   # the run ended while this job was pending
            return rec
        now = state.clock.sim_ms()
        if now > deadline_sim_ms:
            state.mark_lost(rec)
            return rec
        rc2, out2, err2, ms2 = fisclient.status(rec.user, rec.baseline_job)
        if rc2 == 0 and out2.strip() == "done":
            rc3, out3, err3, ms3 = fisclient.result(rec.user, rec.baseline_job)
            if rc3 == 0:
                with state.lock:
                    if rec.state == "lost":
                        return rec
                    rec.output = out3
                    rec.done_sim_ms = state.clock.sim_ms()
                    rec.latency_ms = rec.done_sim_ms - rec.submit_sim_ms
                    rec.correct, rec.total_lines, rec.ambiguous = score_verdicts(state, rec)
                    rec.state = "done"
            else:
                state.mark_lost(rec)
            return rec
        time.sleep(max(0.1, poll_sim_s / max(state.clock.speed, 0.1)))


def submit_and_track(state, user, script_lines, expect_lines=None,
                      timeout_sim_ms=600000, poll_sim_s=2.0):
    rec = submit_only(state, user, script_lines, expect_lines)
    return track_until_done(state, rec, timeout_sim_ms, poll_sim_s)


def track_async(state, rec, timeout_sim_ms=600000):
    t = threading.Thread(target=track_until_done, args=(state, rec, timeout_sim_ms), daemon=True)
    t.start()
    return t
