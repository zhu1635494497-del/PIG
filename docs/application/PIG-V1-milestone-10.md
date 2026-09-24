# PIG V1 Milestone 10：加固、Recovery、Performance 与 Packaging / Hardening, Recovery, Performance, and Packaging

> Historical implemented milestone. New V1 work follows ADR-010 and Workbench
> Milestones W0-W8; this package is not a Workbench acceptance build.

> 中文摘要：本阶段实现 Explicit Recovery、Reversible Quarantine、Qt Worker、
> Performance Baseline 和 PyInstaller Internal Package。可写 Workbench 引入新的
> Recovery 风险，因此必须在 W8 重新验证。

- 状态：已实现，Windows Internal Acceptance Build 已验证 / Status: Implemented; Windows internal acceptance build verified
- 日期：2026-09-19 / Date: 2026-09-19
- 决策 / Decisions: D9-A, D10-A, D11-A, D12-A in `ADR-008`; D13-A through D16-A in `ADR-009`
- Schema Head：Alembic `0005` / Schema head: Alembic `0005`

## 1. Closed recovery flow

```text
User selects Recover Project
  -> close stale active Job / Attempt facts
  -> mark active Nodes INTERRUPTED
  -> create and start a new RECOVER_INTERRUPTED Job
  -> compare Workspace output with persisted Artifact / Manifest keys
  -> move uncommitted output to reversible quarantine
  -> append ORPHAN_QUARANTINED Events
  -> queue DISCOVERED / INTERRUPTED Nodes as new Attempts
  -> persist terminal Job / Project state and RECOVERY_FINISHED
```

Recovery is explicit. A routine Process Project action cannot reinterpret stale
active state and cannot erase old execution history.

## 2. Domain and persistence changes

- `NodeProcessingStatus.INTERRUPTED` distinguishes process interruption from a
  domain failure.
- Recovery/cancellation/interruption Event vocabulary is persisted and
  constrained by SQLite.
- Source or Artifact `VERIFYING` state is reconciled to `UNREADABLE`, with an
  Event, before a new attempt re-verifies it.
- Alembic `0005` migrates enum constraints, restores immutable/append-only
  triggers, and adds the partial unique active-Job index.
- Lineage and Parent/Child Relationships are unchanged. New Attempts operate on
  the same immutable Node identity and append history instead of replacing it.

## 3. Workspace safety

- Recovery accepts only an absolute, real, non-symlink Project root.
- Persisted storage keys are grammar-validated before reconciliation.
- Known Artifact and Manifest outputs are never treated as orphan candidates.
- Candidates are containment-checked and moved with `os.replace`; no recursive
  deletion is performed.
- Each quarantine directory has a machine-readable `report.json`.
- Original Sources remain external references and are never moved or modified.

## 4. Desktop behavior

New Project, Open Project, Import, Process, Recover, Export Manifest, and Open
File are run outside the Qt GUI thread. While one action is active, conflicting
actions are disabled and an indeterminate progress indicator is shown. Closing
the window during an active persistence action is refused. Unexpected process
termination is handled later through explicit recovery.

This does not add task persistence, pause/cancel, automatic retry, or a worker
service.

### 4.1 Project storage selection correction

New Project now requires the user to choose an absolute Workspace root. The
Application request carries that choice to the Workspace adapter, which retains
the approved `<workspace-root>/projects/<project-id>/project.sqlite` layout and
the existing staging/publish protocol. The UI shows the final Project directory
both in a completion message and as a selectable active-project label. Cancelling
either the name or directory dialog creates no Project.

No schema, domain state, Lineage, Source policy, Artifact layout, or business
Event vocabulary changed. Automated coverage verifies custom-root creation,
relative-root rejection, UI selection, final-path display, and all existing V1
flows. The standard human procedure is
`PIG-V1-desktop-acceptance.md`.

## 5. Performance baseline

