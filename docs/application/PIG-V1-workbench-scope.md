# PIG V1 项目文件工作台范围 / Project File Workbench Scope

- 状态：产品规划已批准；W1–W7.2 已实现 / Status: Approved product plan; W1-W7.2 implemented
- 日期：2026-09-23 / Date: 2026-09-23
- 约束决策：`ADR-010`、`ADR-018`、`ADR-019` / Governing decisions: `ADR-010`, `ADR-018`, `ADR-019`

## 中文规范正文

### 1. 产品结果

PIG V1 将复杂项目包转化为可编辑的项目工作区，同时不改变导入原件。

用户必须能够：

1. 将多个文件和文件夹一次拖入 Project；
2. 无需手工解压全部终端文件即可获得 Folder/Archive/Email 嵌套结构；
3. 快速找到并打开目标文件；
4. 独立于导入结构整理 Workspace Tree；
5. 增加文件和文件夹、软删除以及恢复；
6. 在常用桌面程序中编辑已物化的 Working File；
7. 返回 PIG 后看到 Working File 是否变化；
8. 在当前和上一版本之间确认回滚；
9. 对同批拖入中的一个误选顶层输入执行确认撤销；
10. 按 Workspace 相对路径导出单个文件、多选 ZIP 或单个普通文件夹；
11. 关闭并重新打开 PIG 后仍保留布局和修改结果。

### 2. 产品边界

PIG 只管理 Project 范围，不是任意磁盘路径的通用文件管理器、Office/PDF 编辑器
或 Archive 制作工具。

V1 支持 Folder、ZIP、7z、通过批准 7-Zip Adapter 处理的 RAR、MSG、EML，以及在
统一限制内由这些格式组成的嵌套链。Terminal File 沿用现有 Office、CSV、PDF、
文本、图片、Email 和 Unknown 词汇。Unknown 可以登记，但除非未来有明确安全
策略，否则不得交给 OS 打开。

密码保护内容保持 `PASSWORD_REQUIRED`；V1 不收集或保存密码。Symbolic Link
继续被阻止且不得跟随。

### 3. 主要用户流程

```text
创建 Project 并选择存储位置
  -> 拖入文件/文件夹
  -> 校验输入并评估复制
  -> 复制不可变 Original Snapshot
  -> 递归检查允许的 Container 结构
  -> 初始化镜像 Source Structure 的 Workspace Item
  -> 展示 Workspace Tree
  -> 移动/增加/软删除/恢复
  -> 必要时撤销一个误导入的顶层 Import Item
  -> 双击虚拟终端 Item
  -> 物化一个稳定 Working Artifact
  -> 使用批准的 Host Application 打开
  -> 用户原地保存
  -> PIG 刷新 size/SHA-256
  -> 展示 CLEAN / MODIFIED / MISSING / UNREADABLE
  -> 维护 CURRENT_CHECKPOINT / PREVIOUS 两个版本槽
  -> 需要时回滚或导出 Workspace 文件
```

Import 必须支持 `PARTIAL_SUCCESS`。单个损坏或不支持对象不得清除已经接受的
sibling，也不得令整个 Project 无法使用。

### 4. 三种独立结构

| 结构 | 用途 | 可变性 | 主要使用者 |
|---|---|---:|---|
| Original Snapshot | 导入时复制的稳定来源字节 | 不可变 | Handler、Materializer、Restore |
| Source Structure | 原始 Container 层级实际包含的内容 | 不可变 | Application、诊断 |
| Workspace Tree | 用户当前的项目整理方式 | 可变 | Desktop UI |

Physical Storage 不等同于任何逻辑结构。移动 Workspace Tree 只改变数据库中的
Placement，不移动或重命名 Original Snapshot，也不要求移动稳定 Working Artifact。

### 5. 延迟物化边界

“延迟解压”表示导入时不把全部 Terminal File 发布为 Working File，并不表示发现
嵌套结构时可以不读取内层 Container 字节。

Import 可以为内层 Container 创建受限制、操作级的 inspection file。它们属于
cache/staging，而不是 Working Artifact；操作结束后必须删除或可恢复隔离。

首次 Open 虚拟 Terminal Item 时执行：

```text
解析 Source Relationship chain
  -> 读取不可变 Original Snapshot
  -> 只安全物化目标 Entry
  -> 计算实际 size/SHA-256
  -> 发布稳定 Working Artifact
  -> 保存 baseline fingerprint
  -> 交给 OS 打开
```

