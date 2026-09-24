from __future__ import annotations

import io
import sys

import pytest

from pig.infrastructure.archives.seven_zip_rar_adapter import (
    BoundedSubprocessRunner,
    CommandOutputLimitError,
    CommandTimeoutError,
    SevenZipRarBackend,
)


def test_seven_zip_discovers_only_a_standard_windows_installation(
    tmp_path, monkeypatch
) -> None:
    executable = tmp_path / "Program Files" / "7-Zip" / "7z.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fixture")
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "Program Files"))
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)

    assert SevenZipRarBackend.discover_standard_windows_installation() == executable


def test_runner_captures_bounded_stdout_and_stderr_without_a_shell() -> None:
    runner = BoundedSubprocessRunner()

    result = runner.capture(
        (
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'out'); sys.stderr.buffer.write(b'err')",
        ),
        timeout_seconds=5,
        max_stdout_size=100,
        max_stderr_size=100,
    )

    assert result.return_code == 0
    assert result.stdout == b"out"
    assert result.stderr == b"err"


def test_runner_streams_stdout_into_the_callers_writer() -> None:
    runner = BoundedSubprocessRunner()
    output = io.BytesIO()

    result = runner.stream_stdout(
        (sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'evidence')"),
        output,
        timeout_seconds=5,
        max_stderr_size=100,
    )

    assert result.return_code == 0
    assert output.getvalue() == b"evidence"


def test_runner_kills_process_when_capture_exceeds_limit() -> None:
    runner = BoundedSubprocessRunner()

    with pytest.raises(CommandOutputLimitError):
        runner.capture(
            (sys.executable, "-c", "print('x' * 1000)"),
            timeout_seconds=5,
            max_stdout_size=10,
            max_stderr_size=100,
        )


def test_runner_kills_process_at_timeout() -> None:
    runner = BoundedSubprocessRunner()

    with pytest.raises(CommandTimeoutError):
        runner.capture(
            (sys.executable, "-c", "import time; time.sleep(5)"),
            timeout_seconds=0.1,
            max_stdout_size=100,
            max_stderr_size=100,
        )
