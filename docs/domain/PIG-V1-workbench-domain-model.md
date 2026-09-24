# PIG V1 工作台领域模型 / Workbench Domain Model

- 状态：W2–W8 已实现 / Status: W2-W8 implemented
- 版本：1.0-plan / Version: 1.0-plan
- 日期：2026-09-24 / Date: 2026-09-24
- 约束决策：`ADR-010`、`ADR-018`、`ADR-019`、`ADR-020` / Governing decisions: `ADR-010`, `ADR-018`, `ADR-019`, `ADR-020`

## 中文规范正文

### 1. 聚合与所有权边界

`Project` 是隔离边界。Source Discovery 与 Workspace Organization 是不同的一致性
边界，不得用同一个可变 parent 字段表示：

```text
Project
├── ImportSession
│   └── ImportSessionItem(s)
├── OriginalSnapshot
│   ├── OriginalSnapshotEntry -- parent --> OriginalSnapshotEntry
│   └── OriginalArtifact(s)
├── Source
│   └── SourceNode -- SourceRelationship --> SourceNode
└── WorkspaceItem -- WorkspacePlacement --> WorkspaceItem
    └── WorkingArtifact（物化前可为空）
        └── WorkingRevision（当前/上一版本）
└── RecoveryRun
    └── RecoveryItem(s)
```

### 2. 核心实体

**Project** 拥有一个 SQLite Database、不可变 Original Storage、可变 Working
Storage，以及其下全部身份。关键字段为 `id`、`name`、`workspace_locator`、
`model_version`、`status`、`workspace_revision` 和时间字段。W5 Workspace 写 Action
必须用 Expected Revision 原子校验并递增该值。
新 Project 的物理根目录为 `<selected-parent>/<valid-project-name>`；UUID 仍是内部身份，
名称目录不得替代 `Project.id`。

**ImportSession** 表示一次用户授权的拖放或 Add 操作，负责进度、Partial Success、
Resource Policy Scope 和 Idempotency。关键字段包括 `id/project_id/status`、请求/
接受/失败计数、时间、`actor`、`correlation_id` 和不可变 Policy Snapshot。
定向 Add 还保存可选 `target_workspace_parent_id` 与
`expected_workspace_revision`。

**ImportSessionItem** 表示一个有顺序的顶层输入，保存 Input Locator、Item Status、
可选 Snapshot Binding 和结构化 Error。它使一个输入失败时 Sibling 仍可继续，并让
幂等重放返回已落库的逐项结果。
W7.2 Import Undo 以这个顶层 Item 的 Snapshot Binding 为操作边界；Capture 结果作为
历史事实保留，不把内层 Member 伪装成独立 Import Item。

**OriginalSnapshot** 表示由一个外部输入创建的不可变 Project-owned Snapshot
边界。Folder Snapshot 可以包含多个 Original Artifact。External Locator 只作为导入
时信息，不得作为编辑位置；Snapshot `READY` 后即使外部输入消失仍然可用；普通
Workspace Action 不得覆盖、移动、重命名或删除 Snapshot。

**OriginalArtifact** 表示 Original Snapshot 内的不可变字节，保存生成式
`storage_key`、实际 `size/sha256`、时间和 Integrity Status。不可信名称不得选择
Original 路径。Archive/Email Member 可以通过外层 Container 的 Original Artifact
间接获得字节，延迟物化不要求每个终端 Member 在导入时都单独复制。

**OriginalSnapshotEntry** 保存 File/Folder Snapshot 捕获时看到的显式成员树。
Folder Entry 保存 Parent/Ordinal/Original Name 且没有 Artifact；File Entry 必须绑定
同 Snapshot 的 Original Artifact。它是 W2 捕获事实，不等于 W3 Source Structure。

**Source** 表示由 Original Snapshot 支撑的导入边界。Snapshot `READY` 后不再依赖
External Path。

**SourceNode** 表示不可变 Source Structure 中的一次对象出现，是现有 Node 概念的
演进。它保存 Project/Source、Kind/Format、原始/显示名、Source Logical Path、Depth、
Ordinal、Processing Status 和 Discovery Key。接受后的 Source Parent 不可改变；安全
的 Archive 隐式目录可成为 Source Node；Terminal Node 可以没有 Working Artifact；
Unknown 或 Blocked Node 仍可描述但不一定可打开。