### 6. Workspace 操作

**Move** 只改变 `parent_workspace_item_id` 和顺序；必须拒绝 cycle、跨 Project parent
以及把 Source Container 当作 Archive Writer 的目标，并在重启后保持结果。

**Add** 必须把外部输入复制进新的不可变 Snapshot，创建用户新增 Workspace Item，
不得把外部路径当作编辑位置；Container 仍走同一检查/物化流程。

**Delete/Restore** 需要明确确认，只改变 Workspace 生命周期，保留 Source、Original
和 Working 字节。Restore 优先返回原 Placement；无效时回到 Project root 并报告。

**Rename** 不属于首个 Workbench 实现 Milestone。逻辑/物理重命名、无效名称、扩展名
和外部编辑器打开状态需要单独决策；位置调整不自动授权 Rename。

**Rollback** 只维护 `CURRENT_CHECKPOINT` 与 `PREVIOUS` 两个有界版本槽。确认回滚后
二者交换，使误保存可以撤回且回滚本身可再次撤销；不建设完整历史、Diff 或 Merge。

**Import Undo** 只针对一个已完成且绑定 Source Root 的顶层 `ImportSessionItem`。
它必须先展示影响并确认，再移除该 Source 的 Project-owned Original/Working/版本字节；
同批 Sibling 和外部输入保持不变。任意嵌入成员或普通逻辑节点不提供彻底删除。

**Export** 对单选 Terminal File 输出当前 Working 字节；单选普通 Workspace Folder
输出保留 Active 子树和空目录的普通目录；多选输出 ZIP，并保留安全的 Workspace
相对路径。导出目标必须位于受管 Project 目录外；普通目录不得与已有目标合并或覆盖。

### 7. 外部编辑对账

OS 文件关联不一定返回可靠进程句柄，因此 PIG 不声称知道用户点击 Save 的准确
时刻。W6 已实现的刷新原因包括：显式 **Refresh file state**、Open 前刷新，以及供
W7 调用的 PIG 恢复焦点原因。W6 不建立 Watcher，也不自动执行 Project-load 或未来
Export/Close Gate。实际 size 和 SHA-256 决定 `CLEAN` 或 `MODIFIED`。保存到 Project
外的 Save As 不跟踪。

### 8. 规划中的 Application Action

`import_inputs`、`get_workspace_tree`、`get_source_structure`、
`open_workspace_item`、`refresh_working_artifact`、`restore_working_artifact`、
`move_workspace_item`、
`add_workspace_inputs`、`delete_workspace_item`、`restore_workspace_item`、
`search_workspace_items`、`rollback_working_artifact` 和
`preview_import_undo`、`undo_imported_item`、`export_workspace_items` 是 typed
in-process Contract，当前不是公共 Tool。

V1 不实现 MCP、Remote API、Agent 或 Automation Adapter。

### 9. V1 验收边界

V1 必须满足：多路径一次拖入；Project 内复制并验证输入；导入成功后外部输入移除
不影响 Project；正确展示嵌套 Folder/ZIP/7z/RAR/MSG/EML；导入时不批量物化终端
文件；首次 Open 只物化目标文件；Host Application 可原地保存；刷新识别
`MODIFIED/MISSING/UNREADABLE`；Move/Add/Delete/Restore 重启后保持；Workspace
变化不修改 Original/Source Container；单个坏对象不丢弃 sibling；Inspection 和
Materialization 使用同一安全资源策略。

W7.1 还要求：整个 Workspace 空白区可向 Project Root 接收拖入；Working File 使用
安全化的原显示名；每个文件只保留当前与上一版本且可确认回滚；单选和多选可导出
当前工作结果。

W7.2 还要求：新 Project 使用名称目录；右键提供常用 Action；误导入撤销只作用于
一个顶层 Import Item；单个普通 Workspace Folder 可作为完整目录导出。

### 10. 明确延后

当前不实现 Archive/Email 回写、透明重打包、任意节点永久清理、逻辑 Rename、两个有界版本槽
之外的完整多版本历史、
Diff/Merge、跨应用文件锁、Preview、Thumbnail、内容索引、OCR、Semantic Layer、
AI、Agent、Workflow Engine、Automation Engine、MCP、云同步、多人协作和跨项目搜索。

## English normative text

## 1. Product outcome

