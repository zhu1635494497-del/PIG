# ADR-006：不可变 Manifest 与结构搜索 / Immutable Manifest Exports and Structural Search

- 状态：历史记录，不再是 Workbench 验收中心 / Status: Historical; no longer a V1 Workbench acceptance anchor
- 决策日期：2026-09-14 / Decision date: 2026-09-14
- 范围：PIG V1 Milestone 8 / Scope: PIG V1 Milestone 8
- 已批准 Manifest Workspace 方案：A / Approved Manifest workspace option: A

## Context

> 中文摘要：旧 V1 将 Manifest 作为不可覆盖的 Project Derived Output，并提供有界
> Structural Search。两者可以作为内部能力保留，但 ADR-010 后不再驱动 V1 主流程。

Milestone 8 must make the persisted Project Data Layer usable without a UI. It
adds two capabilities: bounded Node search and an exportable Project Manifest.
The Manifest is derived data and needs a real Workspace location. The Milestone
3 baseline intentionally deferred that layout until a milestone owned real
output there.

## Decision: Manifest workspace

The product owner selected Option A:

```text
<project>/manifests/<manifest-id>.json
```

- Every export receives a safe generated ID and creates a new file. Existing
  Manifest bytes are never overwritten.
- Staging occurs under `<project>/manifests/.staging/`. Publication uses an
  atomic, no-overwrite same-filesystem link operation, followed by removal of
  the staging name.
- A bounded UTF-8 JSON payload is hashed before publication. The result Event
  records Manifest ID, project-relative storage key, byte size, SHA-256, schema
  version, included Event count, and last included Event ID.
- The Application commits `MANIFEST_EXPORT_REQUESTED` before snapshot creation.
  It commits exactly one `MANIFEST_EXPORTED` or `MANIFEST_EXPORT_FAILED` terminal
  event for normal in-process outcomes. A process crash between those commits
  remains detectable but requires Milestone 10 recovery.
- Filesystem publication and SQLite do not share a transaction. Until the
  success transaction commits, the write session owns and removes its exact
  output on rollback. Crash-orphan reconciliation remains Milestone 10 scope.

## Decision: Manifest data contract

Schema name is `pig.project-manifest`; initial schema version is `1.0`.
Schema versioning is independent of `Project.model_version`.

The snapshot contains:

- Project;
- Sources and root assignments;
- Nodes and current processing status;
- Artifacts and integrity status;
- direct structural Relationships;
- persisted Lineage closure;
- typed Node Metadata;
- Processing Jobs, Attempts, errors, and Events;
- collection counts and an explicit included-Event boundary.

The success Event is necessarily outside the JSON snapshot that it describes.
The preceding request Event is included. Source and Artifact locators are
included because V1 Manifest is an evidence/catalog export, not a sanitized
external sharing format. A future redacted sharing export would be a different
contract.

Manifest is not added as a Node-bound `Artifact`: it is project-level Derived
Data, while the current `Artifact` invariant requires one owning Node. In M8 its
immutable business record is the structured export Event. A separate Manifest
entity/table is deferred until a real lifecycle beyond export history exists.

Export reads database facts only. It does not reopen, rehash, or modify Original
Sources and does not claim that external references remained unchanged after
their last recorded verification.

## Decision: Search

`search_nodes` is a read-only, project-scoped Application Query with bounded
offset pagination. It supports:

- literal substring search across original name, display name, Logical Path,
  and text-typed Node Metadata;
- filters for Source, Node kind, format, and current processing status;
- deterministic ordering by Logical Path and Node ID;
- direct parent ID and Relationship type in each hit.

SQL wildcard characters in user input are escaped and treated literally.
Search does not write an Event because it is a low-risk read, not a durable
business state change.

SQLite FTS5, a search table, content extraction, ranking, fuzzy matching,
stemming, OCR, and semantic/vector search are not introduced. The current
maximum Project Node count makes ordinary SQLite queries an acceptable M8
baseline; measurement and indexing changes belong to Milestone 10 if evidence
requires them.

## Security and limits

- Database/project identity and Workspace locator must match before either
  capability runs.
- Callers cannot supply a Manifest destination or filename.
- `CatalogPolicy` centrally bounds query length, page size, and Manifest bytes.
- Manifest and staging directories must be real directories, not symbolic
  links. ID collisions fail without removing or replacing existing bytes.
- JSON serialization rejects non-finite numeric values and normalizes timestamps
  to UTC ISO-8601.

## Consequences and debt

- Historical Manifest snapshots consume disk until a separately authorized
  retention policy exists.
- Large snapshots are currently assembled in memory before bounded write;
  streaming serialization is deferred to Milestone 10 performance work.
- SQLite case-insensitive matching is reliable for ASCII case folding; richer
  locale-aware collation is deferred until a concrete requirement exists.
- Filesystems without hard-link support return a structured export failure.
  Cross-platform packaging qualification may add a safe no-overwrite fallback
  through a future ADR if real deployment evidence requires it.
