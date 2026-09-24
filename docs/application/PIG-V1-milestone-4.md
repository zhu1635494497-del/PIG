# PIG V1 Milestone 4：Folder / ZIP 单层处理 / Single-Level Processing

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this document does not authorize new implementation.

> 中文摘要：本阶段实现 Folder/ZIP Detection、Handler、单层 Child Discovery、
> Artifact ID Storage 和 Archive Security。后续 ADR-009 修正了 Archive Directory
> 层级；新 Workbench 将进一步拆分 Inspect 与 Materialize。

> Current correction: ADR-009 D13-A supersedes the original flat archive-member
> model described by this historical milestone. ZIP, 7z, and RAR safe directory
> prefixes are now persisted as structural Folder Nodes with Relationships and
> Lineage. Existing Projects are not rewritten; create a new Project and reimport.

- 状态：已实现 / Status: Implemented
- 日期：2026-09-14 / Date: 2026-09-14
- Scope: deterministic format detection, Folder and ZIP Handler boundary, and one explicitly requested Source-root processing action
- Storage decision: `docs/decisions/ADR-002-artifact-storage-layout.md`

## 1. Outcome

Milestone 4 adds the first processing loop over the Milestone 3 catalog:

```text
process_node(root)
  -> persist Job / Attempt / PENDING
  -> persist RUNNING states
  -> revalidate external Source
  -> detect format
  -> terminal File: finish SUCCESS
  -> supported Container: resolve Handler
  -> inspect direct Children
  -> safely materialize readable child bytes
  -> persist Nodes / Artifacts / Relationships / Lineage / Events
  -> finish Node / Attempt / Job
```

The action is synchronous and processes exactly one Source root. Discovered child Containers remain `DISCOVERED`; no child is automatically fed back into a queue.

## 2. Domain and module boundaries

No new persistent domain entity or database table was required. Milestone 4 activates existing:

- `ProcessingJob`
- `ProcessingAttempt`
- direct `NodeRelationship`
- persisted `LineageRecord`
- Node, Source, Artifact, Project current state
- append-only `ProcessingEvent`

Modules:

- `pig.domain.detection`: deterministic Node format evidence.
- `pig.domain.archive_security`: platform-neutral archive-entry path policy.
- `pig.domain.processing_policy`: centralized, serializable resource limits.
- `pig.domain.paths`: display-name and Logical Path normalization.
- `pig.handlers.base`: common Handler, child descriptor, and materialization contracts.
- `pig.handlers.folder`: direct Folder child discovery.
- `pig.handlers.zip`: Python standard-library ZIP inspection and extraction.
- `pig.infrastructure.filesystem.artifact_store`: bounded staging and Artifact-ID publication.
- `pig.application.processing_service`: lifecycle orchestration only; it does not contain ZIP or Folder parsing.

The processor resolves a Handler by `NodeFormat`; it does not branch on ZIP implementation details.

## 3. Action contract

`process_node` input:

- `project_id`
- absolute `database_path`
- `node_id`
- `actor`
- immutable `ProcessingPolicy`

Output:

- final Node and Job status
- Job and Attempt IDs
- direct child Node IDs
- warning and error counts

Milestone 4 restricts the action to an owning Source root in `DISCOVERED`. This is an Application Action, not yet an external Tool contract.

## 4. Detection rules

- Folder identity is authoritative and becomes `CONTAINER / FOLDER`.
- ZIP local/empty/spanned signatures become `CONTAINER / ZIP`, independent of filename extension.
- `.zip` extension also identifies a claimed ZIP so a corrupt archive is recorded as `CORRUPTED`, not silently treated as Unknown.
- `.xlsx`, `.docx`, and `.pptx` remain Terminal Files even though their bytes are ZIP-based.
- Known V1 terminal extensions receive their controlled `NodeFormat`.
- Unknown ordinary files become `FILE / UNKNOWN` and complete successfully.

Detection method, confidence, extension, and safe signature prefix are persisted on Node.

## 5. Folder Handler

- Uses one `scandir` level only and sorts names deterministically.
- Never follows a symbolic link.
- Registers direct directories as `CONTAINER / FOLDER / DISCOVERED` without an Artifact.
- Hashes each accepted regular file read-only and registers an `ORIGINAL_REFERENCE / EXTERNAL_SOURCE` Artifact.
- Detects each direct child format but does not process a child Container.
- Special filesystem objects are represented as unsupported or blocked evidence without reading their target.

Every accepted child has one `FOLDER_CONTAINS` edge. The Repository creates its self-lineage and copies the parent's ancestors with distance plus one.

## 6. ZIP Handler

- Uses Python `zipfile` only, as required by D4.
- Reads the central directory before extraction.
- Uses central security and resource policies before any member is opened.
- Streams each accepted member through the bounded Artifact Store rather than `extract()` or `extractall()`.
- Never converts an archive member name into a native path.
- Creates `ARCHIVE_ENTRY` edges using central-directory ordinal discovery keys, so duplicate names remain distinct.
- Keeps archive-internal directory segments in Logical Path and, under the
  current ADR-009 behavior, persists their safe prefixes as Folder Nodes.
