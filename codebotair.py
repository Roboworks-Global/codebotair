#!/usr/bin/env python3
"""PyQt6 macOS/Windows app for Codebot Air — Arduino-based robot controller."""

import sys
import os
import re
import time
import json
import glob
import shutil
import subprocess
import signal
import math
import urllib.request
import urllib.error
import base64
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QDoubleSpinBox, QComboBox, QPushButton, QTextEdit,
    QGroupBox, QGridLayout, QLineEdit, QMessageBox,
    QTabWidget, QPlainTextEdit, QStackedWidget, QListWidget,
    QSplitter, QScrollArea, QInputDialog, QTreeWidget, QTreeWidgetItem,
    QTreeWidgetItemIterator, QAbstractItemView, QTableWidget, QTableWidgetItem, QHeaderView,
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QFrame,
    QButtonGroup, QMenu, QRadioButton, QProgressDialog, QSizePolicy, QFileDialog,
)
from PyQt6.QtCore import (
    QThread, pyqtSignal, QRegularExpression, Qt, QSize, QRect,
    QTimer, QMimeData, QPointF, QRectF,
)
from PyQt6.QtGui import (
    QFont, QSyntaxHighlighter, QTextCharFormat, QColor, QPainter, QDrag,
    QPen, QBrush, QPolygonF, QTextCursor, QPainterPath, QPixmap, QIcon,
)

try:
    import serial
    import serial.tools.list_ports
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False

# --- Configuration ---
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_GIT_CREDS_FILE = os.path.join(_PKG_DIR, ".git_credentials.json")

# Arduino-cli executable — full path so it works when launched outside a terminal
ARDUINO_CLI = os.path.expanduser("~/.local/bin/arduino-cli")
# Board FQBN for Wheeltec MiniBalance Duino (ATmega328P, UNO-compatible, CH340)
CODEBOT_FQBN = "arduino:avr:uno"
# Default baud rate for serial communication with Codebot Air
CODEBOT_BAUD = 115200

# Files to show in Full View (relative to _PKG_DIR)
_FULL_VIEW_FILES = [
    "codebotair.py",
    "roboapps",
]

# Default project files/folders that cannot be deleted from Full View
_PROTECTED_FV_FOLDERS = {"roboapps"}
_PROTECTED_FV_FILES = {"codebotair.py"}

# Path to movement.py (retained for editor compatibility; may not exist in Codebot Air)
MOVEMENT_PY = os.path.join(_PKG_DIR, "movement_pkg", "movement.py")

# Code snippets for drag-and-drop in Simple View (8-space indent for __init__ body)
_SIMPLE_VIEW_SNIPPETS = {
    # Control
    "if_statement": (
        "        # --- if statement ---  \u2190 edit\n"
        "        if condition:  # \u2190 edit condition\n"
        "            pass  # \u2190 edit action\n"
    ),
    "while_statement": (
        "        # --- while loop ---  \u2190 edit\n"
        "        while condition:  # \u2190 edit condition\n"
        "            pass  # \u2190 edit action\n"
    ),
    "switch_statement": (
        "        # --- if/elif ---  \u2190 edit\n"
        "        if value == option1:  # \u2190 edit\n"
        "            pass\n"
        "        elif value == option2:  # \u2190 edit\n"
        "            pass\n"
        "        else:\n"
        "            pass\n"
    ),
    "for_loop": (
        "        # --- for loop ---  \u2190 edit\n"
        "        for i in range(10):  # \u2190 edit range\n"
        "            pass  # \u2190 edit action\n"
    ),
    # Movement
    "forward_speed": (
        "        self.move(self.forward_speed)  # drive forward\n"
    ),
    "backward_speed": (
        "        self.move(-self.backward_speed)  # reverse\n"
    ),
    "turn_speed": (
        "        self.set_speed(self.turn_speed)  # set turn speed\n"
    ),
    "turn_clockwise": (
        "        self.turn_cw(self.turn_cw_deg)  # turn CW\n"
    ),
    "turn_anti_clockwise": (
        "        self.turn_acw(self.turn_acw_deg)  # turn ACW\n"
    ),
    "stop_movement": (
        "        self.stop()  # stop robot\n"
    ),
    # Sensing
    "obstacle_distance": (
        "        if self.obstacle_in_front():  # check obstacle\n"
        "            pass  # \u2190 edit action\n"
    ),
    "colour_detection": (
        "        if self.detect_colour():  # detect colour\n"
        "            pass  # \u2190 edit action\n"
    ),
}



# --- Drag-and-drop function buttons for Simple View ---

class DraggableFunctionButton(QPushButton):
    """A light-blue rounded button that can be dragged into the code editor."""

    def __init__(self, label, code_snippet, parent=None):
        super().__init__(label, parent)
        self._code_snippet = code_snippet
        self._drag_start_pos = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setStyleSheet(
            "QPushButton {"
            "  background-color: #E0EAF0; border: 1px solid #B0C4D0;"
            "  border-radius: 8px; padding: 6px 10px; text-align: left;"
            "  font-size: 12px; color: #1A1A1A;"
            "}"
            "QPushButton:hover { background-color: #D0DDE8; }"
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_start_pos is not None
                and event.buttons() & Qt.MouseButton.LeftButton):
            distance = (event.pos() - self._drag_start_pos).manhattanLength()
            if distance >= QApplication.startDragDistance():
                drag = QDrag(self)
                mime = QMimeData()
                mime.setText(self._code_snippet)
                drag.setMimeData(mime)
                drag.exec(Qt.DropAction.CopyAction)
                self._drag_start_pos = None
        super().mouseMoveEvent(event)


