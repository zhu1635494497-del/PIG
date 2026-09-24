# ADR-007：PySide6 桌面与受控打开 / PySide6 Desktop and Controlled File Open

- 状态：部分被 ADR-010 取代 / Status: Superseded in part by ADR-010
- 决策日期：2026-09-15 / Decision date: 2026-09-15
- 实现日期：2026-09-15 / Implementation date: 2026-09-15
- 范围：Milestone 9 / Scope: Milestone 9

## Context

> 中文摘要：PySide6 和 Backend-controlled OS Handoff 继续有效。旧流程在打开前校验
> 不可变 Artifact；ADR-010 将其改为首次安全物化、随后直接编辑稳定 Working
> Artifact，并把 Drag/Drop 与 Workspace Tree 作为新 UI 范围。

> PySide6 and backend-controlled OS handoff remain valid. ADR-010 supersedes the
> immutable-open assumption with stable editable Working Artifacts and makes the
> Workspace Tree, drag/drop, and mutation actions the new V1 desktop scope.

Milestone 9 must expose the already-persisted V1 catalog without moving business
truth into a GUI. It must also implement D8: a user may request an allowed file
to be opened, but only after backend policy and current byte-integrity checks.

## Decision

Use `PySide6-Essentials` and Qt Widgets for one local desktop window. The UI calls
typed in-process Application contracts and never imports SQLAlchemy repositories,
performs extraction, calculates hashes, resolves Artifact locators, or decides
whether a format is safe.

Only Qt Core, Gui, and Widgets are required, so the smaller Essentials package is
used instead of installing Qt Addons. The supported dependency range is
`>=6.8,<6.11`; the verified development version is 6.10.3. PySide6 is Qt's
official Python binding and is available under LGPLv3/GPLv2/GPLv3 or commercial
terms. Distribution notices, binary bundling, and installer/license verification
remain Milestone 10 work.

Official references:

- <https://doc.qt.io/qtforpython-6/>
- <https://doc.qt.io/qtforpython-6/licenses.html>

## Application contracts

- `load_project(database_path)` reads the one-Project SQLite identity without UI
  SQL or a separate global catalog.
- `get_project_tree(project_id, database_path)` returns Nodes with their persisted
  direct-parent context and ordinal.
- `open_node(project_id, database_path, node_id, actor)` owns allowlisting,
  locator resolution, integrity revalidation, event recording, and OS handoff.

These are in-process Application actions/queries. Milestone 9 does not publish a
Tool, API, MCP server, Workflow, or Automation adapter.

## Controlled-open policy

The default allowlist is XLSX/XLS/CSV, PDF, DOCX/DOC, PPTX/PPT, TXT,
JPG/JPEG/PNG, MSG, and EML. Folder, archive Container, Unknown, executable,
script, shortcut, and other formats are denied.

Before handoff, `OpenNodeService` requires exactly one Artifact and:

1. validates the Project database/workspace identity;
2. applies the Domain allowlist;
3. resolves through the SourceInspector or ArtifactStore boundary;
4. rejects symlinks and out-of-bound paths;
5. recalculates SHA-256/size against accepted facts;
6. persists resulting Source/Artifact integrity state and business Events;
7. passes only the verified absolute regular-file path to `FileOpener`.

The system adapters use `os.startfile` on Windows, `open <path>` on macOS,
and `xdg-open <path>` on Linux. Unix invocations use an argument vector with
`shell=False`.

## Event and failure semantics

Successful root external open:

```text
FILE_OPEN_REQUESTED
  -> SOURCE_VERIFICATION_STARTED
  -> SOURCE_VERIFIED
  -> ARTIFACT_VERIFIED
  -> FILE_OPENED
```

Policy denial ends with `FILE_OPEN_DENIED / OPEN_FORMAT_DENIED`. Integrity
denial ends with Source/Artifact integrity Events and `FILE_OPEN_DENIED`.
Host-association failure ends with `FILE_OPEN_FAILED / OPEN_HANDOFF_FAILED`.
Technical exceptions go only to Debug Log; business Events contain safe codes
and generated references.

## Consequences and deferred work

- Project processing is synchronous and may temporarily block the UI; background
  workers/progress cancellation belong to Milestone 10.
- Verification and OS handoff are separate system calls, leaving a small host-OS
  time-of-check/time-of-use window for externally mutable files. V1 detects
  changes up to handoff and never changes the accepted fingerprint.
- No preview renderer, thumbnails, drag/drop, context-menu file mutation,
  reveal-in-folder, recent-project catalog, preferences center, Dashboard, user
  center, or AI chat is added.
- Packaging, bundled 7-Zip provenance, Qt license notices, signing, and
  Windows/macOS/Linux installer qualification remain Milestone 10.
