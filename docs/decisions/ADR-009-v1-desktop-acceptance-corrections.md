# ADR-009：V1 桌面验收修正 / V1 Desktop Acceptance Corrections

- 状态：部分被 ADR-010 取代 / Status: Superseded in part by ADR-010
- 决策日期：2026-09-19 / Decision date: 2026-09-19
- 范围：Milestone 10 验收修正 / Scope: PIG V1 Milestone 10 acceptance corrections

## Context

> 中文摘要：D13 将 Archive Internal Directory 持久化为 Source Structure；D15 保留
> UUID Project Directory 并改善显示；D16 通过 `.open-handoff` 提供带扩展名副本。
> ADR-010 保留 D13/D15 的相关价值，但用 Stable Working Artifact 取代 D16。

> D13 and D15 remain useful for immutable Source Structure and Project identity.
> ADR-010 supersedes D16's temporary open-handoff model with stable editable
> Working Artifacts. The old desktop acceptance flow is historical.

Real desktop acceptance exposed six usability and evidence-model defects: archive
member paths were persisted as a flat child list, the UUID Project directory was
not explained, Event timestamps were displayed as raw UTC ISO strings, Qt filter
values were not converted back to domain enums, extracted Artifact storage names
did not carry a safe file-type suffix for Windows association, and Manifest
success was visible only in the status line.

These are V1 closed-loop corrections. They do not introduce content indexing,
semantic classification, AI, Workflow, Automation, or a new persistence system.

## Decisions

### D13-A - persist archive-internal directory Nodes

For ZIP, 7z, and RAR, every safe directory prefix required by an accepted member
is represented by one structural `FOLDER` Node. The archive-to-top-level edge is
`ARCHIVE_ENTRY`; edges below that directory use `FOLDER_CONTAINS`. Each Node has
one direct persisted parent, `depth` equals parent depth plus one, and persisted
Lineage includes the structural directory Nodes.

An explicit archive directory entry and the same implicit prefix collapse into
the same structural directory occurrence for that archive inspection. Unsafe or
unparseable names that cannot produce safe path parts remain direct blocked
evidence under the archive and are never materialized.

### D14-A - no in-place historical tree repair

Projects imported by an older build retain their historical facts. V1 does not
silently rewrite their Relationships or Lineage. Acceptance of D13-A uses a new
Project and reimports the Original Source. A future explicit migration/repair
operation would require a separate decision and audit design.

### D15-A - retain UUID physical Project directory

The collision-safe layout remains:

```text
<workspace-root>/projects/<project-id>/project.sqlite
```

The desktop displays Project name, a short first-eight-character ID, and the
full storage path. Creation messaging explains that the full UUID is the
internal unique Project ID. No display name is used as a filesystem identity.

### D16-A - verified typed open handoff

Immutable extracted Artifacts keep the approved
`artifacts/<prefix>/<artifact-id>/content` layout. Before handing an allowed
extracted terminal document to the operating system, the Application asks a
filesystem adapter to create:

```text
<project>/.open-handoff/<artifact-id>/document.<trusted-format-suffix>
```

The suffix is selected from the persisted `NodeFormat`, never from an untrusted
source name. The copy is streamed, size/hash verified against the Artifact, and
published atomically. A matching copy may be reused; a mismatching regular copy
is replaced. Symlinks, containment violations, missing integrity facts, and
unapproved formats fail closed. Recovery treats this derived cache as
uncommitted output and moves it to reversible quarantine.

## UI corrections

- Format filtering is a true multi-select control and sends domain
  `NodeFormat` values; status selection is converted to
  `NodeProcessingStatus` before calling Search.
- Search results use the existing controlled-open Application action on double
  click.
- Event instants remain persisted in UTC and are displayed as system-local
  `YYYY-MM-DD HH:MM:SS`; the raw UTC ISO instant is available in the tooltip.
- A successful Manifest export shows a modal confirmation with output path,
  size, SHA-256, and included Event count.

## Consequences and boundaries

- D13-A changes current V1 evidence semantics and supersedes the earlier rule
  that archive directory prefixes existed only inside Logical Path.
- No Alembic migration is required; existing Node, Relationship, Lineage,
  Metadata, Status, and Event tables already represent the corrected facts.
- Existing Projects are readable but keep their prior shape; reimport is the
  supported correction path.
- Original Sources and immutable extracted Artifacts are not renamed, modified,
  or opened through an unverified path.
- `.open-handoff` is derived cache, not evidence, Artifact, or Lineage data.
- No V2 content extraction/index, AI, Agent, Workflow, Automation, MCP, Graph DB,
  Vector DB, task broker, or microservice is introduced.
