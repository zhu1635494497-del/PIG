# PIG V1 工作台状态机 / Workbench State Machines

- 状态：W2–W8 状态与事件已实现 / Status: W2-W8 states and events implemented
- 日期：2026-09-24 / Date: 2026-09-24
- 约束决策：`ADR-010`、`ADR-018`、`ADR-019`、`ADR-020` / Governing decisions: `ADR-010`, `ADR-018`, `ADR-019`, `ADR-020`

## 中文规范正文

状态维度必须分离。Import Progress、Source Discovery、Workspace Lifecycle、
Materialization 和当前 Working File Content 不得塞进一个重载 Status。

### 1. ImportSessionStatus

```text
QUEUED -> SNAPSHOTTING -> INSPECTING
       -> SUCCESS | PARTIAL_SUCCESS | FAILED | INTERRUPTED
```

`SUCCESS` 表示所有接受输入都有可用 Workspace Result；`PARTIAL_SUCCESS` 表示至少
一个可用，同时至少一个 Blocked/Unsupported/Corrupt/Limited/Failed；`FAILED` 表示
没有形成可用结果。进程消失只有经过显式 Recovery 才成为 `INTERRUPTED`。

W2 的职责只到 Snapshot Capture。至少一个顶层输入成功时，Session 必须停在
`INSPECTING` 并由 W3 继续；全部顶层输入失败时才进入 `FAILED`。

### 1.1 ImportItemStatus

```text
PENDING -> CAPTURING -> CAPTURED | FAILED | INTERRUPTED
PENDING -> FAILED | INTERRUPTED
```

每个 `ImportSessionItem` 对应一个有顺序的顶层输入。一个 Item 的失败不改变已成功
Sibling；`FAILED` 必须保存 Error Code 和 Message。

### 2. OriginalSnapshotStatus

```text
COPYING -> VERIFYING -> READY
COPYING / VERIFYING -> FAILED | INTERRUPTED
READY -> VERIFYING -> READY | MISSING | MISMATCH | UNREADABLE
READY | MISSING | MISMATCH | UNREADABLE -> PURGED  [仅确认撤销顶层导入]
```

`READY` 表示 Project 拥有已验证的 backing bytes。外部输入之后消失不影响 Snapshot。
Snapshot Mismatch 属于内部完整性问题，不得把新字节接受为旧 Snapshot。

Snapshot 重新校验时，其 Original Artifact 分别执行：

```text
UNVERIFIED | VERIFIED | MISSING | MISMATCH | UNREADABLE
  -> VERIFYING
  -> VERIFIED | MISSING | MISMATCH | UNREADABLE
```

Snapshot、Source 与 Original Artifact 的当前完整性状态必须在同一校验结果中保持
一致；历史 Event 不被覆盖。

`PURGED` 是 W7.2 顶层 Import Undo 的不可逆可用性终态。相应 Source 从
`AVAILABLE/MISSING/CHANGED/UNREADABLE` 进入 `PURGED`，Original Artifact 从
`VERIFIED/MISSING/MISMATCH/UNREADABLE` 进入 `PURGED`；ImportSessionItem Capture
历史和最小身份 Tombstone 保留。

### 3. SourceNodeProcessingStatus

沿用现有结构处理结果：

```text
DISCOVERED -> QUEUED -> PROCESSING
PROCESSING -> SUCCESS | PARTIAL_SUCCESS | UNSUPPORTED
           | PASSWORD_REQUIRED | CORRUPTED | LIMIT_EXCEEDED
           | FAILED | SKIPPED | INTERRUPTED
```

Terminal Source Node 的 `SUCCESS` 只表示已经登记且可能可物化，不表示 Working
Artifact 已经存在。

### 3.1 ProcessingAttemptStatus

```text
QUEUED -> RUNNING -> COMPLETED | FAILED | INTERRUPTED | CANCELLED
```

