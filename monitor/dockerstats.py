# dockerstats.py -- course staff file, do not modify.
#
# Samples per-container CPU/memory/network/restarts/OOM through the mounted
# docker socket, found by the compose labels, and /work usage on each exec
# node (via docker exec, since the monitor has no other access to that
# node's filesystem). Never blocks the event-firing threads: it runs in its
# own thread and simply skips a container it cannot reach.

import threading
import time

import docker

from state import ALL_NODES, EXEC_NODES

COMPOSE_PROJECT = "fis"


def _cpu_percent(stats):
    try:
        cpu = stats["cpu_stats"]
        precpu = stats["precpu_stats"]
        cpu_delta = cpu["cpu_usage"]["total_usage"] - precpu["cpu_usage"]["total_usage"]
        sys_delta = cpu.get("system_cpu_usage", 0) - precpu.get("system_cpu_usage", 0)
        online = cpu.get("online_cpus") or len(cpu["cpu_usage"].get("percpu_usage") or [1]) or 1
        if sys_delta > 0 and cpu_delta >= 0:
            return (cpu_delta / sys_delta) * online * 100.0
    except (KeyError, TypeError, ZeroDivisionError):
        pass
    return None


def _net_bytes(stats):
    rx = tx = 0
    nets = stats.get("networks") or {}
    for info in nets.values():
        rx += info.get("rx_bytes", 0)
        tx += info.get("tx_bytes", 0)
    return rx, tx


def _work_usage_pct(container):
    try:
        res = container.exec_run(["df", "-P", "/work"], demux=False)
        text = res.output.decode("utf-8", "replace") if res.output else ""
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) >= 2:
            fields = lines[1].split()
            if len(fields) >= 5 and fields[4].endswith("%"):
                return float(fields[4][:-1])
    except Exception:
        pass
    return None


def _find_containers(client):
    found = {}
    try:
        containers = client.containers.list(all=True, filters={
            "label": f"com.docker.compose.project={COMPOSE_PROJECT}"})
    except Exception:
        return found
    for c in containers:
        service = c.labels.get("com.docker.compose.service")
        if service in ALL_NODES:
            found[service] = c
    return found


def sample_once(client, state):
    """One sample of every node. Asking Docker for the statistics of one
    container takes one to two seconds, so the nodes are asked in parallel."""
    containers = _find_containers(client)
    out = {}
    out_lock = threading.Lock()

    def sample_container(name, c):
        entry = {"status": None, "restarts": 0, "oom": False, "cpu_pct": None,
                  "mem_used": None, "mem_limit": None, "net_rx": None, "net_tx": None,
                  "work_pct": None}
        try:
            c.reload()
            entry["status"] = c.status
            attrs_state = c.attrs.get("State", {})
            entry["restarts"] = c.attrs.get("RestartCount", 0)
            entry["oom"] = bool(attrs_state.get("OOMKilled"))
        except Exception:
            pass
        try:
            if entry["status"] == "running":
                stats = c.stats(stream=False)
                entry["cpu_pct"] = _cpu_percent(stats)
                mem = stats.get("memory_stats", {})
                entry["mem_used"] = mem.get("usage")
                entry["mem_limit"] = mem.get("limit")
                rx, tx = _net_bytes(stats)
                entry["net_rx"], entry["net_tx"] = rx, tx
        except Exception:
            pass
        if name in EXEC_NODES and entry["status"] == "running":
            entry["work_pct"] = _work_usage_pct(c)
        with out_lock:
            out[name] = entry

        with state.lock:
            if entry["restarts"] > state.node_restarts.get(name, 0):
                state.node_restarts[name] = entry["restarts"]

    threads = [threading.Thread(target=sample_container, args=(name, c), daemon=True)
               for name, c in containers.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20.0)
    with out_lock:
        return dict(out)


def start_sampler(state, stop_flag, period_sim_s=8.0):
    try:
        client = docker.from_env()
    except Exception:
        client = None

    def loop():
        nonlocal client
        while not stop_flag["stop"]:
            if client is None:
                try:
                    client = docker.from_env()
                except Exception:
                    time.sleep(2.0)
                    continue
            try:
                containers = sample_once(client, state)
                state.add_docker_sample(state.clock.sim_ms(), containers)
            except Exception:
                pass
            real_sleep = max(0.5, period_sim_s / max(state.clock.speed, 0.1))
            time.sleep(real_sleep)

    threading.Thread(target=loop, daemon=True).start()


def find_container(client, name):
    found = _find_containers(client)
    return found.get(name)
