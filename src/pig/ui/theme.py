from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QWidget


WORKBENCH_STYLESHEET = """
QMainWindow, WorkbenchDropSurface {
    background: #f3f5f7;
    color: #1f2937;
}

QWidget {
    color: #1f2937;
    font-size: 13px;
}

QFrame#projectHeader,
QFrame#searchPanel {
    background: #ffffff;
    border: 1px solid #dce2e8;
    border-radius: 8px;
}

QLabel#productEyebrow {
    color: #315f86;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#projectTitle {
    color: #17202b;
    font-size: 20px;
    font-weight: 650;
}

QLabel#projectMeta,
QLabel#sectionHint,
QLabel#detailSubtitle {
    color: #687686;
    font-size: 12px;
}

QLabel#projectState {
    background: #f0f3f6;
    color: #526171;
    border: 1px solid #dce2e8;
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 600;
}

QLabel#projectState[state="ready"] {
    background: #e8f0f7;
    color: #315f86;
    border-color: #c8d9e7;
}

QLabel#projectState[state="warning"] {
    background: #fff5e6;
    color: #9a5b13;
    border-color: #f2d39d;
}

QLabel#recoveryBanner {
    padding: 9px 12px;
    color: #8a4b08;
    background: #fff7e8;
    border: 1px solid #efcf97;
    border-radius: 6px;
}

QLabel#searchTitle,
QLabel#detailTitle,
QLabel#sectionTitle {
    color: #263442;
    font-size: 13px;
    font-weight: 650;
}

QLineEdit,
QToolButton[filter="true"] {
    min-height: 32px;
    padding: 0 10px;
    background: #ffffff;
    border: 1px solid #cdd5dd;
    border-radius: 6px;
}

QLineEdit:hover,
QToolButton[filter="true"]:hover {
    border-color: #91a9bd;
}

QLineEdit:focus,
QToolButton[filter="true"]:checked {
    border: 1px solid #315f86;
}

QPushButton {
    min-height: 32px;
    padding: 0 13px;
    background: #ffffff;
    color: #334155;
    border: 1px solid #cdd5dd;
    border-radius: 6px;
    font-weight: 550;
}

QPushButton:hover {
    background: #f2f5f8;
    border-color: #91a9bd;
}

QPushButton:pressed {
    background: #e9eef3;
}

QPushButton:disabled {
    background: #f3f5f7;
    color: #9aa5b1;
    border-color: #e1e6eb;
}

QPushButton[variant="primary"] {
    background: #315f86;
    color: #ffffff;
    border-color: #315f86;
}

QPushButton[variant="primary"]:hover {
    background: #274f70;
    border-color: #274f70;
}

QPushButton[variant="quiet"] {
    background: transparent;
    border-color: transparent;
    color: #526171;
}

QPushButton[variant="quiet"]:hover {
    background: #edf1f5;
}

QToolBar#mainToolbar {
    spacing: 3px;
    padding: 6px 10px;
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #dce2e8;
}

QToolBar#mainToolbar QToolButton {
    min-height: 30px;
    padding: 2px 8px;
    border: 1px solid transparent;
    border-radius: 5px;
    color: #334155;
}

QToolBar#mainToolbar QToolButton:hover {
    background: #eaf0f5;
    border-color: #d1dce5;
}

QToolBar#mainToolbar QToolButton:pressed {
    background: #dce8f1;
}

QToolBar#mainToolbar::separator {
    width: 1px;
    margin: 6px 8px;
    background: #dce2e8;
}

QTabWidget::pane {
    background: #ffffff;
    border: 1px solid #dce2e8;
    border-radius: 0 0 7px 7px;
}

QTabBar::tab {
    min-height: 30px;
    padding: 0 14px;
    margin-right: 3px;
    color: #657383;
    background: #e9edf1;
    border: 1px solid #d8dee5;
    border-bottom: none;
    border-radius: 6px 6px 0 0;
}

QTabBar::tab:selected {
    color: #315f86;
    background: #ffffff;
    font-weight: 650;
}

QTreeWidget,
QTableWidget,
QTextBrowser {
    background: #ffffff;
    alternate-background-color: #f8fafb;
    border: none;
    selection-background-color: #dfeaf3;
    selection-color: #244861;
    outline: 0;
}

QTreeWidget::item,
QTableWidget::item {
    min-height: 30px;
    padding: 2px 5px;
    border-bottom: 1px solid #edf0f3;
}

QTreeWidget::item:hover,
QTableWidget::item:hover {
    background: #edf3f7;
}

QHeaderView::section {
    min-height: 31px;
    padding: 0 7px;
    color: #586675;
    background: #f1f4f7;
    border: none;
    border-right: 1px solid #e0e5ea;
    border-bottom: 1px solid #d9e0e6;
    font-size: 11px;
    font-weight: 650;
}

QTextBrowser#itemDetails {
    padding: 10px;
}

QSplitter::handle {
    width: 7px;
    background: transparent;
}

QSplitter::handle:hover {
    background: #d7e1e9;
}

QMenu {
    padding: 5px;
    background: #ffffff;
    border: 1px solid #cfd7df;
    border-radius: 6px;
}

QMenu::item {
    min-width: 180px;
    padding: 7px 20px 7px 10px;
    border-radius: 4px;
}

QMenu::item:selected {
    background: #e5eef5;
    color: #274f70;
}

QStatusBar {
    color: #5d6a77;
    background: #ffffff;
    border-top: 1px solid #dce2e8;
}

QProgressBar {
    min-height: 7px;
    max-height: 7px;
    background: #e5eaf0;
    border: none;
    border-radius: 3px;
}

QProgressBar::chunk {
    background: #315f86;
    border-radius: 3px;
}

WorkbenchDropSurface[external_drag_active="true"] {
    background: #e8f0f7;
    border: 2px dashed #315f86;
}
"""


def apply_workbench_theme(widget: QWidget) -> None:
    """Apply the deterministic desktop theme without changing application state."""

    widget.setFont(QFont("Microsoft YaHei UI", 9))
    widget.setStyleSheet(WORKBENCH_STYLESHEET)