每个被实际检查的 Container 产生一个 Attempt。Handler 成功完成检查时，即使发现的
Child 存在 Blocked 结果，Attempt 仍可为 `COMPLETED`，而 Container Node 经汇总成为
`PARTIAL_SUCCESS`。Handler、Backend 或格式检查失败时 Attempt 为 `FAILED`，并保存
结构化 Error；Backend Identity 在 `RUNNING` 时确定并随 Attempt 持久化。

### 4. WorkspaceItemLifecycleStatus

```text
ACTIVE -> DELETED
DELETED -> ACTIVE
ACTIVE | DELETED -> PURGED  [仅 Source Root Import Undo]
```

Delete 需要明确确认，只把所选根 Item 标为 `DELETED`，并保留 Origin、Placement
History、Original 和 Working Bytes。其后代保留自身 Lifecycle，但在存在 Deleted
Ancestor 时有效隐藏且不得参与普通 Workspace Action。Restore 优先回到有效旧位置，
否则回到 Project Root 并记录 fallback。普通 Workspace Item 的任意永久清理不在
V1；`PURGED` 只由已确认的顶层 Import Undo 对该 Source 全部派生 Item 原子执行。

### 5. WorkspaceMaterializationStatus

```text
VIRTUAL -> MATERIALIZING -> MATERIALIZED
MATERIALIZING -> FAILED | INTERRUPTED
FAILED -> MATERIALIZING
MATERIALIZED -> MATERIALIZING
```

`VIRTUAL` 表示 Structure/Origin 已知但稳定 Working Artifact 不存在。Missing 或
Unreadable 时允许显式重新物化；若会覆盖 Modified Bytes，必须先确认。Folder 和
Container View 仅用于展示/展开时不需要 Working Artifact。

### 6. WorkingContentStatus

```text
CLEAN | MODIFIED | MISSING | UNREADABLE
  -> CLEAN | MODIFIED | MISSING | UNREADABLE
```

`CLEAN` 表示 Current Fingerprint 等于 Baseline；`MODIFIED` 是正常工作状态而非完整性
故障；`MISSING` 表示 Working Artifact 不存在但 Original 不受影响；`UNREADABLE`
表示无法安全读取。根据 D48-A，`CHECKING` 只作为操作态且不持久化，数据库从旧的
Durable State 直接写入最终观察结果。恢复 Baseline Bytes 后可由 `MODIFIED` 回到
`CLEAN`，但历史 Event 不删除。相同状态的重复观察允许更新 `last_checked_at`。

### 7. Workspace Move

Move 是原子 Placement 变更而非 Lifecycle Status：校验同 Project、Target Type 和
No Cycle 后更新 Parent/Ordinal 并发出 `WORKSPACE_ITEM_MOVED`。失败时旧 Placement
继续有效；Active Sibling Ordinal 保持从 `0` 开始连续；Source Structure 和 Working
Artifact Physical Location 不变。每次成功写入同时校验并增加 Project
`workspace_revision`。

### 8. 必需 Event

- Import：Requested/Started/Snapshot Capture Finished/Finished/Failed/Interrupted；
- Snapshot：Copy Started/Verification Started/Ready/Integrity Failed；
- Source Inspection：现有 Node/Handler Discovery 与结果 Event；
- Materialization：Started/Materialized/Failed；
- Content Refresh：Modified/Missing/Unreadable，以及可选 Recovery-to-clean；
- Workspace：Added/Moved/Deleted/Restored；
- Open：Requested/Opened/Denied/Failed；
- Working Version：Captured/Rolled Back；
- Export：Requested/Completed/Failed；
- Import Undo：Requested/Completed/Failed；
- Recovery：Interruption 和 Reversible Quarantine。

重复 Refresh 若观察到同一状态，不得产生重复 Business Event。Watcher 通知只进入
Debug Log。

### 8. Working 版本槽状态机（W7.1）

