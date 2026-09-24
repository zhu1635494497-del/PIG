# ADR-001：PIG V1 基础决策 / PIG V1 Foundation Decisions

- 状态：部分被 ADR-010 取代 / Status: Superseded in part by ADR-010
- 决策日期：2026-09-13 / Decision date: 2026-09-13
- 范围：PIG V1 / Scope: PIG V1
- 取代：无 / Supersedes: none

## Context

> 中文摘要：本文记录旧证据导向 V1 的 D1-D8。ADR-010 已针对新 Workbench
> Project 取代 D1；D2-D8 在未被 ADR-010 冲突修改时仍有效。核心内容包括每个
> Project 一个 SQLite、SQLAlchemy/Alembic、ZIP/7z/RAR Backend、Password 与
> Symbolic Link Policy、跨平台目标和受控打开。

> Workbench reset notice: ADR-010 supersedes D1 for new V1 Projects and changes
> the current product scope. D2-D8 remain constraints unless ADR-010 explicitly
> changes their application. This document otherwise records the historical
> evidence-oriented foundation.

PIG V1 must establish Ingestion, Catalog, Lineage, processing state, and processing history without prematurely implementing content indexing, AI, workflow engines, or distributed infrastructure.

This ADR records the eight decisions explicitly approved by the product owner. A later change to any item below is an architecture decision and must not be made silently.

## Decisions

### D1 — Source ingestion uses external references

Selected: Option A.

PIG records and reads the external source in place. It does not create an Original Snapshot or Workspace Copy by default.

Consequences:

- PIG must never modify, rename, move, delete, or extract into an external source.
- An imported source is identified by its recorded locator and import-time fingerprint, not only by its current path.
- Before processing, retrying, exporting bytes, or opening an externally referenced file, PIG must revalidate the source against its recorded fingerprint.
- If the source is missing, the current operation is blocked with `SOURCE_MISSING`.
- If the source differs, the current operation is blocked with `SOURCE_CHANGED`.
- A changed source must be imported as a new Source. Existing Source, Node, hash, and lineage facts must not be overwritten to represent the new bytes.
- Restoring the exact original bytes may make the existing Source processable again after revalidation.
- Folder sources have no single content hash in V1. Each discovered file receives its own observed identity when read.
- Because the bytes remain under external control, PIG provides tamper detection rather than physical immutability. Project portability and self-contained archival are not guaranteed in V1.

### D2 — One SQLite database per Project

Selected: Option B.

Each Project owns a separate SQLite database inside its project workspace.

Consequences:

- Project isolation, backup, recovery, and migration remain simple.
- Cross-project search is outside V1.
- A future global project catalog may reference project databases but must not become their source of domain truth.

### D3 — SQLAlchemy 2.x and Alembic

Selected: Option B.

Persistence will use SQLAlchemy 2.x and Alembic when Milestone 2 is authorized.

Consequences:

- Domain entities and value objects must not depend on SQLAlchemy.
- ORM models are infrastructure mappings, not domain objects or API contracts.
- Schema evolution must use migrations rather than ad hoc table creation.

### D4 — Archive backends

Selected:

- ZIP: Python standard library.
- 7z: prefer a pure Python implementation.
- RAR: controlled 7-Zip adapter.

Before Milestone 7 starts, packaging, executable provenance, supported 7-Zip versions, invocation hardening, and licensing must be reviewed and explicitly confirmed.

Milestone 7 confirmation: packaging Option B was accepted on 2026-09-14. The
concrete backend and trust-boundary decision is recorded in `ADR-005`.

### D5 — Password-protected archives are blocked

Selected: Option B.

V1 detects encrypted archives or entries and records `PASSWORD_REQUIRED`. It does not collect, store, cache, infer, or automatically try passwords.

### D6 — Symbolic links are not followed

Selected: Option B.

PIG records a symbolic-link discovery as blocked/skipped evidence when possible but never follows it during V1 ingestion. This applies to directory sources and archive link entries.

### D7 — Cross-platform V1

Selected: Option B.

V1 targets Windows, macOS, and Linux.

Consequences:

- Domain paths use platform-neutral logical-path semantics.
- External physical locators retain their path flavor and are resolved by an infrastructure adapter.
- Filesystem, default-open, dependency detection, packaging, and security tests must cover all three platforms.
- Platform-specific behavior cannot leak into Domain or Application contracts.

### D8 — Restricted open policy

Selected: Option B.

Only configured document, image, text, and email formats may be handed to the operating system for opening. Unknown, executable, script, shortcut, and otherwise high-risk formats are not opened directly.

Before an external reference is opened, PIG must:

1. resolve it through the approved source locator;
2. ensure it is still within the registered source boundary;
3. reject symbolic links;
4. revalidate its fingerprint;
5. apply the allowed-format policy;
6. emit an open-request result event.

For blocked formats, a future UI may offer a separately authorized “reveal in folder” action. That action is not defined as direct file opening.

## Scope guard

Milestones 1-10 and ADR-002 through ADR-009 remain the historical implementation
record. ADR-010 resets the target V1 product. Workbench W1 and D25-B were later
authorized and completed under ADR-011. The current authorization boundary is
listed in `docs/PIG-V1-planning-index.md`.