- An explicit directory entry may be cataloged as a direct Folder Node; path-prefix matching never turns it into another member's structural parent.

Blocked members remain evidence Nodes with no Artifact and a structured error event.

## 7. Artifact workspace

Accepted ZIP file bytes use:

```text
artifacts/<first-two-artifact-id-characters>/<artifact-id>/content
```

The database stores this project-relative key, not an absolute path. ZIP names remain only in `original_name`, `display_name`, and `logical_path`.

Staging uses `.staging/<job-id>`. Actual streamed sizes and total expanded bytes are rechecked while writing, SHA-256 is computed in the same pass, and partial files never become valid Artifacts.

## 8. Default processing policy

All values are centralized and each Job persists the exact policy snapshot:

| Limit | Default |
|---|---:|
| Maximum depth | 20 |
| Maximum Project Nodes | 100,000 |
| Maximum ZIP entries | 50,000 |
| Maximum single extracted file | 2 GiB |
| Maximum total expanded bytes per operation | 20 GiB |
| Maximum compression ratio | 200:1 |
| I/O chunk size | 1 MiB |

Both declared ZIP metadata and actual streamed output are evaluated. The
original Milestone 4 implementation created only direct member children;
ADR-009 now applies depth checks to each persisted archive directory segment.

## 9. State and event flow

Normal root lifecycle:

```text
Project: IMPORTING -> PROCESSING
Source: AVAILABLE -> VERIFYING -> AVAILABLE
Artifact: VERIFIED -> VERIFYING -> VERIFIED
Node: DISCOVERED -> PENDING -> PROCESSING -> SUCCESS/PARTIAL_SUCCESS
Job: QUEUED -> RUNNING -> SUCCESS/PARTIAL_SUCCESS
Attempt: QUEUED -> RUNNING -> COMPLETED
```

Unexpected implementation exceptions produce `Attempt FAILED`, `Node FAILED`, `Job FAILED`, and a technical reference. Stack traces go only to Debug Log.

Events now exercised include:

- `PROJECT_STATUS_CHANGED`
- `JOB_CREATED`, `JOB_STARTED`, `JOB_FINISHED`
- `ATTEMPT_QUEUED`, `ATTEMPT_STARTED`, `ATTEMPT_FINISHED`, `ATTEMPT_FAILED`
- `SOURCE_VERIFICATION_STARTED`, `SOURCE_VERIFIED`, missing/changed outcomes
- `ARTIFACT_VERIFIED`, `ARTIFACT_INTEGRITY_FAILED`, `ARTIFACT_REGISTERED`
- `NODE_QUEUED`, `NODE_PROCESSING_STARTED`, `NODE_FORMAT_DETECTED`
- `CONTAINER_OPENED`, `CHILD_DISCOVERED`, `CHILD_EXTRACTED`
- `RELATIONSHIP_CREATED`, `LINEAGE_UPDATED`
- processing finished, blocked, and failed outcomes

## 10. Safety outcomes

The central archive policy blocks:

- unresolved `..` traversal;
- absolute and drive-qualified member names;
- Windows device paths;
- NUL-containing names;
- symbolic-link entries;
- password-protected entries;
- excessive entry count, file size, expanded total, or compression ratio.

Unsafe original names may be retained as evidence text, but the Logical Path is encoded without unresolved traversal and no Artifact is materialized. Control and format characters are replaced in display names to reduce UI spoofing risk.

Before processing, an external file Source is rehashed. Missing or changed bytes update Source, Node, and Artifact integrity current states without overwriting the accepted fingerprint.

## 11. Explicitly deferred

Now not implemented:

- automatic child scheduling, iterative queue, retry, pause, resume, or recovery;
- processing depth greater than one or manually processing a descendant;
- EML/MSG, 7z, and RAR Handlers;
- reconciliation/idempotent reuse when a completed Node is processed again;
- global Project readiness projection;
- Manifest, Search, controlled Open, UI, public Tool/MCP, Workflow, Automation, AI, OCR, and content indexing.

Milestone 10 must address crash-window orphan Artifact recovery and three-platform packaging/execution verification.

## 12. Verification

Tests cover:

- terminal-file detection and Unknown/Office ZIP distinction;
- Folder one-level discovery and external Artifact hashing;
- ZIP extraction, nested logical member paths, and direct lineage;
- duplicate ZIP names without overwrite;
- traversal, absolute path, drive path, device path, NUL, and ZIP symbolic-link rejection;
- password-required outcome without extraction;
- entry count, single-file size, compression ratio, and actual streamed-size limits;
- corrupt ZIP outcome;
- Source fingerprint mismatch and immutable accepted hash;
- Artifact-ID layout, publication, rollback, and partial-file cleanup;
- Job/Attempt/Node/Source transitions and persisted policy snapshots.
