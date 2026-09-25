# 🐷 PIG

**Project Ingestion Gateway**

> **PIG eats messy project files and turns them into structured, traceable data.**
>
> **PIG 将杂乱的项目文件转化为结构化、可追溯的数据。**

## 当前版本定位 / Current Version Positioning

PIG V1 是一款面向审计、财务、采购、法务和尽调场景的 Windows 桌面文件工作台。
它解决的不是“磁盘里有哪些文件”，而是“一个复杂项目资料包里到底有什么，以及如何
快速开始工作”。

PIG V1 is a Windows desktop file workbench for audit, finance, procurement,
legal, and due-diligence projects. It is designed to answer not merely “which
files are on disk,” but “what is inside this complex project package, and how
can I start working with it quickly?”

用户可以把文件、文件夹、压缩包和邮件资料直接拖入 PIG。PIG 会保护一份项目内原始
快照，自动发现嵌套结构，并生成可整理的 Workspace Tree。用户随后可以搜索、移动、
增加、删除、恢复、打开、编辑和导出文件，而不需要反复手工解压、保存附件和寻找路径。

Users can drag files, folders, archives, and email material directly into PIG.
PIG protects a Project-owned original snapshot, discovers nested structure, and
builds an editable Workspace Tree. Files can then be searched, moved, added,
deleted, restored, opened, edited, and exported without repeatedly unpacking
archives, saving attachments, and navigating intermediate folders by hand.


## 长期目标 / Long-Term Goal

PIG 的长期概念是 **Project Information Graph**：逐步把原本只能由人手工翻找的项目
资料，变成有结构、有来源、有状态、可检索、可计算，并最终能被 Tool、Workflow 和 AI
稳定消费的数据资产。

PIG's long-term concept is the **Project Information Graph**: progressively
turning project material that previously required manual browsing into
structured, sourced, stateful, searchable, computable data that can eventually
be consumed reliably by Tools, Workflows, and AI.


## PIG V1 功能 / PIG V1 Features

### 1. 项目与安全导入 / Project and Protected Import

- 以明确的项目名称和用户选择的位置创建独立 Project。
- 每个 Project 使用自己的 `project.sqlite` 和受控文件存储。
- 支持将多个文件与文件夹拖入整个 Workbench 区域。
- 导入内容先复制为 Project-owned Original Snapshot；外部原文件不会被修改。
- 保存文件大小、SHA-256 和最小来源绑定，用于完整性检查和重新物化。
- 单项失败不会静默吞掉，也不会使已经接受的 Sibling 一同丢失。

- Create an isolated Project with an explicit name and user-selected location.
- Store each Project in its own `project.sqlite` and controlled file storage.
- Drag multiple files and folders onto the wider Workbench surface.
- Copy accepted input into a Project-owned Original Snapshot without modifying
  the external original.
- Retain size, SHA-256, and minimum origin bindings for integrity checks and
  rematerialization.
- Report per-item failures without discarding accepted siblings.

### 2. 复杂结构发现 / Complex Structure Discovery

- 自动检查 Folder、ZIP、7z、RAR、MSG 和 EML。
- 发现压缩包、邮件附件和嵌套 Container 中的进一步层级。
- 保留压缩包内部的真实目录结构，而不是将所有成员平铺在同一层。
- 对密码保护、损坏、不支持或超出资源限制的对象提供明确结果。
- 未知普通文件不会导致整个 Project 导入失败。

- Inspect Folder, ZIP, 7z, RAR, MSG, and EML containers automatically.
- Discover deeper levels inside archives, email attachments, and nested
  containers.
- Preserve real archive directory hierarchy instead of flattening every member.
- Report password-protected, corrupt, unsupported, or resource-limited objects.
- Keep an unknown ordinary file from failing the whole Project import.

### 3. 可整理的 Workspace Tree / Editable Workspace Tree

