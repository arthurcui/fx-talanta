"""Deterministic compressed audit streams with fixed memory and disk bounds."""

import gzip
import json
import shutil
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
        self._append_encoded(value, encoded)

    def _append_encoded(self, value, encoded):
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


class SegmentedSpool:
    """Lossless long-study stream; immutable bounded parts plus a final manifest."""

    def __init__(self, path, *, segment_bytes=256 * 1024**2):
        if path.exists():
            raise FileExistsError("audit manifest already exists")
        if not MAX_LINE <= segment_bytes <= MAX_RAW:
            raise ValueError("invalid audit segment bound")
        self.path, self.segment_bytes = path, segment_bytes
        self.directory = path.with_suffix(".parts")
        self.directory.mkdir(exist_ok=False)
        self.parts = []
        self.count, self.bytes, self.last = 0, 0, None
        self.digest = sha256()
        self._open()

    def _open(self):
        if shutil.disk_usage(self.directory).free < 512 * 1024**2:
            raise ValueError("audit disk reserve exhausted")
        if len(self.parts) >= 512:
            raise ValueError("audit segment count bound exceeded")
        self.current = Spool(self.directory / f"{len(self.parts):04d}.gz")

    @property
    def raw(self):
        return self.current.raw

    def _seal(self):
        self.current.close()
        receipt = self.current.receipt()
        receipt["first_row"] = self.count - self.current.count
        self.parts.append(receipt)
        if sum((self.directory / p["file"]).stat().st_size for p in self.parts) > 8 * 1024**3:
            raise ValueError("total compressed audit bound exceeded")

    def append(self, value):
        encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
        if len(encoded) > MAX_LINE or self.bytes + len(encoded) > 128 * 1024**3:
            raise ValueError("total audit size bound exceeded")
        if self.current.count and self.current.bytes + len(encoded) > self.segment_bytes:
            self._seal()
            self._open()
        self.current._append_encoded(value, encoded)
        self.digest.update(encoded)
        self.count += 1
        self.bytes += len(encoded)
        self.last = value

    def __getitem__(self, index):
        if index != -1 or self.last is None:
            raise IndexError("only the last audit record is retained in memory")
        return self.last

    def close(self):
        self._seal()
        with self.path.open("x", encoding="utf8") as stream:
            json.dump(
                {
                    "schema": "segmented-audit/1",
                    "parts": self.parts,
                    "rows": self.count,
                    "raw_bytes": self.bytes,
                    "raw_sha256": self.digest.hexdigest(),
                },
                stream,
                sort_keys=True,
            )

    def receipt(self):
        if not self.raw.closed or not self.path.exists():
            raise ValueError("close spool before certifying it")
        return {
            "file": self.path.name,
            "rows": self.count,
            "raw_bytes": self.bytes,
            "raw_sha256": self.digest.hexdigest(),
            "sha256": file_hash(self.path),
        }


def rows(path):
    if path.suffix == ".json":
        manifest = json.loads(path.read_text(encoding="utf8"))
        parts = manifest["parts"]
        if manifest["schema"] != "segmented-audit/1" or not 1 <= len(parts) <= 512:
            raise ValueError("invalid segmented audit manifest")
        count, total, digest = 0, 0, sha256()
        compressed = 0
        for number, part in enumerate(parts):
            if part["file"] != f"{number:04d}.gz" or part["first_row"] != count:
                raise ValueError("audit segment sequence mismatch")
            child = path.with_suffix(".parts") / part["file"]
            compressed += child.stat().st_size
            if child.stat().st_size > MAX_COMPRESSED or compressed > 8 * 1024**3:
                raise ValueError("compressed audit read bound exceeded")
            if child.is_symlink() or file_hash(child) != part["sha256"]:
                raise ValueError("audit segment hash mismatch")
            n, size, segment_hash = 0, 0, sha256()
            for value in rows(child):
                encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
                n += 1
                size += len(encoded)
                digest.update(encoded)
                segment_hash.update(encoded)
                yield value
            if (n, size, segment_hash.hexdigest()) != (
                part["rows"],
                part["raw_bytes"],
                part["raw_sha256"],
            ):
                raise ValueError("audit segment receipt mismatch")
            count += n
            total += size
            if total > 128 * 1024**3:
                raise ValueError("total audit read bound exceeded")
        if (count, total, digest.hexdigest()) != (
            manifest["rows"],
            manifest["raw_bytes"],
            manifest["raw_sha256"],
        ):
            raise ValueError("audit manifest receipt mismatch")
        return
    total = 0
    with gzip.open(path, "rb") as stream:
        while line := stream.readline(MAX_LINE + 1):
            total += len(line)
            if len(line) > MAX_LINE or total > MAX_RAW:
                raise ValueError("audit read bound exceeded")
            yield json.loads(line)
