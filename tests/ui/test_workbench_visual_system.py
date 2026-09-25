from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFrame, QMessageBox

from pig.application import CreateProjectRequest
from pig.bootstrap import create_local_application
from pig.ui.main_window import MainWindow
from pig.ui.theme import WORKBENCH_STYLESHEET


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


def test_workbench_visual_hierarchy_preserves_the_existing_file_flow(
    qt_app, tmp_path: Path, monkeypatch
) -> None:
    application = create_local_application(tmp_path / "projects")
    project = application.create_project(
        CreateProjectRequest(name="直觉工作台", actor="tester")
    )
    source = tmp_path / "供应商报价.txt"
    source.write_bytes(b"quote")
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *_args: None))

    window = MainWindow(application, actor="tester")
    assert window.styleSheet() == WORKBENCH_STYLESHEET
    assert window.findChild(QFrame, "projectHeader") is not None
    assert window.findChild(QFrame, "searchPanel") is not None
    assert window.toolbar.objectName() == "mainToolbar"
    assert window.minimumWidth() == 1080
    assert window.left_tabs.tabText(0) == "工作区"
    assert window.left_tabs.tabText(1) == "搜索结果"
    assert window.left_tabs.tabText(2) == "回收站"
    assert window.right_tabs.tabText(0) == "文件详情"
    assert window.right_tabs.tabText(1) == "活动记录"
    assert window.open_selected_button.property("variant") == "primary"
    assert window.left_tabs.minimumWidth() == 620
    assert window.right_tabs.minimumWidth() == 390
    assert not window.new_project_action.icon().isNull()
    assert not window.export_action.icon().isNull()

    window._activate_project(project.project_id, project.database_path)
    _wait_idle(qt_app, window)
    window._add_inputs((source,), None)
    _wait_idle(qt_app, window)
    item = window.tree.topLevelItem(0)
    window.tree.setCurrentItem(item)
    qt_app.processEvents()

    assert window.project_location.text() == "直觉工作台"
    assert "Revision 1" in window.project_meta.text()
    assert window.project_state.text() == "工作区就绪"
    assert window.detail_title.text() == "供应商报价.txt"
    detail_text = window.details.toPlainText()
    assert "工作区信息" in detail_text
    assert "来源" in detail_text
    assert "按需准备（尚未打开）" in detail_text
    window.close()