- 将 Source Structure 投影为用户实际工作的 Workspace Tree。
- 创建普通 Workspace Folder，并移动或重新排序文件与文件夹。
- 向 Project Root 或指定普通文件夹增加新文件。
- 软删除 Workspace Item，并从 Deleted Items 中恢复。
- 对误拖入的顶层 Import Item，预览影响并显式撤销该次导入。
- Workspace 整理不会重写原始 ZIP、RAR、7z、MSG 或 EML。

- Project Source Structure into the user's editable Workspace Tree.
- Create ordinary Workspace folders and move or reorder files and folders.
- Add new files to the Project root or a selected ordinary folder.
- Soft-delete Workspace Items and restore them from Deleted Items.
- Preview impact and explicitly undo an accidentally imported top-level item.
- Keep Workspace organization separate from backing archive and email content.

### 4. 打开、编辑与版本保护 / Open, Edit, and Version Protection

- 终端文件在需要打开时才物化为稳定 Working File，避免导入时批量解压全部内容。
- 使用 Windows 默认关联的 Host Application 打开允许的文件类型。
- Working File 使用可辨认的安全文件名，而不是统一显示为 `content`。
- 用户在外部应用原地保存后，PIG 可刷新 Size 和 SHA-256 并识别实质修改。
- 为每个 Working File 保留当前版本和一个上一版本，并支持确认回滚。
- Original Snapshot、Source Structure 和 Workspace 位置不受外部编辑影响。

- Materialize a terminal item into a stable Working File only when it is opened.
- Open allowed formats through their Windows-associated host application.
- Give Working Files recognizable, sanitized filenames instead of `content`.
- Refresh size and SHA-256 after an in-place save to detect material changes.
- Retain the current Working version and one previous version, with confirmed
  rollback.
- Leave the Original Snapshot, Source Structure, and Workspace placement intact.

### 5. 查找与交付 / Search and Delivery

- 按名称、格式和当前状态搜索 Workspace Item。
- 格式过滤支持多选；搜索结果可直接双击打开。
- 导出单个文件，并保留当前 Workspace 文件名。
- 将多个选中项导出为 ZIP，并使用安全的 Workspace 相对路径。
- 将整个普通 Workspace Folder 导出为目录，保留嵌套结构、空文件夹和当前字节。
- 导出不会静默覆盖已有目标，成功后会给出明确提示。

- Search Workspace Items by name, format, and current state.
- Select multiple format filters and open a result by double-clicking it.
- Export one file under its current Workspace filename.
- Export multiple selected items as a ZIP with safe Workspace-relative paths.
- Export an ordinary Workspace Folder while preserving its current structure.
- Never overwrite an existing target silently and report successful delivery.

### 6. 恢复与安全边界 / Recovery and Safety Boundaries

- 集中限制深度、数量、单文件大小和展开总大小。
- 防止 Path Traversal、Archive Bomb、Symbolic Link 跟随和恶意文件名选择物理路径。
- 不收集或保存压缩包密码；加密对象记录为 `PASSWORD_REQUIRED`。
- Unknown、可执行文件、脚本和其他未允许格式不会直接交给操作系统打开。
- Project 启动时检查未完成操作和可恢复残留；需要恢复时先进入受限模式。
- 已登记且被用户修改的 Working File 不会被恢复清理误删。

- Enforce centralized limits for depth, count, file size, and expanded size.
- Prevent path traversal, archive bombs, followed symbolic links, and malicious
  filenames from selecting physical destinations.
- Never collect archive passwords; record encrypted content as
  `PASSWORD_REQUIRED`.
- Do not hand Unknown, executable, script, or denied formats to the OS.
- Scan for interrupted operations and residue when opening a Project.
- Preserve registered Working Files modified by the user during recovery.

## 支持的输入 / Supported Inputs