```text
首次物化
  -> CURRENT_CHECKPOINT only

检测到新 Hash
  -> 旧 CURRENT_CHECKPOINT 变为 PREVIOUS
  -> 当前 Working bytes 变为新 CURRENT_CHECKPOINT

确认回滚
  -> PREVIOUS 覆盖 Working File 和 CURRENT_CHECKPOINT
  -> 被覆盖的旧 CURRENT_CHECKPOINT 变为新 PREVIOUS
```

每个角色最多一条。未检测到字节变化不得制造新版本；`MISSING/UNREADABLE` 不得轮换
版本。Original Restore 若实际改变当前 Hash，也必须通过相同轮换保住被覆盖版本。
版本槽变化不得修改 Source、Origin 或 Workspace Placement。

### 10. Recovery 状态机（W8）

```text
RecoveryRun:
DETECTED -> AWAITING_CONFIRMATION -> RUNNING
         -> SUCCESS | PARTIAL_SUCCESS | FAILED

RecoveryItem:
DISCOVERED -> PLANNED
           -> RESTORED | QUARANTINED | REMOVED_REPRODUCIBLE | UNCHANGED | FAILED
```

Project Open Scan 是只读操作，不创建 Run。只有用户确认后才创建 Run/Item 并执行计划。
执行前必须重新扫描并匹配 Inspection Token。上一次进程留下的非终态 Run/Item 在新的
确认恢复中转为 `FAILED`，错误为 `RECOVERY_INTERRUPTED`。正常 `INSPECTING` 导入等待
W3 继续，不属于中断；只有崩溃时仍为 `SNAPSHOTTING` 的写入临界状态需要恢复对账。
Recovery 不得自动覆盖或移走数据库已登记的 Working/Version 字节。

## English normative text

State dimensions are separated deliberately. Import progress, Source discovery,
Workspace lifecycle, materialization, and current Working File content are not
one overloaded status.

## 1. ImportSessionStatus

```text
QUEUED
  -> SNAPSHOTTING
  -> INSPECTING
  -> SUCCESS | PARTIAL_SUCCESS | FAILED | INTERRUPTED
```

Additional transitions:

```text
SNAPSHOTTING -> PARTIAL_SUCCESS | FAILED | INTERRUPTED
INSPECTING   -> PARTIAL_SUCCESS | FAILED | INTERRUPTED
```

Rules:

- `SUCCESS`: every accepted input reached a usable Workspace result.
- `PARTIAL_SUCCESS`: at least one item is usable and at least one item was
  blocked, unsupported, corrupt, limited, or failed.
- `FAILED`: no usable Project result was established for the session.
- Process disappearance becomes `INTERRUPTED` only through explicit recovery,
  not by silently rewriting history.
- W2 ends at snapshot capture. If one or more top-level inputs succeed, the
  session remains `INSPECTING` for W3. It reaches `FAILED` in W2 only when every
  top-level input fails.

### 1.1 ImportItemStatus

```text
PENDING -> CAPTURING -> CAPTURED | FAILED | INTERRUPTED
PENDING -> FAILED | INTERRUPTED
```

Each `ImportSessionItem` represents one ordered top-level input. One failed item
does not rewrite successful siblings, and `FAILED` carries an error code and
message.

## 2. OriginalSnapshotStatus

```text
COPYING -> VERIFYING -> READY
COPYING -> FAILED | INTERRUPTED
VERIFYING -> FAILED | INTERRUPTED
READY -> VERIFYING -> READY | MISSING | MISMATCH | UNREADABLE
READY | MISSING | MISMATCH | UNREADABLE -> PURGED  [confirmed top-level import undo only]
```

Rules:

- `READY` means the Project owns verified backing bytes.
- External input disappearance after `READY` has no effect on the snapshot.
- Snapshot mismatch is an internal integrity problem; it never accepts new bytes
  as the old snapshot.

During snapshot reverification, each Original Artifact follows:

```text
UNVERIFIED | VERIFIED | MISSING | MISMATCH | UNREADABLE
  -> VERIFYING
  -> VERIFIED | MISSING | MISMATCH | UNREADABLE
```