**SourceRelationship** 保存一个不可变直接发现边，并保留 Handler 延迟物化目标所需
的 Entry Identity：Parent/Child、Relationship Type、Ordinal 和 Discovery Key。直接
Relationship Chain 是从 Original Snapshot 定位成员的权威事实。内部可保留 Lineage
Closure，但它不是新的 V1 用户能力。

**SourceEntryLocator** 一对一绑定 Direct Source Relationship，保存延迟物化所需的
显式定位事实。`SNAPSHOT_ENTRY` 使用 `snapshot_entry_id`；`ZIP_MEMBER`、`EML_PART`、
`MSG_ATTACHMENT`、`SEVEN_Z_MEMBER` 和 `RAR_MEMBER` 使用 `member_ordinal`、
`expected_name` 与 `member_role`。Locator 不保存 Parser Object、任意 JSON 或临时物理
路径，并在创建后不可修改或删除。

**ProcessingAttempt** 表示一个 Container Handler 的一次结构检查。除 Handler 名称与
版本外，它还保存 Backend Name/Version 和可选的 Backend SHA-256。RAR Attempt 只记录
通过信任校验的 7-Zip 版本与 Hash，不记录本机 Executable Path。失败 Attempt 保存明确
的 Processing Error；Node 当前结果和 Attempt 历史不得互相替代。

**WorkspaceItem** 表示可变 Workspace Tree 中的用户可见对象，保存可选
`origin_source_node_id`、Item Kind、Display Name、Lifecycle、Materialization Status
和时间。Origin 一旦赋值不得改变；用户创建的逻辑 Folder 可以没有 Origin；Move 只
改变 Placement；`CONTAINER_VIEW` 不是 Archive Authoring Target；Deleted Item 默认
从 Tree/Search 隐藏但必须可恢复。
`PURGED` 只表示已确认撤销某个顶层 Import Item 后的不可恢复 Tombstone；普通软删除
不得进入该状态。

**WorkspacePlacement** 将当前 Parent 和 Order 与 Item Identity 分开保存。Parent/
Child 必须属于同一 Project，Placement 必须无环；Root 无 Parent；移动 Folder 会移动
可见 Subtree，但不重写 Source Fact；Container View 不能接受新增/移动 Child。

**WorkingArtifact** 是交给外部 Desktop Application 的稳定可写文件，保存
`storage_key`、Baseline/Current Size 与 SHA-256、Content Status 和观察时间。Virtual
File 没有 Working Artifact；首次物化从实际输出字节建立 Baseline；Suffix 来自可信
Format；外部修改只更新 Current Fact；PIG 直接打开稳定文件而不是临时 Handoff；
Workspace Logical Move 不要求 Physical Move。

**WorkingRevision** 是 W7.1 引入的有限 Working 版本槽。每个 Working Artifact 最多
一条 `CURRENT_CHECKPOINT` 和一条 `PREVIOUS`；前者与当前 Working File 同 Hash，属于
内部完整性副本，后者是用户可回滚的上一版本。Original Baseline 不计入这两个槽位。
文件修改时间和 PIG 检测时间分开保存，均不代表已证明的 Host Save Event。

**ProcessingEvent** 继续作为关键操作和失败的 Append-only Business Record，而不是
每个文件系统通知的完整审计日志。必须覆盖 Import/Snapshot、Source Discovery、
Materialize/Open、Modified/Missing/Unreadable、Workspace Add/Move/Delete/Restore 和
Recovery/Quarantine。
W7.2 还要求 Import Undo Requested/Completed/Failed；Event 记录影响计数和移除字节，
但不得成为可恢复内容的替代存储。

**RecoveryRun** 表示一次经过用户确认的 Project 恢复执行，保存状态、Actor、
Correlation ID、发现/恢复/失败计数及开始/完成时间。Project Open 的健康只读扫描不
创建 Run；上一次进程留下的非终态 Run 必须显式终态化，不能永久显示 Running。

**RecoveryItem** 保存一个恢复候选的 Kind、Action、Project-relative Storage Key、
Operation ID、原因、原/隔离位置、结果与结构化错误。它表达当前逐项状态；对应 Event
表达历史。`StagingOperationManifest` 是版本化跨介质崩溃证据，不是领域实体或 SQLite
事实替代品。

### 3. 关键关系

