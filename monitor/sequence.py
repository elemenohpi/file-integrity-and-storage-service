# sequence.py -- course staff file, do not modify.
#
# Loads a sequence file and plays it: each event fires at its simulated
# time in its own thread, so a slow event (or a slow system) never delays
# the ones after it.

import json
import threading

import filesgen
import fisclient
import hostile
import jobs
import users


def load_sequence(path):
    with open(path, "r", encoding="utf-8") as f:
        lines = [l for l in f if l.strip()]
    header = json.loads(lines[0])
    events = [json.loads(l) for l in lines[1:]]
    return header, events


def ensure_login(state, logged_in, user):
    with state.lock:
        if user in logged_in:
            return True
    acct = users.ACCOUNTS.get(user)
    if acct is None:
        return False
    rc, out, err, ms = fisclient.login(user, acct["password"])
    if rc == 0:
        with state.lock:
            logged_in.add(user)
        return True
    return False


def do_upload(state, logged_in, event):
    user = event["user"]
    if not ensure_login(state, logged_in, user):
        return
    content = filesgen.content_for_event(event, owner=user)
    path = fisclient.write_local_file(user, event["file"], content)
    rc, out, err, ms = fisclient.upload(user, path)
    state.add_upload_lat(state.clock.sim_ms(), user, ms * state.clock.speed, len(content),
                         rc == 0, name=event["file"])


def do_submit(state, logged_in, event):
    user = event["user"]
    if not ensure_login(state, logged_in, user):
        return
    jobs.submit_and_track(state, user, event["script"], event.get("expect"))


def do_request(state, logged_in, event):
    user = event["user"]
    if not ensure_login(state, logged_in, user):
        return
    rc, out, err, ms = fisclient.request(user, event["file"])
    state.add_request_lat(state.clock.sim_ms(), user, ms * state.clock.speed, len(out or ""),
                          rc == 0)


def fire_event(state, logged_in, event, docker_client):
    try:
        do = event.get("do")
        if do == "upload":
            do_upload(state, logged_in, event)
        elif do == "submit":
            do_submit(state, logged_in, event)
        elif do == "request":
            do_request(state, logged_in, event)
        elif do == "hostile":
            user = event.get("user")
            if user:
                ensure_login(state, logged_in, user)
            hostile.run_hostile(state, logged_in, event, docker_client)
    except Exception as exc:
        state.add_hostile({
            "t_sim": state.clock.sim_ms(), "t_event": event.get("t"),
            "kind": "monitor_error", "description": f"error firing a '{event.get('do')}' event: {exc}",
            "outcome": "error", "evidence": str(exc),
        })
    finally:
        with state.lock:
            state.sequence_fired_events += 1


def play_sequence(state, events, docker_client):
    logged_in = set()
    threads = []
    with state.lock:
        state.sequence_total_events = len(events)

    for event in events:
        target_ms = float(event["t"]) * 1000.0

        def runner(ev=event, target_ms=target_ms):
            state.clock.sleep_until_sim_ms(target_ms)
            fire_event(state, logged_in, ev, docker_client)

        t = threading.Thread(target=runner, daemon=True)
        t.start()
        threads.append(t)
    return threads
