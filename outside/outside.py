#!/usr/bin/env python3
# outside.py -- course staff file, do not modify.
#
# "A computer on the internet that has nothing to do with the service."
# Port 8080: accepts any TCP connection and records everything sent to it
#   (used by the hostile "exfiltrate" event: data leaving the service and
#   landing here is evidence of a leak).
# Port 8081: GET /stats returns what has been seen, as JSON, so the monitor
#   can tell whether data left the system.
#
# Standard library only.

import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT = 8080
STATS_PORT = 8081

MARK_RE = re.compile(rb"MARK-[A-Za-z0-9_]+-[0-9a-fA-F]{8}")

lock = threading.Lock()
state = {
    "connections": 0,
    "bytes_total": 0,
    "markers": [],       # list of unique marker strings seen, in order
    "last_seen_ts": None,
    "events": [],        # recent (ts, remote, bytes) tuples, capped
}


def record(remote, data):
    with lock:
        state["connections"] += 1
        state["bytes_total"] += len(data)
        state["last_seen_ts"] = int(time.time() * 1000)
        for m in MARK_RE.findall(data):
            marker = m.decode("ascii", "replace")
            if marker not in state["markers"]:
                state["markers"].append(marker)
        state["events"].append({
            "ts": state["last_seen_ts"],
            "remote": remote,
            "bytes": len(data),
        })
        if len(state["events"]) > 500:
            state["events"] = state["events"][-500:]


def handle_connection(conn, addr):
    try:
        conn.settimeout(30)
        chunks = []
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            pass
        data = b"".join(chunks)
        if data:
            record(f"{addr[0]}:{addr[1]}", data)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def serve_listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", LISTEN_PORT))
    srv.listen(64)
    while True:
        conn, addr = srv.accept()
        t = threading.Thread(target=handle_connection, args=(conn, addr), daemon=True)
        t.start()


class StatsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep the container log quiet

    def do_GET(self):
        if self.path != "/stats":
            self.send_response(404)
            self.end_headers()
            return
        with lock:
            body = json.dumps(state).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def serve_stats():
    srv = ThreadingHTTPServer(("0.0.0.0", STATS_PORT), StatsHandler)
    srv.serve_forever()


if __name__ == "__main__":
    t1 = threading.Thread(target=serve_listener, daemon=True)
    t1.start()
    serve_stats()
