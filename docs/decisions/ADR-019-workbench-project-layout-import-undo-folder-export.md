# ADR-019：Workbench W7.2 项目目录、撤销导入与文件夹导出 / Workbench W7.2 Project Layout, Import Undo, and Folder Export

- 状态：已接受并实施 / Status: Accepted and implemented
- 决策日期：2026-09-23 / Decision date: 2026-09-23
- 决策：D65-A、D66-B（收紧）、D67-A、D68-A / Decisions: D65-A, D66-B (narrowed), D67-A, D68-A
- 范围：Workbench Milestone W7.2 / Scope: Workbench Milestone W7.2

## 中文规范正文

### 背景

W7.1 真实使用确认三个直接影响办公效率的问题：新 Project 物理目录只显示内部
UUID；一次拖入多个顶层输入时无法撤销其中的误选项；导出不能把 Workspace 文件夹
作为完整子树交付。常用操作也需要 Tree 右键入口。

### 决策

1. **D65-A**：新 Project 使用用户选择的父目录加合法 Project 名称作为物理目录，
   即 `<selected-parent>/<project-name>/project.sqlite`。Project UUID 继续作为数据库
   内部身份。名称不是安全 Windows 路径段或目标已经存在时必须拒绝，不静默改名或
   覆盖。现有 UUID Project 不迁移。
2. **D66-B（收紧）**：永久移除只表示撤销一个已经完成的顶层 `ImportSessionItem`。
   一次 Drag/Drop 中每个顶层文件或文件夹保持独立 Snapshot；撤销一个 Item 不得影响
   同批其他 Item，也不得删除外部原文件。Action 清除其 Project-owned Original、
   Working 与版本字节，并把派生 Workspace Item 标记为不可恢复的 `PURGED`。任意
   Container 成员或普通逻辑节点不提供伪造的独立彻底删除。
3. **D67-A**：Workspace Tree 和 Deleted Items 增加上下文菜单，后端继续校验所有
   Action；Toolbar 保留，右键菜单不是业务事实来源。
4. **D68-A**：单个普通 Workspace 文件夹可以导出为普通目录，保留所选文件夹名称、
   活跃后代、空普通文件夹和 Container View 层级。单文件仍直接导出；多选仍导出
   ZIP。Folder Export 不重打包原 Container。

### 撤销导入不变量

- 目标 Workspace Item 必须绑定 Source Root；当前 Placement 是否移动不影响识别。
- `ImportSessionItem` 的 Capture 结果仍是历史事实；Purge 状态独立表达当前可用性。
- 已修改 Working File、当前/上一版本和全部同 Source 派生项必须进入影响预览。
- 文件先进入操作级暂存隔离；数据库提交失败时必须在进程内恢复。
- 完成后不得 Open、Materialize、Restore 或 Export 已 Purge 内容。
- 保留最小 ID、状态和 Event Tombstone；不保留可恢复字节。

### 文件夹导出不变量

- 只导出有效 Active 子树，排除 `DELETED/PURGED`。
- Virtual File 先受控物化；已物化文件先 Refresh。
- `MISSING/UNREADABLE`、路径冲突或资源超限使整个导出失败。
- 普通目录通过同级暂存目录发布；已有目标目录不合并、不覆盖。
- Workspace 名称只决定安全导出相对路径，不决定 Project 内部存储路径。

## English normative text

## Context

Real W7.1 use exposed three direct office-workflow gaps: a new Project directory
showed only an internal UUID, one accidentally selected top-level input could
not be undone after a multi-path drop, and export could not deliver a complete
Workspace folder subtree. Common actions also need a Tree context menu.

## Decisions

1. **D65-A**: a new Project uses the selected parent plus a valid Project name:
   `<selected-parent>/<project-name>/project.sqlite`. The Project UUID remains
   the internal database identity. An unsafe Windows path segment or existing
   destination is rejected without silent renaming or replacement. Existing
   UUID Projects are not migrated.
2. **D66-B (narrowed)**: permanent removal means undoing one completed top-level
   `ImportSessionItem`. Each top-level file or folder in one drop retains an
   independent Snapshot. Undoing one never affects its siblings or the external
   input. The Action removes its Project-owned Original, Working, and version
   bytes and marks derived Workspace Items irreversibly `PURGED`. Arbitrary
   Container members and logical nodes do not receive a misleading independent
   hard-delete action.
3. **D67-A**: Workspace Tree and Deleted Items gain context menus while backend
   Actions remain authoritative. The toolbar remains; a context menu is not a
   business source of truth.
4. **D68-A**: one ordinary Workspace folder exports as an ordinary directory,
   preserving its name, active descendants, empty ordinary folders, and
   Container View levels. One file still exports directly and multiple selected
   items still export as ZIP. Folder export never repacks a source Container.

## Import-undo invariants

- The target Workspace Item is bound to a Source Root; later placement changes
  do not change its identity.
- Capture outcome remains historical while purge state expresses availability.
- Modified Working Files, current/previous versions, and every derived item of
  the Source appear in the impact preview.
- Bytes move into operation staging first and are restored in-process if the
  database commit fails.
- Purged content cannot be opened, materialized, restored, or exported.
- Minimal identity, state, and Event tombstones remain; recoverable bytes do not.

## Folder-export invariants

- Only the effectively active subtree is exported; `DELETED/PURGED` is excluded.
- Virtual files are materialized and existing Working Files are refreshed.
- `MISSING/UNREADABLE`, path collision, or resource-limit failure fails the
  complete export.
- A normal directory is published through a sibling staging directory. Existing
  destination directories are neither merged nor replaced.
- Workspace names select safe export-relative paths, never internal storage.
