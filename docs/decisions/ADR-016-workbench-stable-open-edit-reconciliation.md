# ADR-016：Workbench 稳定打开与编辑对账 / Workbench Stable Open and Edit Reconciliation

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-23 / Decision date: 2026-09-23
- 决策：D47-A、D48-A、D49-A、D50-A、D51-A、D52-A / Decisions: D47-A, D48-A, D49-A, D50-A, D51-A, D52-A
- 范围：Workbench Milestone W6 / Scope: Workbench Milestone W6
- 后续影响：版本历史排除和 `content.<suffix>` 文件名已由 ADR-018 局部取代；其余决定仍有效。
  / Later impact: ADR-018 locally supersedes the version-history exclusion and
  `content.<suffix>` filename; all other decisions remain active.

## 中文规范正文

### 背景

W1–W5 已建立不可变 Original Snapshot、可重放 Source Structure、延迟物化的稳定
Working Artifact 和可变 Workspace Tree。W6 需要把该 Working Artifact 变成真正的
外部编辑面，同时避免把 Host Application 行为、文件系统通知或临时打开副本误当作
业务事实。

### 决策

1. **D47-A**：提供统一 `open_workspace_item` Action。Virtual File 在首次 Open 时物化；
   已物化 File 在 Open 前刷新。`CLEAN` 与 `MODIFIED` 均可打开，`MISSING` 与
   `UNREADABLE` 拒绝打开并要求用户显式恢复。Refresh 和 Restore 保持独立 Action。
2. **D48-A**：`CHECKING` 仅为操作内阶段，不持久化。SQLite 从旧的 Durable Content
   Status 直接写入本次最终观察状态，避免进程中断遗留永久 `CHECKING`。
3. **D49-A**：后端用 `OpenPolicy.allowed_formats` 执行格式 Allowlist，再通过 OS 默认
   File Association 交接。V1 不接收任意可执行文件路径，也不实现“选择打开方式”。
4. **D50-A**：Restore 必须显式调用。`MISSING` 可直接恢复；覆盖 `MODIFIED` 或现存的
   `UNREADABLE` 路径必须携带确认。Symlink、Directory 和其他非普通文件即使已确认也
   不替换。`baseline_*`、`storage_key` 与 `materialized_at` 保持不变。
5. **D51-A**：刷新原因是 `EXPLICIT`、`BEFORE_OPEN` 或 `FOCUS_GAINED`。W6 不实现
   Watcher。Content Event 仅在状态或可读 Fingerprint 变化时产生；每次 Open Attempt
   独立保存 Requested 与 Opened/Denied/Failed Event。
6. **D52-A**：复用现有 Working Artifact 的 Baseline/Current Fingerprint、Content
   Status 和 `last_checked_at`；不增加观察历史表，也不创建 `0006` Migration。Hash
   读取受大小、Chunk 和稳定性重试限制。`MISSING/UNREADABLE` 保留最后一次成功读取的
   Current Fingerprint。

### 不变量与安全边界

- Original Snapshot 和 Source Structure 从不因 Open、Refresh 或 Restore 改变；
- Working Path 由 Project Root、生成标识和可信 Suffix 决定，不使用 Display Name；
- Refresh 只读取受控 Working Path，拒绝 Traversal、Symlink 和非普通文件；
- Restore 先在 Operation Staging 中生成并校验 Baseline Size/SHA-256，再原子发布；
- `FILE_OPENED` 只表示 OS Handoff 已发起，不表示应用已启动、用户已保存或进程已退出；
- Project 外的 Save As 不跟踪；W6 不建立版本历史、文件锁或后台 Watcher。

### Action 与 Event

W6 新增 `open_workspace_item`、`refresh_working_artifact` 和
`restore_working_artifact` 三个 typed in-process Action。它们是未来 UI/Tool 的稳定
复用边界，但当前不是公共 Tool、MCP 或 Automation 接口。

