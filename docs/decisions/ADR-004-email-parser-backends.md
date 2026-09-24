# ADR-004：邮件解析 Backend / Email Parser Backends

- 状态：已接受 / Status: Accepted
- 决策日期：2026-09-14 / Decision date: 2026-09-14
- 范围：PIG V1 Milestone 6 / Scope: PIG V1 Milestone 6
- 已批准方案：A / Approved option: A

## Context

> 中文摘要：EML 使用 Python Standard Library `email` Parser；MSG 通过受控
> `extract-msg` Adapter。第三方对象和文件系统行为不得越过 Infrastructure Boundary，
> 只返回 PIG 自有 Inspection Record 和 Attachment Bytes。

Milestone 6 must process EML and Outlook MSG as Containers without allowing parser-specific objects, extraction paths, or filesystem behavior to leak into the Processing Application layer. EML has a cross-platform parser in the Python standard library. MSG is an OLE compound format and needs a third-party parser.

The product owner approved Option A: standard-library EML processing plus an `extract-msg` Adapter.

## Decision

- EML uses `email.parser.BytesParser` with the standard `email.policy.default` policy.
- MSG uses `extract-msg>=0.56,<0.57` behind `ExtractMsgBackend`.
- The Adapter returns only PIG-owned immutable inspection records and attachment bytes. No `extract-msg` object crosses the Infrastructure boundary.
- PIG never calls an attachment's `save()` method. The Adapter exports embedded MSG objects to bytes; `LocalArtifactStore` alone controls staging, resource checks, Artifact-ID paths, publication, and rollback.
- The Application and Handler contracts identify children by stable inspection ordinals for one Attempt. Materialization reopens/rechecks the message rather than trusting a caller-provided physical path.
- Network-backed/Web Reference attachments are catalogued as blocked evidence and are never dereferenced.
- Message bodies are not extracted or rendered in V1. Header metadata is structural catalog data; it is not a V2 content index.

## License and packaging consequence

`extract-msg` is distributed under GPLv3. Selecting it as a normal runtime dependency means PIG distribution must be reviewed as a GPLv3 distribution, including the applicable source, license, notice, and downstream-dependency obligations. This is an accepted consequence of Option A, not a deferred technical surprise.

Milestone 6 records the dependency and its boundary. Milestone 10 packaging must add a reproducible dependency lock/SBOM and the required license materials before any external binary or installer is released. External distribution is not approved merely by completing Milestone 6; legal/compliance review remains an explicit release gate.

The minor series is bounded to `0.56.x` because the Adapter depends on parser attachment-type and export APIs. A move to another minor series requires Adapter tests and a dependency/license review, but does not change the domain contract.

References:

- <https://pypi.org/project/extract-msg/>
- <https://github.com/TeamMsgExtractor/msg-extractor/blob/master/LICENSE.txt>

## Failure mapping

- Invalid OLE/MSG structure and standard violations: Node `CORRUPTED`, `CORRUPTED_CONTAINER`.
- Recognized or unrecognized unsupported MSG classes: Node `UNSUPPORTED`, `UNSUPPORTED_FEATURE`.
- Attachment/MIME-part policy limit: Node `LIMIT_EXCEEDED`.
- Web Reference child: Child `SECURITY_BLOCKED`, no Artifact.
- Broken attachment: Child `CORRUPTED`, no Artifact.
- Unsupported attachment representation: Child `UNSUPPORTED`, no Artifact.
- Unexpected parser/programming exception: Node `FAILED`, failed Attempt, technical reference in the Processing error path.

Expected data and format failures remain durable business outcomes. They are not silently skipped and do not become debug logs only.

## Consequences and boundaries

- EML and MSG participate in the existing queue; no recursive Handler calls or new worker framework are introduced.
- Existing `NodeMetadata`, `NodeRelationship`, lineage closure, Artifact, Attempt, Job, and Event tables are sufficient. No schema migration or email-specific aggregate/table is introduced.
- The common Handler inspection result now supports parent metadata and a relationship type per child.
- Python's EML parser and the MSG library may hold a message or attachment payload in memory. Configured file/part/output limits bound accepted inputs, but streaming parser optimization is deferred to Milestone 10.
- Valid-MSG end-to-end testing currently uses the PIG Adapter contract with deterministic fakes; a corrupt real file exercises the installed library's failure mapping. A legally redistributable valid MSG fixture corpus is still required before packaging/release qualification.
- No HTML rendering, active content execution, remote resource loading, digital-signature validation, body indexing, contact/entity normalization, search, UI, Tool protocol, AI, Automation, 7z, or RAR behavior is added.