| 类型 / Type | V1 行为 / V1 behavior | 实现 / Implementation |
|---|---|---|
| Folder | 递归发现目录结构 / Recursively discovers structure | Python filesystem adapter |
| ZIP | 检查层级并按需物化 / Inspects and materializes on demand | Python standard library |
| 7z | 检查层级并按需物化 / Inspects and materializes on demand | `py7zr` |
| RAR | 受控检查和物化 / Controlled inspection and materialization | 用户安装的 7-Zip / Operator-installed 7-Zip |
| MSG | 发现 Outlook 邮件附件 / Discovers Outlook attachments | `extract-msg` |
| EML | 发现 MIME 邮件附件 / Discovers MIME attachments | Python email parser |
| XLSX/XLS/CSV, PDF, DOCX/DOC, PPTX/PPT, TXT, JPG/JPEG/PNG | 终端文件；通过系统关联程序打开 / Terminal files opened through OS association | Controlled open policy |
| Unknown file | 保留并显示，但不直接打开 / Preserved but not opened directly | Safe fallback |

RAR 支持要求 Windows 上安装兼容的 7-Zip。PIG 不捆绑 `7z.exe`；ZIP 和 7z 处理不依赖
外部 7-Zip。

RAR support requires a compatible 7-Zip installation on Windows. PIG does not
bundle `7z.exe`; ZIP and 7z processing do not depend on external 7-Zip.

## 技术栈 / Tech Stack

| 范围 / Area | 技术 / Technology |
|---|---|
| 语言 / Language | Python 3.10+ |
| 桌面端 / Desktop UI | PySide6 / Qt 6 |
| 数据库 / Database | SQLite（每个 Project 独立数据库 / one database per Project） |
| ORM 与迁移 / ORM & migrations | SQLAlchemy 2.x + Alembic |
| 压缩包 / Archives | Python `zipfile`, `py7zr`, controlled 7-Zip adapter |
| 邮件 / Email | Python `email` + `extract-msg` |
| 测试 / Testing | pytest |
| 打包 / Packaging | PyInstaller `onedir` |
| 持续集成 / CI | GitHub Actions |

## 如何使用 / How to Use

### 环境要求 / Requirements

- 当前经过验收的桌面目标：Windows x64。
- 从源码运行：Python 3.10 或更高版本。
- RAR：可选安装 7-Zip；其他核心格式不需要外部解压软件。
- 打开 Office、PDF、图片等文件时，需要 Windows 已配置相应默认应用程序。

- Currently qualified desktop target: Windows x64.
- Source runtime: Python 3.10 or newer.
- RAR: optionally install 7-Zip; other core formats need no external extractor.
- Office, PDF, image, and similar files require an associated Windows app.

### 从源码运行 / Run from Source

```powershell
git clone https://github.com/zhu1635494497-del/PIG.git
cd PIG
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pig.ui.app
```

安装后也可以使用生成的入口：

After installation, the generated entry point is also available:

```powershell
.\.venv\Scripts\pig-desktop.exe
```

### 基本操作流程 / Basic Workflow

1. 启动 PIG，点击 **新建项目 / New Project**。
2. 输入项目名称并选择父目录；数据库位于
   `<所选目录>/<项目名称>/project.sqlite`。
3. 将一个或多个文件、文件夹拖入 Workbench。
4. 等待结构发现完成，然后展开 Folder、Archive 和 Email。
5. 双击允许的终端文件；PIG 会按需创建 Working File 并使用系统关联程序打开。
6. 在 Host Application 中原地保存，返回 PIG 后刷新文件状态。
7. 使用移动、增加文件夹、软删除和恢复整理 Workspace。
8. 使用搜索定位文件，最后导出单文件、多选 ZIP 或整个普通文件夹。

1. Start PIG and select **New Project**.
2. Enter a Project name and choose its parent directory. The database is stored
   at `<selected-directory>/<project-name>/project.sqlite`.
3. Drag one or more files or folders into the Workbench.
4. Wait for discovery, then expand folders, archives, and emails.
5. Double-click an allowed terminal file to materialize and open its Working File.
6. Save in place in the host application, return to PIG, and refresh file state.
7. Organize the Workspace through move, folder creation, soft delete, and restore.
8. Search for files and export one file, a multi-selection ZIP, or a folder.

