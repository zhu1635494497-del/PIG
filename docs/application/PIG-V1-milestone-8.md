# PIG V1 Milestone 8：Project Manifest 与 Node Search / Project Manifest and Node Search

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段实现不可变 Manifest Export 和有界结构 Search。能力可以保留，
> 但 ADR-010 后不再是 Workbench V1 的主流程或验收中心。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-14 / Date: 2026-09-14
- 范围：Structural/Metadata Search 与 Immutable Project Manifest Export / Scope: structural/metadata search and immutable Project Manifest export
- 架构决策 / Architecture decision: `ADR-006`

## 1. Goal and closed loops

Search:

```text
SearchNodesRequest
  -> validate Project database/workspace identity
  -> apply literal text and typed filters in SQLite
  -> return bounded deterministic Node hits with direct parent context
```

Manifest:

```text
ExportManifestRequest
  -> persist MANIFEST_EXPORT_REQUESTED
  -> read one Project database snapshot
  -> serialize explicit Catalog/Relationship/Lineage/History data
  -> bounded staging and immutable publication
  -> persist MANIFEST_EXPORTED or MANIFEST_EXPORT_FAILED
  -> return structured export identity, path, size, and SHA-256
```

Neither path reads or changes Original Source bytes. Search has no filesystem
side effect; Manifest writes only inside the owning Project Workspace.

## 2. Application contracts

`SearchNodesRequest` provides project/database identity, optional literal query,
optional Source, kind/format/status filters, limit, and offset.
`SearchNodesResult` provides total matches, pagination state, Node values, direct
parent IDs, and Relationship types.

`ExportManifestRequest` accepts only project/database identity and actor. It does
not accept an output path. `ExportManifestResult` returns Manifest ID, schema
version, generated time, project-relative storage key, resolved Workspace path,
size, SHA-256, and included-Event boundary.

These are stable in-process Application Query/Action contracts suitable for a
future Desktop UI or Tool adapter. No Tool or transport protocol is added now.

## 3. Repository boundary

`CatalogRepository` adds project-wide ordered reads for Artifacts,
Relationships, Lineage, and Metadata plus one bounded `search_nodes` query.
Filtering is executed by SQLite rather than by loading the whole Project into
Application memory.

Search text covers:

- `original_name`;
- `display_name`;
- `logical_path`;
- `NodeMetadata.value_text` when `value_type=TEXT`.

It does not inspect document/email bodies, extracted file bytes, arbitrary JSON
Metadata, or external Source content.

## 4. Manifest schema 1.0

The UTF-8 JSON document contains top-level schema identity, Manifest identity,
generation time, Event boundary, counts, Project, Sources, Nodes, Artifacts,
Relationships, Lineage, Metadata, and grouped processing history.

Direct Relationships and Lineage are both exported. The consumer never needs to
reconstruct business ancestry from a UI tree. Typed Metadata is exported as
`value_type` plus one normalized `value`. All collections use repository-defined
stable ordering.

The snapshot includes its request Event but not the later success Event. The
result and success Event expose the snapshot hash and boundary.

## 5. Workspace and publication

Approved layout:

```text
<project>/
  project.sqlite
  artifacts/...
  manifests/
    <manifest-id>.json
```

`manifests` is created only on first successful staging attempt. Existing
Manifest IDs cannot be replaced. Failed or rolled-back operations remove only
their own staging/final path and preserve previous snapshots.

## 6. State, Event, and error behavior

Search changes no Project, Source, Node, Job, Attempt, or Artifact state and
emits no business Event.

Manifest export also changes no processing state. Its history is:

```text
MANIFEST_EXPORT_REQUESTED
  -> MANIFEST_EXPORTED
  |  MANIFEST_EXPORT_FAILED
```

Configured byte overflow uses `MANIFEST_SIZE_EXCEEDED`; other export failures use
`MANIFEST_EXPORT_FAILED`. Both are constrained database error codes through
Alembic revision `0003`.

## 7. Security and permissions

- Both capabilities verify that the supplied database belongs to the requested
  Project Workspace.
- Search query/page limits are centralized in immutable `CatalogPolicy`.
- SQL wildcard characters are escaped; filters use typed enums.
- Manifest caller input cannot choose a physical path.
- Workspace, Manifest, and staging directories reject symbolic links.
- Staging/final collisions never overwrite or delete accepted bytes.
- Publication is bounded, hashed, flushed, and no-overwrite.

## 8. Persistence

No search index/table, Manifest table, or FTS virtual table is introduced.
Revision `0003` only extends the constrained Attempt/Event error-code vocabulary.
Export identity and hash are retained in append-only Processing Events.

## 9. Verification

Tests cover:

- Chinese and ASCII case-insensitive filename/Logical Path search;
- literal `%` wildcard handling;
- Source, kind, format, and status filters;
- deterministic bounded pagination and parent Relationship context;
- text Metadata search without body/content search;
- read-only Search with no added Event;
- complete Manifest collections, typed Metadata, direct Relationship, multi-level
  Lineage, processing history, and explicit Event boundary;
- SHA-256/size result consistency and unchanged Original bytes;
- multiple immutable snapshots without overwrite;
- Manifest size failure Event and zero residual output;
- staging/final collision safety and rollback cleanup;
- Alembic upgrade, metadata consistency, and downgrade compatibility;
- full Milestone 1–7 regression compatibility.

## 10. Explicitly deferred

Now not implemented:

- PySide6 Evidence Tree, filters, double-click open, or any UI (Milestone 9);
- controlled OS file opening (Milestone 9 under D8);
- interrupted export recovery, orphan reconciliation, retention, streaming JSON,
  performance qualification, and packaging (Milestone 10);
- FTS5, document/email-body content indexing, OCR, ranking, fuzzy/semantic/vector
  search, snippets, or previews;
- external destination/redacted Manifest export, CSV/XML variants, signing, or
  import-from-Manifest;
- public Tool/MCP adapter, Workflow/Automation engine, AI, RAG, Graph DB, Vector
  DB, or distributed workers.
