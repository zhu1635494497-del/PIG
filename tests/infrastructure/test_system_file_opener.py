from __future__ import annotations

from pathlib import Path

import pytest

from pig.application.errors import ApplicationError
from pig.infrastructure.filesystem.system_opener import SystemFileOpener


def test_windows_open_uses_host_association_without_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = (tmp_path / "report.pdf").absolute()
    target.write_bytes(b"%PDF")
    calls: list[str] = []
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("os.startfile", calls.append, raising=False)

    SystemFileOpener().open(target)

    assert calls == [str(target)]


def test_linux_open_uses_argument_vector_and_disables_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = (tmp_path / "report.pdf").absolute()
    target.write_bytes(b"%PDF")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    SystemFileOpener().open(target)

    assert calls[0][0] == ["xdg-open", str(target)]
    assert calls[0][1]["shell"] is False


def test_macos_open_uses_argument_vector_and_disables_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = (tmp_path / "report.pdf").absolute()
    target.write_bytes(b"%PDF")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr("platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "subprocess.Popen",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )

    SystemFileOpener().open(target)

    assert calls[0][0] == ["open", str(target)]
    assert calls[0][1]["shell"] is False


def test_opener_rejects_relative_and_missing_targets(tmp_path: Path) -> None:
    with pytest.raises(ApplicationError):
        SystemFileOpener().open(Path("relative.pdf"))
    with pytest.raises(ApplicationError):
        SystemFileOpener().open((tmp_path / "missing.pdf").absolute())