`tools/benchmark_catalog.py` creates a catalog-only fixture through the migrated
schema, then measures existing Application query/export boundaries. On the
2026-09-15 Windows reference host with 10,000 Nodes and 9,999 Metadata records:

| Operation | Result |
|---|---:|
| Load full Evidence Tree | 0.7044 s |
| Exact structural/Metadata search | 0.0958 s |
| Export 20,975,859-byte Manifest | 2.7366 s |

Tree memory RSS delta was about 22.2 MiB and Manifest export delta about 27.9
MiB. These values are a reproducible baseline, not a universal SLA. The raw
result is `release/performance-baseline.json`.

## 6. Release evidence

- PyInstaller 6.22.3 Windows `onedir`, without UPX;
- packaged runtime self-test exits 0 after Qt offscreen initialization,
  migrations `0001..0005`, Project creation, and reload;
- acceptance-corrections rebuild: 908 files, 112,755,063 bytes;
- `PIG.exe` SHA-256:
  `297b968d9e859706ae89cb834806831ed5aaa4088bcd44a125919f5ed865e236`;
- no `7z`/`7zz` executable or DLL is bundled;
- runtime SBOM contains 40 components;
- `pip-audit` reports no known vulnerabilities for the captured runtime set.

A current-host packaged-flow pre-acceptance also passed with the corrected
build: `ZIP -> persisted archive Folder -> EML -> ZIP -> PDF` yielded five
persisted Nodes, five Lineage records for the leaf, one structural Search hit,
verified typed controlled Open via a recording adapter, Manifest export, and
reversible quarantine of both the injected orphan and derived handoff cache.
The Original Source SHA-256 remained unchanged. The generated Project and
machine-readable report is under
`acceptance/acceptance-corrections-packaged/8bee4840-7de0-4f4c-a35d-1c2088204044/`.
This is not a clean-VM or manually verified GUI-interaction result.

The current acceptance build lives in `dist/acceptance-corrections-build/PIG/` and
includes the user-selected Project storage flow. Its GUI process logged Qt
platform `windows` and `window.isVisible() == True`; user-side interaction with
prepared data remains required.

The release lock contains exact versions. The generated third-party metadata is
not legal approval: external distribution remains blocked pending human license
review and code signing.

## 7. Explicitly not implemented

Now not implemented: automatic retry, pause/resume, persistent async queue,
multi-machine workers, installer/MSIX/DMG/AppImage, auto-update, code signing,
cross-platform build verification, content indexing, OCR, AI, Agent, Workflow,
Automation, MCP, Graph DB, or Vector DB.

## 7.1 Desktop acceptance corrections

- ZIP, 7z, and RAR safe internal directory prefixes are now persisted as Folder
  Nodes. Direct Relationships and Lineage reproduce the actual nested evidence
  structure. Existing Projects are not rewritten; acceptance requires a new
  Project and reimport.
- The UUID remains the physical Project identity, while the desktop shows the
  Project name, short ID, and full storage path and explains the UUID on create.
- Search converts UI values into domain enums, supports multiple format filters,
  and opens an allowed result through the same controlled double-click action as
  Evidence Tree.
- UTC remains the persisted Event time. The UI renders system-local time and
  exposes the raw UTC ISO instant as a tooltip.
- Extracted Artifact names remain immutable `content`; Windows receives a
  size/hash-verified typed copy from the controlled `.open-handoff` cache.
- Manifest success has an explicit modal confirmation with output identity.

These changes require no schema migration and add no V2 capability. Recovery
quarantines `.open-handoff` as derived, reproducible output.

## 8. Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe tools\benchmark_catalog.py --nodes 10000 --output release\performance-baseline.json
.\.venv\Scripts\python.exe tools\generate_release_metadata.py
.\.venv\Scripts\cyclonedx-py.exe requirements release\requirements-runtime.txt --pyproject pyproject.toml --output-reproducible --of JSON -o release\pig-runtime.cdx.json
.\.venv\Scripts\pip-audit.exe -r release\requirements-runtime.txt
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean packaging\PIG.spec
```
