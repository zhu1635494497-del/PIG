# PIG V1 Workbench W6 实施记录 / Workbench W6 Implementation Record

- 状态：已完成 / Status: Complete
- 日期：2026-09-23 / Date: 2026-09-23
- 决策：`ADR-016` / Decision: `ADR-016`
- 后续状态：W7 已完成；W8 未授权 / Later status: W7 complete; W8 not authorized

## 中文实施记录

### 1. 完成了什么

实现稳定 Working File 的 Open/Edit Reconciliation 闭环：Virtual File 首次打开时按需
物化；后续打开先做确定性 Refresh；用户对稳定路径的原地保存得到保留并标记为
`MODIFIED`；Missing/Unreadable 拒绝打开；显式 Restore 从不可变 Original Recipe
重建 Baseline Bytes。未新增数据库表或 Migration。

### 2. 涉及的领域对象

- `WorkspaceItem`：限定为有效、Source-backed Terminal File；
- `WorkingArtifact`：复用 Baseline/Current Fingerprint、Content Status、Stable Storage Key、
  `materialized_at` 与 `last_checked_at`；
- `Node`/`Source`/`OriginalArtifact`/`SourceEntryLocator`：只读解析 Restore Recipe；
- `ProcessingEvent`：保存 Open Attempt 与 Content Observation 结果；
- `OpenPolicy`：集中保存格式 Allowlist、Hash Size、Chunk 和 Stability Retry 限制。

### 3. 用户操作到输出

```text
Open Workspace File
-> persist FILE_OPEN_REQUESTED
-> validate Project / active terminal item / format allowlist
-> first use: materialize stable Working Artifact
   later use: refresh size + SHA-256 before open
-> deny Missing/Unreadable, allow Clean/Modified
-> hand stable path to OS default association
-> persist FILE_OPENED or FILE_OPEN_DENIED/FAILED

Refresh file state
-> resolve controlled stable path
-> bounded stable read
-> direct durable status/fingerprint update
-> emit content Event only when observation changed

Restore Working File
-> refresh current state
-> require confirmation when an existing path would be replaced
-> replay immutable Original/Container recipe into staging
-> verify baseline size/SHA-256
-> atomically publish at the same storage key
-> persist CLEAN + WORKING_FILE_RESTORED_CLEAN
```

### 4. 状态变化

Durable Content State 在 `CLEAN`、`MODIFIED`、`MISSING`、`UNREADABLE` 之间直接转换；
`CHECKING` 仅为内存操作态。相同观察仍更新 `last_checked_at`，但不重复产生 Business
Event。Missing/Unreadable 保留上一次成功读取的 Current Fingerprint。Restore 不改变
Baseline、Storage Key 或 Materialized Time。

### 5. Event 与 Log

每次 Open Attempt 保存 `FILE_OPEN_REQUESTED`，并以 `FILE_OPENED`、
`FILE_OPEN_DENIED` 或 `FILE_OPEN_FAILED` 结束。Content 变化保存
`WORKING_FILE_MODIFIED`、`WORKING_FILE_MISSING`、`WORKING_FILE_UNREADABLE` 或
`WORKING_FILE_RESTORED_CLEAN`。Event 包含 Refresh Reason、前后状态、可用 Fingerprint、
Error Code 和 Correlation ID；`FILE_OPENED` 明确只代表 Host Handoff 已发起。

### 6. Tool 或 Action

新增 `open_workspace_item`、`refresh_working_artifact`、
`restore_working_artifact` typed Application Action。它们可在 W7 被 Desktop UI 复用，
但 W6 没有新增公共 API、MCP、Agent Tool Registry、Workflow 或 Automation Adapter。

### 7. 安全和权限影响

- 只允许 OpenPolicy Allowlist 格式并使用 OS 默认关联，不执行任意用户指定程序；
- Working Storage Key 必须是受控相对路径，拒绝 Traversal、Backslash 绕过和 Symlink
  Parent；
- Hash 读取受最大文件大小、Chunk Size 和稳定性重试限制；
- Symlink、Directory、Device 或其他非普通目标永不覆盖；
- Modified/现存 Unreadable 的恢复由后端强制要求确认；Missing 可无覆盖确认恢复；
- Original Snapshot、Source Structure、Workspace Placement 和 Logical Name 均不修改。

### 8. 测试覆盖

新增 W6 Application 场景覆盖首次/再次 Open、稳定路径、外部原地 Edit、回归 Baseline、
Save-As 不跟踪、Event Dedup、Refresh Reason、Missing、Unreadable Directory、Restore
确认、Baseline Identity、应用重启、格式 Allowlist 和 Host Handoff Failure。同步更新 Working
Content 状态机测试，确认 Direct Durable Transition 与非持久化 `CHECKING`。

全量结果：`120 passed, 95 skipped, 1 warning`。Skip 仍为 ADR-010 隔离的历史
Evidence/UI 测试和当前 Host 不允许创建的 Symlink 场景；Warning 来自刻意构造的重复
ZIP Member Name。

### 9. 当前尚未闭环的边界

W7 尚未把这些 Action 接入 PySide6 Workspace Tree、双击 Open、Focus-gained Refresh、
状态 Badge 和用户确认 Dialog。W8 尚未验证写入中断恢复、真实规模 Hash 性能及新
Workbench Package。V1 仍不跟踪 Project 外 Save-As，不处理外部应用文件锁或版本历史。

### 10. 技术债务与下一步最小建议

