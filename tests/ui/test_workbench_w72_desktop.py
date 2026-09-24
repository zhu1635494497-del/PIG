from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from pig.application import CreateProjectRequest
from pig.bootstrap import create_local_application
from pig.ui.main_window import ITEM_ID_ROLE, MainWindow


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


def _window(tmp_path: Path):
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="W7.2 Desktop", actor="tester")
    )
    return application, project, MainWindow(application, actor="tester")


def test_right_click_action_undoes_only_the_accidental_top_level_import(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    folder = tmp_path / "A"
    folder.mkdir()
    (folder / "kept.txt").write_bytes(b"kept")
    accidental = tmp_path / "A.txt"
    accidental.write_bytes(b"external remains")
    _application, project, window = _window(tmp_path)
    notices = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda _parent, title, message: notices.append((title, message))),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes),
    )
    window._activate_project(project.project_id, project.database_path)
    _wait_idle(qt_app, window)
    window._add_inputs((folder, accidental), None)
    _wait_idle(qt_app, window)
    roots = {
        window.tree.topLevelItem(index).text(0): window.tree.topLevelItem(index)
        for index in range(window.tree.topLevelItemCount())
    }
    item_id = roots["A.txt"].data(0, ITEM_ID_ROLE)
    window.tree.setCurrentItem(roots["A.txt"])
    menu = window._active_context_menu(item_id)
    assert menu is not None
    assert "撤销此次误导入（彻底移除）" in {
        action.text() for action in menu.actions()
    }

    window._undo_import_item(item_id)
    _wait_idle(qt_app, window)

    assert accidental.read_bytes() == b"external remains"
    assert window.tree.topLevelItemCount() == 1
    assert window.tree.topLevelItem(0).text(0) == "A"
    assert any(title == "已撤销误导入" for title, _message in notices)
    window.close()


def test_single_folder_export_uses_selected_parent_and_preserves_tree(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "资料夹"
    nested = source / "子目录"
    nested.mkdir(parents=True)
    (nested / "结果.txt").write_bytes(b"result")
    export_parent = tmp_path / "deliverables"
    export_parent.mkdir()
    _application, project, window = _window(tmp_path)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *_args, **_kwargs: None),
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *_args, **_kwargs: str(export_parent)),
    )
    window._activate_project(project.project_id, project.database_path)
    _wait_idle(qt_app, window)
    window._add_inputs((source,), None)
    _wait_idle(qt_app, window)
    root = window.tree.topLevelItem(0)
    window.tree.setCurrentItem(root)

    window._export_selected()
    _wait_idle(qt_app, window)

    assert (export_parent / "资料夹" / "子目录" / "结果.txt").read_bytes() == b"result"
    window.close()