class FunctionsPanel(QWidget):
    """Left-side panel listing draggable function blocks grouped by category."""

    _CATEGORIES = [
        ("Control", [
            ("if_statement", "if_statement"),
            ("while_statement", "while_statement"),
            ("switch_statement", "switch_statement"),
            ("for_loop", "for_loop"),
        ]),
        ("Movement", [
            ("move_forward", "forward_speed"),
            ("move_backward", "backward_speed"),
            ("set_turn_speed", "turn_speed"),
            ("turn_clockwise", "turn_clockwise"),
            ("turn_anti_clockwise", "turn_anti_clockwise"),
            ("stop", "stop_movement"),
        ]),
        ("Sensing", [
            ("check_obstacle", "obstacle_distance"),
            ("detect_colour", "colour_detection"),
        ]),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("FUNCTIONS")
        title.setFont(QFont("Menlo", 13, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("margin-bottom: 4px;")
        layout.addWidget(title)

        for cat_name, functions in self._CATEGORIES:
            header = QLabel(cat_name)
            header.setFont(QFont("Menlo", 11, QFont.Weight.Bold))
            header.setStyleSheet("margin-top: 8px; color: #555555;")
            layout.addWidget(header)
            for btn_label, snippet_key in functions:
                btn = DraggableFunctionButton(
                    btn_label, _SIMPLE_VIEW_SNIPPETS[snippet_key]
                )
                layout.addWidget(btn)

        layout.addStretch()


# --- Code editor with line numbers ---

class _LineNumberArea(QWidget):
    """Gutter widget that displays line numbers for a LineNumberEditor."""

    def __init__(self, editor):
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self):
        return QSize(self._editor._line_area_width(), 0)

    def paintEvent(self, event):
        self._editor.line_number_area_paint(event)


class LineNumberEditor(QPlainTextEdit):
    """QPlainTextEdit with a line-number gutter on the left."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._line_area = _LineNumberArea(self)
        self.blockCountChanged.connect(self._update_line_area_width)
        self.updateRequest.connect(self._update_line_area)
        self.cursorPositionChanged.connect(self._line_area.update)
        self._update_line_area_width()

    def _line_area_width(self):
        digits = max(1, len(str(self.blockCount())))
        return int(1.5 * (10 + self.fontMetrics().horizontalAdvance('9') * digits))

    def _update_line_area_width(self, _=0):
        self.setViewportMargins(self._line_area_width(), 0, 0, 0)

    def _update_line_area(self, rect, dy):
        if dy:
            self._line_area.scroll(0, dy)
        else:
            self._line_area.update(0, rect.y(), self._line_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_line_area_width()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_area.setGeometry(
            cr.left(), cr.top(), self._line_area_width(), cr.height()
        )

    def line_number_area_paint(self, event):
        painter = QPainter(self._line_area)
        painter.fillRect(event.rect(), QColor("#F0F0F0"))
        current_block_number = self.textCursor().blockNumber()
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                if block_number == current_block_number:
                    painter.fillRect(
                        0, top, self._line_area.width(),
                        self.fontMetrics().height(), QColor("#D0D0FF"),
                    )
                    painter.setPen(QColor("#0000CC"))
                else:
                    painter.setPen(QColor("#999999"))
                painter.drawText(
                    0, top,
                    self._line_area.width(),
                    self.fontMetrics().height(),
                    Qt.AlignmentFlag.AlignCenter,
                    str(block_number + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1
        painter.end()


class SimpleViewEditor(LineNumberEditor):
    """Editor for Simple View — only allows drops inside the control_loop section."""

    def _logic_start_line(self):
        """Return the line number of 'def control_loop', or None."""
        for i, line in enumerate(self.toPlainText().split('\n')):
            if 'def control_loop' in line:
                return i
        return None

    def dragEnterEvent(self, event):
        """Accept drag so the cursor tracks, but actual gating is in dropEvent."""
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        """Show forbidden cursor when hovering over the parameter section."""
        logic_line = self._logic_start_line()
        if logic_line is not None:
            hover_line = self.cursorForPosition(event.position().toPoint()).blockNumber()
            if hover_line <= logic_line:
                event.ignore()
                return
        event.acceptProposedAction()

    def dropEvent(self, event):
        """Block drops above the control_loop section."""
        logic_line = self._logic_start_line()
        if logic_line is not None:
            drop_line = self.cursorForPosition(event.position().toPoint()).blockNumber()
            if drop_line <= logic_line:
                event.ignore()
                return
        super().dropEvent(event)


# --- Syntax highlighter for Simple View ---

class SimpleCodeHighlighter(QSyntaxHighlighter):
    """Highlights editable parameter values in the Simple View code editor."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._keyword_fmt = QTextCharFormat()
        self._keyword_fmt.setForeground(QColor("#AA00AA"))
        self._keyword_fmt.setFontWeight(QFont.Weight.Bold)

        self._value_fmt = QTextCharFormat()
        self._value_fmt.setForeground(QColor("#0055DD"))
        self._value_fmt.setFontWeight(QFont.Weight.Bold)

        self._string_fmt = QTextCharFormat()
        self._string_fmt.setForeground(QColor("#008800"))
        self._string_fmt.setFontWeight(QFont.Weight.Bold)

        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor("#888888"))

        self._self_fmt = QTextCharFormat()
        self._self_fmt.setForeground(QColor("#AA5500"))
        self._self_fmt.setFontWeight(QFont.Weight.Bold)

        self._edit_marker_fmt = QTextCharFormat()
        self._edit_marker_fmt.setForeground(QColor("#FF4400"))
        self._edit_marker_fmt.setFontWeight(QFont.Weight.Bold)

        self._drop_guide_fmt = QTextCharFormat()
        self._drop_guide_fmt.setForeground(QColor("#FF0000"))
        self._drop_guide_fmt.setFontWeight(QFont.Weight.Bold)

    def highlightBlock(self, text):
        stripped = text.lstrip()

        # Full-line comments
        if stripped.startswith('#'):
            # Drag-and-drop guide line — red + bold
            if 'Drag and drop' in text:
                self.setFormat(0, len(text), self._drop_guide_fmt)
            else:
                self.setFormat(0, len(text), self._comment_fmt)
            return

        # Python keywords
        for kw in ['import', 'from', 'class', 'def', 'super']:
            for m in re.finditer(rf'\b{kw}\b', text):
                self.setFormat(m.start(), len(m.group()), self._keyword_fmt)

        # self.param_name (before =)
        for m in re.finditer(r'self\.(\w+)\s*=', text):
            self.setFormat(m.start(), len(m.group()) - 1, self._self_fmt)

        # Numeric values after =
        for m in re.finditer(r'=\s*([\d.]+)', text):
            self.setFormat(m.start(1), len(m.group(1)), self._value_fmt)

        # Quoted strings
        for m in re.finditer(r'"([^"]*)"', text):
            self.setFormat(m.start(), len(m.group()), self._string_fmt)

        # Inline comments
        idx = text.find('#')
        if idx > 0:
            self.setFormat(idx, len(text) - idx, self._comment_fmt)

        # "← edit" marker in bright orange-red (overrides comment grey)
        edit_idx = text.find('\u2190 edit')
        if edit_idx >= 0:
            self.setFormat(edit_idx, 6, self._edit_marker_fmt)


# --- Syntax highlighter for Full View ---

class FullViewHighlighter(QSyntaxHighlighter):
    """Syntax highlighting for Full View: green comments, red warning comments."""

    _WARNING_PATTERNS = [
        "do not edit", "do not delete", "do not change", "do not remove",
        "could break", "take precaution",
        "customize main function below", "end main customization",
        "note: editing any of the generated code",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._comment_fmt = QTextCharFormat()
        self._comment_fmt.setForeground(QColor("#2E7D32"))  # green

        self._warning_fmt = QTextCharFormat()
        self._warning_fmt.setForeground(QColor("#D32F2F"))  # red

    def highlightBlock(self, text):
        stripped = text.lstrip()
        if stripped.startswith('#'):
            idx = text.index('#')
            comment_text = text[idx:]
        else:
            idx = text.find('#')
            if idx < 0:
                return
            comment_text = text[idx:]

        lower = comment_text.lower()
        for pat in self._WARNING_PATTERNS:
            if pat in lower:
                self.setFormat(idx, len(text) - idx, self._warning_fmt)
                return

        self.setFormat(idx, len(text) - idx, self._comment_fmt)


class CodeEditorDialog(QDialog):
    """Popup code editor for editing node/topic source files."""

    def __init__(self, title, file_path, search_text="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(700, 500)
        self._file_path = file_path
        self._saved = False
        self._show_in_code = False

        layout = QVBoxLayout(self)

        # Top row: Show In Code (left) | file path | Cancel + Save (right)
        top_row = QHBoxLayout()

        show_in_code_btn = QPushButton("Show In Code")
        show_in_code_btn.setStyleSheet(
            "QPushButton { padding: 6px 16px; border-radius: 8px; "
            "border: 1px solid #007AFF; color: #007AFF; }")
        show_in_code_btn.clicked.connect(self._on_show_in_code)
        top_row.addWidget(show_in_code_btn)

        path_label = QLabel(os.path.basename(file_path))
        path_label.setStyleSheet("color: #666; font-size: 11px;")
        top_row.addWidget(path_label)
        top_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { padding: 6px 16px; border-radius: 8px; border: 1px solid #ccc; }")
        cancel_btn.clicked.connect(self.reject)
        top_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; "
            "padding: 6px 16px; border-radius: 8px; font-weight: bold; }")
        save_btn.clicked.connect(self._save)
        top_row.addWidget(save_btn)
        layout.addLayout(top_row)

        # Code editor
        self._editor = LineNumberEditor()
        self._editor.setFont(QFont("Menlo", 12))
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._highlighter = FullViewHighlighter(self._editor.document())
        layout.addWidget(self._editor)

        # Load file + jump to search_text
        try:
            with open(file_path, "r") as f:
                self._editor.setPlainText(f.read())
        except Exception as e:
            self._editor.setPlainText(f"# Error loading file: {e}")
        if search_text:
            cursor = self._editor.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            self._editor.setTextCursor(cursor)
            self._editor.find(search_text)

    def _save(self):
        try:
            with open(self._file_path, "w") as f:
                f.write(self._editor.toPlainText())
            self._saved = True
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Save Error", str(e))

    def _on_show_in_code(self):
        self._show_in_code = True
        self.accept()

    @property
    def saved(self):         return self._saved
    @property
    def show_in_code(self):  return self._show_in_code
    @property
    def file_path(self):     return self._file_path
    @property
    def content(self):       return self._editor.toPlainText()


def _make_github_icon(size=20, color="#333333"):
    """Return a QIcon containing the GitHub Invertocat mark rendered at *size*×*size*."""
    # GitHub mark SVG path (24×24 viewBox, MIT-licensed mark)
    SVG_D = (
        "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385"
        ".6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724"
        "-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7"
        "c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236"
        " 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605"
        "-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22"
        "-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23"
        ".96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405"
        " 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176"
        ".765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92"
        ".42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286"
        " 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297"
        "c0-6.627-5.373-12-12-12"
    )

    # Parse SVG path into QPainterPath
    path = QPainterPath()
    tokens = re.findall(
        r'[MmCcLlZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?', SVG_D)
    i = 0
    cmd = None
    cx = cy = sx = sy = 0.0

    def nf():
        nonlocal i
        v = float(tokens[i]); i += 1; return v

    while i < len(tokens):
        if tokens[i] in 'MmCcLlZz':
            cmd = tokens[i]; i += 1; continue
        if cmd == 'M':
            x, y = nf(), nf(); path.moveTo(x, y); cx = x; cy = y; sx = x; sy = y; cmd = 'L'
        elif cmd == 'm':
            x = cx + nf(); y = cy + nf(); path.moveTo(x, y); cx = x; cy = y; sx = x; sy = y; cmd = 'l'
        elif cmd == 'L':
            x, y = nf(), nf(); path.lineTo(x, y); cx = x; cy = y
        elif cmd == 'l':
            x = cx + nf(); y = cy + nf(); path.lineTo(x, y); cx = x; cy = y
        elif cmd == 'C':
            x1, y1, x2, y2, x, y = nf(), nf(), nf(), nf(), nf(), nf()
            path.cubicTo(x1, y1, x2, y2, x, y); cx = x; cy = y
        elif cmd == 'c':
            x1 = cx + nf(); y1 = cy + nf()
            x2 = cx + nf(); y2 = cy + nf()
            x  = cx + nf(); y  = cy + nf()
            path.cubicTo(x1, y1, x2, y2, x, y); cx = x; cy = y
        elif cmd in 'Zz':
            path.closeSubpath(); cx = sx; cy = sy; cmd = None
        else:
            i += 1

    # Render path into a QPixmap
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    scale = size / 24.0
    painter.scale(scale, scale)
    painter.fillPath(path, QBrush(QColor(color)))
    painter.end()
    return QIcon(px)


class GitHubButton(QPushButton):
    """Circular button (same style as the ? help button) with a GitHub mark icon."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)
        self.setIcon(_make_github_icon(20, "#333333"))
        self.setIconSize(QSize(20, 20))
        self.setToolTip("Git / GitHub")
        self.setStyleSheet(
            "QPushButton { background-color: white; border-radius: 18px; "
            "border: 1px solid #CCCCCC; }"
            "QPushButton:hover { background-color: #F0F0F0; }"
        )


# ---------------------------------------------------------------------------
# Git dialogs
# ---------------------------------------------------------------------------

class GitInitDialog(QDialog):
    """Dialog: Initialize local git repo + create GitHub repository via API."""

    def __init__(self, creds, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Initialize & Create GitHub Repo")
        self.setMinimumWidth(460)
        self._result_creds = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        self._user  = QLineEdit(creds.get("username", ""))
        self._user.setPlaceholderText("your-github-username")

        # PAT row: field + help link
        pat_row = QHBoxLayout()
        self._pat = QLineEdit(creds.get("token", ""))
        self._pat.setEchoMode(QLineEdit.EchoMode.Password)
        self._pat.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx")
        pat_help = QPushButton("?")
        pat_help.setFixedSize(22, 22)
        pat_help.setStyleSheet(
            "QPushButton { background: white; border-radius: 11px; "
            "border: 1px solid #ccc; font-weight: bold; font-size: 11px; color: #555; }"
            "QPushButton:hover { background: #f0f0f0; }"
        )
        pat_help.setToolTip("How to create a GitHub Personal Access Token")
        pat_help.clicked.connect(lambda: subprocess.Popen(
            ["open", "https://github.com/settings/tokens/new"
             "?description=TestDrive&scopes=repo"]))
        pat_row.addWidget(self._pat)
        pat_row.addWidget(pat_help)

        self._repo = QLineEdit(creds.get("repo_name", ""))
        self._repo.setPlaceholderText("my-robot-project")

        self._desc = QLineEdit(creds.get("description", ""))
        self._desc.setPlaceholderText("Optional description")

        form.addRow("GitHub Username:", self._user)
        form.addRow("Personal Access Token:", pat_row)
        form.addRow("Repository Name:", self._repo)
        form.addRow("Description:", self._desc)
        layout.addLayout(form)

        # Public / Private toggle
        vis_row = QHBoxLayout()
        vis_label = QLabel("Visibility:")
        vis_label.setFixedWidth(140)
        vis_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._pub_btn  = QPushButton("Public")
        self._priv_btn = QPushButton("Private")
        for btn in (self._pub_btn, self._priv_btn):
            btn.setCheckable(True)
            btn.setFixedWidth(90)
        self._pub_btn.setChecked(True)
        self._pub_btn.clicked.connect(lambda: self._set_vis(False))
        self._priv_btn.clicked.connect(lambda: self._set_vis(True))
        self._private = False
        self._update_vis_style()
        vis_row.addWidget(vis_label)
        vis_row.addWidget(self._pub_btn)
        vis_row.addWidget(self._priv_btn)
        vis_row.addStretch()
        layout.addLayout(vis_row)

        # Options
        self._readme_cb = QCheckBox("Create README.md")
        self._readme_cb.setChecked(True)
        self._save_cb   = QCheckBox("Save credentials for this session")
        self._save_cb.setChecked(creds.get("save", True))
        layout.addWidget(self._readme_cb)
        layout.addWidget(self._save_cb)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(
            "QPushButton { padding: 8px; border-radius: 8px; border: 1px solid #ccc; }")
        cancel_btn.clicked.connect(self.reject)
        create_btn = QPushButton("Create")
        create_btn.setFixedWidth(90)
        create_btn.setStyleSheet(
            "QPushButton { background-color: #2DA44E; color: white; "
            "padding: 8px; border-radius: 8px; font-weight: bold; }"
            "QPushButton:hover { background-color: #218A41; }"
        )
        create_btn.clicked.connect(self._accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(create_btn)
        layout.addLayout(btn_row)

    def _set_vis(self, private: bool):
        self._private = private
        self._pub_btn.setChecked(not private)
        self._priv_btn.setChecked(private)
        self._update_vis_style()

    def _update_vis_style(self):
        active   = "background-color: #0969DA; color: white; padding: 6px; border-radius: 6px; font-weight: bold;"
        inactive = "background-color: #f6f8fa; color: #333; padding: 6px; border-radius: 6px; border: 1px solid #ccc;"
        self._pub_btn.setStyleSheet(active if not self._private else inactive)
        self._priv_btn.setStyleSheet(active if self._private else inactive)

    def _accept(self):
        if not self._user.text().strip():
            QMessageBox.warning(self, "Missing Field", "GitHub Username is required."); return
        if not self._pat.text().strip():
            QMessageBox.warning(self, "Missing Field", "Personal Access Token is required."); return
        if not self._repo.text().strip():
            QMessageBox.warning(self, "Missing Field", "Repository Name is required."); return
        self._result_creds = {
            "username":    self._user.text().strip(),
            "token":       self._pat.text().strip(),
            "repo_name":   self._repo.text().strip(),
            "description": self._desc.text().strip(),
            "private":     self._private,
            "readme":      self._readme_cb.isChecked(),
            "save":        self._save_cb.isChecked(),
        }
        self.accept()

    def result_creds(self):
        return self._result_creds


class GitPushDialog(QDialog):
    """Dialog: Commit + push to GitHub."""

    def __init__(self, creds, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Commit & Push to GitHub")
        self.setMinimumWidth(460)
        self._result = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(10)

        default_msg = f"TestDrive update {time.strftime('%Y-%m-%d %H:%M')}"
        self._msg  = QLineEdit(default_msg)

        # Build default repo URL from saved creds
        saved_user = creds.get("username", "")
        saved_repo = creds.get("repo_name", "")
        default_repo_url = (
            f"https://github.com/{saved_user}/{saved_repo}"
            if saved_user and saved_repo else ""
        )
        self._repo_url = QLineEdit(default_repo_url)
        self._repo_url.setPlaceholderText("https://github.com/username/repo")

        # PAT row
        pat_row = QHBoxLayout()
        self._pat = QLineEdit(creds.get("token", ""))
        self._pat.setEchoMode(QLineEdit.EchoMode.Password)
        self._pat.setPlaceholderText("ghp_xxxxxxxxxxxxxxxxxxxx")
        pat_help = QPushButton("?")
        pat_help.setFixedSize(22, 22)
        pat_help.setStyleSheet(
            "QPushButton { background: white; border-radius: 11px; "
            "border: 1px solid #ccc; font-weight: bold; font-size: 11px; color: #555; }"
            "QPushButton:hover { background: #f0f0f0; }"
        )
        pat_help.setToolTip("How to create a GitHub Personal Access Token")
        pat_help.clicked.connect(lambda: subprocess.Popen(
            ["open", "https://github.com/settings/tokens/new"
             "?description=TestDrive&scopes=repo"]))
        pat_row.addWidget(self._pat)
        pat_row.addWidget(pat_help)

        self._branch = QComboBox()
        self._branch.addItems(["main", "windows", "roboapps"])
        saved_branch = creds.get("branch", "main")
        idx = self._branch.findText(saved_branch)
        self._branch.setCurrentIndex(idx if idx >= 0 else 0)

        form.addRow("Commit Message:", self._msg)
        form.addRow("GitHub Repository:", self._repo_url)
        form.addRow("Branch:", self._branch)
        form.addRow("Personal Access Token:", pat_row)
        layout.addLayout(form)

        self._save_cb = QCheckBox("Save credentials for this session")
        self._save_cb.setChecked(creds.get("save", True))
        layout.addWidget(self._save_cb)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(90)
        cancel_btn.setStyleSheet(
            "QPushButton { padding: 8px; border-radius: 8px; border: 1px solid #ccc; }")
        cancel_btn.clicked.connect(self.reject)
        push_btn = QPushButton("Push")
        push_btn.setFixedWidth(90)
        push_btn.setStyleSheet(
            "QPushButton { background-color: #0969DA; color: white; "
            "padding: 8px; border-radius: 8px; font-weight: bold; }"
            "QPushButton:hover { background-color: #0757BA; }"
        )
        push_btn.clicked.connect(self._accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(push_btn)
        layout.addLayout(btn_row)

    def _accept(self):
        if not self._repo_url.text().strip():
            QMessageBox.warning(self, "Missing Field", "GitHub Repository URL is required."); return
        if not self._pat.text().strip():
            QMessageBox.warning(self, "Missing Field", "Personal Access Token is required."); return
        self._result = {
            "message":  self._msg.text().strip() or f"TestDrive update {time.strftime('%Y-%m-%d %H:%M')}",
            "repo_url": self._repo_url.text().strip(),
            "branch":   self._branch.currentText(),
            "token":    self._pat.text().strip(),
            "save":     self._save_cb.isChecked(),
        }
        self.accept()

    def result_data(self):
        return self._result


# --- Main window ---

class RobotControlApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Codebot Air")
        self.setMinimumWidth(600)
        self._workers = []
        self._serial_conn = None
        self._usb_port = None
        self._known_ports = None  # None = first scan not yet done; skip auto-connect
        self._syncing = False
        self._full_view_current_file = None
        self._fv_edit_mode = False
        self._blocking_item_changed = False

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Header row with Git / ? / Run / Stop buttons ---
        header_row = QHBoxLayout()

        self.git_btn = GitHubButton()
        self.git_btn.clicked.connect(self._show_git_menu)
        header_row.addWidget(self.git_btn)

        header_row.addSpacing(6)

        self.support_btn = QPushButton("?")
        self.support_btn.setFixedSize(36, 36)
        self.support_btn.setStyleSheet(
            "QPushButton { background-color: white; color: #333333; "
            "border-radius: 18px; border: 1px solid #CCCCCC; "
            "font-size: 16px; font-weight: bold; }"
            "QPushButton:hover { background-color: #F0F0F0; }"
        )
        self.support_btn.setToolTip("Contact Support")
        self.support_btn.clicked.connect(self._show_support_dialog)
        header_row.addWidget(self.support_btn)

        header_row.addStretch()

        self.run_btn = QPushButton("Run")
        self.run_btn.setFixedWidth(90)
        self.run_btn.setStyleSheet(
            "QPushButton { background-color: #34C759; color: white; padding: 8px; "
            "border-radius: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #B0B0B0; color: #707070; border-radius: 8px; }"
        )
        self.run_btn.setToolTip("Compile and upload code to Codebot Air")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._run_code)
        header_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setFixedWidth(90)
        self.stop_btn.setStyleSheet(
            "QPushButton { background-color: #FF3B30; color: white; padding: 8px; "
            "border-radius: 8px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #B0B0B0; color: #707070; border-radius: 8px; }"
        )
        self.stop_btn.setToolTip("Stop the robot")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_robot)
        header_row.addWidget(self.stop_btn)

        main_layout.addLayout(header_row)

        # --- Tabs ---
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_robot_control_tab()
        self._build_code_editor_tab()
        self._build_roboapps_tab()

        # USB port scanner — updates every 2 seconds
        self._usb_timer = QTimer(self)
        self._usb_timer.setInterval(2000)
        self._usb_timer.timeout.connect(self._scan_usb_ports)
        self._usb_timer.start()

    # ------------------------------------------------------------------ #
    #  Tab 1: Robot Control                                                #
    # ------------------------------------------------------------------ #

    def _build_robot_control_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- USB Connection group ---
        conn_group = QGroupBox("Robot Connection")
        conn_layout = QVBoxLayout()

        instr_lbl = QLabel(
            "Connect your Codebot Air to your computer using a USB-C cable."
        )
        instr_lbl.setWordWrap(True)
        instr_lbl.setStyleSheet("color: #555; font-size: 13px; padding: 4px 0;")
        conn_layout.addWidget(instr_lbl)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("USB Port:"))
        self._port_combo = QComboBox()
        self._port_combo.setMinimumWidth(280)
        self._port_combo.setPlaceholderText("No device detected")
        port_row.addWidget(self._port_combo)
        port_row.addStretch()
        conn_layout.addLayout(port_row)

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; padding: 8px; border-radius: 8px; }"
            "QPushButton:disabled { background-color: #B0B0B0; color: #707070; border-radius: 8px; }"
        )
        self.connect_btn.setMinimumWidth(100)
        self.connect_btn.setEnabled(False)
        self.connect_btn.clicked.connect(self._do_usb_connect)
        btn_row.addWidget(self.connect_btn)

        self.conn_status = QLabel("Not connected")
        self.conn_status.setStyleSheet("color: #FF3B30; font-weight: bold; padding-left: 8px;")
        btn_row.addWidget(self.conn_status)
        btn_row.addStretch()
        conn_layout.addLayout(btn_row)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # --- Parameters group ---
        param_group = QGroupBox("Parameters")
        param_layout = QGridLayout()

        # Left column
        param_layout.addWidget(QLabel("Forward Speed (m/s):"), 0, 0)
        self.forward_speed = QDoubleSpinBox()
        self.forward_speed.setRange(0.01, 2.0)
        self.forward_speed.setSingleStep(0.05)
        self.forward_speed.setDecimals(2)
        self.forward_speed.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.forward_speed, 0, 1)

        param_layout.addWidget(QLabel("Backward Speed (m/s):"), 1, 0)
        self.backward_speed = QDoubleSpinBox()
        self.backward_speed.setRange(0.01, 2.0)
        self.backward_speed.setSingleStep(0.05)
        self.backward_speed.setDecimals(2)
        self.backward_speed.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.backward_speed, 1, 1)

        param_layout.addWidget(QLabel("Turn Speed (rad/s):"), 2, 0)
        self.turn_speed = QDoubleSpinBox()
        self.turn_speed.setRange(0.1, 3.0)
        self.turn_speed.setSingleStep(0.1)
        self.turn_speed.setDecimals(2)
        self.turn_speed.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.turn_speed, 2, 1)

        param_layout.addWidget(QLabel("Obstacle Distance (m):"), 3, 0)
        self.obstacle_distance = QDoubleSpinBox()
        self.obstacle_distance.setRange(0.10, 2.0)
        self.obstacle_distance.setSingleStep(0.05)
        self.obstacle_distance.setDecimals(2)
        self.obstacle_distance.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.obstacle_distance, 3, 1)

        # Right column
        param_layout.addWidget(QLabel("Turn Clockwise (deg):"), 0, 2)
        self.turn_cw = QDoubleSpinBox()
        self.turn_cw.setRange(0, 360)
        self.turn_cw.setSingleStep(5)
        self.turn_cw.setDecimals(1)
        self.turn_cw.setValue(90.0)
        self.turn_cw.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.turn_cw, 0, 3)

        param_layout.addWidget(QLabel("Turn Anti-Clockwise (deg):"), 1, 2)
        self.turn_acw = QDoubleSpinBox()
        self.turn_acw.setRange(0, 360)
        self.turn_acw.setSingleStep(5)
        self.turn_acw.setDecimals(1)
        self.turn_acw.setValue(90.0)
        self.turn_acw.valueChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.turn_acw, 1, 3)

        param_layout.addWidget(QLabel("Colour Detection:"), 2, 2)
        self.colour_detection = QComboBox()
        self.colour_detection.addItems(["Red", "Blue", "Yellow", "Green"])
        self.colour_detection.currentTextChanged.connect(self._sync_simple_view_from_spinboxes)
        param_layout.addWidget(self.colour_detection, 2, 3)

        _btn_row = QHBoxLayout()
        _btn_row.setSpacing(8)
        _btn_row.setContentsMargins(0, 0, 0, 0)

        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet(
            "background-color: #34C759; color: white; padding: 8px; border-radius: 8px;"
        )
        self.save_btn.setMinimumWidth(100)
        self.save_btn.clicked.connect(self.save)
        _btn_row.addWidget(self.save_btn)

        self.deploy_btn = QPushButton("Deploy")
        self.deploy_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; padding: 8px; border-radius: 8px; }"
            "QPushButton:disabled { background-color: #B0B0B0; color: #707070; border-radius: 8px; }"
        )
        self.deploy_btn.setMinimumWidth(100)
        self.deploy_btn.clicked.connect(self.deploy)
        self.deploy_btn.setEnabled(False)
        _btn_row.addWidget(self.deploy_btn)

        _btn_row.addStretch()
        _btn_container = QWidget()
        _btn_container.setLayout(_btn_row)
        param_layout.addWidget(_btn_container, 4, 0, 1, 4)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # --- Log area ---
        log_group = QGroupBox("Log Output")
        log_layout = QVBoxLayout()
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setFont(QFont("Menlo", 11))
        self.log_area.setMinimumHeight(300)
        log_layout.addWidget(self.log_area)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        self.tabs.addTab(tab, "Robot Control")
    # ------------------------------------------------------------------ #

    def _build_code_editor_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Top bar
        top_bar = QHBoxLayout()

        # Undo / Redo buttons (high-contrast circular style)
        _circle_btn_style = (
            "QPushButton { font-size: 20px; font-weight: bold;"
            "  min-width: 36px; max-width: 36px;"
            "  min-height: 36px; max-height: 36px; border-radius: 18px;"
            "  background-color: #007AFF; color: white;"
            "  border: 2px solid #005ECB; }"
            "QPushButton:hover { background-color: #005ECB; }"
        )
        self.undo_btn = QPushButton("\u21BA")          # ↺ anti-clockwise
        self.undo_btn.setToolTip("Undo")
        self.undo_btn.setStyleSheet(_circle_btn_style)
        self.undo_btn.clicked.connect(self._undo)
        top_bar.addWidget(self.undo_btn)

        self.redo_btn = QPushButton("\u21BB")          # ↻ clockwise
        self.redo_btn.setToolTip("Redo")
        self.redo_btn.setStyleSheet(_circle_btn_style)
        self.redo_btn.clicked.connect(self._redo)
        top_bar.addWidget(self.redo_btn)

        _toggle_btn_style = (
            "QPushButton { border: none; padding: 6px 16px; border-radius: 8px;"
            "  color: white; background: #8E8E93; font-size: 13px; }"
            "QPushButton:checked { background: #007AFF; }"
        )

        self.simple_view_btn = QPushButton("Simple View")
        self.simple_view_btn.setCheckable(True)
        self.simple_view_btn.setChecked(True)
        self.simple_view_btn.setStyleSheet(_toggle_btn_style)
        self.simple_view_btn.clicked.connect(self._show_simple_view)
        top_bar.addWidget(self.simple_view_btn)

        self.full_view_btn = QPushButton("Expert View")
        self.full_view_btn.setCheckable(True)
        self.full_view_btn.setStyleSheet(_toggle_btn_style)
        self.full_view_btn.clicked.connect(self._show_full_view)
        top_bar.addWidget(self.full_view_btn)

        self._view_group = QButtonGroup(tab)
        self._view_group.setExclusive(True)
        self._view_group.addButton(self.simple_view_btn)
        self._view_group.addButton(self.full_view_btn)

        top_bar.addStretch()

        # Font size buttons (high-contrast circular style)
        self.font_smaller_btn = QPushButton("A")
        self.font_smaller_btn.setToolTip("Decrease font size")
        self.font_smaller_btn.setStyleSheet(
            _circle_btn_style + " QPushButton { font-size: 14px; }"
        )
        self.font_smaller_btn.clicked.connect(self._decrease_font_size)
        top_bar.addWidget(self.font_smaller_btn)

        self.font_larger_btn = QPushButton("A")
        self.font_larger_btn.setToolTip("Increase font size")
        self.font_larger_btn.setStyleSheet(
            _circle_btn_style + " QPushButton { font-size: 20px; }"
        )
        self.font_larger_btn.clicked.connect(self._increase_font_size)
        top_bar.addWidget(self.font_larger_btn)

        # Full View: search button
        self.fv_search_btn = QPushButton("\U0001F50D")
        self.fv_search_btn.setToolTip("Search in code")
        self.fv_search_btn.setStyleSheet(_circle_btn_style)
        self.fv_search_btn.clicked.connect(self._fv_toggle_search)
        top_bar.addWidget(self.fv_search_btn)
        self.fv_search_btn.hide()

        # Full View: add (+) button
        self.fv_add_btn = QPushButton("+")
        self.fv_add_btn.setToolTip("Add package or file")
        self.fv_add_btn.setStyleSheet(_circle_btn_style)
        self.fv_add_btn.clicked.connect(self._fv_add_menu)
        top_bar.addWidget(self.fv_add_btn)
        self.fv_add_btn.hide()

        # Full View: delete (−) button
        _fv_delete_btn_style = (
            "QPushButton { font-size: 20px; font-weight: bold;"
            "  min-width: 36px; max-width: 36px;"
            "  min-height: 36px; max-height: 36px; border-radius: 18px;"
            "  background-color: #FF3B30; color: white;"
            "  border: 2px solid #CC2A22; }"
            "QPushButton:hover { background-color: #CC2A22; }"
            "QPushButton:checked { background-color: #CC2A22;"
            "  border: 2px solid #FFFFFF; }"
        )
        self.fv_delete_btn = QPushButton("\u2212")
        self.fv_delete_btn.setToolTip("Delete mode — click red X to remove items")
        self.fv_delete_btn.setCheckable(True)
        self.fv_delete_btn.setStyleSheet(_fv_delete_btn_style)
        self.fv_delete_btn.clicked.connect(self._fv_toggle_delete_mode)
        top_bar.addWidget(self.fv_delete_btn)
        self.fv_delete_btn.hide()

        self.editor_save_btn = QPushButton("Save")
        self.editor_save_btn.setStyleSheet(
            "QPushButton { background-color: #34C759; color: white; padding: 6px 14px; border-radius: 8px; }"
        )
        self.editor_save_btn.setMinimumWidth(100)
        self.editor_save_btn.clicked.connect(self._save_from_editor)
        top_bar.addWidget(self.editor_save_btn)

        self.editor_deploy_btn = QPushButton("Deploy")
        self.editor_deploy_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; padding: 6px 14px; border-radius: 8px; }"
            "QPushButton:disabled { background-color: #B0B0B0; color: #707070; border-radius: 8px; }"
        )
        self.editor_deploy_btn.setMinimumWidth(100)
        self.editor_deploy_btn.setEnabled(False)
        self.editor_deploy_btn.clicked.connect(self._deploy_from_editor)
        top_bar.addWidget(self.editor_deploy_btn)

        layout.addLayout(top_bar)

        # Stacked widget (Simple View = 0, Full View = 1)
        self.editor_stack = QStackedWidget()

        # --- Simple View (splitter: functions panel | code editor) ---
        simple_view_splitter = QSplitter(Qt.Orientation.Horizontal)

        functions_panel = FunctionsPanel()
        func_scroll = QScrollArea()
        func_scroll.setWidgetResizable(True)
        func_scroll.setWidget(functions_panel)
        func_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        func_scroll.setMinimumWidth(180)
        simple_view_splitter.addWidget(func_scroll)

        self.simple_editor = SimpleViewEditor()
        self.simple_editor.setFont(QFont("Menlo", 13))
        self.simple_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._simple_highlighter = SimpleCodeHighlighter(
            self.simple_editor.document()
        )
        self.simple_editor.textChanged.connect(self._on_simple_code_changed)
        simple_view_splitter.addWidget(self.simple_editor)

        simple_view_splitter.setStretchFactor(0, 0)   # panel: fixed
        simple_view_splitter.setStretchFactor(1, 1)   # editor: stretches
        simple_view_splitter.setSizes([200, 600])

        self.editor_stack.addWidget(simple_view_splitter)

        # --- Full View ---
        full_view_widget = QWidget()
        full_view_outer = QVBoxLayout(full_view_widget)
        full_view_outer.setContentsMargins(0, 0, 0, 0)
        full_view_outer.setSpacing(0)

        # Search bar (hidden by default)
        self._fv_search_bar = QWidget()
        _sb_layout = QHBoxLayout(self._fv_search_bar)
        _sb_layout.setContentsMargins(4, 4, 4, 4)
        self._fv_search_input = QLineEdit()
        self._fv_search_input.setPlaceholderText("Search...")
        self._fv_search_input.textChanged.connect(self._fv_perform_search)
        _sb_layout.addWidget(self._fv_search_input)
        _sb_close = QPushButton("\u2715")
        _sb_close.setFixedSize(28, 28)
        _sb_close.setStyleSheet(
            "QPushButton { border: none; font-size: 16px; }"
            "QPushButton:hover { color: red; }"
        )
        _sb_close.clicked.connect(self._fv_toggle_search)
        _sb_layout.addWidget(_sb_close)
        self._fv_search_bar.hide()
        full_view_outer.addWidget(self._fv_search_bar)

        # Horizontal content: file tree + editor
        _fv_content = QWidget()
        full_layout = QHBoxLayout(_fv_content)
        full_layout.setContentsMargins(0, 0, 0, 0)
        full_view_outer.addWidget(_fv_content)

        # Left container: header row + file tree (fixed 220px)
        fv_left_container = QWidget()
        fv_left_container.setFixedWidth(220)
        fv_left_layout = QVBoxLayout(fv_left_container)
        fv_left_layout.setContentsMargins(0, 0, 0, 0)
        fv_left_layout.setSpacing(2)

        fv_tree_lbl = QLabel("FILES")
        fv_tree_lbl.setFont(QFont("Menlo", 11, QFont.Weight.Bold))
        fv_tree_lbl.setContentsMargins(4, 2, 4, 2)
        fv_left_layout.addWidget(fv_tree_lbl)

        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderHidden(True)
        self.file_tree.setFont(QFont("Menlo", 11))
        self.file_tree.itemClicked.connect(self._on_file_tree_clicked)
        self.file_tree.itemDoubleClicked.connect(self._fv_tree_double_clicked)
        self.file_tree.itemChanged.connect(self._fv_tree_item_changed)
        fv_left_layout.addWidget(self.file_tree)

        full_layout.addWidget(fv_left_container)

        self.full_editor = LineNumberEditor()
        self.full_editor.setFont(QFont("Menlo", 12))
        self.full_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._full_view_highlighter = FullViewHighlighter(
            self.full_editor.document()
        )
        full_layout.addWidget(self.full_editor)

        self.editor_stack.addWidget(full_view_widget)

        layout.addWidget(self.editor_stack)

        self.tabs.addTab(tab, "Code Editor")

        # Populate views
        self._load_file_tree()
        self._load_simple_view_from_movement_py()

        # Auto-save timer (every 5 seconds)
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start(5000)

    # ------------------------------------------------------------------ #
    #  Tab 4: RoboApps                                                     #
    # ------------------------------------------------------------------ #

    def _build_roboapps_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # --- Top bar ---
        top_bar = QHBoxLayout()
        top_bar.addStretch()

        roboapps_label = QLabel("RoboApps")
        roboapps_label.setFont(QFont("Menlo", 13, QFont.Weight.Bold))
        roboapps_label.setStyleSheet("color: #34C759;")
        roboapps_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_bar.addWidget(roboapps_label)

        top_bar.addStretch()
        layout.addLayout(top_bar)

        # --- Main area (white background) ---
        main_area = QWidget()
        main_area.setStyleSheet("background-color: white;")
        main_area_layout = QVBoxLayout(main_area)
        main_area_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        main_area_layout.setContentsMargins(24, 24, 24, 24)

        # Icons row — horizontal, left-aligned, icons added here at runtime
        icons_container = QWidget()
        self._roboapps_icons_layout = QHBoxLayout(icons_container)
        self._roboapps_icons_layout.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self._roboapps_icons_layout.setSpacing(16)
        self._roboapps_icons_layout.setContentsMargins(0, 0, 0, 0)

        # RoboSim app icon (iPhone-style)
        robosim_btn = QPushButton("RoboSim")
        robosim_btn.setFixedSize(120, 120)
        robosim_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #007AFF;"
            "  color: white;"
            "  font-size: 16px;"
            "  font-weight: bold;"
            "  border-radius: 27px;"
            "  border: none;"
            "}"
            "QPushButton:hover {"
            "  background-color: #005ECB;"
            "}"
            "QPushButton:pressed {"
            "  background-color: #004AAD;"
            "}"
        )
        robosim_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        robosim_btn.setToolTip("Launch RoboSim5")
        robosim_btn.clicked.connect(self._launch_robosim)
        self._roboapps_icons_layout.addWidget(robosim_btn)
        self._roboapps_icons_layout.addStretch()

        main_area_layout.addWidget(icons_container)
        main_area_layout.addStretch()
        layout.addWidget(main_area)

        self.tabs.addTab(tab, "RoboApps")

    def _launch_robosim(self):
        """Launch RoboSim5 as a subprocess: python RobotSim5.py"""
        if self._robosim_proc is not None and self._robosim_proc.poll() is None:
            self._log(f"RoboSim is already running (PID {self._robosim_proc.pid}).")
            return

        robosim_dir = os.path.join(_PKG_DIR, "roboapps", "RobotSim5")
        script = "RobotSim5.py"

        if not os.path.isfile(os.path.join(robosim_dir, script)):
            self._log("ERROR: RobotSim5.py not found at: " + robosim_dir)
            return

        self._log("Launching RoboSim5...")
        try:
            self._robosim_proc = subprocess.Popen(
                [sys.executable, script],
                cwd=robosim_dir,
                start_new_session=True,
            )
            self._log(f"  RoboSim5 started (PID {self._robosim_proc.pid}).")
        except Exception as e:
            self._log(f"ERROR launching RoboSim5: {e}")

    # --- Support dialog ---

    def _show_support_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Contact Support")
        dialog.setMinimumWidth(400)
        form_layout = QFormLayout(dialog)

        subject_input = QLineEdit()
        first_name_input = QLineEdit()
        last_name_input = QLineEdit()
        email_input = QLineEdit()
        description_input = QTextEdit()
        description_input.setMinimumHeight(100)

        form_layout.addRow("Subject:", subject_input)
        form_layout.addRow("Your First Name:", first_name_input)
        form_layout.addRow("Your Last Name:", last_name_input)
        form_layout.addRow("Your Email:", email_input)
        form_layout.addRow("Issue Description:", description_input)

        send_btn = QPushButton("Send")
        send_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; "
            "padding: 8px 24px; border-radius: 8px; font-weight: bold; }"
        )
        form_layout.addRow("", send_btn)

        def _on_send():
            subj = subject_input.text().strip()
            fname = first_name_input.text().strip()
            lname = last_name_input.text().strip()
            email = email_input.text().strip()
            desc = description_input.toPlainText().strip()

            if not all([subj, fname, lname, email, desc]):
                QMessageBox.warning(dialog, "Missing Fields",
                                    "Please fill in all fields before sending.")
                return

            import urllib.parse
            body = f"From: {fname} {lname} <{email}>\n\n{desc}"
            mailto_url = (
                f"mailto:hi@mirobot.ai"
                f"?subject={urllib.parse.quote(subj)}"
                f"&body={urllib.parse.quote(body)}"
            )
            try:
                subprocess.Popen(["open", mailto_url])
                QMessageBox.information(dialog, "Email Client Opened",
                                        "Your default email client has been opened "
                                        "with the support request pre-filled.")
                dialog.accept()
            except Exception as e:
                QMessageBox.critical(dialog, "Error",
                                     f"Could not open email client: {e}")

        send_btn.clicked.connect(_on_send)
        dialog.exec()

    # --- Undo / Redo / Autosave ---

    def _undo(self):
        if self.editor_stack.currentIndex() == 0:
            self.simple_editor.undo()
        else:
            self.full_editor.undo()

    def _redo(self):
        if self.editor_stack.currentIndex() == 0:
            self.simple_editor.redo()
        else:
            self.full_editor.redo()

    def _autosave(self):
        """Auto-save: persist editor content to disk every 5 seconds."""
        if self.editor_stack.currentIndex() == 0:
            # Simple View — write params + logic to movement.py
            self._write_params_to_movement_py()
            self._write_simple_logic_to_movement_py()
        else:
            self._save_full_view_file()

    def _change_font_size(self, delta):
        """Adjust the font size of the active editor by *delta* points."""
        if self.editor_stack.currentIndex() == 0:
            editor = self.simple_editor
        else:
            editor = self.full_editor
        font = editor.font()
        new_size = max(8, font.pointSize() + delta)
        font.setPointSize(new_size)
        editor.setFont(font)

    def _increase_font_size(self):
        self._change_font_size(1)

    def _decrease_font_size(self):
        self._change_font_size(-1)

    # --- Simple View helpers ---

    def _generate_simple_code(self):
        """Generate Codebot Air default code from current parameter values."""
        fwd = self.forward_speed.value()
        bwd = self.backward_speed.value()
        turn = self.turn_speed.value()
        obs = self.obstacle_distance.value()
        cw = self.turn_cw.value()
        acw = self.turn_acw.value()
        colour = self.colour_detection.currentText()

        return (
            f'from codebotair import Robot\n'
            f'\n'
            f'class Movement(Robot):\n'
            f'    def __init__(self):\n'
            f'        super().__init__()\n'
            f'        # === Editable Parameters ===\n'
            f'        self.forward_speed = {fwd:.2f}       # m/s  \u2190 edit\n'
            f'        self.backward_speed = {bwd:.2f}      # m/s  \u2190 edit\n'
            f'        self.turn_speed = {turn:.2f}          # rad/s  \u2190 edit\n'
            f'        self.obstacle_distance = {obs:.2f}   # metres  \u2190 edit\n'
            f'        self.turn_cw_deg = {cw:.1f}         # degrees CW  \u2190 edit\n'
            f'        self.turn_acw_deg = {acw:.1f}        # degrees ACW  \u2190 edit\n'
            f'        self.colour_detection = "{colour}"   # Red|Blue|Yellow|Green  \u2190 edit\n'
            f'\n'
            f'    # vvv Drag and drop functions below vvv\n'
            f'\n'
            f'    def control_loop(self):\n'
            f'        # === Movement Logic ===\n'
            f'        if self.obstacle_in_front():\n'
            f'            self.stop()                       # stop movement\n'
            f'            self.turn_cw(self.turn_cw_deg)    # turn clockwise  \u2190 edit\n'
            f'        else:\n'
            f'            self.move(self.forward_speed)     # drive forward  \u2190 edit\n'
        )

    def _on_simple_code_changed(self):
        """Parse Simple View text and update spinboxes in Robot Control tab."""
        if self._syncing:
            return
        self._syncing = True
        try:
            text = self.simple_editor.toPlainText()
            m = re.search(r'self\.forward_speed\s*=\s*([\d.]+)', text)
            if m:
                self.forward_speed.setValue(float(m.group(1)))
            m = re.search(r'self\.backward_speed\s*=\s*([\d.]+)', text)
            if m:
                self.backward_speed.setValue(float(m.group(1)))
            m = re.search(r'self\.turn_speed\s*=\s*([\d.]+)', text)
            if m:
                self.turn_speed.setValue(float(m.group(1)))
            m = re.search(r'self\.obstacle_distance\s*=\s*([\d.]+)', text)
            if m:
                self.obstacle_distance.setValue(float(m.group(1)))
            m = re.search(r'self\.turn_cw_deg\s*=\s*([\d.]+)', text)
            if m:
                self.turn_cw.setValue(float(m.group(1)))
            m = re.search(r'self\.turn_acw_deg\s*=\s*([\d.]+)', text)
            if m:
                self.turn_acw.setValue(float(m.group(1)))
            m = re.search(r'self\.colour_detection\s*=\s*"([^"]+)"', text)
            if m:
                colour = m.group(1)
                if colour in ["Red", "Blue", "Yellow", "Green"]:
                    self.colour_detection.setCurrentText(colour)
        finally:
            self._syncing = False

    def _sync_simple_view_from_spinboxes(self):
        """Update Simple View parameter values in-place (preserves user logic)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            code = self.simple_editor.toPlainText()
            # First launch — editor is empty, generate fresh code
            if not code.strip():
                self.simple_editor.setPlainText(self._generate_simple_code())
                return

            # In-place regex replacement of parameter values only.
            # Use count=1 to only replace the first occurrence (in __init__),
            # leaving any duplicates in the logic section untouched.
            replacements = [
                (r'(self\.forward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.forward_speed.value():.2f}'),
                (r'(self\.backward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.backward_speed.value():.2f}'),
                (r'(self\.turn_speed\s*=\s*)[\d.]+', rf'\g<1>{self.turn_speed.value():.2f}'),
                (r'(self\.obstacle_distance\s*=\s*)[\d.]+', rf'\g<1>{self.obstacle_distance.value():.2f}'),
                (r'(self\.turn_cw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_cw.value():.1f}'),
                (r'(self\.turn_acw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_acw.value():.1f}'),
                (r'(self\.colour_detection\s*=\s*")[^"]*"',
                 rf'\g<1>{self.colour_detection.currentText()}"'),
            ]
            new_code = code
            for pattern, repl in replacements:
                new_code = re.sub(pattern, repl, new_code, count=1)

            if new_code != code:
                # Save and restore cursor position
                cursor = self.simple_editor.textCursor()
                pos = cursor.position()
                self.simple_editor.setPlainText(new_code)
                cursor = self.simple_editor.textCursor()
                cursor.setPosition(min(pos, len(new_code)))
                self.simple_editor.setTextCursor(cursor)
        finally:
            self._syncing = False

    def _sync_full_view_from_spinboxes(self):
        """Apply current spinbox parameter values to the Full View editor."""
        code = self.full_editor.toPlainText()
        if not code.strip():
            return
        replacements = [
            (r'(self\.forward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.forward_speed.value():.2f}'),
            (r'(self\.backward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.backward_speed.value():.2f}'),
            (r'(self\.turn_speed\s*=\s*)[\d.]+', rf'\g<1>{self.turn_speed.value():.2f}'),
            (r'(self\.obstacle_distance\s*=\s*)[\d.]+', rf'\g<1>{self.obstacle_distance.value():.2f}'),
            (r'(self\.turn_cw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_cw.value():.1f}'),
            (r'(self\.turn_acw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_acw.value():.1f}'),
            (r'(self\.colour_detection\s*=\s*")[^"]*"',
             rf'\g<1>{self.colour_detection.currentText()}"'),
        ]
        new_code = code
        for pattern, repl in replacements:
            new_code = re.sub(pattern, repl, new_code, count=1)
        if new_code != code:
            cursor = self.full_editor.textCursor()
            pos = cursor.position()
            self.full_editor.setPlainText(new_code)
            cursor = self.full_editor.textCursor()
            cursor.setPosition(min(pos, len(new_code)))
            self.full_editor.setTextCursor(cursor)

    # --- Simple View ↔ movement.py sync engine ---

    def _extract_simple_view_logic(self):
        """Extract the control_loop body text from the Simple View editor."""
        text = self.simple_editor.toPlainText()
        lines = text.split('\n')
        logic_start = None
        for i, line in enumerate(lines):
            if '# === Movement Logic ===' in line:
                logic_start = i + 1
                break
        if logic_start is None:
            return None
        logic_lines = lines[logic_start:]
        # Strip trailing empty lines
        while logic_lines and not logic_lines[-1].strip():
            logic_lines.pop()
        if not logic_lines:
            return None
        return '\n'.join(logic_lines)

    def _write_simple_logic_to_movement_py(self):
        """Replace the control_loop user section in movement.py with Simple View logic."""
        logic = self._extract_simple_view_logic()
        if logic is None:
            return
        if not os.path.isfile(MOVEMENT_PY):
            return
        with open(MOVEMENT_PY, 'r') as f:
            code = f.read()

        marker_start = '        # user control_loop logic below\n'
        marker_end = '        # end user control_loop logic'

        start_idx = code.find(marker_start)
        end_idx = code.find(marker_end)
        if start_idx == -1 or end_idx == -1:
            return

        new_code = code[:start_idx + len(marker_start)] + logic + '\n' + code[end_idx:]

        if new_code != code:
            with open(MOVEMENT_PY, 'w') as f:
                f.write(new_code)

    def _load_simple_view_from_movement_py(self):
        """Read movement.py markers and rebuild Simple View with current params + saved logic."""
        if not os.path.isfile(MOVEMENT_PY):
            # No movement.py — populate with generated default if editor is empty
            if not self.simple_editor.toPlainText().strip():
                self._syncing = True
                try:
                    self.simple_editor.setPlainText(self._generate_simple_code())
                finally:
                    self._syncing = False
            return
        with open(MOVEMENT_PY, 'r') as f:
            code = f.read()

        # Extract logic between markers
        m = re.search(
            r'        # user control_loop logic below\n(.*?)        # end user control_loop logic',
            code, re.DOTALL,
        )
        if not m:
            # No markers — fall back to generated default
            self._syncing = True
            try:
                self.simple_editor.setPlainText(self._generate_simple_code())
            finally:
                self._syncing = False
            return

        saved_logic = m.group(1).rstrip('\n')

        # Build Simple View with current spinbox params and saved logic
        base_code = self._generate_simple_code()
        lines = base_code.split('\n')
        logic_start = None
        for i, line in enumerate(lines):
            if '# === Movement Logic ===' in line:
                logic_start = i + 1
                break
        if logic_start is not None:
            new_lines = lines[:logic_start]
            new_lines.append(saved_logic)
            base_code = '\n'.join(new_lines) + '\n'

        self._syncing = True
        try:
            self.simple_editor.setPlainText(base_code)
        finally:
            self._syncing = False

    def _write_params_to_movement_py(self):
        """Write current spinbox parameter values into movement.py on disk."""
        if not os.path.isfile(MOVEMENT_PY):
            return
        with open(MOVEMENT_PY, 'r') as f:
            code = f.read()

        replacements = [
            (r'(self\.forward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.forward_speed.value():.2f}'),
            (r'(self\.backward_speed\s*=\s*)[\d.]+', rf'\g<1>{self.backward_speed.value():.2f}'),
            (r'(self\.turn_speed\s*=\s*)[\d.]+', rf'\g<1>{self.turn_speed.value():.2f}'),
            (r'(self\.obstacle_distance\s*=\s*)[\d.]+', rf'\g<1>{self.obstacle_distance.value():.2f}'),
            (r'(self\.turn_cw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_cw.value():.1f}'),
            (r'(self\.turn_acw_deg\s*=\s*)[\d.]+', rf'\g<1>{self.turn_acw.value():.1f}'),
            (r'(self\.colour_detection\s*=\s*")[^"]*"',
             rf'\g<1>{self.colour_detection.currentText()}"'),
        ]

        for pattern, repl in replacements:
            code = re.sub(pattern, repl, code, count=1)

        with open(MOVEMENT_PY, 'w') as f:
            f.write(code)

    def _sync_simple_view_to_full_view(self):
        """Persist Simple View params + logic to movement.py and refresh Full View."""
        self._write_params_to_movement_py()
        self._write_simple_logic_to_movement_py()
        # Reload Full View editor if movement.py is the currently open file
        if self._full_view_current_file == "movement_pkg/movement.py":
            with open(MOVEMENT_PY, 'r') as f:
                self.full_editor.setPlainText(f.read())

    def _show_simple_view(self):
        # If switching from Full View, save the file first
        if self.editor_stack.currentIndex() == 1:
            self._save_full_view_file()
        self.editor_stack.setCurrentIndex(0)
        self.simple_view_btn.setChecked(True)
        self.full_view_btn.setChecked(False)
        self.fv_add_btn.hide()
        self.fv_delete_btn.hide()
        self.fv_search_btn.hide()
        self._fv_search_bar.hide()
        self._fv_search_input.clear()
        # Load persisted logic from movement.py
        self._load_simple_view_from_movement_py()

    def _show_full_view(self):
        # If switching from Simple View, sync changes to movement.py and reload
        if self.editor_stack.currentIndex() == 0:
            self._sync_simple_view_to_full_view()
        self.editor_stack.setCurrentIndex(1)
        self.full_view_btn.setChecked(True)
        self.simple_view_btn.setChecked(False)
        self.fv_add_btn.show()
        self.fv_delete_btn.show()
        self.fv_search_btn.show()
        # Sync spinbox parameter values into Full View if movement.py is open
        if self._full_view_current_file == "movement_pkg/movement.py":
            self._sync_full_view_from_spinboxes()

    # --- Full View search ---

    def _fv_toggle_search(self):
        """Toggle search bar visibility in Full View."""
        visible = self._fv_search_bar.isVisible()
        self._fv_search_bar.setVisible(not visible)
        if visible:
            self._fv_search_input.clear()
            self.full_editor.setExtraSelections([])
        else:
            self._fv_search_input.setFocus()

    def _fv_perform_search(self):
        """Highlight all occurrences of the search term in the Full View editor."""
        term = self._fv_search_input.text()
        if not term:
            self.full_editor.setExtraSelections([])
            return

        selections = []
        doc = self.full_editor.document()
        highlight_fmt = QTextCharFormat()
        highlight_fmt.setBackground(QColor("#FFE082"))

        cursor = QTextCursor(doc)
        while True:
            cursor = doc.find(term, cursor)
            if cursor.isNull():
                break
            sel = QTextEdit.ExtraSelection()
            sel.cursor = cursor
            sel.format = highlight_fmt
            selections.append(sel)

        self.full_editor.setExtraSelections(selections)

    # --- Full View helpers ---

    # Directories to hide from the Full View file tree
    _FV_HIDDEN_DIRS = {"__pycache__", ".git", "resource", "msg", "srv",
                       ".egg-info"}

    def _load_file_tree(self):
        self._blocking_item_changed = True
        self.file_tree.clear()

        delete_on = self._fv_edit_mode
        if delete_on:
            self.file_tree.setColumnCount(2)
            self.file_tree.header().setStretchLastSection(False)
            self.file_tree.header().setSectionResizeMode(
                0, self.file_tree.header().ResizeMode.Stretch)
            self.file_tree.header().setSectionResizeMode(
                1, self.file_tree.header().ResizeMode.Fixed)
            self.file_tree.header().resizeSection(1, 30)
        else:
            self.file_tree.setColumnCount(1)

        folders = {}   # dir_name -> QTreeWidgetItem
        seen_files = set()
        first_file_item = None

        _protected_files = _PROTECTED_FV_FILES
        _protected_folders = _PROTECTED_FV_FOLDERS

        def _add_delete_col(tree_item, protected=False):
            if delete_on and not protected:
                tree_item.setText(1, "\u2716")
                tree_item.setForeground(1, QColor("#FF3B30"))

        def _ensure_folder(dir_name):
            """Return (or create) the QTreeWidgetItem for *dir_name*."""
            if dir_name in folders:
                return folders[dir_name]
            folder_item = QTreeWidgetItem(self.file_tree)
            folder_item.setText(0, f"\U0001F4C1 {dir_name}")
            folder_item.setFont(0, QFont("Menlo", 11, QFont.Weight.Bold))
            folder_item.setForeground(0, QColor("#34C759"))
            folder_item.setExpanded(True)
            _add_delete_col(folder_item, dir_name in _protected_folders)
            folders[dir_name] = folder_item
            return folder_item

        def _add_file(parent, file_name, rel_path):
            nonlocal first_file_item
            if rel_path in seen_files:
                return
            seen_files.add(rel_path)
            fi = QTreeWidgetItem(parent)
            fi.setText(0, file_name)
            fi.setData(0, Qt.ItemDataRole.UserRole, rel_path)
            fi.setForeground(0, QColor("#007AFF"))
            _add_delete_col(fi, rel_path in _protected_files)
            if first_file_item is None:
                first_file_item = fi

        # 1) Static files from _FULL_VIEW_FILES
        for rel_path in _FULL_VIEW_FILES:
            full_path = os.path.join(_PKG_DIR, rel_path)
            if not os.path.isfile(full_path):
                continue
            dir_name = os.path.dirname(rel_path)
            file_name = os.path.basename(rel_path)
            parent = _ensure_folder(dir_name) if dir_name else self.file_tree.invisibleRootItem()
            _add_file(parent, file_name, rel_path)

        # 2) Scan every subdirectory on disk (skip hidden / dunder)
        for entry in sorted(os.listdir(_PKG_DIR)):
            entry_path = os.path.join(_PKG_DIR, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.startswith(".") or entry.startswith("__"):
                continue
            if any(entry.endswith(h) or entry == h
                   for h in self._FV_HIDDEN_DIRS):
                continue
            parent = _ensure_folder(entry)
            for fname in sorted(os.listdir(entry_path)):
                fpath = os.path.join(entry_path, fname)
                if os.path.isfile(fpath):
                    _add_file(parent, fname, os.path.join(entry, fname))

        # 3) Root-level files not in _FULL_VIEW_FILES
        for entry in sorted(os.listdir(_PKG_DIR)):
            entry_path = os.path.join(_PKG_DIR, entry)
            if os.path.isfile(entry_path) and not entry.startswith("."):
                _add_file(self.file_tree.invisibleRootItem(), entry, entry)

        if first_file_item:
            self.file_tree.setCurrentItem(first_file_item)
            self._on_file_tree_clicked(first_file_item, 0)

        self._blocking_item_changed = False

    def _on_file_tree_clicked(self, item, column):
        # Edit-mode delete via red minus column
        if column == 1 and self._fv_edit_mode:
            rel_path = item.data(0, Qt.ItemDataRole.UserRole)
            is_folder = rel_path is None
            target = item.text(0).strip() if is_folder else rel_path
            if not target:
                return
            reply = QMessageBox.warning(
                self, "Delete Item",
                "Are you sure you want to delete this item? "
                "You can not undo this action.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                return
            if is_folder:
                # Extract folder name (remove icon prefix)
                folder_display = item.text(0).strip()
                for prefix in ("\U0001F4C1 ", "\U0001F4C1"):
                    if folder_display.startswith(prefix):
                        folder_display = folder_display[len(prefix):]
                        break
                folder_path = os.path.join(_PKG_DIR, folder_display)
                if os.path.isdir(folder_path):
                    shutil.rmtree(folder_path)
            else:
                full_path = os.path.join(_PKG_DIR, rel_path)
                if os.path.isfile(full_path):
                    os.remove(full_path)
                if self._full_view_current_file == rel_path:
                    self._full_view_current_file = None
                    self.full_editor.clear()
            self._load_file_tree()
            return

        rel_path = item.data(0, Qt.ItemDataRole.UserRole)
        if not rel_path:
            return  # Clicked a folder — ignore
        # Save previously edited file
        self._save_full_view_file()
        # Load new file
        full_path = os.path.join(_PKG_DIR, rel_path)
        self._full_view_current_file = rel_path
        try:
            with open(full_path, "r") as f:
                self.full_editor.setPlainText(f.read())
        except Exception as e:
            self.full_editor.setPlainText(f"# Error loading file: {e}")

    def _select_file_tree_item(self, rel_path):
        """Select a file in the Full View tree by its relative path."""
        it = QTreeWidgetItemIterator(self.file_tree)
        while it.value():
            node = it.value()
            if node.data(0, Qt.ItemDataRole.UserRole) == rel_path:
                self.file_tree.setCurrentItem(node)
                self._on_file_tree_clicked(node, 0)
                return
            it += 1

    def _save_full_view_file(self):
        """Save the currently open Full View file to disk."""
        if not self._full_view_current_file:
            return
        full_path = os.path.join(_PKG_DIR, self._full_view_current_file)
        try:
            with open(full_path, "w") as f:
                f.write(self.full_editor.toPlainText())
        except Exception:
            pass

    def _deploy_from_editor(self):
        """Save & Deploy triggered from Code Editor tab."""
        if self.editor_stack.currentIndex() == 0:
            # Simple View — write params + logic to movement.py before deploy
            self._write_params_to_movement_py()
            self._write_simple_logic_to_movement_py()
        else:
            # Full View — save current file to disk first
            self._save_full_view_file()
            # If movement.py was edited, reload params from it
            if (self._full_view_current_file
                    and self._full_view_current_file.endswith("movement.py")):
                self._load_params()
        self.deploy()

    # --- Full View delete mode ---

    def _fv_toggle_delete_mode(self):
        self._fv_edit_mode = not self._fv_edit_mode
        self.fv_delete_btn.setChecked(self._fv_edit_mode)
        self._load_file_tree()

    def _fv_add_menu(self):
        """+ button dialog: Add Package / Add File / Cancel."""
        items = ["Add Package", "Add File", "Cancel"]
        choice, ok = QInputDialog.getItem(
            self, "Add to Full View", "What would you like to add?",
            items, 0, False)
        if not ok or choice == "Cancel":
            return
        if choice == "Add Package":
            name, ok = QInputDialog.getText(
                self, "New Package", "Package folder name:")
            if ok and name.strip():
                pkg_dir = os.path.join(_PKG_DIR, name.strip())
                os.makedirs(pkg_dir, exist_ok=True)
                self._load_file_tree()
        elif choice == "Add File":
            disk_folders = set(
                d for d in os.listdir(_PKG_DIR)
                if os.path.isdir(os.path.join(_PKG_DIR, d))
                and not d.startswith(".") and not d.startswith("__")
                and not any(d.endswith(h) or d == h
                            for h in self._FV_HIDDEN_DIRS)
            )
            pkg_folders = sorted(disk_folders)
            if not pkg_folders:
                QMessageBox.information(
                    self, "No Package",
                    "Create a package folder first.")
                return
            folder, ok = QInputDialog.getItem(
                self, "Select Package",
                "Add the file to which package folder?",
                pkg_folders, 0, False)
            if not ok:
                return
            name, ok2 = QInputDialog.getText(
                self, "New File", "File name (e.g. my_sketch.ino):")
            if ok2 and name.strip():
                folder_path = os.path.join(_PKG_DIR, folder)
                os.makedirs(folder_path, exist_ok=True)
                fpath = os.path.join(folder_path, name.strip())
                if not os.path.exists(fpath):
                    with open(fpath, "w") as f:
                        f.write("")
                self._load_file_tree()

    def _fv_tree_item_changed(self, item, column):
        """No-op — Full View tree is not inline-editable."""
        return

    def _fv_tree_double_clicked(self, item, column):
        """Double-click to rename a file or folder in the Full View tree."""
        rel_path = item.data(0, Qt.ItemDataRole.UserRole)
        is_folder = rel_path is None
        if is_folder:
            type_label = "folder"
            display = item.text(0).strip()
            for prefix in ("\U0001F4C1 ", "\U0001F4C1"):
                if display.startswith(prefix):
                    display = display[len(prefix):]
                    break
            old_name = display
        else:
            type_label = "file"
            old_name = os.path.basename(rel_path)
        reply = QMessageBox.question(
            self, "Rename",
            f"Would you like to change the name of this {type_label}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        new_name, ok = QInputDialog.getText(
            self, f"Rename {type_label}", "New name:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if is_folder:
            old_path = os.path.join(_PKG_DIR, old_name)
            new_path = os.path.join(_PKG_DIR, new_name)
            if os.path.isdir(old_path):
                try:
                    os.rename(old_path, new_path)
                except Exception as e:
                    QMessageBox.warning(self, "Rename failed", str(e))
                    return
            if (self._full_view_current_file
                    and self._full_view_current_file.startswith(old_name + "/")):
                self._full_view_current_file = (
                    new_name + self._full_view_current_file[len(old_name):])
        else:
            old_path = os.path.join(_PKG_DIR, rel_path)
            new_rel = os.path.join(os.path.dirname(rel_path), new_name)
            new_path = os.path.join(_PKG_DIR, new_rel)
            try:
                os.rename(old_path, new_path)
            except Exception as e:
                QMessageBox.warning(self, "Rename failed", str(e))
                return
            if self._full_view_current_file == rel_path:
                self._full_view_current_file = new_rel
        self._load_file_tree()

    def save(self):
        """Save current parameter values to the Simple View editor."""
        self._write_params_to_movement_py()
        self._write_simple_logic_to_movement_py()
        self._log("Saved to project folder.")
        self._flash_save_buttons()

    def _save_from_editor(self):
        """Save triggered from Code Editor tab."""
        if self.editor_stack.currentIndex() == 0:
            self._write_params_to_movement_py()
            self._write_simple_logic_to_movement_py()
        else:
            self._save_full_view_file()
        self._log("Saved to project folder.")
        self._flash_save_buttons()

    def deploy(self):
        """Deploy: compile and upload the sketch to Codebot Air."""
        self._run_code()

    def _load_params(self):
        """No-op stub — Codebot Air has no ROS movement params to load."""
        pass

    def _populate_canvas_file_tree(self):
        """No-op stub — Codebot Air has no Node Canvas."""
        pass

    def _run_worker(self, worker):
        """No-op stub — Codebot Air has no SSH workers."""
        pass

    def _flash_save_buttons(self):
        """Briefly flash the Save button green to confirm save."""
        if hasattr(self, 'editor_save_btn'):
            self.editor_save_btn.setText("Saved!")
            QTimer.singleShot(1000, lambda: self.editor_save_btn.setText("Save"))

    def _flash_deploy_buttons(self):
        """Briefly flash the Deploy button to confirm deploy."""
        if hasattr(self, 'editor_deploy_btn'):
            self.editor_deploy_btn.setText("Uploaded!")
            QTimer.singleShot(1500, lambda: self.editor_deploy_btn.setText("Deploy"))

    def check_launch_logs(self):
        """Show recent git activity in the log."""
        self._log("--- Git Activity ---")
        r = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            for line in r.stdout.strip().splitlines():
                self._log(f"  {line}")
        else:
            self._log("  No commits yet" + (
                f": {r.stderr.strip()}" if r.stderr.strip() else ""))
        r = subprocess.run(
            ["git", "status", "--short"],
            cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode == 0:
            status_out = r.stdout.strip()
            self._log(f"  git status: "
                      f"{status_out if status_out else 'clean (nothing to commit)'}")
        else:
            self._log(f"  git status error: {r.stderr.strip()}")

    def _find_conda_env(self):
        """Locate the conda 'ros_env' environment.

        Returns (conda_prefix, error_message). On success error_message is None.
        """
        conda_exe = shutil.which("conda")
        if conda_exe is None:
            candidates = [
                os.path.expanduser("~/miniforge3/condabin/conda"),
                os.path.expanduser("~/miniforge3/bin/conda"),
                os.path.expanduser("~/miniconda3/condabin/conda"),
                os.path.expanduser("~/miniconda3/bin/conda"),
                os.path.expanduser("~/anaconda3/condabin/conda"),
                os.path.expanduser("~/anaconda3/bin/conda"),
                "/opt/homebrew/Caskroom/miniforge/base/condabin/conda",
            ]
            for c in candidates:
                if os.path.isfile(c):
                    conda_exe = c
                    break
        if conda_exe is None:
            return None, (
                "Conda not found.\n\n"
                "Please install Miniforge first, then run:\n"
                "  bash setup_robostack.sh\n\n"
                "(from the project directory)"
            )
        try:
            result = subprocess.run(
                [conda_exe, "env", "list", "--json"],
                capture_output=True, text=True, timeout=15,
            )
            envs = json.loads(result.stdout).get("envs", [])
            for env_path in envs:
                if env_path.endswith("/ros_env"):
                    return env_path, None
        except Exception as e:
            return None, f"Error querying conda environments: {e}"
        return None, (
            "Conda environment 'ros_env' not found.\n\n"
            "Run this in Terminal:\n"
            "  bash setup_robostack.sh\n\n"
            "(from the project directory)"
        )

    # ------------------------------------------------------------------ #
    #  Shared logic                                                        #
    # ------------------------------------------------------------------ #

    def _log(self, msg):
        self.log_area.append(f"> {msg}")
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum())

    # ------------------------------------------------------------------
    # USB connection
    # ------------------------------------------------------------------

    @staticmethod
    def _is_ch340(port_info):
        """Return True if the port belongs to a CH340 USB-serial chip (Codebot Air)."""
        return (
            'CH340' in (port_info.description or '').upper()
            or 'CH340' in (port_info.manufacturer or '').upper()
            or port_info.vid == 0x1A86
        )

    def _scan_usb_ports(self):
        """Scan for CH340 USB serial devices and update the port combo."""
        if not _SERIAL_AVAILABLE:
            return
        all_port_infos = serial.tools.list_ports.comports()
        # Only show CH340 ports (Codebot Air's USB chip) to avoid clutter
        ch340_infos = [p for p in all_port_infos if self._is_ch340(p)]
        ports = [p.device for p in ch340_infos]

        first_scan = self._known_ports is None
        # Detect newly plugged-in ports
        new_ports = [] if first_scan else [p for p in ports if p not in self._known_ports]
        self._known_ports = set(ports)

        current = self._port_combo.currentText()
        self._port_combo.blockSignals(True)
        self._port_combo.clear()
        self._port_combo.addItems(ports)
        if current in ports:
            self._port_combo.setCurrentText(current)
        self._port_combo.blockSignals(False)
        has_ports = len(ports) > 0
        # Only enable Connect if not already connected
        if self._serial_conn is None or not self._serial_conn.is_open:
            self.connect_btn.setEnabled(has_ports)

        # Auto-disconnect when the connected port disappears
        if (self._serial_conn and self._serial_conn.is_open
                and self._usb_port and self._usb_port not in ports):
            try:
                self._serial_conn.close()
            except Exception:
                pass
            self._serial_conn = None
            self._usb_port = None
            self.connect_btn.setText("Connect")
            self.conn_status.setText("Not connected")
            self.conn_status.setStyleSheet("color: #FF3B30; font-weight: bold; padding-left: 8px;")
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.deploy_btn.setEnabled(False)
            self.editor_deploy_btn.setEnabled(False)
            self._log("USB: Codebot Air disconnected.")

        # Auto-connect when a CH340 port appears (including on first scan if already plugged in)
        auto_candidates = ports if first_scan else new_ports
        if auto_candidates and (self._serial_conn is None or not self._serial_conn.is_open):
            self._port_combo.setCurrentText(auto_candidates[0])
            self._do_usb_connect()

    def _do_usb_connect(self):
        """Connect to or disconnect from the selected USB port."""
        if self._serial_conn and self._serial_conn.is_open:
            # Disconnect
            try:
                self._serial_conn.close()
            except Exception:
                pass
            self._serial_conn = None
            self._usb_port = None
            self.connect_btn.setText("Connect")
            self.conn_status.setText("Not connected")
            self.conn_status.setStyleSheet("color: #FF3B30; font-weight: bold; padding-left: 8px;")
            self.run_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.deploy_btn.setEnabled(False)
            self.editor_deploy_btn.setEnabled(False)
            self._log("USB: Disconnected.")
            return

        port = self._port_combo.currentText()
        if not port:
            QMessageBox.warning(self, "No Port", "No USB port selected.")
            return
        if not _SERIAL_AVAILABLE:
            QMessageBox.warning(self, "pyserial Not Installed",
                                "Install pyserial:  pip install pyserial")
            return
        try:
            self._serial_conn = serial.Serial(port, CODEBOT_BAUD, timeout=2)
            self._usb_port = port
            self.connect_btn.setText("Disconnect")
            self.conn_status.setText(f"Connected — {port}")
            self.conn_status.setStyleSheet("color: #34C759; font-weight: bold; padding-left: 8px;")
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(True)
            self.deploy_btn.setEnabled(True)
            self.editor_deploy_btn.setEnabled(True)
            self._log(f"USB: Connected to {port} at {CODEBOT_BAUD} baud.")
        except Exception as e:
            QMessageBox.critical(self, "Connection Failed", str(e))
            self._log(f"USB ERROR: {e}")

    # ------------------------------------------------------------------
    # Run / Stop
    # ------------------------------------------------------------------

    def _run_code(self):
        """Compile and upload the current sketch to Codebot Air via arduino-cli."""
        sketch_dir = _PKG_DIR
        port = self._usb_port or (self._port_combo.currentText())
        if not port:
            QMessageBox.warning(self, "No Port", "Connect Codebot Air via USB-C first.")
            return
        self._log(f"Run: compiling and uploading sketch to {port}...")
        try:
            proc = subprocess.Popen(
                [ARDUINO_CLI, "compile", "--upload", "-p", port, "--fqbn", CODEBOT_FQBN, sketch_dir],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in proc.stdout:
                self._log(line.rstrip())
            proc.wait()
            if proc.returncode == 0:
                self._log("Run: Upload successful.")
            else:
                self._log(f"Run: Upload failed (exit {proc.returncode}).")
        except FileNotFoundError:
            self._log("ERROR: arduino-cli not found. Install it from https://arduino.github.io/arduino-cli/")
        except Exception as e:
            self._log(f"Run ERROR: {e}")

    def _stop_robot(self):
        """Send a stop command to Codebot Air over the serial connection."""
        if self._serial_conn and self._serial_conn.is_open:
            try:
                self._serial_conn.write(b"STOP\n")
                self._log("Stop command sent to Codebot Air.")
            except Exception as e:
                self._log(f"Stop ERROR: {e}")
        else:
            self._log("Stop: no active USB connection.")

    def _save_log_for_logbook(self, logbook_folder):
        """Write the current log window content to .testdrive_log.txt in logbook_folder."""
        try:
            log_path = os.path.join(logbook_folder, ".testdrive_log.txt")
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(self.log_area.toPlainText())
        except Exception:
            pass

    def closeEvent(self, event):
        """Clean up serial connection and save Logbook log on window close."""
        self._usb_timer.stop()
        if self._serial_conn and self._serial_conn.is_open:
            try:
                self._serial_conn.close()
            except Exception:
                pass
        for app_info in getattr(self, "_custom_apps_list", []):
            if app_info.get("py_file") == "logbook.py":
                self._save_log_for_logbook(app_info["folder"])
                break
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Git / GitHub integration
    # ------------------------------------------------------------------

    def _load_git_creds(self):
        """Load saved git credentials from disk."""
        try:
            with open(_GIT_CREDS_FILE, "r") as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _save_git_creds(self, creds: dict):
        """Persist git credentials (username, token, repo_name) to disk."""
        try:
            existing = self._load_git_creds()
            existing.update(creds)
            with open(_GIT_CREDS_FILE, "w") as fh:
                json.dump(existing, fh, indent=2)
        except Exception:
            pass

    def _show_git_menu(self):
        """Show the Git action dropdown beneath the GitHub button."""
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: white; border: 1px solid #ddd; border-radius: 8px; "
            "padding: 4px 0; font-size: 13px; }"
            "QMenu::item { padding: 8px 24px; color: #1a1a1a; }"
            "QMenu::item:selected { background: #F0F0F0; color: #1a1a1a; border-radius: 4px; }"
            "QMenu::separator { height: 1px; background: #eee; margin: 4px 0; }"
        )
        init_action = menu.addAction("  Create GitHub Repo")
        push_action = menu.addAction("  Commit & Push")
        pull_action = menu.addAction("  Pull from GitHub")
        menu.addSeparator()
        menu.addAction("  Cancel")

        btn_rect  = self.git_btn.rect()
        btn_pos   = self.git_btn.mapToGlobal(btn_rect.bottomLeft())
        chosen    = menu.exec(btn_pos)

        if chosen == init_action:
            self._git_init()
        elif chosen == push_action:
            self._git_push()
        elif chosen == pull_action:
            self._git_pull()

    # --- git init + GitHub repo creation ---

    def _git_init(self):
        creds  = self._load_git_creds()
        dialog = GitInitDialog(creds, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.result_creds()

        if data.get("save"):
            self._save_git_creds({
                "username":    data["username"],
                "token":       data["token"],
                "repo_name":   data["repo_name"],
                "description": data["description"],
                "save":        True,
            })

        errors = []

        # 1. git init (idempotent)
        r = subprocess.run(["git", "init"], cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode != 0:
            errors.append(f"git init failed:\n{r.stderr.strip()}")

        # 2. git config author (use GitHub username)
        subprocess.run(["git", "config", "user.name",  data["username"]], cwd=_PKG_DIR)
        subprocess.run(["git", "config", "user.email", f"{data['username']}@users.noreply.github.com"],
                       cwd=_PKG_DIR)

        # 3. Ensure .gitignore hides credential files
        gitignore = os.path.join(_PKG_DIR, ".gitignore")
        hidden = {".git_credentials.json", ".robot_profiles.json", ".node_canvas.json",
                  "__pycache__/", "*.pyc"}
        try:
            existing_lines = open(gitignore).read().splitlines() if os.path.exists(gitignore) else []
            with open(gitignore, "a") as fh:
                for entry in hidden:
                    if entry not in existing_lines:
                        fh.write(entry + "\n")
        except Exception:
            pass

        # 4. Create README.md if requested
        if data["readme"]:
            readme_path = os.path.join(_PKG_DIR, "README.md")
            if not os.path.exists(readme_path):
                try:
                    with open(readme_path, "w") as fh:
                        fh.write(f"# {data['repo_name']}\n\n{data['description']}\n")
                except Exception:
                    pass

        # 5. Create GitHub repo via API
        try:
            payload = json.dumps({
                "name":        data["repo_name"],
                "description": data["description"],
                "private":     data["private"],
                "auto_init":   False,
            }).encode()
            req = urllib.request.Request(
                "https://api.github.com/user/repos",
                data=payload,
                headers={
                    "Authorization": f"token {data['token']}",
                    "Content-Type":  "application/json",
                    "Accept":        "application/vnd.github+json",
                    "User-Agent":    "TestDrive-App",
                },
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                repo_info = json.loads(resp.read())
            clone_url = repo_info.get("clone_url", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            errors.append(f"GitHub API error {e.code}:\n{body[:300]}")
            clone_url = ""
        except Exception as e:
            errors.append(f"GitHub API error: {e}")
            clone_url = ""

        # 6. Set remote origin (embed token for auth)
        if clone_url:
            auth_url = clone_url.replace(
                "https://", f"https://{data['username']}:{data['token']}@")
            subprocess.run(["git", "remote", "remove", "origin"],
                           cwd=_PKG_DIR, capture_output=True)
            subprocess.run(["git", "remote", "add", "origin", auth_url],
                           cwd=_PKG_DIR, capture_output=True)

        # 7. Initial commit + push
        subprocess.run(["git", "add", "."], cwd=_PKG_DIR, capture_output=True)
        r = subprocess.run(["git", "commit", "-m", "Initial commit — TestDrive"],
                           cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode != 0 and "nothing to commit" not in r.stdout:
            errors.append(f"git commit failed:\n{r.stderr.strip()}")

        if clone_url:
            r = subprocess.run(
                ["git", "push", "-u", "origin", "HEAD"],
                cwd=_PKG_DIR, capture_output=True, text=True)
            if r.returncode != 0:
                errors.append(f"git push failed:\n{r.stderr.strip()}")

        if errors:
            QMessageBox.warning(self, "Git — Issues Encountered",
                                "\n\n".join(errors))
        else:
            repo_url = f"https://github.com/{data['username']}/{data['repo_name']}"
            QMessageBox.information(
                self, "Git — Repository Created",
                f"Repository created and initial push complete.\n\n{repo_url}")

    # --- git commit + push ---

    def _git_push(self):
        creds  = self._load_git_creds()
        dialog = GitPushDialog(creds, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        data = dialog.result_data()

        if data.get("save"):
            # Extract username/repo_name from URL for future pre-fill
            m = re.match(r'https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$',
                         data["repo_url"])
            update = {"token": data["token"], "branch": data["branch"]}
            if m:
                update["username"] = m.group(1)
                update["repo_name"] = m.group(2)
            self._save_git_creds(update)

        errors = []
        branch = data.get("branch", "main")

        self._log("--- Git Commit & Push ---")
        self._log(f"Repository: {data['repo_url']}")
        self._log(f"Branch: {branch}")
        self._log(f"Commit message: {data['message']}")

        # Ensure remote is set with auth token
        auth_url = re.sub(r'^https://',
                          f'https://{creds.get("username", "")}:{data["token"]}@',
                          data["repo_url"])
        # If username not in saved creds, try extracting from URL
        m = re.match(r'https://github\.com/([^/]+)', data["repo_url"])
        if m:
            auth_url = data["repo_url"].replace(
                "https://", f"https://{m.group(1)}:{data['token']}@")

        subprocess.run(["git", "remote", "remove", "origin"],
                       cwd=_PKG_DIR, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin", auth_url],
                       cwd=_PKG_DIR, capture_output=True)

        self._log("Running: git add .")
        subprocess.run(["git", "add", "."], cwd=_PKG_DIR, capture_output=True)

        self._log(f"Running: git commit -m \"{data['message']}\"")
        r = subprocess.run(
            ["git", "commit", "-m", data["message"]],
            cwd=_PKG_DIR, capture_output=True, text=True)
        if r.stdout.strip():
            self._log(r.stdout.strip())
        if r.stderr.strip():
            self._log(r.stderr.strip())
        if r.returncode != 0 and "nothing to commit" not in r.stdout and "nothing to commit" not in r.stderr:
            errors.append(f"git commit: {r.stderr.strip() or r.stdout.strip()}")
            self._log(f"ERROR: git commit failed (exit code {r.returncode})")
        else:
            self._log("git commit: OK")

        self._log(f"Running: git pull --rebase origin {branch}")
        r = subprocess.run(
            ["git", "pull", "--rebase", "origin", branch],
            cwd=_PKG_DIR, capture_output=True, text=True)
        if r.stdout.strip():
            self._log(r.stdout.strip())
        if r.stderr.strip():
            self._log(r.stderr.strip())
        if r.returncode != 0:
            errors.append(f"git pull --rebase failed:\n{r.stderr.strip() or r.stdout.strip()}")
            self._log(f"ERROR: git pull --rebase failed (exit code {r.returncode})")
        else:
            self._log("git pull --rebase: OK")

        self._log(f"Running: git push -u origin HEAD:{branch}")
        r = subprocess.run(
            ["git", "push", "-u", "origin", f"HEAD:{branch}"],
            cwd=_PKG_DIR, capture_output=True, text=True)
        if r.stdout.strip():
            self._log(r.stdout.strip())
        if r.stderr.strip():
            self._log(r.stderr.strip())
        if r.returncode != 0:
            errors.append(f"git push failed:\n{r.stderr.strip()}")
            self._log(f"ERROR: git push failed (exit code {r.returncode})")
        else:
            self._log("git push: OK")

        if errors:
            self._log("--- Push finished with errors ---")
            QMessageBox.warning(self, "Git — Push Issues", "\n\n".join(errors))
        else:
            self._log("--- Push complete ---")
            QMessageBox.information(self, "Git — Push Complete",
                                    f"Changes pushed to:\n{data['repo_url']}")

    # --- git pull ---

    def _git_pull(self):
        creds = self._load_git_creds()
        token = creds.get("token", "")

        # Check we're inside a git repo
        r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                           cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode != 0:
            QMessageBox.warning(self, "Git — Not Initialised",
                                "This project is not a git repository yet.\n"
                                "Use 'Initialize & Create GitHub Repo' first.")
            return

        # Inject token into remote URL if we have one
        if token:
            r2 = subprocess.run(["git", "remote", "get-url", "origin"],
                                 cwd=_PKG_DIR, capture_output=True, text=True)
            remote_url = r2.stdout.strip()
            if remote_url and "github.com" in remote_url:
                m = re.match(r'https://github\.com/([^/]+)', remote_url)
                if m:
                    auth_url = remote_url.replace(
                        "https://", f"https://{m.group(1)}:{token}@")
                    subprocess.run(["git", "remote", "set-url", "origin", auth_url],
                                   cwd=_PKG_DIR, capture_output=True)

        r = subprocess.run(["git", "pull"],
                           cwd=_PKG_DIR, capture_output=True, text=True)
        if r.returncode != 0:
            QMessageBox.warning(self, "Git — Pull Failed", r.stderr.strip())
        else:
            msg = r.stdout.strip() or "Already up to date."
            QMessageBox.information(self, "Git — Pull Complete", msg)


def main():
    app = QApplication(sys.argv)
    window = RobotControlApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
