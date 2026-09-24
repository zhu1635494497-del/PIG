from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from pig.application import CreateProjectRequest
from pig.bootstrap import create_local_application
from pig.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_idle(qt_app, window: MainWindow, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    idle_since = None
    while time.monotonic() < deadline:
        qt_app.processEvents()
        idle = window._worker_thread is None and not window._reload_after_background
        if idle:
            idle_since = time.monotonic() if idle_since is None else idle_since
            if time.monotonic() - idle_since >= 0.05:
                return
        else:
            idle_since = None
        time.sleep(0.01)
    raise AssertionError(f"desktop did not become idle: {window._busy_operation}")


def test_project_open_enters_read_only_recovery_gate_then_recovers(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W8 Desktop", actor="tester")
    )
    residue = project.workspace_path / ".inspection" / "interrupted"
    residue.mkdir(parents=True)
    (residue / "content").write_bytes(b"cache")
    answers = iter(
        (
            QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
    )
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: next(answers)),
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda _parent, title, message: notices.append((title, message))),
    )
    window = MainWindow(application, actor="tester")

    window._project_loaded(project.project_id, project.database_path)
    _wait_idle(qt_app, window)

    assert window._recovery_required
    assert not window.recovery_banner.isHidden()
    assert not window.add_files_action.isEnabled()
    assert window.recovery_action.isEnabled()
    assert residue.exists()

    window._inspect_active_project_recovery()
    _wait_idle(qt_app, window)

    assert not window._recovery_required
    assert not residue.exists()
    assert window.add_files_action.isEnabled()
    assert any(title == "恢复完成" for title, _message in notices)
    window.close()