| 起点 | 关系 | 终点 | 可变性 |
|---|---|---|---:|
| Project | owns | OriginalSnapshot | 否 |
| ImportSession | requests | ImportSessionItem | 否 |
| ImportSessionItem | captures | OriginalSnapshot | 否 |
| OriginalSnapshot | contains | OriginalArtifact | 否 |
| OriginalSnapshotEntry | parent of | OriginalSnapshotEntry | 否 |
| OriginalSnapshotEntry | backed by | OriginalArtifact | 否 |
| Source | backed by | OriginalSnapshot | 否 |
| SourceNode | discovered under | SourceNode | 否 |
| WorkspaceItem | originated from | SourceNode | 否 |
| Project | owns | RecoveryRun | 否 |
| RecoveryRun | plans/results | RecoveryItem | 仅状态迁移 |
| WorkspaceItem | placed under | WorkspaceItem | 是 |
| WorkingArtifact | materializes | WorkspaceItem | 当前字节可变化 |
| WorkingRevision | checkpoints | WorkingArtifact | 当前槽轮换，上一槽最多一个 |

### 4. 逻辑和物理路径

必须区分：`SourceLogicalPath`、`WorkspaceLogicalPath` 和受控 Project-relative
`StorageKey`。不得通过字符串拼接互相转换。

W2 已批准并实现的 Original Layout 为：

```text
<project>/project.sqlite
<project>/originals/<snapshot-id>/objects/<artifact-id>/content
<project>/.staging/imports/<import-session-id>/<snapshot-id>/...
```

W3 已批准并实现以下 Working 与 Inspection 位置：

```text
<project>/working/<workspace-item-id>/<safe-display-name>.<trusted-suffix>
<project>/working-versions/<working-artifact-id>/current
<project>/working-versions/<working-artifact-id>/previous
<project>/.staging/materializations/<operation-id>/<workspace-item-id>/<safe-display-name>.<trusted-suffix>
<project>/.staging/import-undo/<operation-id>/...
<project>/.inspection/<operation-id>/objects/<generated-id>/content
<project>/recovery/quarantine/...
```

Inspection 路径由 D33-A/D34-A 授权；友好 Working 名称和两个版本槽由 ADR-018 授权；
`recovery/quarantine` 仍属于 W8。原始不可信路径不得直接决定 Physical Path，Display
Name 必须经过单段文件名安全处理，Suffix 必须来自可信格式检测。

### 5. 不变量

1. 普通操作不得修改外部输入或 Original Snapshot。
2. 每个 Source Node 只属于一个 Source 和 Project。
3. 每个 Active Workspace Item 只有一个当前 Placement，且不能形成 Cycle。
4. Placement 不得改变 Source Relationship 或 Origin Binding。
5. Original 完整时，Missing Working Artifact 可以重新物化。
6. Delete 必须可恢复且不得删除 Original。
7. Materialization/Refresh 必须遵守集中资源与路径安全限制。
8. Watcher 通知未经确定性观察不得改变权威 Content State。
9. Container View 不是 V1 Write-back Target。
10. UI State 不是 Placement、Origin 或 Content Fact 的来源。
11. 一个 Snapshot 只有一个 Root Entry，Entry Parent 不得跨 Snapshot。
12. W2 成功捕获后 Session 必须保持 `INSPECTING`，不得提前宣称 W3 已完成。
13. Source Entry Locator 一旦持久化不得重写；Workspace Move 不改变 Locator。
14. Backend Identity 属于 Processing Attempt，不属于可变 UI State 或任意 Event JSON。
15. Import Undo 只接受 Source Root 对应的顶层 Import Item，且不得修改外部输入或同批
    Sibling。
16. Import Undo 删除 Project-owned 可恢复字节，但保留 Capture 身份、`PURGED` 状态和
    Append-only Event Tombstone。

### 6. 现有模型复用与替换

可复用 Project Identity、SQLite Isolation、Handler Registry、Resource Policy、Source
Node Detection、Direct Relationship、Queue Processing 和 Structured Error。外部引用
Source 语义改为 Snapshot-backed Source；旧 Extracted Artifact 和 `.open-handoff`
不能代表新的稳定可编辑 Working Artifact；现有 Lineage Closure 可以保留，但不得
用它编码 Workspace Organization。

## English normative text

## 1. Aggregate and ownership boundaries

`Project` is the isolation boundary. Source discovery and Workspace organization
are separate consistency boundaries and must not be represented by one mutable
parent field.

```text
Project
├── ImportSession
│   └── ImportSessionItem(s)
├── OriginalSnapshot
│   ├── OriginalSnapshotEntry -- parent --> OriginalSnapshotEntry
│   └── OriginalArtifact(s)
├── Source
│   └── SourceNode -- SourceRelationship --> SourceNode
└── WorkspaceItem -- WorkspacePlacement --> WorkspaceItem
    └── WorkingArtifact (optional until materialized)
```

