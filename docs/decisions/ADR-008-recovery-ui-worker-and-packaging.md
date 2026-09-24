# ADR-008：Recovery、UI Worker 与打包 / Recovery, UI Worker, and Packaging

- 状态：历史记录，Workbench Recovery/Package 需重新验证 / Status: Historical; Workbench recovery/package behavior requires requalification
- 决策日期：2026-09-15 / Decision date: 2026-09-15
- 范围：PIG V1 Milestone 10 / Scope: PIG V1 Milestone 10

## Context

> 中文摘要：本文记录 Explicit Recovery、Reversible Quarantine、Qt Worker Boundary
> 和 PyInstaller onedir Packaging。新 Workbench 存在可修改 Working File，因此这些
> Recovery 和 Packaging 结论必须在 W8 重新验证。

Milestone 9 completed the desktop evidence browser. Milestone 10 must harden
interrupted processing, reconcile uncommitted Workspace output, keep the Qt UI
responsive, establish a repeatable release process, and measure current catalog
performance without introducing a task platform or changing Original policy.

## Decisions

### D9-A - explicit interrupted state and a new recovery execution

Active Nodes become `INTERRUPTED` only during an explicit recovery action.
Existing Job and Attempt facts are closed as `INTERRUPTED` or `CANCELLED`; they
are never rewritten as if they completed. Recovery creates a new
`RECOVER_INTERRUPTED` Job and new Attempts. Normal processing rejects unresolved
active/interrupted state with `RECOVERY_REQUIRED`.

### D10-A - reversible orphan quarantine

Uncommitted Artifact staging, unknown Artifact output, and unknown Manifest
output are moved to:

```text
<project>/recovery/quarantine/<recovery-job-id>/<sequence>/payload
```

Each successful move is represented by `ORPHAN_QUARANTINED`, including original
and quarantine storage keys and safe file facts. Known persisted Artifacts and
Manifests are preserved. Recovery never deletes orphan bytes automatically.

### D11-A - Qt worker boundary only

Desktop actions that can touch storage or the database execute in a dedicated
`QThread`. Application use cases remain synchronous and deterministic. The UI
disables conflicting actions and displays indeterminate progress while work is
active. This is not pause/resume, a distributed worker, or an asynchronous task
system.

### D12-A - PyInstaller onedir release

The Windows reference build uses PyInstaller `onedir`, `console=False`, and
`upx=False`. Alembic migrations and release metadata are bundled. 7-Zip remains
an operator-provided external executable and is not bundled. A version lock,
runtime inventory, CycloneDX SBOM, vulnerability result, third-party notice, and
human release checklist accompany the build.

macOS and Linux may use the same spec on a native runner. PyInstaller output is
platform-specific, so those builds are not produced from Windows and are not
claimed as verified in this milestone.

## Consequences and boundaries

- SQLite enforces one active Job per Project and one active Attempt per Node.
- Recovery is user-triggered; no automatic retry, resume checkpoint, scheduler,
  or background service exists.
- A quarantine report is also written inside the recovery directory. An OS
  crash between a filesystem move and the following database Event remains a
  detectable manual-review edge; no data is silently deleted.
- The Windows artifact is an internal acceptance build. External distribution
  remains blocked until human license review and code signing are complete.
- No V2 content extraction/index, AI, Agent, MCP, Workflow, Automation, Graph DB,
  Vector DB, Redis, queue broker, or microservice is introduced.