PIG V1 turns a complex project package into an editable project workspace
without changing the imported original.

The user must be able to:

1. drop multiple files and folders into one Project;
2. obtain the nested Folder/archive/email structure without manually unpacking
   every terminal file;
3. find and open a target file quickly;
4. arrange the Workspace Tree independently from the imported structure;
5. add files and folders, soft-delete items, and restore them;
6. edit a materialized Working File in its normal desktop application;
7. return to PIG and see whether that Working File changed;
8. confirm a rollback between the current and previous versions;
9. undo one accidentally selected top-level input from a multi-path drop;
10. export one file, a multi-selection ZIP, or one ordinary Workspace folder;
11. close and reopen PIG without losing layout or edits.

## 2. Product boundary

PIG is project-scoped. It is not a general explorer for arbitrary disk paths,
an Office/PDF editor, or an archive authoring utility.

V1 supports structural handling for:

- Folder;
- ZIP;
- 7z;
- RAR through the approved 7-Zip adapter;
- MSG;
- EML;
- nested combinations of the above within centralized limits.

Terminal files include the existing Office, CSV, PDF, text, image, email, and
Unknown vocabulary. Unknown content can be cataloged but is not handed to the OS
unless an explicit safe format policy is added later.

Password-protected content remains `PASSWORD_REQUIRED`; V1 does not collect or
store passwords. Symbolic links remain blocked and are never followed.

## 3. Primary user flow

```text
Create Project and choose storage
  -> drop files/folders
  -> validate input and estimate copy
  -> copy immutable Original Snapshot
  -> recursively inspect permitted Container structure
  -> initialize Workspace Items that mirror Source Structure
  -> show Workspace Tree
  -> move/add/soft-delete/restore items
  -> double-click a virtual terminal item
  -> materialize one stable Working Artifact
  -> open it with an approved host application
  -> user saves in place
  -> PIG refreshes size/SHA-256
  -> show CLEAN / MODIFIED / MISSING / UNREADABLE
  -> maintain CURRENT_CHECKPOINT / PREVIOUS version slots
  -> roll back or export Workspace files when requested
```

Import must report partial success. One corrupt or unsupported object cannot
erase already accepted siblings or make the entire Project unusable.

## 4. Three separate structures

| Structure | Purpose | Mutability | Primary consumer |
|---|---|---:|---|
| Original Snapshot | Stable backing bytes copied at import | Immutable | Handler/materializer/restore |
| Source Structure | What the imported Container hierarchy actually contained | Immutable | Application and diagnostics |
| Workspace Tree | How the user currently organizes project work | Mutable | Desktop UI |

Physical storage paths are not any of these logical structures. Workspace Tree
movement changes database placement only; it does not move or rename Original
Snapshot bytes and need not move a stable Working Artifact.

## 5. Lazy materialization boundary

"Lazy extraction" means terminal files are not all published as Working Files
during import. It does not mean nested structures can be discovered without
reading nested Container bytes.

Import may create bounded operation-scoped inspection files for inner
Containers. They are cache/staging data, not Working Artifacts, and must be
removed or recoverably quarantined when no longer committed to an operation.

First Open of a virtual terminal item performs:

```text
resolve Source Relationship chain
  -> read from immutable Original Snapshot
  -> safely materialize only the target entry
  -> calculate actual size/SHA-256
  -> publish stable Working Artifact
  -> persist baseline fingerprint
  -> hand the verified path to the OS
```

## 6. Workspace operations

### Move

- changes only `parent_workspace_item_id` and ordering;
- rejects cycles and cross-Project parents;
- cannot target a Source Container as if it were an archive writer;
- persists across restart.

### Add

- copies the selected external input into a new immutable snapshot boundary;
- creates a user-added Workspace Item;
- never keeps the external path as the editable working file;
- reuses the same safe inspection/materialization pipeline for Containers.

### Delete and restore

- requires explicit confirmation;
- changes Workspace lifecycle only;
- preserves Source Structure, Original Snapshot, and Working Artifact bytes;
- Restore returns the item to its recorded prior placement when valid, otherwise
  to the Project root with a clear result.

### Import undo

Import undo applies only to one completed top-level `ImportSessionItem` bound to
a Source Root. It previews impact and requires confirmation before removing that
Source's Project-owned Original, Working, and version bytes. Siblings from the
same drop and the external input remain unchanged. Embedded members and ordinary
logical nodes do not gain arbitrary permanent deletion.