W6 使用同步受限 Hash，适合当前本地单用户 Application Action；W7 必须在 Worker 中
调用以避免阻塞 UI。Focus-gained 只是已定义的 Refresh Reason，自动触发属于 W7 UI，
当前不建立 Watcher。下一步最小建议是单独批准 W7，只把 W1–W6 已完成 Contract 接入
一个 Workbench 界面，不重写业务规则，也不提前进入 W8。

## English implementation record

## 1. What changed

Implemented the stable Working File Open/Edit reconciliation loop. A virtual
file materializes on first Open; later Opens perform deterministic refresh
first. In-place saves at the stable path are preserved and marked `MODIFIED`.
Missing/Unreadable files are denied. Explicit Restore rebuilds baseline bytes
from the immutable Original recipe. No database table or migration was added.

## 2. Domain objects

- `WorkspaceItem` is restricted to an effective active, source-backed terminal
  file.
- `WorkingArtifact` reuses baseline/current fingerprints, content status,
  stable storage key, `materialized_at`, and `last_checked_at`.
- `Node`, `Source`, `OriginalArtifact`, and `SourceEntryLocator` are read only to
  resolve the restore recipe.
- `ProcessingEvent` stores Open attempts and content-observation outcomes.
- `OpenPolicy` centralizes format allowlist, hash-size, chunk, and stability
  retry limits.

## 3. User action to output

```text
Open Workspace File
-> persist FILE_OPEN_REQUESTED
-> validate Project / active terminal item / format allowlist
-> first use: materialize stable Working Artifact
   later use: refresh size + SHA-256 before open
-> deny Missing/Unreadable, allow Clean/Modified
-> hand stable path to OS default association
-> persist FILE_OPENED or FILE_OPEN_DENIED/FAILED

Refresh file state
-> resolve controlled stable path
-> bounded stable read
-> direct durable status/fingerprint update
-> emit content Event only when observation changed

Restore Working File
-> refresh current state
-> require confirmation when an existing path would be replaced
-> replay immutable Original/Container recipe into staging
-> verify baseline size/SHA-256
-> atomically publish at the same storage key
-> persist CLEAN + WORKING_FILE_RESTORED_CLEAN
```

## 4. State changes

Durable content state moves directly among `CLEAN`, `MODIFIED`, `MISSING`, and
`UNREADABLE`; `CHECKING` is operation-local only. An unchanged observation still
updates `last_checked_at` but emits no duplicate business Event.
Missing/Unreadable preserves the last successfully read current fingerprint.
Restore changes no baseline, storage key, or materialization time.

## 5. Events and logs

Every Open attempt persists `FILE_OPEN_REQUESTED` and terminates with
`FILE_OPENED`, `FILE_OPEN_DENIED`, or `FILE_OPEN_FAILED`. Content changes persist
`WORKING_FILE_MODIFIED`, `WORKING_FILE_MISSING`, `WORKING_FILE_UNREADABLE`, or
`WORKING_FILE_RESTORED_CLEAN`. Events include refresh reason, prior/final state,
available fingerprints, error code, and correlation ID. `FILE_OPENED` explicitly
means only that host handoff was initiated.

## 6. Tool or action impact

Added typed Application actions `open_workspace_item`,
`refresh_working_artifact`, and `restore_working_artifact`. W7 can reuse them in
the Desktop UI, but W6 adds no public API, MCP, Agent Tool Registry, Workflow,
or Automation adapter.

## 7. Permission and safety

- Only OpenPolicy-allowlisted formats use the OS default association; no
  user-supplied executable is launched.
- A Working storage key must be a controlled relative path; traversal,
  backslash bypasses, and symlink parents are rejected.
- Hash reads are bounded by maximum file size, chunk size, and stability retry.
- Symlinks, directories, devices, and other non-regular targets are never
  replaced.
- Restoring Modified or existing Unreadable content requires backend-enforced
  confirmation; Missing may be restored without overwrite confirmation.
- Original Snapshot, Source Structure, Workspace Placement, and logical names
  are unchanged.

## 8. Tests

New W6 Application scenarios cover first/repeated Open, stable path, external
in-place edit, return to baseline, Save-As non-tracking, Event deduplication,
refresh reason, Missing, unreadable directory, restore confirmation, baseline
identity, application restart, format allowlist, and host handoff failure. Working-content transition
tests now assert direct durable transitions and non-persistent `CHECKING`.

The full result is `120 passed, 95 skipped, 1 warning`. Skips remain the
ADR-010-quarantined historical Evidence/UI tests plus symlink cases unavailable
on this host. The warning is from the intentionally duplicated ZIP member-name
fixture.

## 9. Open boundaries

W7 has not connected these actions to the PySide6 Workspace Tree, double-click
Open, focus-gained refresh, status badges, or confirmation dialogs. W8 has not
validated interrupted writes, realistic hash performance, or a new Workbench
package. V1 still does not track Save-As outside the Project, external editor
locks, or version history.

## 10. Technical debt and smallest next step

W6 uses synchronous bounded hashing, appropriate for the current local
single-user Application action; W7 must invoke it from a Worker to avoid UI
blocking. `FOCUS_GAINED` is a defined refresh reason, while automatic triggering
belongs to W7 UI; no watcher is introduced. The smallest next step is separately
authorizing W7 and wiring only the completed W1-W6 contracts into one Workbench
view, without rewriting business rules or advancing into W8.
