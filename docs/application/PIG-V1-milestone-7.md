# PIG V1 Milestone 7：7z 与 RAR 处理 / 7z and RAR Processing

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段增加 Pure Python 7z 与受控 System 7-Zip RAR Adapter，保存
> Backend Identity 并执行版本、路径、参数和资源限制。

- 状态：已实现 / Status: Implemented
- 日期：2026-09-14 / Date: 2026-09-14
- 范围：Deterministic 7z/RAR Inspection、Bounded Extraction、Recursion 与 Lineage / Scope: deterministic 7z/RAR inspection, bounded extraction, recursion, and lineage
- 架构决策 / Architecture decision: `ADR-005`

## 1. Goal and closed loop

Milestone 7 extends the existing processing queue without adding a second
processing framework:

```text
7z/RAR Node
  -> revalidate Source or Workspace Artifact
  -> resolve format Handler and archive backend
  -> inspect ordered member descriptors under configured limits
  -> catalog allowed and blocked Child Nodes
  -> stream each allowed member into ArtifactStore
  -> persist ARCHIVE_ENTRY relationship and lineage closure
  -> enqueue newly DISCOVERED children
  -> process nested ZIP/7z/RAR/email descendants in the same Job
```

Handlers neither recurse nor write the database. `ProjectProcessingService` owns
the iterative queue and Job-wide limits; `NodeExecutor` persists each result
atomically.

## 2. Domain and persistence

Milestone 7 reuses `Project`, `Source`, `Node`, `Artifact`,
`NodeRelationship`, `LineageRecord`, `ProcessingJob`, `ProcessingAttempt`, and
`ProcessingEvent`. A 7z or RAR is a Container Node; a materialized member is a
Child Node plus an `EXTRACTED_ARTIFACT` in `PROJECT_WORKSPACE`.

No archive-specific table or JSON relationship is added. Migration `0002` only
extends the constrained processing error-code values for dependency and external
process outcomes. Direct `ARCHIVE_ENTRY` relationships remain canonical; the
persisted lineage closure remains the queryable ancestry fact.

## 3. Backend boundary

`ArchiveHandler` depends on the PIG-owned `ArchiveBackend` protocol:

- `inspect` returns ordered member identity, type, sizes, encryption/link flags,
  and non-authoritative backend diagnostics;
- `write_member` writes exactly one previously inspected member to a supplied
  binary stream;
- backend exceptions are translated into structured domain status, category,
  and error code at the Handler boundary.

`ContainerInspection.details` carries backend name/version diagnostics into the
existing `CONTAINER_OPENED` event. It does not replace catalog facts.

## 4. 7z behavior

`Py7zrBackend` uses the pinned-compatible `py7zr` 1.1 series. It lists the
archive in process, detects archive passwords, and writes a selected member via
a `WriterFactory` directly into the Artifact Store's bounded writer. It does not
materialize archive paths on disk.

## 5. RAR behavior

`SevenZipRarBackend` accepts only an explicitly configured absolute path to a
system-installed 7-Zip executable. It validates the file type, absence of
symlink components, version range, and SHA-256 identity. It performs no PATH
lookup, bundling, download, or password interaction.

Listing and single-member stdout extraction run without a shell or stdin, with
bounded time and diagnostics. Extracted stdout is subject to the same Artifact
Store single-file and Job-total byte limits as every other Container format.

## 6. Logical and physical identity

The evidence path uses the existing Container boundary notation:

```text
/supplier.rar!/mail.7z!/quote.zip!/final.xlsx
```

Member names are evaluated as untrusted logical names. They never determine the
physical Artifact path, which remains:

```text
artifacts/<id-prefix>/<artifact-id>/content
```

Duplicate non-directory member names are retained as blocked evidence because a
name-only backend cannot prove deterministic member selection. Directory marker
Nodes are cataloged but not materialized.

## 7. State, event, and failure behavior

Successful Containers and descendants follow the existing
`DISCOVERED -> QUEUED -> PROCESSING -> SUCCESS|PARTIAL_SUCCESS` flow. Expected
password, corrupt, unsupported, dependency, security, and limit outcomes are
durable Node/Attempt/Event data. An unknown terminal file still succeeds as a
cataloged terminal Node and does not fail the project.

Normal Container, Child, Artifact, relationship, lineage, and terminal events
remain unchanged. `CONTAINER_OPENED.details.inspection` adds backend version and,
for RAR, the accepted executable SHA-256. Debug traces and local executable paths
are not business event data.

## 8. Security and permissions

- External Originals remain read-only and fingerprint-revalidated.
- No archive backend extracts into the Original or a name-derived directory.
- Traversal, absolute/device paths, malicious names, symbolic/hard links,
  excessive depth/count/size/ratio, encryption, corruption, and unsupported
  features receive explicit outcomes.
- Staged Artifact output is hash/signature counted while written and removed on
  failure or limit breach.
- Only the RAR adapter may create a subprocess, under the restrictions in
  ADR-005. This adds no UI or general command-execution surface.

## 9. Verification

Automated tests cover:

- a real `py7zr` 7z containing ZIP containing XLSX, including logical path,
  relationship, multi-level lineage, events, and unchanged Original bytes;
- encrypted and corrupt 7z outcomes;
- path traversal, link, encrypted, duplicate, entry/ratio/output limits;
- Artifact callback streaming, atomic publish, and staging cleanup;
- missing, old, and changed system 7-Zip executable identities;
- exact shell-free RAR list/extract argument vectors and nested ZIP recursion via
  a deterministic fake command runner;
- subprocess stdout/stderr capture, streaming, output cap, timeout, and kill;
- Alembic upgrade/head consistency and downgrade, plus all prior milestones.

The current development host has no compatible system 7-Zip executable, so an
actual RAR file/executable integration test has not run here. This is explicit
release evidence still required by Milestone 10, not a silently passing test.

## 10. Explicitly deferred

Now not implemented:

- Manifest and Search (Milestone 8);
- PySide6 Evidence Tree, filtering, and open-file UI (Milestone 9);
- recovery, performance tuning, cross-platform packaging, signed dependency
  installer/discovery, and release qualification (Milestone 10);
- password entry/storage, archive creation/repair, multi-volume RAR orchestration,
  SFX execution, preview, or content indexing;
- Tool protocol, Workflow/Automation engine, MCP, AI, OCR, RAG, Graph DB, Vector
  DB, distributed workers, or any V2–V5 feature.