### Rename

Rename is not part of the first Workbench implementation milestone. Logical and
physical rename semantics, invalid names, extensions, and interaction with an
open external editor need a separate decision. Position adjustment does not
implicitly authorize rename.

### Rollback

Only two bounded slots exist: `CURRENT_CHECKPOINT` and `PREVIOUS`. A confirmed
rollback swaps them, so an accidental save can be undone and the rollback can
itself be reversed. This is not full history, diff, or merge.

### Export

A single selected terminal file exports its current Working bytes. One ordinary
Workspace folder exports as an ordinary directory with its active subtree and
empty directories. Multiple selections export to ZIP with safe
Workspace-relative paths. The destination remains outside the managed Project;
directory export never merges into or replaces an existing destination.

## 7. External edit reconciliation

The host OS may not provide a reliable process handle when a file is opened by
association. PIG therefore does not claim to know exactly when the user clicks
Save.

W6 defines these refresh reasons:

- explicit **Refresh file state** action;
- before Open of an already materialized file;
- PIG window regaining focus, for W7 to invoke after UI stability/debounce.

W6 adds no file-system watcher and does not automatically refresh at Project
load or future export/close gates. Actual size and SHA-256 determine `CLEAN` or
`MODIFIED`. Save-As outside the Project is outside V1 tracking.

## 8. Planned Application actions

These are typed in-process Application contracts, not public Tools yet:

| Action/query | Risk | Purpose |
|---|---|---|
| `import_inputs` | Write | Snapshot and inspect dropped paths |
| `get_workspace_tree` | Read | Load mutable Project organization |
| `get_source_structure` | Read | Resolve original Container structure |
| `open_workspace_item` | Write/external | Materialize or refresh the stable Working Artifact and open it |
| `refresh_working_artifact` | Read + state write | Reconcile current fingerprint |
| `restore_working_artifact` | Confirmed write | Replay immutable baseline bytes into the stable path |
| `move_workspace_item` | Write | Change logical placement/order |
| `add_workspace_inputs` | Write | Add new snapshotted inputs |
| `delete_workspace_item` | Write | Soft-delete after confirmation |
| `restore_workspace_item` | Write | Restore deleted placement |
| `search_workspace_items` | Read | Search current Workspace Tree |
| `rollback_working_artifact` | Confirmed write | Swap current and previous bounded versions |
| `preview_import_undo` | Read | Describe the complete Source-root removal impact |
| `undo_imported_item` | Confirmed destructive Project write | Remove one accidental top-level import while preserving its external input and capture tombstone |
| `export_workspace_items` | Read + external write | Export current Workspace bytes outside the managed Project |

No MCP, remote API, Agent, or Automation adapter is part of V1.

## 9. V1 acceptance boundary

V1 passes when all of the following are true:

1. multiple files/folders can be dropped in one operation;
2. accepted external bytes are copied and verified inside the Project;
3. the external inputs remain unchanged and can be removed after successful
   import without breaking the Project;
4. nested Folder/ZIP/7z/RAR/MSG/EML structure is displayed within limits;
5. terminal members are not all durably materialized during import;
6. first Open materializes only the selected file with a safe usable suffix;
7. the normal host application can save that Working File in place;
8. deterministic refresh detects `MODIFIED`, `MISSING`, and unreadable states;
9. move/add/soft-delete/restore survive restart;
10. Workspace changes never modify Original Snapshot or source Containers;
11. one broken object yields an explicit item result without discarding siblings;
12. security/resource policies apply to inspection and materialization.
13. the whole Workspace empty surface accepts drops to Project root;
14. materialized files use safe recognizable display names;
15. current and previous versions survive restart and support confirmed rollback;
16. single- and multi-selection export current Working results safely.
17. a new Project is stored at `<selected-parent>/<project-name>/project.sqlite`;
18. one accidental top-level import can be previewed and undone without changing
    its siblings or external input;
19. one ordinary Workspace folder exports as a normal structure-preserving
    directory.

## 10. Explicit deferrals

Now not implemented: archive/email write-back, transparent repack, arbitrary-node
permanent purge, logical rename, full history beyond the two bounded version slots,
diff/merge, file locking across
applications, preview renderer, thumbnails, content index, OCR, semantic layer,
AI, Agent, Workflow engine, Automation engine, MCP, cloud sync, multi-user
collaboration, or cross-project search.
