# PIG v1.0.0-rc.1 发布说明 / Release Notes

> **候选版 / Pre-release:** 这是未签名的 Windows x64 便携候选版，用于公开测试和反馈。
> 它不是已完成 Authenticode 签名、第三方许可人工复核和干净主机矩阵验收的正式版。
>
> **Pre-release:** This is an unsigned Windows x64 portable candidate for public
> testing and feedback. It is not the final release qualified through
> Authenticode signing, human third-party-license review, and the clean-host
> acceptance matrix.

## 版本标识 / Version Identity

- Git Tag / GitHub Pre-release: `v1.0.0-rc.1`
- Python package version: `1.0.0rc1`
- Target: Windows x64 portable `onedir` ZIP
- Signature: Unsigned / 未签名

## 当前定位 / Current Positioning

PIG — Project Ingestion Gateway 是面向审计、财务、采购、法务和尽调等项目场景的
Windows 文件工作台。它将分散、嵌套的 Folder、Archive 和 Email 资料转换为
保留原始备份、结构清晰且可持续编辑的 Project Workspace。

PIG — Project Ingestion Gateway is a Windows file workbench for audit, finance,
procurement, legal, and due-diligence projects. It turns fragmented and nested
folders, archives, and email material into an editable Project Workspace backed
by a protected original snapshot.

## 主要能力 / Highlights

- 拖入多个文件或文件夹，并建立不可变 Original Snapshot。
- 自动发现 Folder、ZIP、7z、RAR、MSG 和 EML 的嵌套结构。
- 在可编辑 Workspace Tree 中新建文件夹、移动、软删除和恢复。
- 按需物化终端文件，通过 Windows 关联应用打开并识别外部保存。
- 为 Working File 保留当前版本和一个上一版本，支持确认回滚。
- 按名称、格式和状态搜索，并导出单文件、多选 ZIP 或保留结构的文件夹。
- 记录受控错误、处理事件和恢复证据，不修改外部原文件。

- Drag multiple files or folders into an immutable Original Snapshot.
- Discover nested Folder, ZIP, 7z, RAR, MSG, and EML structure automatically.
- Create folders, move items, soft-delete, and restore within an editable
  Workspace Tree.
- Materialize terminal files lazily, open them with Windows-associated host
  applications, and detect external saves.
- Retain the current and one previous Working File version with confirmed
  rollback.
- Search by name, format, and state, then export one file, a multi-selection
  ZIP, or a structure-preserving folder.
- Record controlled failures, processing events, and recovery evidence without
  modifying external source files.

## 安装与运行 / Install and Run

1. 下载 `PIG-v1.0.0-rc.1-windows-x64-unsigned.zip`。
2. 校验同名 `.sha256` 文件。
3. 将 ZIP 完整解压到本地文件夹；不要直接在 ZIP 内运行。
4. 运行解压目录中的 `PIG.exe`。
5. Windows 可能对未签名候选版显示 SmartScreen 警告；请先核对 SHA-256。

1. Download `PIG-v1.0.0-rc.1-windows-x64-unsigned.zip`.
2. Verify it against the accompanying `.sha256` file.
3. Extract the complete ZIP to a local folder; do not run it from inside the ZIP.
4. Run `PIG.exe` from the extracted directory.
5. Windows may display a SmartScreen warning for this unsigned candidate;
   verify the SHA-256 before running it.

RAR 支持需要 Windows 标准位置安装兼容的 7-Zip。PIG 不捆绑 `7z.exe`。

RAR support requires a compatible 7-Zip installation in a standard Windows
location. PIG does not bundle `7z.exe`.

## 已知边界 / Known Boundaries

- 当前只验证 Windows x64，没有 Installer 或应用内自动更新。
- 不回写或重新打包 ZIP、RAR、7z、MSG 或 EML。
- 不追踪在 Host Application 中使用 **Save As** 保存到 Project 之外的文件。
- 大量小文件、超大 Archive 和大规模 Tree 可能出现明显等待；安全资源上限不是性能 SLA。
- 当前不包含 OCR、RAG、AI Chat、Agent、MCP、云同步或多人协作。

- Only Windows x64 is currently qualified; there is no installer or in-app
  updater.
- PIG does not write back or repack ZIP, RAR, 7z, MSG, or EML.
- A **Save As** outside the Project is not tracked.
- Very large trees, archives, and collections of small files may require long
  waits; safety limits are not performance SLAs.
- OCR, RAG, AI chat, Agents, MCP, cloud sync, and multi-user collaboration are
  not included.

## 反馈与安全 / Feedback and Security

请通过 GitHub Issues 提交可复现的问题，但不得上传真实客户文件、Project
数据库、邮件、附件、访问令牌、证书或密钥。安全问题请遵循 `SECURITY.md`。

Use GitHub Issues for reproducible problems, but never upload real customer
files, Project databases, email, attachments, access tokens, certificates, or
keys. Follow `SECURITY.md` for security reports.
