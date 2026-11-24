# fisclient.py -- course staff file, do not modify.
#
# A thin wrapper around the compiled "fis" client binary. Every bit of
# normal activity the monitor plays goes through here, never through the
# wire protocol directly, so that a student's redesign of the protocol or
# the client is exercised honestly.

import itertools
import os
import subprocess
import time

import users

BIN = "/app/bin/fis"
SESSION_DIR = "/tmp/fis-sessions"
FILES_DIR = "/tmp/fis-files"

os.makedirs(SESSION_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)


def _env(user):
    env = dict(os.environ)
    env["FIS_GATEWAY"] = os.environ.get("FIS_GATEWAY", "gateway")
    env["FIS_SESSION"] = f"{SESSION_DIR}/{user}.session"
    return env


def _run(user, args, timeout=20.0):
    start = time.monotonic()
    try:
        r = subprocess.run([BIN] + args, env=_env(user), capture_output=True,
                            text=True, timeout=timeout)
        ms = (time.monotonic() - start) * 1000.0
        return r.returncode, r.stdout, r.stderr, ms
    except subprocess.TimeoutExpired:
        ms = (time.monotonic() - start) * 1000.0
        return 124, "", "client timed out", ms


def login(user, password):
    return _run(user, ["login", user, password])


def is_logged_in(user):
    return os.path.exists(f"{SESSION_DIR}/{user}.session")


def _run_with_relogin(user, args, timeout=20.0):
    """Run a non-login command; if it fails, log back in (the session may
    have been lost -- e.g. the gateway restarted after a hostile event) and
    retry the command exactly once. The reported latency includes the whole
    retry sequence, since that is how long a real client actually took.
    Like every latency this module returns, it is in real milliseconds; the
    callers convert it to simulated time."""
    rc, out, err, ms = _run(user, args, timeout)
    if rc == 0:
        return rc, out, err, ms
    acct = users.ACCOUNTS.get(user)
    if acct is None:
        return rc, out, err, ms
    lrc, lout, lerr, lms = login(user, acct["password"])
    rrc, rout, rerr, rms = _run(user, args, timeout)
    total_ms = ms + lms + rms
    return rrc, rout, rerr, total_ms


def write_local_file(user, name, content_bytes):
    path = os.path.join(FILES_DIR, user)
    os.makedirs(path, exist_ok=True)
    full = os.path.join(path, name)
    with open(full, "wb") as f:
        f.write(content_bytes)
    return full


_script_counter = itertools.count(1)


def write_script(user, lines):
    """Each script gets its own file, because several events of one user can
    be submitting at the same moment."""
    folder = os.path.join(FILES_DIR, user)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"script-{next(_script_counter)}.txt")
    with open(path, "w", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def upload(user, local_path):
    return _run_with_relogin(user, ["upload", local_path])


def submit(user, script_path):
    return _run_with_relogin(user, ["submit", script_path])


def status(user, job):
    return _run_with_relogin(user, ["status", str(job)])


def result(user, job):
    return _run_with_relogin(user, ["result", str(job)])


def request(user, filename):
    return _run_with_relogin(user, ["request", filename])