## 2. Core entities

### 2.1 Project

Owns one SQLite database, immutable Original storage, mutable Working storage,
and all identities below it.

Key fields:

- `id`
- `name`
- `workspace_locator`
- `model_version`
- `status`
- `workspace_revision`
- `created_at`, `updated_at`

Each W5 Workspace write atomically checks an expected revision and advances
this value.
New Projects use `<selected-parent>/<valid-project-name>` as their physical root;
the UUID remains the internal identity and is never replaced by the directory
name.

### 2.2 ImportSession

Represents one user-authorized drag/drop or add operation. It provides progress,
partial-success accounting, resource-policy scope, and idempotency.

Key fields:

- `id`, `project_id`
- `status`
- `requested_item_count`
- `accepted_item_count`, `failed_item_count`
- `started_at`, `finished_at`
- `actor`, `correlation_id`
- immutable `policy_snapshot`
- optional `target_workspace_parent_id`, `expected_workspace_revision`

A targeted Add persists both optional fields so inspection can project directly
under the requested folder and reject a concurrent Workspace change.

### 2.3 ImportSessionItem

Represents one ordered top-level input. It stores the input locator, item state,
optional snapshot binding, and structured error. One failed input can coexist
with successful siblings, and idempotent replay returns persisted item results.

Key fields:

- `id`, `project_id`, `import_session_id`, `ordinal`
- `input_locator`, `status`
- optional `snapshot_id`, `error_code`, `error_message`

W7.2 Import Undo uses this top-level Snapshot binding as its boundary. Capture
remains historical, and embedded members are never represented as synthetic
independent Import Items.

### 2.4 OriginalSnapshot

Represents the immutable Project-owned snapshot boundary created from one
accepted external input. A folder snapshot may contain many Original Artifacts.

Key fields:

- `id`, `project_id`, `import_session_id`
- `input_kind`
- `original_display_name`
- `external_locator_at_import` for information only
- `status`
- `created_at`, `verified_at`

Rules:

- The external locator is never used as the editable working location.
- A ready snapshot remains usable after the external input disappears.
- Snapshot content cannot be overwritten, renamed, moved, or deleted by normal
  Workspace operations.

### 2.5 OriginalArtifact

Represents immutable bytes inside an Original Snapshot. Folder imports create an
Artifact for each accepted byte-bearing member; Container files also have an
Artifact that can back recursive inspection.

Key fields:

- `id`, `project_id`, `snapshot_id`
- `source_node_id` when assigned
- `storage_key`
- `size`, `sha256`
- `observed_modified_at`
- `integrity_status`
- `created_at`

Physical storage uses generated identities. Untrusted names never select an
Original storage path.

An archive/email member may be backed transitively by its outer Container's
Original Artifact. Lazy materialization does not require copying every terminal
member into a separate Original Artifact during import.

### 2.6 OriginalSnapshotEntry

Persists the explicit member tree observed while capturing a file/folder
snapshot. A folder Entry has parent/order/original-name facts and no Artifact. A
file Entry references an Original Artifact from the same snapshot. This is a W2
capture fact, not the W3 Source Structure.

### 2.7 Source

Names one imported source boundary backed by an Original Snapshot. It no longer
depends on the external path after the snapshot reaches `READY`.

Key fields:

- `id`, `project_id`, `snapshot_id`
- `kind`, `display_name`
- `root_source_node_id`
- `status`
- `created_at`

### 2.8 SourceNode

Represents one occurrence in the immutable discovered Source Structure. This is
the evolution of the existing Node concept.

Key fields:

- `id`, `project_id`, `source_id`
- `kind`, `format`
- `original_name`, `display_name`
- `source_logical_path`
- `depth`, `ordinal`
- `processing_status`
- `discovery_key`
- `created_at`, `updated_at`

Rules:

- Source parentage is immutable after accepted discovery.
- Safe implicit archive directories may be Source Nodes.
- A terminal Source Node may exist without a Working Artifact.
- Unknown and blocked Nodes remain describable without being openable.

### 2.9 SourceRelationship

Stores one immutable direct discovery edge. It retains enough entry identity for
the Handler to locate a target member during lazy materialization.

Key fields:

- `id`, `project_id`
- `parent_source_node_id`, `child_source_node_id`
- `relationship_type`
- `ordinal`, `discovery_key`
- `created_at`

The direct relationship chain, not a mutable Workspace path, is canonical for
resolving a member from its Original Snapshot. Persisted transitive closure may
remain internally but is not required as a new V1 user feature.

