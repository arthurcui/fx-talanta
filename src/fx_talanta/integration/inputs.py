"""Resolve account-bound operating facts from retained, content-addressed artifacts.

Hashes establish integrity, not economic/broker qualification. This API is a
trusted operator ingestion boundary, never a model-writable HTTP endpoint.
"""

import json
from pathlib import Path

from fx_talanta.connected_shadow.inputs import GROUPS, canonical_hash, normalize


def load_context(directory: Path, references: dict, scope: str, now_ms: int):
    values, hashes, missing = {}, {}, []
    starts, ends = [], []
    for group, fields in GROUPS.items():
        reference = references.get(group)
        if (
            not isinstance(reference, str)
            or len(reference) != 64
            or any(c not in "0123456789abcdef" for c in reference)
        ):
            missing.append(group.upper() + "_MISSING")
            continue
        path = directory / (reference + ".json")
        if not path.is_file():
            missing.append(group.upper() + "_MISSING")
            continue
        if path.stat().st_size > 65536:
            raise ValueError("OPERATIONAL_ARTIFACT_TOO_LARGE")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        if canonical_hash(artifact) != reference:
            raise ValueError("OPERATIONAL_ARTIFACT_HASH")
        if set(artifact) != {
            "schema",
            "group",
            "account_scope",
            "observed_at_ms",
            "valid_until_ms",
            "values",
            "sources",
        }:
            raise ValueError("OPERATIONAL_ARTIFACT_SCHEMA")
        if (
            artifact["schema"] != "operating-facts/1"
            or artifact["group"] != group
            or artifact["account_scope"] != scope
            or set(artifact["values"]) != fields
        ):
            raise ValueError("OPERATIONAL_ARTIFACT_BINDING")
        start, end = artifact["observed_at_ms"], artifact["valid_until_ms"]
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end
            or end - start > 60000
        ):
            raise ValueError("OPERATIONAL_ARTIFACT_INTERVAL")
        if not start <= now_ms < end:
            missing.append(group.upper() + "_STALE_OR_FUTURE")
            continue
        sources = artifact["sources"]
        if not isinstance(sources, list) or not 1 <= len(sources) <= 32:
            raise ValueError("OPERATIONAL_SOURCE_REQUIRED")
        # Retained source bytes must exist, not just a plausible-looking hash.
        import hashlib

        for source in sources:
            if (
                not isinstance(source, str)
                or len(source) != 64
                or any(c not in "0123456789abcdef" for c in source)
            ):
                raise ValueError("OPERATIONAL_SOURCE_REFERENCE")
            raw = directory / (source + ".source")
            if not raw.is_file() or raw.stat().st_size > 8_000_000:
                raise ValueError("OPERATIONAL_SOURCE_UNAVAILABLE")
            if hashlib.sha256(raw.read_bytes()).hexdigest() != source:
                raise ValueError("OPERATIONAL_SOURCE_HASH")
        values.update(artifact["values"])
        hashes[group] = reference
        starts.append(start)
        ends.append(end)
    if missing:
        return None, tuple(missing)
    return dict(
        account_scope=scope,
        observed_at_ms=max(starts),
        valid_until_ms=min(ends),
        values=values,
        evidence=hashes,
    ), ()


def assemble(capture, directory, references, *, symbol, side, now_ms):
    if (
        type(now_ms) is not int
        or now_ms < capture["measured_at_ms"]
        or now_ms - capture["measured_at_ms"] > 60000
    ):
        raise ValueError("CAPTURE_TIME_INVALID")
    context, missing = load_context(directory, references, capture["account_scope"], now_ms)
    # normalize validates the original capture digest and preserves mapping gaps.
    result = normalize(capture, symbol=symbol, side=side, context=context)
    return result, missing
