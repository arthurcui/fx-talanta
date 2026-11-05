"""Deterministic compressed audit streams with fixed memory and disk bounds."""

import gzip
import json
from decimal import Decimal
from hashlib import sha256

MAX_LINE = 2 * 1024 * 1024
MAX_RAW = 8 * 1024**3
MAX_COMPRESSED = 512 * 1024**2


def file_hash(path):
    result = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


class Spool:
    def __init__(self, path):
        self.path = path
        self.raw = path.open("xb")
        self.stream = gzip.GzipFile(
            filename="", fileobj=self.raw, mode="wb", compresslevel=1, mtime=0
        )
        self.count, self.bytes, self.last = 0, 0, None
        self.digest = sha256()

    def append(self, value):
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if (
            len(encoded) > MAX_LINE
            or self.bytes + len(encoded) > MAX_RAW
            or self.raw.tell() > MAX_COMPRESSED
        ):
            raise ValueError("audit spool size bound exceeded")
        self.stream.write(encoded)
        self.digest.update(encoded)
        self.count += 1
        self.bytes += len(encoded)
        self.last = value

    def __getitem__(self, index):
        if index != -1 or self.last is None:
            raise IndexError("only the last audit record is retained in memory")
        return self.last

    def close(self):
        self.stream.close()
        self.raw.close()
        if self.path.stat().st_size > MAX_COMPRESSED:
            raise ValueError("compressed audit bound exceeded")

    def receipt(self):
        if not self.raw.closed:
            raise ValueError("close spool before certifying it")
        return {
            "file": self.path.name,
            "rows": self.count,
            "raw_bytes": self.bytes,
            "raw_sha256": self.digest.hexdigest(),
            "sha256": file_hash(self.path),
        }


class EquitySpool(Spool):
    def __init__(self, path, capital):
        super().__init__(path)
        self.peak, self.drawdown = capital, Decimal(0)

    def append(self, value):
        super().append(value)
        equity = Decimal(value["equity"])
        self.peak = max(self.peak, equity)
        self.drawdown = max(self.drawdown, (self.peak - equity) / self.peak)


def rows(path):
    total = 0
    with gzip.open(path, "rb") as stream:
        while line := stream.readline(MAX_LINE + 1):
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_RAW:
                raise ValueError("audit read bound exceeded")
            yield json.loads(line)