### 2.9.1 SourceEntryLocator

Binds one-to-one to a direct Source Relationship and persists explicit lazy-
materialization identity. `SNAPSHOT_ENTRY` uses `snapshot_entry_id`.
`ZIP_MEMBER`, `EML_PART`, `MSG_ATTACHMENT`, `SEVEN_Z_MEMBER`, and `RAR_MEMBER`
use `member_ordinal`, `expected_name`, and `member_role`. A Locator never stores
a parser object, arbitrary JSON token, or temporary physical path and is
immutable after creation.

### 2.9.2 ProcessingAttempt

Represents one Container Handler inspection. In addition to Handler name and
version, it persists backend name/version and an optional backend SHA-256. A RAR
Attempt records the trusted 7-Zip version and hash but never the local executable
path. A failed Attempt carries a structured Processing Error. Current Node state
and Attempt history do not replace each other.

### 2.10 WorkspaceItem

Represents one user-facing occurrence in the mutable Workspace Tree.

Key fields:

- `id`, `project_id`
- `origin_source_node_id: Optional[id]`
- `item_kind` (`FOLDER`, `FILE`, `CONTAINER_VIEW`)
- `display_name`
- `lifecycle_status`
- `materialization_status`
- `created_at`, `updated_at`, `deleted_at`

Rules:

- `origin_source_node_id` never changes after assignment.
- A user-added logical folder may have no origin.
- Moving changes Workspace Placement, never origin.
- `CONTAINER_VIEW` is not an archive-authoring target.
- A deleted item remains restorable and is excluded from normal tree/search
  results unless explicitly requested.
- `PURGED` is an irreversible tombstone used only after confirmed undo of the
  corresponding top-level Import Item; ordinary soft delete never enters it.

### 2.11 WorkspacePlacement

Stores the current mutable parent and order separately from Workspace Item
identity.

Key fields:

- `workspace_item_id`
- `parent_workspace_item_id: Optional[id]`
- `ordinal`
- `previous_parent_id`, `previous_ordinal` for one-step restore placement
- `updated_at`

Rules:

- Parent and child belong to the same Project.
- Placement is acyclic.
- Root placement has no parent.
- Moving a Folder moves its visible subtree without rewriting Source facts.
- A Container View cannot accept a moved or added child in V1.

### 2.12 WorkingArtifact

Represents the stable writable file handed to an external desktop application.

Key fields:

- `id`, `project_id`, `workspace_item_id`
- `storage_key`
- `baseline_size`, `baseline_sha256`
- `current_size`, `current_sha256`
- `content_status`
- `materialized_at`, `last_checked_at`, `updated_at`

Rules:

- A virtual file has no Working Artifact.
- First materialization calculates the baseline from actual emitted bytes.
- The trusted suffix comes from detected format, never raw input path syntax.
- External edits may change current facts but never baseline facts.
- PIG opens the stable Working Artifact directly; it is not an ephemeral handoff
  cache.
- Workspace logical moves do not require physical moves.

### 2.12a WorkingRevision

Represents W7.1's bounded Working-version slots. Each Working Artifact has at
most one `CURRENT_CHECKPOINT` and one `PREVIOUS` row. The current checkpoint has
the same hash as the current Working File and is an internal integrity copy; the
previous slot is the one user-restorable version. Original Baseline is separate
and does not count toward these slots. File modification time and PIG detection
time are distinct facts and neither is a proven Host Save event.

### 2.13 ProcessingEvent

Remains an append-only business record for important operations and failures,
not a full keystroke or file-system audit log.

Required V1 Workbench event families:

- import/snapshot requested, completed, partially completed, failed;
- Source Node discovery/processing result;
- Working Artifact materialization/open result;
- Working Artifact modified/missing/unreadable detection;
- Workspace Item added/moved/deleted/restored;
- import-undo requested/completed/failed outcome;
- recovery/quarantine result.

### 2.14 RecoveryRun and RecoveryItem

`RecoveryRun` represents one explicitly confirmed Project reconciliation and
stores status, actor, correlation, counts, and timing. A healthy read-only Open
scan creates no Run. Any nonterminal run left by a prior process is explicitly
terminalized rather than remaining falsely Running.

`RecoveryItem` stores one candidate's kind, action, Project-relative storage
key, operation ID, reason, quarantine key, result, and structured error. It is
the current per-item state while Events remain history. A versioned
`StagingOperationManifest` is cross-media crash evidence, not a domain entity or
a replacement for SQLite facts.

