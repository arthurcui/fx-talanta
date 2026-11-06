# Technical documentation

Start with the product [README](../README.md). For the current implementation and
its limits, read [status](product/status.md) before using a historical milestone note.

## Understand the system

1. [Architecture walkthrough](architecture/overview.md) — components, authority,
   evidence and failure behavior across one decision.
2. [Repository layout](architecture/repository-layout.md) — runtime, research,
   development tools, tests and the path migration map.
3. [Roadmap](product/roadmap.md) — milestone boundaries and remaining acceptance.
4. [Architecture specification](architecture/specification.md) — detailed contracts
   and acceptance requirements; [execution boundary](architecture/execution-boundary.md)
   expands the fixed-EA design and [ADR 001](adr/001-fixed-ea-execution.md) records why.

## Run and develop

- [Offline quick start](guides/getting-started.md): Windows, Unix, containers and archive transfer.
- [Read-only dashboard](guides/dashboard.md): local UI, evidence chat, timing and calendar upload.
- [Development guide](guides/development.md): checks, packaging, native tests and contribution rules.
- [Operating guides](operations/README.md): read-only observation, calendar upload,
  demo account rollover and channel setup. A guide is not authorization to trade.

## Assess the evidence

- [Evidence index](evidence/README.md): actual demo execution, source qualification,
  independent results and the distinction between fixture and broker evidence.
- [Implementation notes](engineering/README.md): current technical interfaces and detailed gate reports.
- [Historical record](history/README.md): earlier milestone reports, investigations
  and retired approaches, preserved for traceability rather than deployment instructions.

## Documentation ownership

The product README is the introduction. `product/status.md` owns the current status;
`product/roadmap.md` summarizes progression; the architecture specification owns detailed
requirements. Operating guides own runnable procedures. Implementation reports describe
their recorded window and never silently supersede failed evidence.

When a change affects behavior, update the relevant guide and current status in the
same PR. Add evidence rather than rewriting an old result. Keep private credentials,
account identifiers, raw captures and local journals out of public documents.
