# ADR-002：提取 Artifact 存储布局 / Extracted Artifact Storage Layout

- 状态：历史记录，新 Workbench 存储由 ADR-010 取代 / Status: Historical; superseded for new Workbench storage by ADR-010
- 决策日期：2026-09-14 / Decision date: 2026-09-14
- 范围：PIG V1 Project Workspace / Scope: PIG V1 Project Workspace
- 批准人：产品负责人 / Approved by: Product owner

## Context

> 中文摘要：旧实现使用 `<project>/artifacts/<prefix>/<artifact-id>/content`，使不可信
> Archive Name 无法决定物理路径；Staging 后原子发布并由 Recovery 处理 Orphan。
> 新 Workbench 需要独立的不可变 Original 与稳定可编辑 Working Storage。

> This layout describes immutable extracted Artifacts in the implemented
> evidence-oriented system. ADR-010 requires separate immutable Original and
> stable editable Working storage. Its exact new layout is not yet authorized.

Milestone 4 is the first milestone that materializes bytes derived from a Container. ZIP member names are untrusted evidence text and may contain traversal syntax, platform-specific reserved names, duplicate names, control characters, or paths too long for the host filesystem.

The storage layout must preserve Logical Path / Physical Storage separation and must not allow an archive name to choose a physical destination.

## Options considered

### Option A — Artifact-ID-based storage

```text
<project>/artifacts/<artifact-id-prefix>/<artifact-id>/content
```

### Option B — Mirror evidence paths under `extracted/`

```text
<project>/extracted/<source-id>/<logical-path>
```

Option B is easier to browse outside PIG but couples evidence presentation to physical storage and requires collision, reserved-name, path-length, separator, and cross-platform filename rules throughout the extraction path.

## Decision

Selected: Option A.

Consequences:

- An untrusted original name never participates in a workspace filesystem path.
- `Artifact.locator` for `PROJECT_WORKSPACE` is a project-relative storage key such as `artifacts/ab/<artifact-id>/content`.
- Original names and Logical Paths remain authoritative database evidence.
- Duplicate archive names receive different Node and Artifact IDs and cannot overwrite one another.
- A two-character Artifact-ID prefix prevents one flat directory from growing without bound.
- Changing this layout requires an explicit storage migration; it must not rewrite Node identity, Relationship, Lineage, or Logical Path.

## Publication protocol

Bytes are streamed to:

```text
<project>/.staging/<operation-id>/<artifact-id>.part
```

The stream is bounded, hashed, flushed, and then atomically renamed on the same filesystem to the final ID-based location. The database stores the final project-relative key.

The Application publishes staged Artifacts immediately before committing their database transaction. If the transaction fails in the running process, the Artifact session removes only the paths created by that operation.

SQLite and the filesystem do not provide one shared transaction. A process or machine crash after rename but before SQLite commit can leave an orphan physical Artifact. Milestone 10 recovery must identify and quarantine or remove such orphans. PIG does not claim distributed-transaction atomicity.
