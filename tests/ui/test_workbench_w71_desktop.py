from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMessageBox

from pig.application import CreateProjectRequest
from pig.bootstrap import create_local_application
from pig.ui.main_window import MainWindow


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def _wait_idle(qt_app, window: MainWindow, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if window._worker_thread is None and not window._reload_after_background:
            return
        time.sleep(0.01)
    raise AssertionError("desktop did not become idle")


def test_central_workbench_surface_drops_external_paths_to_project_root(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    app = create_local_application(tmp_path / "projects")
    project = app.create_project(CreateProjectRequest(name="Drop", actor="tester"))
    source = tmp_path / "dropped.txt"
    source.write_bytes(b"dropped")
    second = tmp_path / "second.txt"
    second.write_bytes(b"second")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_args: None))
    window = MainWindow(app, actor="tester")
    window._activate_project(project.project_id, project.database_path)
    _wait_idle(qt_app, window)

    class Mime:
        def hasUrls(self):
            return True

        def urls(self):
            return (
                QUrl.fromLocalFile(str(source)),
                QUrl.fromLocalFile(str(second)),
            )

    class Event:
        accepted = False

        def mimeData(self):
            return Mime()

        def acceptProposedAction(self):
            self.accepted = True

        def ignore(self):
            self.accepted = False

    event = Event()
    window.drop_surface.dropEvent(event)
    _wait_idle(qt_app, window)
    assert event.accepted is True
    assert window.tree.topLevelItemCount() == 2
    assert {
        window.tree.topLevelItem(index).text(0)
        for index in range(window.tree.topLevelItemCount())
    } == {"dropped.txt", "second.txt"}
    window.tree.topLevelItem(0).setSelected(True)
    window.tree.topLevelItem(1).setSelected(True)
    assert len(window._selected_export_ids()) == 2
    window.close()
