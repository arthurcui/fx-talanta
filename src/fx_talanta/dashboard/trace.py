"""Explicit reference traversal for offline inspection; correlation is not causality."""

import hashlib
from uuid import UUID

from fx_talanta.advisor.evidence import FIELDS


def trace(snapshot, record_id):
    target = UUID(record_id)
    index = {r.record_id: r for r in snapshot.records}
    if target not in index or index[target].body.kind not in FIELDS:
        raise ValueError("record unavailable in inspection scope")
    edges = set()
    for r in snapshot.records:
        for link in r.references:
            edges.add((r.record_id, link.record_id, link.relation))
        if r.supersedes:
            edges.add((r.record_id, r.supersedes, "SUPERSEDES"))
        if r.body.kind == "lesson":
            for rid in r.body.supporting_cases:
                edges.add((r.record_id, rid, "SUPPORTING_CASE"))
            for rid in r.body.contradicting_cases:
                edges.add((r.record_id, rid, "CONTRADICTING_CASE"))
    # Only explicit links connect components. Missing nodes cannot bridge components.
    visited, pending = set(), [target]
    adjacent = {}
    for a, b, _ in edges:
        if a in index and b in index:
            adjacent.setdefault(a, set()).add(b)
            adjacent.setdefault(b, set()).add(a)
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacent.get(current, set()) - visited)
    links = sorted((a, b, rel) for a, b, rel in edges if a in visited or b in visited)
    nodes = []
    for r in sorted((index[i] for i in visited), key=lambda r: (r.recorded_at, str(r.record_id))):
        body = r.body.model_dump(mode="json")
        nodes.append(
            dict(
                id=str(r.record_id),
                kind=r.body.kind,
                at=r.recorded_at.isoformat(),
                provenance=r.provenance,
                details_available=r.body.kind in FIELDS,
                facts={k: body[k] for k in FIELDS.get(r.body.kind, ())},
                sha256=hashlib.sha256(r.model_dump_json().encode()).hexdigest(),
            )
        )
    return dict(
        root=str(target),
        cutoff=snapshot.captured_at.isoformat(),
        scope="EXPLICIT_REFERENCES_ONLY_NOT_PROOF_OF_EXECUTION",
        nodes=nodes,
        links=[
            dict(source=str(a), target=str(b), relation=rel, resolved=a in index and b in index)
            for a, b, rel in links
        ],
        missing=sorted({str(i) for a, b, _ in links for i in (a, b) if i not in index}),
        execution_enabled=False,
    )
