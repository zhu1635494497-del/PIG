# PIG — Project Ingestion Gateway

> 当前状态：Workbench W8 功能闭环与源码桌面验收已通过；W9 发布资格实施中。
> 目前没有正式签名的 V1 二进制 Release。

> Current status: the Workbench W8 functional loop and source-desktop
> acceptance have passed; W9 release qualification is in progress. There is no
> officially signed V1 binary Release yet.

## PIG 是什么 / What PIG is

PIG 是面向审计、财务、采购、法务和尽调项目的复杂文件工作台。它把文件夹、ZIP、
7z、RAR、MSG、EML 和普通文档导入受保护的 Project，在不修改外部原件的前提下发现
嵌套结构，并提供可整理、可打开、可持续编辑和可导出的 Workspace。

PIG is a complex-file workbench for audit, finance, procurement, legal, and
due-diligence projects. It imports folders, ZIP, 7z, RAR, MSG, EML, and ordinary
documents into a protected Project, discovers nested structure without modifying
external originals, and provides an organizable, openable, editable, and
exportable Workspace.

```text
External Input
  -> Immutable Original Snapshot
  -> Source Structure Discovery
  -> Editable Workspace Tree
  -> Lazy Materialization
  -> Controlled Open / External Edit Refresh
  -> Export
```

## V1 当前能力 / Current V1 capabilities

- 拖入文件或文件夹，并建立 Project 内不可变 Original Snapshot。
- 检查 Folder、ZIP、7z、RAR、MSG 和 EML 的嵌套结构。
- 将 Source Structure 投影为可移动、增加、软删除和恢复的 Workspace Tree。
- 仅在打开时物化终端文件，并在 Host Application 保存后刷新状态。
- 保留当前 Working File 和一个 Previous Version，可确认回滚。
- 支持搜索、单文件导出、多选 ZIP 导出和保结构文件夹导出。
- 对误拖入的顶层 Import Item 提供影响预览和显式撤销。
- 使用每 Project 一个 SQLite 数据库和项目内受控文件存储。

- Drag files or folders into a Project-owned immutable Original Snapshot.
- Inspect nested Folder, ZIP, 7z, RAR, MSG, and EML structures.
- Project Source Structure into a movable, addable, soft-deletable, restorable
  Workspace Tree.
- Materialize terminal files only when opened and refresh state after edits in a
  host application.
- Retain the current Working File and one Previous Version with confirmed
  rollback.
- Search and export one file, a multi-selection ZIP, or a structure-preserving
  folder.
- Preview and explicitly undo an accidentally imported top-level item.
- Store one SQLite database per Project with controlled Project-local files.

V1 不实现 OCR、RAG、AI Chat、知识图谱、云同步、多人协作、透明 Archive 回写或应用
内自动更新。详细边界见
[当前规划索引](docs/PIG-V1-planning-index.md)。

V1 does not implement OCR, RAG, AI chat, a knowledge graph, cloud sync,
multi-user collaboration, transparent archive write-back, or in-application
auto-update. See the [active planning index](docs/PIG-V1-planning-index.md) for
the authoritative boundary.

## 从源码运行 / Run from source

当前桌面目标是 Windows x64。源码环境需要 Python 3.10 或更高版本。RAR 处理需要用户
或管理员另行安装受支持的 7-Zip；PIG 不捆绑 `7z.exe`。ZIP 和 7z 不依赖外部 7-Zip。

The current desktop target is Windows x64. Source development requires Python
3.10 or newer. RAR processing requires a supported operator-installed 7-Zip;
PIG does not bundle `7z.exe`. ZIP and 7z do not require external 7-Zip.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\pig-desktop.exe
```

运行自动化测试：

Run the automated test suite:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 下载与版本 / Downloads and versions

正式版本将发布在
[GitHub Releases](https://github.com/zhu1635494497-del/PIG/releases)，而不是提交到
Git 源码历史。每个正式 Windows Release 必须包含版本化 Portable ZIP、SHA-256、SBOM、
第三方声明和双语 Release Notes。

Official versions will be published through
[GitHub Releases](https://github.com/zhu1635494497-del/PIG/releases), not
committed into Git source history. Each official Windows release must include a
versioned portable ZIP, SHA-256, SBOM, third-party notices, and bilingual release
notes.

在人工第三方许可证复核、Authenticode 签名、干净 Windows 主机矩阵和最终桌面验收全部
通过前，任何自动构建都只是 **Unsigned Internal RC**，不是正式 Release。

Until human third-party license review, Authenticode signing, the clean-Windows
host matrix, and final desktop acceptance all pass, every automated build is an
**Unsigned Internal RC**, not an official Release.

## 文档与贡献 / Documentation and contribution

- 项目长期规则：[PIG Project Rules.md](PIG%20Project%20Rules.md)
- 当前规划：[docs/PIG-V1-planning-index.md](docs/PIG-V1-planning-index.md)
- Workbench 范围：[docs/application/PIG-V1-workbench-scope.md](docs/application/PIG-V1-workbench-scope.md)
- 桌面验收：[docs/application/PIG-V1-desktop-acceptance.md](docs/application/PIG-V1-desktop-acceptance.md)
- 贡献说明：[CONTRIBUTING.md](CONTRIBUTING.md)
- 安全报告：[SECURITY.md](SECURITY.md)

所有 PIG 自有 Markdown 使用中英文双语。Issue 或 Pull Request 不得包含真实客户资料、
Project 数据库、邮件、附件、文件名清单或本机绝对路径。

All first-party PIG Markdown is bilingual. Issues and pull requests must never
contain real customer material, Project databases, email, attachments, filename
inventories, or local absolute paths.

## 许可证 / License

PIG 自有代码使用 [Apache License 2.0](LICENSE)。第三方组件继续受各自许可证约束；
自动生成的 [Third-Party Notices](release/THIRD_PARTY_NOTICES.md) 不是人工合规批准。

PIG-owned code is licensed under the [Apache License 2.0](LICENSE). Third-party
components remain governed by their own licenses; generated
[Third-Party Notices](release/THIRD_PARTY_NOTICES.md) are not a substitute for
human compliance approval.