## 3. Key relationships

| From | Relationship | To | Mutable? |
|---|---|---|---:|
| Project | owns | OriginalSnapshot | No |
| ImportSession | requests | ImportSessionItem | No |
| ImportSessionItem | captures | OriginalSnapshot | No |
| OriginalSnapshot | contains | OriginalArtifact | No |
| OriginalSnapshotEntry | parent of | OriginalSnapshotEntry | No |
| OriginalSnapshotEntry | backed by | OriginalArtifact | No |
| Source | backed by | OriginalSnapshot | No |
| SourceNode | discovered under | SourceNode | No |
| WorkspaceItem | originated from | SourceNode | No |
| WorkspaceItem | placed under | WorkspaceItem | Yes |
| WorkingArtifact | materializes | WorkspaceItem | Current bytes may change |
| WorkingRevision | checkpoints | WorkingArtifact | Current rotates; one previous |
| Project | owns | RecoveryRun | No |
| RecoveryRun | plans/results | RecoveryItem | State transitions only |

## 4. Logical and physical paths

Three path concepts are mandatory:

- `SourceLogicalPath`: immutable discovered location with Container boundaries;
- `WorkspaceLogicalPath`: current user organization derived from Placement;
- `StorageKey`: controlled Project-relative physical locator.

None may be converted directly into another by string concatenation.

The approved and implemented W2 Original layout is:

```text
<project>/project.sqlite
<project>/originals/<snapshot-id>/objects/<artifact-id>/content
<project>/.staging/imports/<import-session-id>/<snapshot-id>/...
```

W3 approved and implemented these Working and inspection locations:

```text
<project>/working/<workspace-item-id>/<safe-display-name>.<trusted-suffix>
<project>/working-versions/<working-artifact-id>/current
<project>/working-versions/<working-artifact-id>/previous
<project>/.staging/materializations/<operation-id>/<workspace-item-id>/<safe-display-name>.<trusted-suffix>
<project>/.staging/import-undo/<operation-id>/...
<project>/.inspection/<operation-id>/objects/<generated-id>/content
<project>/recovery/quarantine/...
```

Inspection paths are authorized by D33-A/D34-A. ADR-018 authorizes the sanitized
display basename under a generated Working Item directory and the two generated
version slots; `recovery/quarantine` remains a W8 concern. Raw untrusted path
syntax never selects a physical destination, and suffixes remain trusted-format
facts.

## 5. Invariants

1. Normal operations never modify external input after reading it.
2. Normal operations never modify Original Snapshot bytes.
3. Every Source Node belongs to exactly one Source and Project.
4. Every active Workspace Item has exactly one current Placement.
5. Workspace Placement never changes Source Relationship or origin binding.
6. A Source member can be rematerialized after its Working Artifact is missing,
   provided Original Snapshot integrity succeeds.
7. A Workspace Tree cycle is impossible.
8. Delete is reversible and cannot delete Original Snapshot bytes.
9. Materialization and refresh obey centralized size, depth, count, and path
   safety limits.
10. File-system notifications do not change authoritative content state without
    a deterministic observation.
11. Container Views are not write-back targets in V1.
12. UI state is never the source of Placement, origin, or content facts.
13. A snapshot has one root Entry, and Entry parentage cannot cross snapshots.
14. A successful W2 capture leaves its session at `INSPECTING`; it cannot claim
    that W3 has completed.
15. A persisted Source Entry Locator is immutable; Workspace moves never rewrite
    it.
16. Backend identity belongs to a Processing Attempt, not mutable UI state or an
    opaque Event-only JSON field.
17. Import Undo accepts only the Source Root for a top-level Import Item and
    never changes the external input or sibling items from the same session.
18. Import Undo removes Project-owned recoverable bytes while retaining capture
    identity, `PURGED` availability state, and append-only Event tombstones.
19. A read-only recovery scan does not mutate Project bytes or SQLite state.
20. Recovery never automatically overwrites, deletes, or quarantines registered
    Working or Working-version bytes.

## 6. Existing model reuse and replacement

- Existing Project identity, SQLite isolation, Handler registry, resource policy,
  Source Node detection, direct Relationships, queue processing, and structured
  errors remain useful.
- Existing external-reference Source semantics are replaced by snapshot-backed
  Source semantics.
- Existing extracted immutable Artifact and `.open-handoff` behavior do not
  represent the new stable editable Working Artifact.
- Existing Lineage closure may remain, but Workspace organization must not be
  encoded by changing or extending it.
