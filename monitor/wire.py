# wire.py -- course staff file, do not modify.
#
# The *baseline* wire protocol (see handout/src/common.h / common.cpp),
# spoken raw and only for hostile events. Normal activity must never use
# this module -- it must go through the compiled "fis" client (fisclient.py)
# so that a student's redesign of the protocol is exercised honestly. If a
# student changes the protocol, a raw message built here will simply fail
# to be understood, and the hostile event that used it counts as blocked.

import socket

_FIELDS = [
    ("type", 16), ("sender", 32), ("token", 64), ("name", 128),
    ("arg", 64), ("length", 16), ("reserved", 192),
]
HEADER_SIZE = sum(size for _, size in _FIELDS)  # 512


def _pad(text, size):
    if size <= 0:
        return b""
    data = text.encode("utf-8", "replace")[:max(size - 1, 0)]
    return data + b"\x00" * (size - len(data))


def build_header(type_, sender="", token="", name="", arg="", length_text=None, data_len=0):
    if length_text is None:
        length_text = str(data_len)
    chunks = [
        _pad(type_, 16), _pad(sender, 32), _pad(token, 64),
        _pad(name, 128), _pad(arg, 64), _pad(length_text, 16),
        b"\x00" * 192,
    ]
    return b"".join(chunks)


def _recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            break
        buf += chunk
    return bytes(buf)


def recv_message(sock):
    header = _recv_exact(sock, HEADER_SIZE)
    if len(header) < HEADER_SIZE:
        return None
    fields = {}
    off = 0
    for fname, size in _FIELDS:
        raw = header[off:off + size]
        off += size
        fields[fname] = raw.split(b"\x00", 1)[0].decode("utf-8", "replace")
    try:
        length = int(fields.get("length", "0") or "0")
    except ValueError:
        length = 0
    if length < 0 or length > 64 * 1024 * 1024:
        return {**fields, "data": b""}
    data = _recv_exact(sock, length) if length > 0 else b""
    fields["data"] = data
    return fields


def call(host, port, type_, sender="monitor", token="", name="", arg="", data=b"",
         timeout=5.0, length_text=None, expect_reply=True):
    """Sends one raw message and (optionally) waits for a reply. Returns the
    reply dict, or None if the connection failed or no reply came back
    (which also counts as the target not understanding / not responding --
    used by hostile events to detect that the attack was blocked)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            header = build_header(type_, sender, token, name, arg, length_text, len(data))
            sock.sendall(header)
            if length_text is None:
                sock.sendall(data)
            if not expect_reply:
                return {"ok": True}
            return recv_message(sock)
    except OSError:
        return None