不要手工修改 Project 内的 `project.sqlite`、Original、Working 或内部缓存目录。需要
交付资料时，请使用 PIG 的导出操作。

Do not manually modify `project.sqlite`, Original, Working, or internal cache
directories. Use PIG's export actions for delivery.

## 当前限制 / Current Limitations

- V1 不回写或重新打包 ZIP、RAR、7z、MSG 或 EML。
- 在外部程序中使用 **Save As** 保存到 Project 外部时，PIG 不自动跟踪该文件。
- 每个 Working File 只保留当前版本和一个上一版本。
- 历史 Evidence 模型创建的旧 Project 不在兼容范围内。
- 当前没有内容索引、OCR、RAG、AI Chat、Agent、MCP、云同步或多人协作。
- 当前没有 Installer 或应用内自动更新。

- V1 does not write back or repack ZIP, RAR, 7z, MSG, or EML.
- PIG does not track a **Save As** performed outside the Project.
- Each Working File retains only the current and one previous version.
- Historical Evidence-model Projects are outside the compatibility scope.
- Content indexing, OCR, RAG, AI chat, Agents, MCP, cloud sync, and multi-user
  collaboration are not present.
- There is no installer or in-application updater.

## 测试、文档与贡献 / Testing, Documentation, and Contribution

```powershell
.\.venv\Scripts\python.exe -m pytest
```

- [项目长期规则 / Project rules](PIG%20Project%20Rules.md)
- [当前规划索引 / Active planning index](docs/PIG-V1-planning-index.md)
- [V1 Workbench 范围 / V1 Workbench scope](docs/application/PIG-V1-workbench-scope.md)
- [桌面验收流程 / Desktop acceptance](docs/application/PIG-V1-desktop-acceptance.md)
- [贡献说明 / Contributing](CONTRIBUTING.md)
- [安全报告 / Security](SECURITY.md)

Issue 和 Pull Request 不得包含真实客户资料、Project 数据库、邮件、附件、客户文件名、
本机绝对路径、访问令牌、证书或密钥。

Issues and pull requests must never contain real customer material, Project
databases, email, attachments, customer filenames, local absolute paths, access
tokens, certificates, or keys.

## 下载与发布 / Downloads and Releases

正式 Windows 版本将发布在 [GitHub Releases](https://github.com/zhu1635494497-del/PIG/releases)，
而不是提交到 Git 历史。计划中的正式包包含版本化 Portable ZIP、SHA-256、SBOM、
第三方声明和双语 Release Notes。

Official Windows versions will be published through
[GitHub Releases](https://github.com/zhu1635494497-del/PIG/releases), not
committed into Git history. A formal package is expected to include a versioned
portable ZIP, SHA-256, SBOM, third-party notices, and bilingual release notes.

在许可证人工复核、Authenticode 签名、干净 Windows 主机矩阵、真实 RAR 和最终桌面
验收全部通过前，不应把未签名候选包标记为正式 V1 Release。

No unsigned candidate should be labeled as the official V1 Release until human
license review, Authenticode signing, the clean-Windows host matrix, real-RAR
verification, and final desktop acceptance have passed.

## 许可证 / License

PIG 自有代码使用 [Apache License 2.0](LICENSE)。第三方组件继续受各自许可证约束；
自动生成的 [Third-Party Notices](release/THIRD_PARTY_NOTICES.md) 不能代替人工合规复核。

PIG-owned code is licensed under the [Apache License 2.0](LICENSE). Third-party
components remain governed by their own licenses. Generated
[Third-Party Notices](release/THIRD_PARTY_NOTICES.md) do not replace human
compliance review.

## 贡献者 / Contributors

- [Littlie pig](https://github.com/zhu1635494497-del) — 项目发起人与产品负责人 / Project creator and product owner
- **ChatGPT (OpenAI)** — 架构、实现、测试与文档协作 / Architecture, implementation, testing, and documentation collaboration