The current Snapshot, Source, and Original Artifact integrity states remain
consistent within one verification result; earlier Events are not overwritten.

`PURGED` is the irreversible W7.2 availability terminal used only by top-level
Import Undo. The related Source moves from
`AVAILABLE/MISSING/CHANGED/UNREADABLE` to `PURGED`, and Original Artifacts move
from `VERIFIED/MISSING/MISMATCH/UNREADABLE` to `PURGED`. Import capture history
and minimal identity tombstones remain.

## 3. SourceNodeProcessingStatus

The existing structural-processing outcomes remain applicable:

```text
DISCOVERED -> QUEUED -> PROCESSING
PROCESSING -> SUCCESS | PARTIAL_SUCCESS | UNSUPPORTED
           | PASSWORD_REQUIRED | CORRUPTED | LIMIT_EXCEEDED
           | FAILED | SKIPPED | INTERRUPTED
```

`SUCCESS` for a terminal Source Node means it is cataloged and can potentially
be materialized. It does not mean a Working Artifact already exists.

### 3.1 ProcessingAttemptStatus

```text
QUEUED -> RUNNING -> COMPLETED | FAILED | INTERRUPTED | CANCELLED
```

Each Container that is actually inspected receives one Attempt. An Attempt may
be `COMPLETED` even when one discovered child is blocked; the Container Node then
rolls up to `PARTIAL_SUCCESS`. A Handler, backend, or format-inspection failure
makes the Attempt `FAILED` with a structured Error. Backend identity is resolved
while running and persisted with the Attempt.

## 4. WorkspaceItemLifecycleStatus

```text
ACTIVE -> DELETED
DELETED -> ACTIVE
ACTIVE | DELETED -> PURGED  [Source-root Import Undo only]
```

Rules:

- Delete requires explicit user confirmation.
- Delete marks only the selected root Item `DELETED` and preserves origin,
  Placement history, Original Snapshot, and Working Artifact bytes. Descendants
  retain their own lifecycle but are effectively hidden and unavailable to
  normal Workspace actions while an ancestor is deleted.
- Restore uses the prior parent/order when valid; otherwise it returns the item
  to the Project root and records that fallback.
- Arbitrary permanent purge of ordinary Workspace Items remains outside V1.
  `PURGED` is applied atomically to all Source-derived Items only by confirmed
  top-level Import Undo.

## 5. WorkspaceMaterializationStatus

For file items:

```text
VIRTUAL -> MATERIALIZING -> MATERIALIZED
MATERIALIZING -> FAILED | INTERRUPTED
FAILED -> MATERIALIZING
MATERIALIZED -> MATERIALIZING
```

Rules:

- `VIRTUAL` means structure and origin are known but no stable Working Artifact
  exists.
- The second transition from `MATERIALIZED` supports explicit rematerialization
  after a missing/unreadable working copy; it requires confirmation if modified
  bytes would be replaced.
- Folder and Container View items do not require a Working Artifact merely to be
  displayed or expanded.

## 6. WorkingContentStatus

```text
CLEAN | MODIFIED | MISSING | UNREADABLE
  -> CLEAN | MODIFIED | MISSING | UNREADABLE
```

Rules:

- `CLEAN`: current size/SHA-256 equals the materialization baseline.
- `MODIFIED`: current bytes differ from the baseline. This is a normal Workbench
  state, not an integrity failure.
- `MISSING`: stable Working Artifact is absent; Original Snapshot is unaffected.
- `UNREADABLE`: current path cannot be safely read or verified.
- Under D48-A, `CHECKING` is operation-local and is never persisted. The
  database moves directly from the prior durable state to the final observed
  state. A repeated same-state observation may update `last_checked_at`.
- Returning to baseline bytes may transition `MODIFIED -> CLEAN`; earlier
  modification Events remain history.

## 7. Workspace move transition

Move is an atomic Placement change, not a lifecycle status:

```text
(old_parent, old_ordinal)
  -> validate same Project, target type, and no cycle
  -> (new_parent, new_ordinal)
  -> WORKSPACE_ITEM_MOVED
```