Content 变化使用 `WORKING_FILE_MODIFIED/MISSING/UNREADABLE/RESTORED_CLEAN`；Open
使用 `FILE_OPEN_REQUESTED/OPENED/DENIED/FAILED`。刷新原因、前后状态、可用 Fingerprint
和 Error Code 写入结构化 Event。

### 明确不做

W6 不实现 W7 UI、任意程序选择、文件系统 Watcher、自动覆盖恢复、Container
Write-back、Save-As 跟踪、版本历史、Diff/Merge、AI、Agent、Workflow、Automation
或 MCP；也不提前实施 W8 Recovery、Benchmark 或 Packaging。

## English normative text

## Context

W1-W5 established immutable Original Snapshots, replayable Source Structure,
stable lazily materialized Working Artifacts, and a mutable Workspace Tree. W6
makes each Working Artifact a real external editing surface without treating
host-application behavior, file-system notifications, or temporary open copies
as business facts.

## Decisions

1. **D47-A**: expose one `open_workspace_item` action. A virtual file is
   materialized on first Open; a materialized file is refreshed before Open.
   `CLEAN` and `MODIFIED` may open. `MISSING` and `UNREADABLE` are denied until
   the user explicitly restores them. Refresh and Restore remain separate
   actions.
2. **D48-A**: `CHECKING` is operation-local and is not persisted. SQLite moves
   directly from the prior durable content status to the final observation so
   an interrupted process cannot strand an Artifact in `CHECKING`.
3. **D49-A**: the backend enforces `OpenPolicy.allowed_formats`, then hands the
   file to the host's default association. V1 accepts no arbitrary executable
   path and implements no choose-an-application flow.
4. **D50-A**: Restore is explicit. `MISSING` can be restored directly;
   replacing `MODIFIED` or an existing `UNREADABLE` path requires confirmation.
   Symlinks, directories, and other non-regular files are never replaced, even
   with confirmation. `baseline_*`, `storage_key`, and `materialized_at` remain
   immutable.
5. **D51-A**: refresh reasons are `EXPLICIT`, `BEFORE_OPEN`, and
   `FOCUS_GAINED`. W6 adds no watcher. Content Events are emitted only when the
   state or readable fingerprint changes; every Open attempt independently
   persists Requested plus Opened/Denied/Failed Events.
6. **D52-A**: reuse the current Working Artifact baseline/current fingerprints,
   content status, and `last_checked_at`; add neither an observation-history
   table nor migration `0006`. Hashing is bounded by size, chunk, and stability
   retry policy. `MISSING/UNREADABLE` preserves the last successfully read
   current fingerprint.

## Invariants and safety boundary

- Open, Refresh, and Restore never alter Original Snapshot or Source Structure.
- Project root, generated identity, and trusted suffix determine the Working
  path; display names do not.
- Refresh reads only a controlled Working path and rejects traversal, symlinks,
  and non-regular files.
- Restore generates and verifies baseline size/SHA-256 in operation staging
  before atomic publication.
- `FILE_OPENED` means only that OS handoff was initiated; it proves neither
  application startup, user save, nor process exit.
- Save-As outside the Project is not tracked. W6 adds no version history, file
  lock, or background watcher.

## Actions and events

W6 adds three typed in-process actions: `open_workspace_item`,
`refresh_working_artifact`, and `restore_working_artifact`. They are stable
reuse boundaries for a future UI or Tool, but are not public Tools, MCP, or
Automation interfaces now.

Content changes use `WORKING_FILE_MODIFIED/MISSING/UNREADABLE/RESTORED_CLEAN`.
Open uses `FILE_OPEN_REQUESTED/OPENED/DENIED/FAILED`. Structured Events retain
the refresh reason, prior/final states, available fingerprints, and error code.

## Explicit exclusions

W6 does not implement the W7 UI, arbitrary application selection, file-system
watchers, automatic destructive restore, Container write-back, Save-As
tracking, version history, Diff/Merge, AI, Agent, Workflow, Automation, or MCP.
It also does not advance into W8 recovery, benchmarks, or packaging.
