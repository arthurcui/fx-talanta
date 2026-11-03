"""Bounded NTP measurement, never clock adjustment or a broker-clock inference."""

import math
import socket
import struct
import time
from datetime import UTC, datetime

EPOCH = 2208988800


def packet(at):
    value = at + EPOCH
    stamp = struct.pack("!II", int(value), int((value % 1) * 2**32))
    return bytes([0x23]) + bytes(39) + stamp


def decode(response, request, sent, received, monotonic_elapsed):
    if (
        len(response) < 48
        or response[0] & 7 != 4
        or response[0] >> 6 == 3
        or not 1 <= response[1] <= 15
        or response[24:32] != request[40:48]
    ):
        raise ValueError("invalid clock response")
    if abs((received - sent) - monotonic_elapsed) > 0.01:
        raise ValueError("host clock changed during measurement")

    def stamp(offset):
        whole, fraction = struct.unpack("!II", response[offset : offset + 8])
        return whole - EPOCH + fraction / 2**32

    server_receive, server_send = stamp(32), stamp(40)
    delay = (received - sent) - (server_send - server_receive)
    offset = ((server_receive - sent) + (server_send - received)) / 2
    root_delay = struct.unpack("!i", response[4:8])[0] / 65536
    dispersion = struct.unpack("!I", response[8:12])[0] / 65536
    if not all(map(math.isfinite, (delay, offset))) or not 0 <= delay <= 2:
        raise ValueError("invalid clock timing")
    # Network asymmetry bounded by RTT/2; retain an additional 1 ms measurement guard.
    return {
        "offset_ms": offset * 1000,
        "round_trip_ms": delay * 1000,
        "error_bound_ms": (abs(offset) + delay / 2 + max(0, root_delay) / 2 + dispersion) * 1000
        + 1,
    }


def probe():
    sources = []
    for host in ("time.windows.com", "time.cloudflare.com"):
        samples = []
        for _ in range(2):
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(2)
                client.connect((host, 123))
                began = time.monotonic()
                sent = time.time()
                request = packet(sent)
                client.send(request)
                response = client.recv(512)
                received = time.time()
                samples.append(decode(response, request, sent, received, time.monotonic() - began))
        sources.append(
            {
                "reference": host,
                "samples": samples,
                "error_bound_ms": min(s["error_bound_ms"] for s in samples),
            }
        )
    bound = max(s["error_bound_ms"] for s in sources)
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "sources": sources,
        "error_bound_ms": bound,
        "passed": bound <= 100,
        "limitation": (
            "Unauthenticated NTP corroboration; bounded observation, "
            "not long-term clock qualification"
        ),
    }