On failure, the old Placement remains authoritative. Source Structure and
physical Working Artifact location do not change. Active sibling ordinals remain
dense and zero-based. Every successful write also checks and advances Project
`workspace_revision`.

## 8. Required Workbench Events

| Area | Events |
|---|---|
| Import | `IMPORT_REQUESTED`, `IMPORT_STARTED`, `IMPORT_SNAPSHOT_CAPTURE_FINISHED`, `IMPORT_FINISHED`, `IMPORT_FAILED`, `IMPORT_INTERRUPTED` |
| Snapshot | `SNAPSHOT_COPY_STARTED`, `SNAPSHOT_VERIFICATION_STARTED`, `SNAPSHOT_READY`, `SNAPSHOT_INTEGRITY_FAILED` |
| Source inspection | existing Node/Handler discovery and terminal outcome Events |
| Materialization | `WORKING_FILE_MATERIALIZATION_STARTED`, `WORKING_FILE_MATERIALIZED`, `WORKING_FILE_MATERIALIZATION_FAILED` |
| Content refresh | `WORKING_FILE_MODIFIED`, `WORKING_FILE_MISSING`, `WORKING_FILE_UNREADABLE`, optional recovery-to-clean Event |
| Workspace | `WORKSPACE_ITEM_ADDED`, `WORKSPACE_ITEM_MOVED`, `WORKSPACE_ITEM_DELETED`, `WORKSPACE_ITEM_RESTORED` |
| Open | `FILE_OPEN_REQUESTED`, `FILE_OPENED`, `FILE_OPEN_DENIED`, `FILE_OPEN_FAILED` |
| Working version | `WORKING_VERSION_CAPTURED`, `WORKING_FILE_ROLLED_BACK` |
| Export | `WORKSPACE_EXPORT_REQUESTED`, `WORKSPACE_EXPORT_COMPLETED`, `WORKSPACE_EXPORT_FAILED` |
| Import undo | `IMPORT_ITEM_UNDO_REQUESTED`, `IMPORT_ITEM_UNDO_COMPLETED`, `IMPORT_ITEM_UNDO_FAILED` |
| Recovery | interruption and reversible quarantine Events as applicable |

Repeated refreshes that observe the same state should not emit duplicate
business Events. Debug-level watcher notifications remain Debug Logs.

## 9. Working version-slot state machine (W7.1)

```text
first materialization
  -> CURRENT_CHECKPOINT only

new hash detected
  -> old CURRENT_CHECKPOINT becomes PREVIOUS
  -> current Working bytes become the new CURRENT_CHECKPOINT

confirmed rollback
  -> PREVIOUS replaces Working File and CURRENT_CHECKPOINT
  -> replaced old CURRENT_CHECKPOINT becomes the new PREVIOUS
```

Each role has at most one row. No byte change means no new version;
`MISSING/UNREADABLE` never rotates slots. An Original Restore that changes the
current hash uses the same rotation so replaced bytes remain recoverable.
Version-slot changes never modify Source, Origin, or Workspace Placement.

## 10. Recovery state machine (W8)

```text
RecoveryRun:
DETECTED -> AWAITING_CONFIRMATION -> RUNNING
         -> SUCCESS | PARTIAL_SUCCESS | FAILED

RecoveryItem:
DISCOVERED -> PLANNED
           -> RESTORED | QUARANTINED | REMOVED_REPRODUCIBLE | UNCHANGED | FAILED
```

Project Open scanning is read-only and creates no Run. Run/Item facts and plan
execution begin only after explicit confirmation. Execution must rescan and
match the inspection token. Nonterminal Run/Item facts left by a prior process
are failed as `RECOVERY_INTERRUPTED` during the next confirmed recovery. A
normal `INSPECTING` import is waiting for W3 and is not interrupted; only a
crashed write-critical `SNAPSHOTTING` state requires reconciliation. Recovery
never overwrites or moves registered Working/version bytes automatically.
