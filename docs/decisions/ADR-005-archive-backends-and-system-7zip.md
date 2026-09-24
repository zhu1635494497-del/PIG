# ADR-005：7z/RAR Backend、打包与信任边界 / 7z and RAR Backends, Packaging, and Trust Boundary

- 状态：已接受 / Status: Accepted
- 决策日期：2026-09-14 / Decision date: 2026-09-14
- 范围：PIG V1 Milestone 7 / Scope: PIG V1 Milestone 7
- 扩展：`ADR-001` D4/D5 / Extends: `ADR-001` D4 and D5

## Context

> 中文摘要：7z 优先使用 Pure Python Backend；RAR 使用用户提供且版本受控的
> System 7-Zip，PIG 不捆绑该 Executable。调用必须经过 Absolute Path、Version、
> Provenance、Argument 和 Output Validation，不允许任意 PATH Discovery。

Milestone 7 must process 7z and RAR Containers without weakening the existing
Original Source, Artifact Store, processing-limit, and lineage boundaries. RAR
support also introduces an external executable trust boundary. D4 required the
packaging, provenance, supported-version, invocation-hardening, and license
decisions to be confirmed before implementation.

The product owner selected packaging Option B: users provide a system-installed
7-Zip executable. PIG does not bundle it. This can be reconsidered by a future
ADR if deployment evidence shows that assumption is unsuitable.

## Decision

### 7z

- Use `py7zr>=1.1.3,<1.2` as the in-process backend.
- PIG inspects member metadata and extracts one selected member through a
  `WriterFactory` into the bounded Artifact Store writer.
- PIG never asks `py7zr` to extract into a filesystem directory.
- `py7zr` is an application dependency distributed with PIG. Its
  LGPL-2.1-or-later obligations and transitive dependency notices must be
  included in the Milestone 10 packaging/SBOM work.
- The lower bound excludes 1.1.2, which PyPI identifies as yanked because its
  security fix was incomplete.

### RAR

- Use a controlled adapter around a user-installed official 7-Zip executable.
- The executable path is an explicit absolute application configuration value.
  PIG performs no PATH search, registry search, automatic download, or runtime
  installation.
- PIG does not redistribute a 7-Zip executable under this option. Product
  documentation must still identify 7-Zip as an external runtime dependency and
  link its license. Any future bundled binary requires a new ADR and packaging
  license review.
- Initially accept `25.01 <= version < 27.00`. Version is determined by a
  bounded `7-Zip i` probe, not by the filename. Expanding this range requires
  compatibility tests and an explicit maintenance decision.
- Resolve the configured path strictly and require a regular, non-symbolic-link
  file. Record the accepted executable SHA-256 and reported version in the
  structured Container-open event. Recompute and compare the SHA-256 before
  later use. Do not persist the local executable path in business events.
- List with technical output mode and extract exactly one selected member to
  stdout. PIG streams stdout into its bounded Artifact writer; 7-Zip receives no
  output directory.
- Invoke with an argument vector, `shell=False`, disabled stdin, a bounded
  timeout, bounded captured diagnostics, a minimal environment, and a hidden
  window on Windows. Archive paths and member names occur only as argument
  values after the switch terminator.
- Never pass, prompt for, infer, cache, or persist passwords. Encrypted RAR
  evidence becomes `PASSWORD_REQUIRED`.

## Shared Handler behavior

`ArchiveHandler` is the format-neutral Application boundary for both backends.
It applies the centralized archive-entry path policy, symbolic-link block,
duplicate-member rule, entry count, depth/node, per-file size, total expanded
size, and compression-ratio limits. It returns Child descriptors to the existing
queue; it does not recurse or write SQL.

7z and RAR children use `ARCHIVE_ENTRY`. Extracted bytes use
`EXTRACTED_ARTIFACT` / `PROJECT_WORKSPACE`, and physical locations remain based
on Artifact ID rather than untrusted member names.

## Structured outcomes

- missing or invalid configured executable: `UNSUPPORTED` /
  `DEPENDENCY_UNAVAILABLE`;
- unsupported executable version: `UNSUPPORTED` /
  `DEPENDENCY_VERSION_UNSUPPORTED`;
- external-process timeout: `LIMIT_EXCEEDED` /
  `EXTERNAL_PROCESS_TIMEOUT`;
- bounded process output exceeded: `LIMIT_EXCEEDED` /
  `EXTERNAL_PROCESS_OUTPUT_EXCEEDED`;
- encrypted archive or entry: `PASSWORD_REQUIRED`;
- corrupt archive: `CORRUPTED`;
- blocked path or link: `SECURITY_BLOCKED`;
- unsupported archive feature or ambiguous duplicate file identity:
  `UNSUPPORTED`.

## License and provenance references

- [`py7zr` project metadata and release history](https://pypi.org/project/py7zr/)
- [`py7zr` extraction API](https://py7zr.readthedocs.io/en/latest/api.html)
- [7-Zip license](https://www.7-zip.org/license.txt)
- [Official 7-Zip downloads](https://www.7-zip.org/download.html)
- [Official 7-Zip release history](https://www.7-zip.org/sdk.html)

## Consequences and debt

- RAR support is unavailable until an operator supplies a compatible executable
  path; this is a durable per-Node outcome, not an application-startup failure.
- The adapter has deterministic fake-runner integration tests, but the current
  development host has no installed 7-Zip executable or redistributable RAR
  fixture. Real executable/RAR compatibility and Windows/macOS/Linux packaging
  qualification remain a Milestone 10 release gate.
- No RAR creation, repair, SFX execution, multi-volume orchestration, or password
  workflow is introduced.
