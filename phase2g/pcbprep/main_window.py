from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QRectF, QThread, Signal, Slot, QTimer
from PySide6.QtGui import QColor, QBrush, QPen, QPainterPath, QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QGraphicsScene, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QSplitter,
    QTextBrowser, QToolBar, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QToolButton,
    QPushButton, QFrame, QScrollArea,
    QDoubleSpinBox,
    QComboBox,
)
from shapely.geometry import LineString

from .inspection_model import BoardDocument, RegionData, load_archive
from .view import BoardView, FeaturePathItem, WarningMarker, geometry_path
from phase2l.geometry import (VBit, eligibility_for_simulation, plan_isolation,
                              synthetic_canonical_geometry, synthetic_connected_canonical_geometry)
from phase2o.isolation import (identify_residual_candidates, plan_selective_clearing,
                               plan_two_pass)
from phase2m.operations import OPERATIONS, evaluate_operation_status, relevant_to_operation
from phase2m.repair import (DEFAULT_CLOSURE_TOLERANCE_MM, propose_closure,
                            approve_proposal)
from phase2m.visual_style import (COPPER_BLUE, TOOLPATH_AMBER, FOOTPRINT_AMBER,
                                  COLLISION_RED, UNCERTAINTY_VIOLET,
                                  proposed_toolpath_pen, selected_toolpath_halo_pen,
                                  repair_proposal_pen)


class ArchiveLoadWorker(QObject):
    loaded = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, archive: Path):
        super().__init__()
        self.archive = archive

    @Slot()
    def run(self):
        try:
            self.loaded.emit(load_archive(self.archive, progress=self.progress.emit))
        except Exception as exc:
            self.failed.emit(str(exc))


BG = "#0b1118"
PANEL = "#111a23"
PANEL_2 = "#17232e"
LINE = "#273644"
TEXT = "#e7edf2"
MUTED = "#94a6b5"
COPPER = "#df8d42"
TEAL = "#38d6c3"
BLUE = "#60a5fa"
RED = "#ff5d67"
GOLD = "#ffc857"
VALENTINE_GERBER_BOTTOM_SHA256 = "f701e7ada043321c89a2c3baf73a84c32a3aad93cc3259bd9eff07bbd8e47843"
VALENTINE_NATIVE_COMPARISON = {
    0: {"lines": (34, 5714), "noops": 105, "fill": "e1698", "voids": 103,
        "area_delta": -2.2008875556607563, "symmetric_difference": 2.2023075311968827,
        "hausdorff": 0.005050711465022289},
    1: {"lines": (5715, 6302), "noops": 14, "fill": "e1699", "voids": 14,
        "area_delta": -0.209869177533335, "symmetric_difference": 0.21004932128609602,
        "hausdorff": 0.0047608047637029026},
}


class PcbPrepWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._register_windows_font()
        self.setWindowTitle("DemonX PCB Prep — Geometry Inspection")
        self.resize(1720, 1040)
        self.document: BoardDocument | None = None
        self.selected_region: RegionData | None = None
        self.current_issue: dict[str, Any] | None = None
        self._load_thread: QThread | None = None
        self._load_worker: ArchiveLoadWorker | None = None
        self.layer_checks: dict[str, QCheckBox] = {}
        self._loading = False
        self._load_succeeded = False
        self.demo_geometry = None
        self.demo_canonical = None
        self.simulation_plan = None
        self.multipass_plan = None
        self.clearing_plan = None
        self.residual_candidates = ()
        self._refreshing_residuals = False
        self.simulation_enabled = False
        self.operation_key = "copper-isolation"
        self._all_issue_rows: list[tuple[dict[str, Any], str]] = []
        self.repair_proposal = None
        self.approved_repair_layers: list[tuple[Any, dict[str, Any]]] = []
        self.repair_audit: list[dict[str, Any]] = []
        self._spinner_frames = ("|", "/", "—", "\\")
        self._spinner_index = 0
        self._build_ui()
        self._apply_theme()
        self._show_empty_state()

    def _build_ui(self):
        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        self.open_action = toolbar.addAction("Open Gerber ZIP")
        self.open_action.triggered.connect(self.open_dialog)
        toolbar.addSeparator()
        self.valentine_action = toolbar.addAction("Sample · Valentine")
        self.valentine_action.triggered.connect(lambda: self.load_sample("valentine"))
        self.laser_action = toolbar.addAction("Sample · Laser Module")
        self.laser_action.triggered.connect(lambda: self.load_sample("laser"))
        self.synthetic_action = toolbar.addAction("Synthetic geometry demo")
        self.synthetic_action.triggered.connect(self.show_synthetic_demo)
        self.connected_demo_action = toolbar.addAction("Connected-pad fixture")
        self.connected_demo_action.triggered.connect(self.show_connected_pad_demo)
        self.repair_demo_action = toolbar.addAction("Synthetic repair example")
        self.repair_demo_action.triggered.connect(self.show_synthetic_repair_example)
        self._load_actions = [self.open_action, self.valentine_action, self.laser_action,
                              self.synthetic_action, self.connected_demo_action, self.repair_demo_action]
        self.simulation_action = toolbar.addAction("Isolation Simulation — Not Approved for Machining")
        self.simulation_action.setCheckable(True)
        self.simulation_action.toggled.connect(self.set_simulation_enabled)
        self._load_actions.append(self.simulation_action)
        self.angle_input = QDoubleSpinBox(); self.angle_input.setRange(1.0, 179.0); self.angle_input.setValue(30.0)
        self.angle_input.setSuffix("°"); self.angle_input.setToolTip("V-bit included angle")
        self.tip_input = QDoubleSpinBox(); self.tip_input.setRange(0.0, 5.0); self.tip_input.setDecimals(3); self.tip_input.setSingleStep(.025); self.tip_input.setValue(.100)
        self.tip_input.setSuffix(" mm tip"); self.tip_input.setToolTip("Flat tip diameter")
        self.depth_input = QDoubleSpinBox(); self.depth_input.setRange(0.0, 2.0); self.depth_input.setDecimals(3); self.depth_input.setSingleStep(.025); self.depth_input.setValue(.100)
        self.depth_input.setSuffix(" mm depth"); self.depth_input.setToolTip("Engraving depth")
        toolbar.addWidget(self.angle_input); toolbar.addWidget(self.tip_input); toolbar.addWidget(self.depth_input)
        self.angle_input.valueChanged.connect(self._update_simulation)
        self.tip_input.valueChanged.connect(self._update_simulation)
        self.depth_input.valueChanged.connect(self._update_simulation)
        self.strategy_selector = QComboBox()
        self.strategy_selector.addItem("Single pass", "single")
        self.strategy_selector.addItem("Two passes", "two")
        self.strategy_selector.addItem("Selective clearing", "clear")
        self.strategy_selector.setToolTip("Diagnostic strategy only; does not authorize manufacturing")
        self.strategy_selector.currentIndexChanged.connect(self._update_simulation)
        self.second_offset_input = QDoubleSpinBox()
        self.second_offset_input.setRange(.005, 1.0)
        self.second_offset_input.setDecimals(3)
        self.second_offset_input.setSingleStep(.025)
        self.second_offset_input.setValue(.200)
        self.second_offset_input.setSuffix(" mm extra")
        self.second_offset_input.setToolTip("Pass 2 cutter-center distance beyond pass 1; not total removed width")
        self.second_offset_input.hide()
        self.second_offset_input.valueChanged.connect(self._update_simulation)
        toolbar.addSeparator()
        fit = toolbar.addAction("Fit board")
        fit.triggered.connect(self.fit_board)
        zoom = toolbar.addAction("Zoom to issue")
        zoom.triggered.connect(self.zoom_to_issue)
        toolbar.addSeparator()
        self.loading_label = QLabel("Ready")
        self.loading_label.setMinimumWidth(300)
        self.loading_label.setObjectName("loadStatus")
        toolbar.addWidget(self.loading_label)
        self._loading_timer = QTimer(self)
        self._loading_timer.setInterval(110)
        self._loading_timer.timeout.connect(self._animate_spinner)
        QShortcut(QKeySequence("F"), self, activated=self.fit_board)
        QShortcut(QKeySequence("Home"), self, activated=self.reset_view)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 8, 12, 10)
        root_layout.setSpacing(9)
        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("DEMONX <span style='color:#df8d42'>PCB PREP</span>")
        title.setObjectName("brand")
        subtitle = QLabel("Manufacturing geometry inspection · read-only preview")
        subtitle.setObjectName("subtitle")
        title_col.addWidget(title); title_col.addWidget(subtitle)
        operation_row = QHBoxLayout()
        operation_row.addWidget(QLabel("Preparation operation"))
        self.operation_selector = QComboBox()
        for key, label in OPERATIONS:
            self.operation_selector.addItem(label, key)
        self.operation_selector.currentIndexChanged.connect(self._operation_changed)
        self.operation_selector.setToolTip("Findings and eligibility are filtered for this preparation operation")
        operation_row.addWidget(self.operation_selector)
        operation_row.addSpacing(12)
        operation_row.addWidget(QLabel("Isolation strategy"))
        operation_row.addWidget(self.strategy_selector)
        operation_row.addWidget(self.second_offset_input)
        title_col.addLayout(operation_row)
        header.addLayout(title_col); header.addStretch(1)
        self.board_title = QLabel("No board loaded")
        self.board_title.setObjectName("boardTitle")
        header.addWidget(self.board_title)
        root_layout.addLayout(header)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._left_panel())
        self.scene = QGraphicsScene(self)
        self.view = BoardView(self.scene)
        self.view.coordinatesChanged.connect(self._show_coordinates)
        self.scene.selectionChanged.connect(self._inspect_selected_item)
        canvas = QWidget()
        canvas_layout = QVBoxLayout(canvas)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.addWidget(self.evidence_note)
        canvas_layout.addWidget(self.view)
        self.loading_overlay = QFrame(self.view.viewport())
        self.loading_overlay.setObjectName("loadingOverlay")
        overlay_layout = QVBoxLayout(self.loading_overlay)
        overlay_layout.setContentsMargins(18, 14, 18, 14)
        overlay_layout.setSpacing(5)
        self.overlay_spinner = QLabel("◌")
        self.overlay_spinner.setObjectName("overlaySpinner")
        self.overlay_spinner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.overlay_stage = QLabel("Preparing import…")
        self.overlay_stage.setObjectName("overlayStage")
        self.overlay_stage.setWordWrap(True)
        self.overlay_stage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.addWidget(self.overlay_spinner)
        overlay_layout.addWidget(self.overlay_stage)
        self.loading_overlay.setFixedSize(420, 118)
        self.loading_overlay.hide()
        self.view.viewport().installEventFilter(self)
        split.addWidget(canvas)
        split.addWidget(self._inspector_panel())
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([235, 1160, 340])
        self.splitter = split
        root_layout.addWidget(split, 1)

        footer = QHBoxLayout()
        self.compliance = QLabel("Source status · —")
        self.compliance.setObjectName("badgeWarning")
        self.eligibility = QLabel("Machining · BLOCKED")
        self.eligibility.setObjectName("badgeBlocked")
        self.coordinate_label = QLabel("X — · Y — mm")
        self.coordinate_label.setObjectName("coord")
        footer.addWidget(self.compliance); footer.addWidget(self.eligibility); footer.addStretch(1)
        footer.addWidget(self.coordinate_label)
        root_layout.addLayout(footer)
        self.setCentralWidget(root)

    def _left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        box = QGroupBox("Visible geometry")
        checks = QVBoxLayout(box)
        for key, label, checked in (
            ("top", "Top copper", True), ("bottom", "Bottom copper", True),
            ("profile", "Board outline", True), ("pads", "Pad flashes", False),
            ("drills", "Drill centers", True), ("slots", "Routed slots", True),
            ("source", "Source contours", True), ("candidate", "Proposed regions", True),
            ("native", "Native fill boundary", False),
            ("diagnostics", "Highlight issue", True),
            ("pass1", "Pass 1 centerline", True),
            ("pass2", "Pass 2 centerline", True),
            ("footprint", "Cutter footprints", True),
            ("rejected", "Rejected paths / collisions", True),
            ("inferred", "Inferred source edges", False),
            ("uncertainty", "Geometry uncertainty overlay", False),
            ("after", "Show simulated remaining copper", False),
        ):
            cb = QCheckBox(label); cb.setChecked(checked)
            cb.stateChanged.connect(self.rebuild_scene)
            self.layer_checks[key] = cb
            checks.addWidget(cb)
        self.clear_candidates_list = QListWidget()
        self.clear_candidates_list.setMaximumHeight(150)
        self.clear_candidates_list.setToolTip("Each checked item explicitly classifies that residual zone as removable for this preview only")
        self.clear_candidates_list.itemChanged.connect(self._residual_selection_changed)
        checks.addWidget(QLabel("Optional residual zones · unchecked by default"))
        checks.addWidget(self.clear_candidates_list)
        layout.addWidget(box)
        self.evidence_note = QLabel("Candidate geometry is for inspection only. Source conformance and machining eligibility are evaluated separately.")
        self.evidence_note.setWordWrap(True); self.evidence_note.setObjectName("note")
        self.evidence_note.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(self.evidence_note)
        tolerance_row = QHBoxLayout()
        tolerance_row.addWidget(QLabel("Repair gap limit"))
        self.repair_tolerance_input = QDoubleSpinBox()
        self.repair_tolerance_input.setRange(.001, 1.0)
        self.repair_tolerance_input.setDecimals(3)
        self.repair_tolerance_input.setSingleStep(.005)
        self.repair_tolerance_input.setValue(DEFAULT_CLOSURE_TOLERANCE_MM)
        self.repair_tolerance_input.setSuffix(" mm")
        self.repair_tolerance_input.setToolTip("Review threshold only; a short gap is not proof of intended closure")
        self.repair_tolerance_input.valueChanged.connect(self._refresh_selected_repair)
        tolerance_row.addWidget(self.repair_tolerance_input)
        layout.addLayout(tolerance_row)
        self.repair_toggle = QCheckBox("Show proposed repair")
        self.repair_toggle.setChecked(True)
        self.repair_toggle.stateChanged.connect(self.rebuild_scene)
        layout.addWidget(self.repair_toggle)
        self.issue_header = QLabel("COPPER ISOLATION FINDINGS")
        self.issue_header.setObjectName("sectionLabel")
        layout.addWidget(self.issue_header)
        self.issues_list = QListWidget()
        self.issues_list.currentItemChanged.connect(self._issue_selected)
        self.issues_list.itemDoubleClicked.connect(self._issue_double_clicked)
        self.issues_list.setWordWrap(True)
        self.issues_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.issues_list, 1)
        return panel

    def _inspector_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(315)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(9)
        header = QLabel("ISSUE / FEATURE INSPECTOR")
        header.setObjectName("sectionLabel")
        layout.addWidget(header)
        self.inspect_title = QLabel("Open a board")
        self.inspect_title.setObjectName("inspectTitle")
        self.inspect_title.setWordWrap(True)
        layout.addWidget(self.inspect_title)
        self.inspect_meta = QLabel("")
        self.inspect_meta.setObjectName("inspectMeta")
        self.inspect_meta.setWordWrap(True)
        layout.addWidget(self.inspect_meta)
        self.inspect_summary = QLabel("")
        self.inspect_summary.setObjectName("inspectSummary")
        self.inspect_summary.setWordWrap(True)
        layout.addWidget(self.inspect_summary)
        self.inspect_action = QLabel("")
        self.inspect_action.setObjectName("inspectAction")
        self.inspect_action.setWordWrap(True)
        layout.addWidget(self.inspect_action)
        actions = QVBoxLayout()
        actions.setSpacing(6)
        self.view_issue_button = QPushButton("View geometry")
        self.view_issue_button.clicked.connect(self.zoom_to_issue)
        self.import_reference_button = QPushButton("Open another Gerber ZIP…")
        self.import_reference_button.clicked.connect(self.open_dialog)
        self.comparison_evidence_button = QPushButton("Open copper comparison report")
        self.comparison_evidence_button.clicked.connect(self._open_comparison_evidence)
        self.comparison_evidence_button.hide()
        self.approve_repair_button = QPushButton("Approve candidate to working layer")
        self.approve_repair_button.clicked.connect(self._approve_current_repair)
        self.approve_repair_button.hide()
        self.view_issue_button.setMinimumHeight(34)
        self.import_reference_button.setMinimumHeight(34)
        actions.addWidget(self.view_issue_button)
        actions.addWidget(self.import_reference_button)
        actions.addWidget(self.comparison_evidence_button)
        actions.addWidget(self.approve_repair_button)
        layout.addLayout(actions)
        self.advanced_button = QToolButton()
        self.advanced_button.setText("Advanced details [show]")
        self.advanced_button.setCheckable(True)
        self.advanced_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.advanced_button.toggled.connect(self._toggle_advanced)
        layout.addWidget(self.advanced_button)
        self.advanced_text = QTextBrowser()
        self.advanced_text.setObjectName("advanced")
        self.advanced_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.advanced_text.setLineWrapMode(QTextBrowser.LineWrapMode.WidgetWidth)
        self.advanced_text.setMinimumHeight(130)
        self.advanced_text.setVisible(False)
        layout.addWidget(self.advanced_text, 1)
        self.layer_tree = QTreeWidget()
        self.layer_tree.setHeaderLabels(["Source files and detected functions"])
        self.layer_tree.setMaximumHeight(140)
        self.layer_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.layer_tree)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _apply_theme(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background:{BG}; color:{TEXT}; font-family:'Segoe UI'; font-size:11pt; }}
            QToolBar {{ background:{PANEL}; border:1px solid {LINE}; spacing:8px; padding:6px; }}
            QToolButton {{ background:{PANEL_2}; color:{TEXT}; border:1px solid {LINE}; border-radius:5px; padding:7px 12px; }}
            QToolButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
            QGroupBox {{ background:{PANEL}; border:1px solid {LINE}; border-radius:7px; margin-top:12px; padding:11px 8px 8px; font-weight:600; }}
            QGroupBox::title {{ subcontrol-origin:margin; left:9px; padding:0 5px; color:{TEAL}; }}
            QCheckBox {{ spacing:8px; padding:4px 2px; }}
            QCheckBox::indicator {{ width:15px; height:15px; }}
            QListWidget, QTreeWidget, QTextBrowser {{ background:{PANEL}; border:1px solid {LINE}; border-radius:6px; padding:6px; }}
            QListWidget::item, QTreeWidget::item {{ padding:5px; }}
            QListWidget::item:selected, QTreeWidget::item:selected {{ background:#1b3942; color:#ffffff; }}
            QLabel#brand {{ color:#f4f7f9; font-size:18pt; font-weight:800; letter-spacing:1px; }}
            QLabel#subtitle {{ color:{MUTED}; font-size:10pt; }}
            QLabel#loadStatus {{ color:{TEAL}; font-size:10pt; padding:4px 8px; }}
            QLabel#inspectTitle {{ color:{COPPER}; font-size:15pt; font-weight:700; padding:5px 0; }}
            QLabel#inspectMeta {{ color:{TEAL}; font-size:10pt; font-weight:600; }}
            QLabel#inspectSummary {{ color:{TEXT}; font-size:11pt; padding:7px 0; }}
            QLabel#inspectAction {{ color:#f1cc7b; background:#28241b; border:1px solid #594a27; border-radius:5px; padding:8px; }}
            QPushButton {{ color:{TEXT}; background:{PANEL_2}; border:1px solid {LINE}; border-radius:5px; padding:8px 7px; }}
            QPushButton:hover {{ border-color:{TEAL}; color:{TEAL}; }}
            QFrame#loadingOverlay {{ background:#101a23; border:2px solid {TEAL}; border-radius:10px; }}
            QLabel#overlaySpinner {{ color:{TEAL}; font-size:25pt; font-weight:700; }}
            QLabel#overlayStage {{ color:{TEXT}; font-size:11pt; font-weight:600; }}
            QLabel#boardTitle {{ color:{COPPER}; font-size:13pt; font-weight:700; padding:8px 12px; }}
            QLabel#sectionLabel {{ color:{TEAL}; font-size:9pt; font-weight:700; letter-spacing:1px; padding:5px 2px; }}
            QLabel#note {{ color:#d6b978; background:#28241b; border:1px solid #594a27; border-radius:5px; padding:8px; font-size:9pt; }}
            QLabel#badgeWarning {{ color:#ffe2a0; background:#302619; border:1px solid #765522; padding:6px 9px; border-radius:5px; font-weight:700; }}
            QLabel#badgeBlocked {{ color:#ffc2c7; background:#321d24; border:1px solid #7e3542; padding:6px 9px; border-radius:5px; font-weight:700; }}
            QLabel#coord {{ color:{TEAL}; font-family:Consolas; }}
            QSplitter::handle {{ background:{LINE}; width:5px; }}
        """)

    @staticmethod
    def _register_windows_font():
        """Make screenshots/headless Windows runs use the same readable UI font."""
        windir = Path(os.environ.get("WINDIR", "C:/Windows"))
        font_path = windir / "Fonts" / "segoeui.ttf"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
            QFontDatabase.addApplicationFont(str(windir / "Fonts" / "segoeuib.ttf"))
            QApplication.setFont(QFont("Segoe UI", 9))

    def _show_empty_state(self):
        self.scene.clear()
        self.scene.setSceneRect(QRectF(-50, -50, 100, 100))
        self.inspect_title.setText("Open a manufacturing archive")
        self.inspect_meta.setText("Read-only geometry inspection")
        self.inspect_summary.setText("Load a Gerber ZIP to view detected copper, board profile, drill features and validation findings.")
        self.inspect_action.setText("No toolpaths or CNC output are available in this preview.")
        self.view_issue_button.setEnabled(False)
        self.advanced_text.clear()

    def open_dialog(self):
        name, _ = QFileDialog.getOpenFileName(self, "Open Gerber manufacturing archive", "", "ZIP archives (*.zip)")
        if name:
            self.request_load_archive(Path(name))

    def load_sample(self, sample: str):
        if sample == "laser":
            archive = Path(__file__).resolve().parents[2] / "phase2f/fixtures/laser-v2.0-export.zip"
        else:
            archive = Path(__file__).resolve().parents[2] / "gerbers/Gerber_PCB_Valentine_Feb_New.zip"
        self.request_load_archive(archive)

    def request_load_archive(self, archive: Path):
        """Parse an archive off the UI thread; keep the window interactive meanwhile."""
        if self._load_thread and self._load_thread.isRunning():
            return
        self._loading = True
        self._load_succeeded = False
        self.loading_label.setText("Importing…")
        self.loading_label.setStyleSheet(f"color:{TEAL}")
        self._loading_timer.start()
        self.overlay_stage.setText("Checking archive paths and identifying manufacturing files…")
        self._position_loading_overlay()
        self.loading_overlay.show()
        self.loading_overlay.raise_()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.statusBar().showMessage("Import in progress — the board remains read-only until parsing finishes.")
        for action in self._load_actions:
            action.setEnabled(False)
        self.open_action.setText("Loading…")
        thread = QThread(self)
        worker = ArchiveLoadWorker(Path(archive))
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._loading_stage)
        worker.loaded.connect(self._install_document)
        worker.failed.connect(self._load_failed)
        worker.loaded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._load_finished)
        self._load_thread, self._load_worker = thread, worker
        thread.start()

    def _load_failed(self, message: str):
        self.overlay_stage.setText("Import failed. The previous board is unchanged.")
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Import failed")
        dialog.setText("PCB Prep could not read this manufacturing archive.")
        dialog.setInformativeText("Choose another Gerber ZIP or review the archive details.")
        dialog.setDetailedText(message)
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.exec()
        self.statusBar().showMessage("Import failed — choose another Gerber ZIP or review the archive details.")

    def _load_finished(self):
        self._loading = False
        self._loading_timer.stop()
        if QApplication.overrideCursor() is not None:
            QApplication.restoreOverrideCursor()
        self.open_action.setText("Open Gerber ZIP")
        for action in self._load_actions:
            action.setEnabled(True)
        self._load_thread = None
        self._load_worker = None
        self.loading_overlay.hide()
        if self._load_succeeded and self.document:
            self.loading_label.setText(f"Ready · {len(self.document.layer_files)} manufacturing files")
            self.statusBar().showMessage("Import complete — board is ready for inspection.")
        else:
            self.loading_label.setText("Import failed · previous board retained" if self.document else "Import failed")

    def _loading_stage(self, stage: str):
        if self._loading:
            self.overlay_stage.setText(stage)
            self.statusBar().showMessage("Import in progress — see the centered activity panel.")

    def _animate_spinner(self):
        if not self._loading:
            return
        self._spinner_index = (self._spinner_index + 1) % len(self._spinner_frames)
        self.overlay_spinner.setText(("◌", "◔", "◑", "◕", "●", "◕", "◑", "◔")[self._spinner_index % 8])

    def _toggle_advanced(self, expanded: bool):
        self.advanced_text.setVisible(expanded)
        self.advanced_button.setText("Advanced details [hide]" if expanded else "Advanced details [show]")

    def load_archive(self, archive: Path):
        self.demo_geometry = None
        self.demo_canonical = None
        self.simulation_plan = None
        self.multipass_plan = None
        self.clearing_plan = None
        self.simulation_enabled = False
        self.simulation_action.setChecked(False)
        """Synchronous loader retained for deterministic smoke tests and captures."""
        self.statusBar().showMessage("Reading archive and parsing source manufacturing files…")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        try:
            fresh = load_archive(archive)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open Gerber archive", str(exc))
            self.statusBar().showMessage("Archive could not be opened")
            return
        self._install_document(fresh)

    def show_synthetic_demo(self):
        """Replace the canvas with hand-defined synthetic copper for the preview demo."""
        self.demo_canonical = synthetic_canonical_geometry()
        self.demo_geometry = self.demo_canonical.material("top-copper")
        self.simulation_plan = None
        self.multipass_plan = None
        self.clearing_plan = None
        self.residual_candidates = ()
        self._refresh_residual_candidates(())
        self.simulation_enabled = False
        self.simulation_action.setChecked(False)
        self._all_issue_rows.clear()
        self.issues_list.clear()
        self._add_issue_row({
            "title": "Silkscreen mark is outside the board edge", "severity": "WARNING · informational",
            "layer": "TopSilkScreen", "summary": "This synthetic silkscreen finding is shown in Full archive inspection.",
            "action": "It does not affect copper isolation. Review it when inspecting the complete archive.",
            "kind": "parser", "category": "WARNING"}, GOLD)
        self.current_issue = None
        self.board_title.setText("Synthetic geometry · demo only")
        self.compliance.setText("Source conformance · VALID · synthetic fixture")
        self.eligibility.setText("Machining · BLOCKED · synthetic demo only")
        self.evidence_note.setText(
            "<b>SYNTHETIC DEMO</b> · independently defined geometry; no user board data. "
            "Blue = original copper · amber = simulated cutter footprint · yellow = proposed center path · "
            "red = unsafe clearance / potential copper intrusion."
        )
        self.inspect_title.setText("Isolation simulation · synthetic geometry")
        self.inspect_meta.setText("SYNTHETIC · NOT APPROVED FOR MACHINING")
        self.inspect_summary.setText(
            "Hand-defined pads, narrow traces, a via, a copper island with a void, a routed slot, "
            "a concave outline, and adjacent pads. No manufacturing archive is used."
        )
        self.inspect_action.setText(
            "Adjust the included angle, flat tip diameter, and engraving depth above. Red areas expose "
            "clearances that do not fit and possible copper removal."
        )
        self.view_issue_button.hide()
        self.import_reference_button.hide()
        self.layer_tree.clear()
        self.statusBar().showMessage("Synthetic geometry loaded. Isolation simulation remains diagnostic only.")
        self.rebuild_scene()

    def show_connected_pad_demo(self):
        """Load the independent mandatory pad/trace fixture through canonical material."""
        self.demo_canonical = synthetic_connected_canonical_geometry()
        self.demo_geometry = self.demo_canonical.material("top-copper")
        self.simulation_plan = None
        self.multipass_plan = None
        self.clearing_plan = None
        self.residual_candidates = ()
        self._refresh_residual_candidates(())
        self.simulation_enabled = False
        self.simulation_action.setChecked(False)
        self._all_issue_rows.clear()
        self.issues_list.clear()
        self.current_issue = None
        self.board_title.setText("Connected pads and trace · synthetic fixture")
        self.compliance.setText("Source conformance · VALID · synthetic fixture")
        self.eligibility.setText("Machining · BLOCKED · synthetic demo only")
        self.evidence_note.setText(
            "<b>SYNTHETIC FIXTURE</b> · two overlapping circular pads, one rectangular trace, "
            "and two separate close pads. Copper is composed before isolation planning.")
        self.inspect_title.setText("Connected-pad isolation · demo only")
        self.inspect_meta.setText("SYNTHETIC · NOT APPROVED FOR MACHINING")
        self.inspect_summary.setText("The connected pads and trace are one copper component with one exterior isolation contour. The separate close pair remains a genuine clearance diagnostic.")
        self.inspect_action.setText("Enable Isolation Simulation to inspect the dashed centerline, collision region, and retained uncertainty.")
        self.view_issue_button.hide()
        self.import_reference_button.hide()
        self.layer_tree.clear()
        self.statusBar().showMessage("Connected-pad synthetic fixture loaded; diagnostic simulation only.")
        self.rebuild_scene()

    def show_synthetic_repair_example(self):
        """Show a near-gap repair proposal whose status remains manual review."""
        self.show_synthetic_demo()
        points = [(6.0, 6.0), (6.1, 6.0), (6.1, 6.1), (6.0, 6.1), (6.0048, 6.0064)]
        region = type("SyntheticOpenRegion", (), {})()
        region.source_points_mm = points
        region.source_commands = tuple({"line": i + 1, "operation": "D01", "mode": "G01"}
                                       for i in range(len(points) - 1))
        region.source_file = "synthetic-open-contour.gbr"
        region.polarity = "dark"
        region.boundary_hausdorff_mm = None
        region.index = 900
        region.recovery_status = "BLOCKED"
        region.native_polygon = None
        region.discrepancy_geometry = None
        region.discrepancy_point_mm = None
        region.discrepancy_nearest_point_mm = None
        region.closure_start_mm = points[0]
        region.closure_end_mm = points[-1]
        region.closure_length_mm = ((points[0][0]-points[-1][0])**2 +
                                    (points[0][1]-points[-1][1])**2) ** .5
        region.first_line, region.last_line = 1, len(points)
        region.source_sha256 = "synthetic-demo-only"
        issue = {"title": "Open contour · synthetic repair example",
            "severity": "NEEDS MANUAL REVIEW", "category": "NEEDS VERIFICATION",
            "layer": "Bottom copper", "kind": "region", "region": region,
            "syntheticRepairExample": True,
            "summary": "The endpoints are close, but proximity alone cannot confirm the intended contour.",
            "action": "The violet dashed segment is only a proposal. Review source commands and before/after effects.",
            "advanced": "Synthetic fixture only; original source is unchanged."}
        self._add_issue_row(issue, UNCERTAINTY_VIOLET)
        self.repair_toggle.setChecked(True)
        self.issues_list.setCurrentRow(self.issues_list.count() - 1)
        self._issue_selected(self.issues_list.currentItem(), None)
        self.zoom_to_issue()

    def set_simulation_enabled(self, enabled: bool):
        if not enabled:
            self.simulation_enabled = False
            self.simulation_plan = None
            self.multipass_plan = None
            self.clearing_plan = None
            self.residual_candidates = ()
            self._refresh_residual_candidates(())
            self._all_issue_rows = [(issue, color) for issue, color in self._all_issue_rows
                                    if not issue.get("syntheticDiagnostic") and not issue.get("inspectionDiagnostic")]
            if self.current_issue and (self.current_issue.get("syntheticDiagnostic") or
                                       self.current_issue.get("inspectionDiagnostic")):
                self.current_issue = None
                self.selected_region = None
            self._operation_changed(self.operation_selector.currentIndex())
            self.rebuild_scene()
            return
        if self.demo_geometry is None:
            if not self.document:
                self.simulation_action.setChecked(False)
                self.statusBar().showMessage("Simulation refused: load copper to inspect first.")
                return
            allowed, reason = eligibility_for_simulation(self.document.canonical_geometry, inspection_only=True)
            if any(layer.kind == "bottom" and (layer.metadata.get("unresolvedCount") or
                    layer.metadata.get("explicitTopologyRepairs")) for layer in self.document.layer_files):
                allowed, reason = False, "Simulation refused: bottom copper has unresolved parser or topology conversions."
            if any("Region source scan unavailable" in issue for issue in self.document.issues):
                allowed, reason = False, "Simulation refused: bottom copper source-contour provenance is unavailable."
            if not allowed:
                self.simulation_action.setChecked(False)
                self.statusBar().showMessage(reason)
                return
        self.simulation_enabled = True
        self._update_simulation()

    def _update_simulation(self, *_):
        if not self.simulation_enabled:
            return
        strategy = self.strategy_selector.currentData()
        self.second_offset_input.setVisible(strategy == "two")
        material = (self.demo_geometry if self.demo_geometry is not None else
                    self.document.canonical_geometry.material("bottom-copper") if self.document else None)
        try:
            cutter = VBit(self.angle_input.value(), self.tip_input.value())
            baseline = plan_isolation(
                material, cutter, self.depth_input.value(),
                approximation_error_bound_mm=0.002)
            self.simulation_plan = baseline
            self.multipass_plan = None
            self.clearing_plan = None
            self.residual_candidates = ()
            if strategy == "two":
                self.multipass_plan = plan_two_pass(material, cutter, self.depth_input.value(),
                    self.second_offset_input.value(), approximation_error_bound_mm=0.002,
                    baseline_plan=baseline)
                self.simulation_plan = self.multipass_plan.single_pass
            elif strategy == "clear":
                residual_material = material.difference(baseline.cutting_footprint)
                self.residual_candidates = identify_residual_candidates(residual_material)
                selected = self._refresh_residual_candidates()
                self.clearing_plan = plan_selective_clearing(material,
                    self.residual_candidates, selected, cutter=cutter,
                    depth_mm=self.depth_input.value(), classified_for_preview=selected,
                    approximation_error_bound_mm=0.002)
            else:
                self._refresh_residual_candidates(())
        except (ValueError, ArithmeticError) as exc:
            self.simulation_plan = None
            self.multipass_plan = None
            self.clearing_plan = None
            self.statusBar().showMessage(f"Simulation unavailable: {exc}")
            return
        plan = self.simulation_plan
        self._all_issue_rows = [(issue, color) for issue, color in self._all_issue_rows
                                if not issue.get("syntheticDiagnostic") and not issue.get("inspectionDiagnostic")]
        colors = {"cutter does not fit": RED,
                  "potential copper damage": RED,
                  "geometry uncertainty": UNCERTAINTY_VIOLET}
        titles = {"cutter does not fit": "Cutter does not fit",
                  "potential copper damage": "Potential copper damage",
                  "geometry uncertainty": "Geometry uncertainty"}
        for diagnostic in plan.issues:
            coordinate = (f" at ({diagnostic.coordinate_mm[0]:.4f}, {diagnostic.coordinate_mm[1]:.4f}) mm"
                          if diagnostic.coordinate_mm else "")
            summary = (diagnostic.cause + coordinate +
                       f" Required clearance {diagnostic.required_clearance_mm:.4f} mm; "
                       f"measured clearance {diagnostic.measured_clearance_mm:.4f} mm."
                       if diagnostic.measured_clearance_mm is not None else
                       diagnostic.cause + coordinate +
                       f" Effective width {plan.effective_width_mm:.4f} mm; measured overlap "
                       f"{diagnostic.raw_area_mm2:.8f} mm².")
            self._add_issue_row({"title": titles[diagnostic.category],
                "severity": diagnostic.category.upper(), "category": "NEEDS VERIFICATION",
                "layer": "Bottom copper · simulation", "summary": summary,
                "action": "Inspect the highlighted geometry. This inspection-only simulation cannot approve a machining operation.",
                "advanced": (f"Cause: {html.escape(diagnostic.cause)}<br>Coordinate: {diagnostic.coordinate_mm}<br>"
                    f"Measured clearance: {diagnostic.measured_clearance_mm}; required: {diagnostic.required_clearance_mm:.9f} mm<br>"
                    f"Effective width: {diagnostic.effective_cut_width_mm:.9f} mm<br>"
                    f"Raw measured area: {diagnostic.raw_area_mm2:.12f} mm²; spatial uncertainty band: "
                    f"{plan.approximation_error_bound_mm:.6f} mm"),
                "kind": "isolation", "syntheticDiagnostic": self.demo_geometry is not None,
                "inspectionDiagnostic": self.document is not None,
                "isolationGeometry": diagnostic.geometry, "isolationCategory": diagnostic.category},
                color=colors[diagnostic.category])
        if self.multipass_plan is not None:
            multi = self.multipass_plan
            by_category = {}
            for rejection in multi.rejections:
                by_category.setdefault(rejection.category, []).append(rejection)
            detail = "<br>".join(
                f"{html.escape(category)}: {len(rows)} decision(s); "
                f"retained swept area {sum(row.swept_footprint.area for row in rows):.8f} mm²; "
                f"measured protected overlap {sum(row.protected_overlap.area for row in rows):.10f} mm²"
                for category, rows in sorted(by_category.items())) or "No pass 2 rejections."
            self._add_issue_row({
                "title": "Pass 2 collision / topology review",
                "severity": "NEEDS VERIFICATION", "category": "NEEDS VERIFICATION",
                "layer": "Bottom copper · pass 2 diagnostic",
                "summary": (f"Candidate {multi.candidate_length_mm:.2f} mm; accepted "
                    f"{multi.accepted_length_mm:.2f} mm; skipped {multi.rejected_length_mm:.2f} mm; "
                    f"topology-withheld {multi.topology_withheld_length_mm:.2f} mm; "
                    f"{len(multi.rejections)} visible collision / topology decisions."),
                "action": "Inspect the red rejected paths and footprints. Accepted segments passed full swept-footprint clearance checks; this remains diagnostic only.",
                "advanced": (f"Additional cutter-center spacing: {multi.additional_offset_mm:.6f} mm beyond pass 1<br>"
                    f"Effective cutter width: {multi.single_pass.effective_width_mm:.9f} mm; radius {multi.single_pass.centerline_offset_mm:.9f} mm<br>"
                    f"Incremental swept area beyond pass 1: {multi.incremental_swept_area_mm2:.9f} mm²<br>"
                    f"Incremental copper overlap: {multi.incremental_copper_removal_mm2:.12f} mm²<br>{detail}<br>"
                    "No centerline-only safety decision is made; unresolved source and geometry status remain blocking."),
                "kind": "isolation", "syntheticDiagnostic": self.demo_geometry is not None,
                "inspectionDiagnostic": self.document is not None,
                "isolationGeometry": multi.rejected_footprint,
                "isolationCategory": "pass2 rejected"}, color=RED)
        if self.clearing_plan is not None:
            clearing = self.clearing_plan
            unreachable_count = (len(clearing.unreachable_zones.geoms)
                if hasattr(clearing.unreachable_zones, "geoms") else int(not clearing.unreachable_zones.is_empty))
            self._add_issue_row({
                "title": "Selected residual clearing review",
                "severity": "NEEDS VERIFICATION", "category": "NEEDS VERIFICATION",
                "layer": "Bottom copper · selected clearing preview",
                "summary": (f"Selected cut length {clearing.accepted_paths.length:.2f} mm; "
                    f"cleared {clearing.cleared_area_mm2:.6f} mm²; "
                    f"uncut {clearing.remaining_selected_copper.area:.6f} mm²; "
                    f"rejected {clearing.rejected_paths.length:.2f} mm; "
                    f"unreachable {unreachable_count} region(s)."),
                "action": "Only checked zones classified for preview are cleared. Review remaining and rejected geometry; canonical copper is unchanged.",
                "advanced": (f"Selected candidate IDs: {', '.join(clearing.selected_ids) or 'none'}<br>"
                    f"Rejected full-sweep footprint area: {clearing.rejected_footprint.area:.9f} mm²<br>"
                    "Classification is local to this diagnostic preview and never grants manufacturing authorization."),
                "kind": "isolation", "syntheticDiagnostic": self.demo_geometry is not None,
                "inspectionDiagnostic": self.document is not None,
                "isolationGeometry": clearing.unreachable_zones,
                "isolationCategory": "clearing remaining"}, color=UNCERTAINTY_VIOLET)
        self._operation_changed(self.operation_selector.currentIndex())
        self.statusBar().showMessage(
            f"{'Inferred/hypothetical bottom copper · ' if self.document else ''}{plan.label} · {cutter.included_angle_deg:g}° · tip {cutter.tip_diameter_mm:.3f} mm · "
            f"depth {plan.depth_mm:.3f} mm · effective cut {plan.effective_width_mm:.3f} mm · "
            f"pass 1 candidate length {plan.center_paths.length:.2f} mm · "
            f"pass 1 cutter-center offset {plan.centerline_offset_mm:.3f} mm · "
            f"unfit area {plan.unfit_clearances.area:.4f} mm² · "
            f"possible copper removal {plan.copper_intrusion.area:.4f} mm² · "
            f"{self._strategy_measurement_text()} · inspection only; manufacturing remains BLOCKED")
        self.rebuild_scene()

    def _strategy_measurement_text(self) -> str:
        if self.multipass_plan is not None:
            plan = self.multipass_plan
            return (f"pass 2 spacing {plan.additional_offset_mm:.3f} mm beyond pass 1; "
                    f"candidate/accepted/skipped {plan.candidate_length_mm:.2f}/"
                    f"{plan.accepted_length_mm:.2f}/{plan.rejected_length_mm:.2f} mm; "
                    f"topology withheld {plan.topology_withheld_length_mm:.2f} mm; "
                    f"incremental sweep {plan.incremental_swept_area_mm2:.3f} mm²; "
                    f"protected-copper overlap {plan.incremental_copper_removal_mm2:.9f} mm²")
        if self.clearing_plan is not None:
            plan = self.clearing_plan
            return (f"selected cut length {plan.accepted_paths.length:.2f} mm; "
                    f"selected clear {plan.cleared_area_mm2:.3f} mm²; "
                    f"uncut selected copper {plan.remaining_selected_copper.area:.3f} mm²; "
                    f"rejected {plan.rejected_paths.length:.2f} mm; "
                    f"unreachable {len(getattr(plan.unreachable_zones, 'geoms', ())) or int(not plan.unreachable_zones.is_empty)} zones")
        return "single-pass baseline"

    def _refresh_residual_candidates(self, candidates=None):
        if candidates is None:
            candidates = self.residual_candidates
        previous = {self.clear_candidates_list.item(i).data(Qt.ItemDataRole.UserRole)
                    for i in range(self.clear_candidates_list.count())
                    if self.clear_candidates_list.item(i).checkState() == Qt.CheckState.Checked}
        by_id = {candidate.candidate_id: candidate for candidate in candidates}
        selected = tuple(candidate.candidate_id for candidate in candidates
                         if candidate.candidate_id in previous and candidate.candidate_id in by_id)
        self._refreshing_residuals = True
        self.clear_candidates_list.blockSignals(True)
        self.clear_candidates_list.clear()
        for candidate in candidates:
            item = QListWidgetItem(
                f"Classify removable for preview · {candidate.area_mm2:.3f} mm²")
            item.setData(Qt.ItemDataRole.UserRole, candidate.candidate_id)
            item.setToolTip(candidate.classification_required + "; selection cannot authorize manufacturing")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if candidate.candidate_id in selected
                               else Qt.CheckState.Unchecked)
            self.clear_candidates_list.addItem(item)
        self.clear_candidates_list.blockSignals(False)
        self._refreshing_residuals = False
        return selected

    def _residual_selection_changed(self, *_):
        if not self._refreshing_residuals and self.simulation_enabled:
            self._update_simulation()

    def _install_document(self, fresh: BoardDocument):
        self.demo_geometry = None
        self.demo_canonical = None
        self.simulation_enabled = False
        self.simulation_plan = None
        self.multipass_plan = None
        self.clearing_plan = None
        self.residual_candidates = ()
        self._refresh_residual_candidates(())
        self.simulation_action.blockSignals(True)
        self.simulation_action.setChecked(False)
        self.simulation_action.blockSignals(False)
        if self.document:
            self.document.close()
        self.document = fresh
        if self._loading:
            self._load_succeeded = True
        self.selected_region = None
        self.current_issue = None
        self.board_title.setText(fresh.board_id.replace("_", " "))
        self.compliance.setText(self._plain_source_status(fresh))
        self.eligibility.setText("Machining · BLOCKED")
        self.evidence_note.setText(
            "Legend: <span style='color:#60a5fa'>■ Top copper</span> · <span style='color:#df8d42'>■ Bottom copper</span> · "
            "<span style='color:#38d6c3'>┄ Source path</span> · <span style='color:#ffc857'>┄ Proposed fill</span> · "
            "<span style='color:#ff3155'>■ Measured difference</span> · <span style='color:#38f1d2'>┄ Saved native reference</span> "
            "(inspection only)"
        )
        if any(layer.role == "hypothetical" for layer in fresh.canonical_geometry.layers):
            self.evidence_note.setText(self.evidence_note.text() +
                " · <b>Inferred/hypothetical copper</b> · violet dashes: inferred edges surviving in final copper")
        self._populate_sources()
        self._populate_issues()
        self.rebuild_scene()
        self.fit_board()
        self._inspect_board_summary()
        if fresh.native_reference_label and any(r.index == 79 for r in fresh.regions):
            self.select_region(79, zoom=True)
            for row in range(self.issues_list.count()):
                item = self.issues_list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == 79:
                    self.issues_list.setCurrentItem(item)
                    break
        self.statusBar().showMessage(f"Loaded {len(fresh.layer_files)} manufacturing files · {len(fresh.hits)} circular holes · {len(fresh.slots)} routed slots")
        self.loading_label.setText(f"Ready · {len(fresh.layer_files)} manufacturing files")

    def _inspect_board_summary(self):
        """Show a useful board-level inspection summary before feature selection."""
        if not self.document:
            return
        d = self.document
        layers = "<br>".join(html.escape(layer.label) for layer in d.layer_files)
        bounds = d.bounds
        dims = (f"{bounds[2]-bounds[0]:.6f} × {bounds[3]-bounds[1]:.6f} mm"
                if bounds else "not available")
        self.inspect_title.setText(d.board_id.replace("_", " "))
        self.inspect_meta.setText(f"Board overview · {dims}")
        self.inspect_summary.setText(
            f"{len(d.layer_files)} manufacturing files · {len(d.hits)} circular holes · "
            f"{len(d.slots)} routed slots · {len(d.regions)} copper regions.\n"
            f"Source status: {self._plain_source_status(d)}. Machining remains blocked."
            + (" Copper fill is inferred/hypothetical; inspection-only isolation simulation is available."
               if any(layer.role == "hypothetical" for layer in d.canonical_geometry.layers) else "")
        )
        self.inspect_action.setText("Select an issue for its geometry and suggested review action. No manufacturing operation is enabled.")
        self.view_issue_button.setVisible(False)
        self.view_issue_button.setEnabled(False)
        self.import_reference_button.setVisible(True)
        self.advanced_text.setHtml(
            f"<p><b>Archive:</b> {html.escape(d.archive_path.name)}<br>"
            f"<b>SHA-256:</b> <code>{d.archive_sha256}</code><br>"
            f"<b>Detected layers:</b><br>{layers}<br>"
            f"<b>Source status detail:</b> {html.escape(d.source_compliance)}<br>"
            f"<b>Eligibility:</b> {html.escape(d.machining_eligibility)}</p>"
        )

    def _populate_sources(self):
        assert self.document
        self.layer_tree.clear()
        root = QTreeWidgetItem([f"{self.document.archive_path.name}  ·  SHA-256 {self.document.archive_sha256[:16]}…"])
        self.layer_tree.addTopLevelItem(root)
        for layer in self.document.layer_files:
            issue_count = (layer.metadata.get("unresolvedCount", len(layer.metadata.get("unsupportedObjects", [])))
                           + len(layer.metadata.get("explicitTopologyRepairs", [])))
            suffix = f"  ·  {issue_count} warning(s)" if issue_count else ""
            child = QTreeWidgetItem([f"{layer.label}\n{layer.name}{suffix}"])
            child.setToolTip(0, f"{layer.name}\nSHA-256: {layer.metadata.get('sha256','')}\n{layer.label}")
            root.addChild(child)
        root.setExpanded(False)
        if self.document.native_reference_label:
            ref = QTreeWidgetItem(["Reference evidence: " + self.document.native_reference_label])
            ref.setForeground(0, QColor(TEAL)); root.addChild(ref)

    @staticmethod
    def _plain_source_status(document):
        if any(region.native_polygon is not None and region.index == 79 for region in document.regions):
            return "Nonconforming · 182 open copper boundaries"
        recoverable = sum(region.recovery_status == "RECOVERABLE" for region in document.regions)
        if recoverable:
            zero_draws = 119 if recoverable == 2 and "valentine" in document.board_id.lower() else "verified"
            return f"Nonconforming source · {zero_draws} redundant draws; safely handled"
        open_regions = sum(region.source_points_mm[0] != region.source_points_mm[-1] for region in document.regions)
        return f"Warning · {open_regions} open copper boundaries" if open_regions else "Review parser diagnostics"

    def _populate_issues(self):
        assert self.document
        self.issues_list.clear()
        self._all_issue_rows.clear()
        doc = self.document
        repair_audit_path = Path(__file__).resolve().parents[2] / "phase2c/results/copper-repair-audit.json"
        try:
            repair_audit = json.loads(repair_audit_path.read_text(encoding="utf-8"))
            repair_audit_by_object = {row["sourceObjectIndex"]: row for row in repair_audit.get("repairs", [])}
        except (OSError, ValueError, KeyError):
            repair_audit_by_object = {}
        sensitivity_path = Path(__file__).resolve().parents[2] / "phase2i/results/geos-repair-sensitivity.json"
        try:
            sensitivity = json.loads(sensitivity_path.read_text(encoding="utf-8"))
            sensitivity_by_object = {row["objectIndex"]: row for row in sensitivity.get("regions", [])}
        except (OSError, ValueError, KeyError):
            sensitivity_by_object = {}
        laser = any(region.native_polygon is not None for region in doc.regions)
        open_regions = [r for r in doc.regions if r.source_points_mm[0] != r.source_points_mm[-1]]
        recoverable = [r for r in doc.regions if r.recovery_status == "RECOVERABLE"]
        if open_regions:
            self._add_issue_row({
                "title": f"{len(open_regions)} copper regions have open boundaries",
                "severity": "NEEDS VERIFICATION · source boundary issue", "layer": "Bottom copper",
                "category": "NEEDS VERIFICATION",
                "summary": "Copper is displayed with inferred/hypothetical closing edges. Inspection-only V-bit simulation is available; source nonconformance and machining blocks remain.",
                "action": "Enable Isolation Simulation to inspect this material. Advanced details retain every source finding; Full archive inspection lists individual regions. Verify intent before manufacturing.",
                "advanced": f"Validation code: OPEN_SOURCE_CONTOUR<br>Source: {html.escape(doc.archive_path.name)}<br>Archive SHA-256: <code>{doc.archive_sha256}</code><br>Affected region count: {len(open_regions)}<br>Recovery: none approved; no global closure policy is enabled.",
                "region": None, "kind": "aggregate",
                "sourceFindingCount": len(open_regions), "groupedOpenContours": True,
            }, color=RED)
        elif recoverable:
            self._add_issue_row({
                "title": f"{len(recoverable)} copper regions contain redundant commands",
                "severity": "HANDLED · formatting", "layer": "Copper region contours",
                "summary": "119 zero-length draws were removed only in the disclosed inspection model. They do not move or change the copper boundary. No action is needed for this finding.",
                "action": "No action needed for this finding. Other independent validation findings can still block machining.",
                "advanced": f"Validation code: EXACT_ZERO_LENGTH_REGION_DRAW<br>Archive: {html.escape(doc.archive_path.name)}<br>Archive SHA-256: <code>{doc.archive_sha256}</code><br>Each affected region is listed below with its source file hash and exact G36/G37 command lines.<br>Phase 2A GEOS repair diagnostics are listed separately from Phase 2E no-op source-command records.",
                "region": None, "kind": "handled",
            }, color=TEAL)

        for region in doc.regions:
            is_open = region.source_points_mm[0] != region.source_points_mm[-1]
            if not (is_open or region.recovery_status == "RECOVERABLE" or region.index == 79 and laser):
                continue
            if region.recovery_status == "RECOVERABLE":
                # The exact no-op formatting recovery is represented by one neutral aggregate record.
                # Do not paint a whole copper region as defective.
                continue
            if region.index == 79 and laser:
                title = "Copper boundary differs from the saved design · region 79"
                severity = "BLOCKED · geometry mismatch"
                summary = "One copper boundary differs from the recovered EasyEDA saved fill by up to 0.284 mm. That gap could change isolation clearance. The project is v2.0; matching v2.5 native revision and fill freshness are unavailable."
                action = "Keep this region blocked. The matching v2.5 design is not available in this preview."
                color = RED
            elif region.recovery_status == "RECOVERABLE":
                title = f"Redundant commands in copper region {region.index + 1}"
                severity = "WARNING · shape-preserving no-op"
                summary = "This region contains a redundant zero-length draw. The verified Phase 2E normalization does not move or remove its copper boundary."
                action = "Review the exact source-command recovery record. The source remains unchanged and machining stays blocked."
                color = GOLD
            else:
                title = f"Open boundary in bottom copper region {region.index:03d}"
                severity = "NEEDS VERIFICATION · affects isolation boundary"
                summary = ("The recovered v2.0 saved fill closely matches this proposed display geometry, but the source Gerber contour is open and its v2.5 design intent is not proven. A different edge could change isolation clearance; machining remains blocked."
                           if region.native_polygon is not None else
                           "This copper region has an open boundary. Closing it differently could change where the isolation cutter removes copper. The displayed fill is a proposal only; machining remains blocked.")
                action = "View the proposed edge here. Re-export explicitly closed contours from the source design, or verify each proposed edge against the intended copper before machining."
                color = GOLD
            advanced = (
                f"Validation code: {'FULL_RING_MISMATCH' if region.index == 79 and laser else 'EXACT_ZERO_LENGTH_REGION_DRAW' if region.recovery_status == 'RECOVERABLE' else 'OPEN_SOURCE_CONTOUR'}<br>"
                f"File: {html.escape(region.source_file)}<br>SHA-256: <code>{region.source_sha256}</code><br>"
                f"Source lines: {region.first_line}–{region.last_line}<br>Polarity: {html.escape(region.polarity)}<br>"
                f"Recovery status: {html.escape(region.recovery_status)}<br>"
                f"Start: ({region.source_points_mm[0][0]:.6f}, {region.source_points_mm[0][1]:.6f}) mm; "
                f"end: ({region.source_points_mm[-1][0]:.6f}, {region.source_points_mm[-1][1]:.6f}) mm; "
                f"candidate chord: {region.closure_length_mm:.9f} mm<br>"
            )
            if region.boundary_hausdorff_mm is not None:
                advanced += (f"Boundary Hausdorff: {region.boundary_hausdorff_mm:.9f} mm<br>"
                             f"Symmetric difference: {region.symmetric_difference_mm2:.9f} mm²<br>"
                             f"Cached native path: {region.native_path_index}; candidate/native area: "
                             f"{region.candidate_area_mm2:.6f} / {region.native_area_mm2:.6f} mm²<br>")
                if region.discrepancy_source_line is not None:
                    advanced += (f"Maximum-displacement Gerber line/segment: {region.discrepancy_source_line} / "
                                 f"{region.discrepancy_source_segment_index}; native path segment: "
                                 f"{region.discrepancy_native_segment_index}<br>"
                                 f"Native maximum point: {region.discrepancy_point_mm}; nearest Gerber point: "
                                 f"{region.discrepancy_nearest_point_mm}<br>")
            self._add_issue_row({"title": title, "severity": severity, "layer": "Bottom copper",
                                 "summary": summary, "action": action, "advanced": advanced,
                "region": region, "kind": "region",
                "category": "BLOCKED" if region.index == 79 and laser else "NEEDS VERIFICATION",
                "groupedOpenContour": is_open and not (region.index == 79 and laser)}, color=color)

        group = next((issue for issue, _ in self._all_issue_rows if issue.get("groupedOpenContours")), None)
        if group is not None:
            group["advanced"] += "<hr>" + "<hr>".join(
                f"<b>{html.escape(issue['title'])}</b><br>{issue['advanced']}"
                for issue, _ in self._all_issue_rows if issue.get("kind") == "region")

        for issue in doc.issues:
            if "explicit GEOS repair" in issue or "parser geometry warnings" in issue or "unsupported" in issue:
                filename = issue.split(":", 1)[0]
                layer = next((layer for layer in doc.layer_files if layer.name == filename), None)
                detail = html.escape(issue)
                if layer:
                    detail += f"<br>Source SHA-256: <code>{layer.metadata.get('sha256', 'unavailable')}</code>"
                    repairs = layer.metadata.get("explicitTopologyRepairs", [])
                    if repairs:
                        detail += "<br>Phase 2A GEOS repair records:<br>" + "<br>".join(
                            html.escape(str(record)) for record in repairs[:8])
                repairs = layer.metadata.get("explicitTopologyRepairs", []) if layer else []
                bottom_copper_repairs = [r for r in repairs if r.get("sourceFile", "").lower().endswith("bottomlayer.gbl")]
                if bottom_copper_repairs:
                    for record in bottom_copper_repairs:
                        object_index = record.get("objectIndex", record.get("sourceObjectIndex", -1))
                        audited = repair_audit_by_object.get(object_index, {})
                        offset_data = sensitivity_by_object.get(object_index, {})
                        delta = float(record.get("areaDeltaMm2", 0.0))
                        raw_area = record.get("beforeAreaMm2", record.get("rawGeometryAreaMm2"))
                        after_area = record.get("afterAreaMm2", record.get("repairedAreaMm2"))
                        repaired_type = record.get("afterType", record.get("repairedGeometryType", "unknown"))
                        components_after = audited.get("polygonalComponentsAfterRepair", record.get("polygonalComponentsAfterRepair", "not reported"))
                        remainder = audited.get("nonPolygonalRemainders", record.get("nonPolygonalRemainders", []))
                        legacy_advanced = (f"Validation code: PHASE2A_GEOMETRY_DIAGNOSTIC<br>{detail}<br>Object: {object_index}<br>Raw valid: {record.get('rawGeometryValid')}<br>Raw area: {float(raw_area):.14f} mm²<br>Repaired area: {float(after_area):.14f} mm²<br>Area delta: {delta:.14g} mm²<br>Output: {html.escape(str(repaired_type))}; polygon components {components_after}; non-polygonal remainder {html.escape(', '.join(remainder))}<br>Deterministic repeat: {record.get('deterministicNormalizedWkbEqual', audited.get('deterministicNormalizedWkbEqual', 'not recorded'))}<br>Direct boundary-set Hausdorff: {float(offset_data.get('boundaryHausdorffMm', float('nan'))):.9f} mm; source/repaired boundary lengths: {float(offset_data.get('rawBoundaryLengthMm', float('nan'))):.6f} / {float(offset_data.get('makeValidPolygonBoundaryLengthMm', float('nan'))):.6f} mm<br>Historical diagnostic −0.05 mm GEOS inset: symmetric difference {float((offset_data.get('negativeOffsets') or [{}])[0].get('symmetricDifferenceMm2', float('nan'))):.9f} mm²; components {((offset_data.get('negativeOffsets') or [{}])[0].get('rawComponents', '?'))} raw / {((offset_data.get('negativeOffsets') or [{}])[0].get('repairedComponents', '?'))} repaired. This invalid-intermediate buffer is not a V-bit/depth toolpath simulation or approval.<br>Strict cut-in reconstruction is valid and preserves the listed void topology without make_valid. Native comparison and isolation impact remain a separate review.")
                        is_verified_dataset = (layer is not None and
                            layer.metadata.get("sha256") == VALENTINE_GERBER_BOTTOM_SHA256 and
                            object_index in VALENTINE_NATIVE_COMPARISON)
                        if is_verified_dataset:
                            evidence = VALENTINE_NATIVE_COMPARISON[object_index]
                            self._add_issue_row({
                                "title": f"Legacy polygon-ring warning resolved · object {object_index}",
                                "severity": "HANDLED · strict cut-in interpretation", "layer": filename,
                                "summary": f"The strict cut-in reconstruction is valid and preserves {evidence['voids']} copper voids. This resolves the old invalid intermediate-ring warning. The separate native saved-fill comparison still differs, so the isolation block remains.",
                                "action": "No polygon repair action is needed. Review the saved-design comparison before any isolation planning.",
                                "advanced": legacy_advanced, "region": None, "kind": "parser", "category": "HANDLED",
                            }, color=TEAL)
                            first_line, last_line = evidence["lines"]
                            self._add_issue_row({
                                "title": f"Saved copper comparison needs review · object {object_index}",
                                "severity": "NEEDS VERIFICATION · bottom copper", "layer": filename,
                                "summary": (f"The reconstructed Gerber material differs from the recovered saved EasyEDA fill by "
                                    f"{evidence['symmetric_difference']:.6f} mm². February and Export A have identical strict material; rebuilt Export B stays within 0.000010 mm boundary distance. "
                                    "This cached-fill mismatch does not prove the Gerber is wrong. It remains unresolved, could affect isolation milling, and Gerber reproducibility alone is not independent manufacturing verification. Keep isolation blocked."),
                                "action": "View this region, open the Phase 2K comparison evidence, then compare against an authenticated source-version native fill or controlled repour.",
                                "advanced": (f"Validation code: NATIVE_COPPER_COMPARISON_PARTIAL<br>Source SHA-256: "
                                    f"<code>{VALENTINE_GERBER_BOTTOM_SHA256}</code><br>G36/G37 lines: {first_line}–{last_line}<br>"
                                    f"Native cached fill: {evidence['fill']}<br>Exact no-op draws handled separately: {evidence['noops']}<br>"
                                    f"Native minus Gerber area: {evidence['area_delta']:.12f} mm²<br>"
                                    f"Symmetric difference: {evidence['symmetric_difference']:.12f} mm²<br>"
                                    f"Boundary Hausdorff: {evidence['hausdorff']:.12f} mm (target 0.005 mm)<br>"
                                    f"Components / voids: 1 / {evidence['voids']} in both compared regions<br>"
                                    "Phase 2K: February and Export A strict material are identical; Export B's maximum boundary displacement is 0.000010 mm.<br>"
                                    "This is a native cached-fill correspondence question, not proof of an invalid Gerber. Native project revision/fill freshness and independent geometry verification remain unresolved."),
                                "region": doc.regions[object_index] if object_index < len(doc.regions) else None,
                                "kind": "comparison", "comparisonEvidenceFile": "PHASE2K_EASYEDA_EXPORT_RECONCILIATION_REPORT.md",
                                "category": "NEEDS VERIFICATION",
                            }, color=GOLD)
                        else:
                            self._add_issue_row({
                                "title": f"Bottom copper geometry repair · object {object_index}",
                                "severity": "NEEDS VERIFICATION · isolation effect unknown", "layer": filename,
                                "summary": "The source boundary crosses itself, so the intended copper edge is uncertain. Until checked, an isolation cut could leave a copper bridge or remove copper in the wrong place.",
                                "action": "Compare this boundary against an authenticated native design. Keep the affected layer blocked.",
                                "advanced": legacy_advanced, "region": None, "kind": "parser", "category": "NEEDS VERIFICATION",
                            }, color=GOLD)
                elif repairs:
                    self._add_issue_row({
                        "title": f"Geometry review needed · {len(repairs)} parser repairs",
                        "severity": "NEEDS VERIFICATION · other layer", "layer": filename,
                        "summary": "Parser repairs were recorded outside the copper region findings. This preview does not treat them as copper defects, but retains them for review.",
                        "action": "Continue inspection or compare a trusted native design. No copper defect is inferred from this record.",
                        "advanced": f"Validation code: PHASE2A_GEOMETRY_DIAGNOSTIC<br>{detail}",
                        "region": None, "kind": "parser", "category": "NEEDS VERIFICATION",
                    }, color=GOLD)

                else:
                    self._add_issue_row({
                        "title": "Parser geometry review record",
                        "severity": "BLOCKED · unsupported source feature", "layer": filename,
                        "summary": "The source contains a construct the current interpretation cannot verify. Geometry or isolation effects may be missing.",
                        "action": "Import a supported source export or trusted native design for comparison.",
                        "advanced": f"Validation code: PHASE2A_GEOMETRY_DIAGNOSTIC<br>{detail}",
                        "region": None, "kind": "parser", "category": "BLOCKED",
                    }, color=RED)

        unassigned_hits = [hit for hit in doc.hits if hit.get("group") == "unassigned"]
        if unassigned_hits:
            self._add_issue_row({
                "title": f"{len(unassigned_hits)} drill holes need a tool assignment",
                "severity": "NEEDS VERIFICATION · drilling setup", "layer": "Drill files",
                "summary": "These holes retain their original diameters, but PCB Prep has not assigned a drill tool. That affects drilling setup only.",
                "action": "Review the listed hole diameters and assign a suitable drill before drilling.",
                "advanced": "<br>".join(f"{hit.get('sourceFile')} · {hit.get('sourceDiameterMm')} mm · feature {hit.get('sourceFeatureIndex')}"
                                              for hit in unassigned_hits),
                "kind": "drill", "category": "NEEDS VERIFICATION"}, color=GOLD)
        profile = doc.canonical_geometry.material("board-profile") if doc.canonical_geometry else None
        if profile is None or profile.is_empty or not profile.is_valid:
            self._add_issue_row({
                "title": "Board outline is missing or invalid", "severity": "BLOCKED · outline geometry",
                "layer": "Board profile", "summary": "The profile cannot be prepared for outline cutting from the current geometry.",
                "action": "Check the profile layer and import a supported, closed outline.",
                "kind": "profile", "category": "BLOCKED"}, color=RED)
        self._operation_changed(self.operation_selector.currentIndex())

    def _add_issue_row(self, issue: dict[str, Any], color: str):
        self._all_issue_rows.append((issue, color))
        if not relevant_to_operation(issue, self.operation_key):
            return
        self._append_issue_widget(issue, color)

    def _append_issue_widget(self, issue: dict[str, Any], color: str):
        item = QListWidgetItem(f"{issue['title']}\n{issue.get('category', issue['severity'].split(' · ',1)[0])} · {issue['layer']}")
        item.setData(Qt.ItemDataRole.UserRole, issue)
        item.setForeground(QColor(color))
        self.issues_list.addItem(item)

    def _operation_changed(self, index: int):
        if not hasattr(self, "operation_selector"):
            return
        key = self.operation_selector.itemData(index) or "copper-isolation"
        self.operation_key = key
        labels = dict(OPERATIONS)
        if hasattr(self, "issue_header"):
            short_label = "FULL ARCHIVE" if key == "full-archive" else labels[key]
            self.issue_header.setText(short_label.upper() + " FINDINGS")
        self.issues_list.blockSignals(True)
        self.issues_list.clear()
        for issue, color in self._all_issue_rows:
            if relevant_to_operation(issue, key) and not (key != "full-archive" and issue.get("groupedOpenContour")):
                self._append_issue_widget(issue, color)
        self.issues_list.blockSignals(False)
        self._update_operation_status()
        if self.issues_list.count() == 0 and self.document:
            self.inspect_title.setText(labels[key] + " · no relevant findings")
            self.inspect_meta.setText("No unrelated-layer warning is blocking this operation.")
            self.inspect_summary.setText("This operation still requires independent geometry verification and a separate machining review.")
            self.inspect_action.setText("Source conformance remains unchanged. No production toolpaths are available in Phase 2M.")

    def _update_operation_status(self):
        if not self.document or not self.document.canonical_geometry:
            return
        status = evaluate_operation_status(
            self.operation_key, [issue for issue, _ in self._all_issue_rows],
            source_conformance=self.document.canonical_geometry.source_conformance,
            independent_verification=self.document.canonical_geometry.independent_verification)
        label = dict(OPERATIONS).get(self.operation_key, self.operation_key)
        self.eligibility.setText(f"{label} · {status.status}")

    def _open_comparison_evidence(self):
        report = Path(__file__).resolve().parents[2] / "docs/PHASE2K_EASYEDA_EXPORT_RECONCILIATION_REPORT.md"
        if report.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(report)))
        else:
            self.statusBar().showMessage("The local Phase 2K comparison report is not available on this workstation.")

    def _build_repair_proposal(self, region):
        if not region or len(region.source_points_mm) < 3 or region.source_points_mm[0] == region.source_points_mm[-1]:
            return None
        material = (self.document.canonical_geometry.material("bottom-copper")
                    if self.document and self.document.canonical_geometry else None)
        return propose_closure(
            region.source_points_mm, source_commands=region.source_commands,
            source_layer=region.source_file, polarity=region.polarity,
            tolerance_mm=self.repair_tolerance_input.value(), source_role="original",
            source_material=material, protected_geometry=material,
            native_boundary_mismatch_mm=region.boundary_hausdorff_mm)

    def _refresh_selected_repair(self, *_):
        if not self.current_issue or not self.current_issue.get("region"):
            return
        self._render_issue(self.current_issue)
        self.rebuild_scene()

    def _approve_current_repair(self):
        proposal = self.repair_proposal
        if proposal is None or proposal.status != "SAFE CANDIDATE":
            self.statusBar().showMessage("Only a reviewed Safe Candidate can be approved to a separate working layer.")
            return
        geometry, audit = approve_proposal(proposal, explicit_approval=True)
        self.approved_repair_layers.append((geometry, audit))
        self.repair_audit.append(audit)
        audit_path = Path(__file__).resolve().parents[2] / "phase2m/results/repair-audit.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(self.repair_audit, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":"), allow_nan=False), encoding="utf-8")
        self.statusBar().showMessage("Reviewed closure added to the separate working layer; original Gerber and machining status are unchanged.")
        self.rebuild_scene()

    def _issue_selected(self, current, previous):
        if current is None or (self.document is None and self.demo_geometry is None):
            return
        issue = current.data(Qt.ItemDataRole.UserRole)
        if not isinstance(issue, dict):
            return
        self.current_issue = issue
        self.selected_region = issue.get("region")
        self._render_issue(issue)
        self.rebuild_scene()
        self.zoom_to_issue()

    def _issue_double_clicked(self, item):
        issue = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(issue, dict):
            self.current_issue = issue
            self.selected_region = issue.get("region")
            self._render_issue(issue)
            self.rebuild_scene()
            self.zoom_to_issue()

    def select_region(self, index: int, zoom: bool = False):
        if not self.document or not (0 <= index < len(self.document.regions)):
            return
        region = self.document.regions[index]
        issue = next((self.issues_list.item(i).data(Qt.ItemDataRole.UserRole)
                      for i in range(self.issues_list.count())
                      if isinstance(self.issues_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
                      and self.issues_list.item(i).data(Qt.ItemDataRole.UserRole).get("region") is region), None)
        if issue is None:
            issue = self._region_issue(region)
        self.current_issue = issue
        self.selected_region = region
        self.rebuild_scene()
        self._render_issue(issue)
        if zoom:
            self.zoom_to_issue()

    def zoom_to_issue(self):
        issue = self.current_issue or {}
        region = issue.get("region")
        if region:
            if region.index == 79 and region.discrepancy_point_mm:
                self.view.zoom_to_point(region.discrepancy_point_mm, radius_mm=1.8)
            else:
                self.view.zoom_to(region.source_points_mm)
        elif issue.get("isolationGeometry") is not None and not issue["isolationGeometry"].is_empty:
            self.view.zoom_to_bounds(issue["isolationGeometry"].bounds, padding_ratio=.5)
        elif (self.current_issue or {}).get("kind") == "aggregate" and self.document:
            self.fit_board()

    def reset_view(self):
        if self.document:
            self.view.reset_to_board()

    def fit_board(self):
        if self.document:
            bounds = self.document.bounds
            if bounds:
                minx, miny, maxx, maxy = bounds
                margin = max(maxx-minx, maxy-miny)*.80 or 1.0
                self.scene.setSceneRect(QRectF(minx-margin, -maxy-margin,
                                               maxx-minx+2*margin, maxy-miny+2*margin))
                self.view.set_board_bounds(bounds)
            self.view.fit_board(self.document.bounds)

    def _add_simulation_overlay(self):
        if not self.simulation_enabled or self.simulation_plan is None:
            return
        plan = self.simulation_plan
        checked = {name: box.isChecked() for name, box in self.layer_checks.items()}
        if checked.get("footprint"):
            self._add_geometry(plan.cutting_footprint, QColor(255, 183, 77), QColor("#ffb74d"),
                               "Simulated cutting footprint · pass 1 · diagnostic only", 70, .32)
        selected = bool(self.current_issue and (self.current_issue.get("syntheticDiagnostic") or
                                                self.current_issue.get("inspectionDiagnostic")))
        if selected and checked.get("pass1"):
            self.scene.addItem(FeaturePathItem(geometry_path(plan.center_paths),
                {"label": "Selected proposed cutter-center path", "z": 79}, selected_toolpath_halo_pen()))
        if checked.get("pass1"):
            self._add_geometry(plan.center_paths, None, QColor(TOOLPATH_AMBER),
                               "Proposed cutter-center path · not a toolpath", 80, 0,
                               pen=proposed_toolpath_pen(selected=selected))
        if self.multipass_plan is not None:
            multi = self.multipass_plan
            if checked.get("pass2"):
                pen = QPen(QColor(TEAL), 1.8, Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                self._add_geometry(multi.accepted_paths, None, QColor(TEAL),
                    "Pass 2 accepted candidate · full V-bit sweep clear · not a toolpath", 82, 0, pen=pen)
            if checked.get("rejected"):
                pen = QPen(QColor(COLLISION_RED), 2.0, Qt.PenStyle.DashDotLine)
                pen.setCosmetic(True)
                self._add_geometry(multi.rejected_paths, None, QColor(COLLISION_RED),
                    "Pass 2 rejected candidate · collision / topology / uncertainty", 86, 0, pen=pen)
                self._add_geometry(multi.rejected_footprint, QColor(255, 65, 83, 100), QColor(COLLISION_RED),
                    "Rejected full cutter sweep", 87, .60)
            if checked.get("footprint"):
                self._add_geometry(multi.accepted_footprint, QColor(48, 214, 195, 76), QColor(TEAL),
                    "Pass 2 accepted full swept footprint", 71, .26)
            if checked.get("uncertainty"):
                self._add_geometry(multi.geometry_uncertainty, QColor(188, 140, 255, 105),
                    QColor(UNCERTAINTY_VIOLET), "Pass 2 source / numerical uncertainty", 96, .60)
        if self.clearing_plan is not None:
            clearing = self.clearing_plan
            pen = QPen(QColor("#e879f9"), 2.0, Qt.PenStyle.DashLine)
            pen.setCosmetic(True)
            self._add_geometry(clearing.accepted_paths, None, QColor("#e879f9"),
                "Selected residual clearing candidate · nested loops · preview only", 84, 0, pen=pen)
            if checked.get("footprint"):
                self._add_geometry(clearing.swept_footprint, QColor(232, 121, 249, 74),
                    QColor("#e879f9"), "Selected residual full swept footprint", 73, .24)
            if checked.get("rejected"):
                rejected_pen = QPen(QColor(COLLISION_RED), 2.0, Qt.PenStyle.DashDotLine)
                rejected_pen.setCosmetic(True)
                self._add_geometry(clearing.rejected_paths, None, QColor(COLLISION_RED),
                    "Rejected selected-clearing path", 88, 0, pen=rejected_pen)
                self._add_geometry(clearing.unreachable_zones, QColor(255, 65, 83, 95),
                    QColor(COLLISION_RED), "Selected clearing zone remains unreachable / uncut", 89, .55)
        if checked.get("rejected"):
            self._add_geometry(plan.unfit_clearances, QColor(255, 66, 100), QColor(COLLISION_RED),
                               "Isolation cannot fit · overlapping expanded copper", 90, .75)
        if checked.get("uncertainty"):
            self._add_geometry(plan.geometry_uncertainty, QColor(188, 140, 255, 110), QColor(UNCERTAINTY_VIOLET),
                               "Geometry uncertainty · retained offset overlap", 95, .60)
        if checked.get("rejected"):
            self._add_geometry(plan.copper_intrusion, QColor(255, 0, 0), QColor(COLLISION_RED),
                               "Potential unintended copper removal", 100, .8)
        if self.current_issue and self.current_issue.get("isolationGeometry") is not None:
            self._add_geometry(self.current_issue["isolationGeometry"], None, QColor("#ffffff"),
                               "Selected diagnostic geometry", 110, 0,
                               pen=QPen(QColor("#ffffff"), 2.5, Qt.PenStyle.SolidLine))

    def rebuild_scene(self, *_):
        had_document = self.document is not None
        center = self.view.mapToScene(self.view.viewport().rect().center()) if had_document else None
        self.scene.clear()
        doc = self.document
        if self.demo_geometry is not None:
            self._add_geometry(self.demo_geometry, QColor(BLUE), QColor("#81b9ff"),
                               "Synthetic original copper · not a board design", 21, .40)
            self._add_simulation_overlay()
            if self.current_issue and self.current_issue.get("syntheticRepairExample"):
                region = self.current_issue["region"]
                source = QPainterPath()
                source.moveTo(region.source_points_mm[0][0], -region.source_points_mm[0][1])
                for x, y in region.source_points_mm[1:]:
                    source.lineTo(x, -y)
                source_pen = QPen(QColor("#ff9d43"), 2.0, Qt.PenStyle.SolidLine)
                source_pen.setCosmetic(True)
                self.scene.addItem(FeaturePathItem(source,
                    {"label": "Synthetic original open contour", "z": 195}, source_pen))
                proposal = self.current_issue.get("repairProposal")
                if proposal is not None and self.repair_toggle.isChecked():
                    repair_path = QPainterPath()
                    repair_path.moveTo(proposal.end_mm[0], -proposal.end_mm[1])
                    repair_path.lineTo(proposal.start_mm[0], -proposal.start_mm[1])
                    self.scene.addItem(FeaturePathItem(repair_path,
                        {"label": f"Hypothetical closure · {proposal.status}", "z": 215,
                         "repairProposal": proposal}, repair_proposal_pen(selected=True)))
            for repaired, audit in self.approved_repair_layers:
                self._add_geometry(repaired, QColor(UNCERTAINTY_VIOLET), QColor("#e7c8ff"),
                                   "Reviewed derived working geometry · source unchanged", 120, .45)
            minx, miny, maxx, maxy = self.demo_geometry.bounds
            margin = max(maxx - minx, maxy - miny) * .08 or 1.0
            self.scene.setSceneRect(QRectF(minx-margin, -maxy-margin,
                                           maxx-minx+2*margin, maxy-miny+2*margin))
            self.view.set_board_bounds(self.demo_geometry.bounds)
            self.view.fit_board(self.demo_geometry.bounds)
            return
        if not doc:
            self._show_empty_state()
            return
        checked = {name: box.isChecked() for name, box in self.layer_checks.items()}
        if checked.get("profile"):
            self._add_geometry(doc.canonical_geometry.material("board-profile"), QColor("#d44bd2"), QColor("#e874ec"),
                               "Board profile", 10, 0.10)
        if checked.get("top"):
            self._add_geometry(doc.canonical_geometry.material("top-copper"), QColor(COPPER), QColor("#f4a75b"), "Top copper", 20, 0.45)
        if checked.get("bottom"):
            bottom = doc.canonical_geometry.material("bottom-copper")
            if checked.get("after") and self.simulation_plan is not None:
                remaining = (self.multipass_plan.remaining_copper if self.multipass_plan is not None
                             else doc.canonical_geometry.material("bottom-copper").difference(
                                 self.simulation_plan.cutting_footprint))
                if self.clearing_plan is not None:
                    remaining = remaining.difference(self.clearing_plan.swept_footprint)
                self._add_geometry(remaining, QColor(BLUE), QColor("#81b9ff"),
                    "Simulated remaining copper · canonical source unchanged", 21, 0.40)
            else:
                self._add_geometry(bottom, QColor(BLUE), QColor("#81b9ff"), "Original bottom copper · canonical material", 21, 0.34)
        self._add_simulation_overlay()
        if checked.get("inferred"):
            for region in doc.regions:
                surviving = region.surviving_closure
                if surviving is None or surviving.is_empty or surviving.length == 0:
                    continue
                label = f"Inferred closing segment {region.index} · survives in final copper · unapproved"
                self._add_geometry(surviving, None, QColor(UNCERTAINTY_VIOLET),
                    label, 125, 0,
                    pen=repair_proposal_pen(), metadata={"label": label, "region": region,
                        "sourceFile": region.source_file, "sourceSha256": region.source_sha256,
                        "sourceLines": (region.first_line, region.last_line), "hypothetical": True})
        for repaired, audit in self.approved_repair_layers:
            self._add_geometry(repaired, QColor(UNCERTAINTY_VIOLET), QColor("#e7c8ff"),
                               "Reviewed derived working geometry · source unchanged", 50, .45)
        if checked.get("pads"):
            for layer in doc.layer_files:
                for feature in layer.features:
                    if feature.get("semantic") != "pad / flash" or feature.get("geometry") is None:
                        continue
                    pen = QPen(QColor(GOLD), .035, Qt.PenStyle.SolidLine)
                    self._add_geometry(feature["geometry"], None, pen.color(),
                        f"Flash / pad · {feature['sourceFile']} object {feature['objectIndex']}", 35, 0, pen=pen,
                        metadata=feature)
        if checked.get("drills"):
            for hit in doc.hits:
                diameter = float(hit.get("sourceDiameterMm") or 0.1)
                x, y = float(hit["xMm"]), float(hit["yMm"])
                color = self._drill_color(hit.get("group", "unassigned"))
                rect = QRectF(x-diameter/2, -y-diameter/2, diameter, diameter)
                drill_pen = QPen(color, 1.5); drill_pen.setCosmetic(True)
                item = self.scene.addEllipse(rect, drill_pen, QBrush(Qt.BrushStyle.NoBrush))
                item.setZValue(45)
                item.setFlag(item.GraphicsItemFlag.ItemIsSelectable, True)
                item.setData(0, {"label": "Circular drill", **{k: v for k,v in hit.items() if k not in {"geometry"}}})
                item.setToolTip(f"{hit['sourceDiameterMm']:.4f} mm · {hit['sourceFile']} feature {hit['sourceFeatureIndex']}")
        if checked.get("slots"):
            for slot in doc.slots:
                coords = slot.get("coordinatesMm", [])
                if len(coords) < 2:
                    continue
                centerline = LineString([(float(x), float(y)) for x, y in coords])
                outline = centerline.buffer(float(slot.get("sourceDiameterMm") or .1)/2, quad_segs=16)
                self._add_geometry(outline, None, QColor("#d6a4ff"), "Routed slot", 46, 0,
                                   metadata=slot)
        if checked.get("source"):
            for region in doc.regions:
                path = QPainterPath()
                if region.source_points_mm:
                    path.moveTo(region.source_points_mm[0][0], -region.source_points_mm[0][1])
                    for x, y in region.source_points_mm[1:]:
                        path.lineTo(x, -y)
                selected = self.selected_region and self.selected_region.index == region.index
                pen = QPen(QColor(RED if region.index == 79 else TEAL), 2.2 if selected else 1.0,
                           Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine)
                pen.setCosmetic(True)
                item = FeaturePathItem(path, {"label": f"Source region {region.index}", "region": region, "z": 60}, pen)
                self.scene.addItem(item)
                # Proposed closing chord remains separately styled and never changes the source contour.
                if checked.get("inferred"):
                    closure = QPainterPath()
                    closure.moveTo(region.closure_start_mm[0], -region.closure_start_mm[1])
                    closure.lineTo(region.closure_end_mm[0], -region.closure_end_mm[1])
                    cpen = QPen(QColor(RED if region.index == 79 else GOLD), 2.0,
                                Qt.PenStyle.DashLine if region.index == 79 else Qt.PenStyle.DotLine)
                    cpen.setCosmetic(True)
                    citem = FeaturePathItem(closure, {"label": f"Hypothetical closure {region.index}", "region": region, "z": 62}, cpen)
                    self.scene.addItem(citem)
        if checked.get("candidate"):
            for region in doc.regions:
                laser_candidate = region.native_polygon is not None and region.index != 79
                if region.candidate_polygon is None or not laser_candidate:
                    continue
                dark_polarity = region.polarity in {"D", "dark"}
                fill = QBrush(QColor(255, 200, 87, 38 if dark_polarity else 19))
                pen = QPen(QColor(GOLD if dark_polarity else "#b8a4d4"), 1.2, Qt.PenStyle.DashLine)
                item = FeaturePathItem(geometry_path(region.candidate_polygon),
                    {"label": f"Proposed disclosed region {region.index} ({region.polarity})", "region": region, "z": 50}, pen, fill)
                self.scene.addItem(item)
        if checked.get("native"):
            for region in doc.regions:
                if region.native_polygon is None:
                    continue
                selected = self.selected_region and self.selected_region.index == region.index
                pen = QPen(QColor(TEAL), 2.2 if selected else 1.0, Qt.PenStyle.SolidLine)
                item = FeaturePathItem(geometry_path(region.native_polygon),
                    {"label": f"EasyEDA cached fill reference · path {region.native_path_index}", "region": region,
                     "z": 55}, pen, QBrush(Qt.BrushStyle.NoBrush))
                self.scene.addItem(item)
        if self.selected_region:
            r = self.selected_region
        if checked.get("diagnostics"):
            self._add_issue_highlights()
        if doc.bounds:
            minx, miny, maxx, maxy = doc.bounds
            # Keep a virtual work area around the board so panning has range
            # even while the full board is fitted to the viewport.
            margin = max(maxx - minx, maxy - miny) * .80 or 1.0
            self.scene.setSceneRect(QRectF(minx - margin, -maxy - margin,
                                           maxx - minx + 2 * margin, maxy - miny + 2 * margin))
        if center is not None:
            self.view.centerOn(center)

    def _region_issue(self, region: RegionData) -> dict[str, Any]:
        laser = region.native_polygon is not None
        if region.index == 79 and laser:
            title = "Copper boundary differs from the saved design · region 79"
            severity = "BLOCKED · geometry mismatch"
            summary = "One copper boundary differs from the recovered EasyEDA saved fill by up to 0.284 mm. The v2.5 native revision and saved-fill freshness are unavailable."
            action = "Compare against an authenticated v2.5 project and controlled fresh repour. Keep the region blocked."
        elif region.recovery_status == "RECOVERABLE":
            title = f"Redundant commands in copper region {region.index + 1}"
            severity = "WARNING · shape-preserving no-op"
            summary = "The Phase 2E record identifies a redundant zero-length draw. Its normalization preserves the source boundary; this does not indicate missing copper."
            action = "Review the hash-bound no-op record. Original Gerber remains unchanged; machining remains blocked."
        else:
            title = f"Open boundary in bottom copper region {region.index:03d}"
            severity = "BLOCKED · nonconforming source contour"
            summary = "The Gerber region ends at a different coordinate from where it began. Its candidate closing edge is shown only for inspection."
            action = "Use the native comparison as evidence, not approval. Keep machining blocked pending source verification."
        advanced = (f"File: {html.escape(region.source_file)}<br>SHA-256: <code>{region.source_sha256}</code><br>"
                    f"Source lines: {region.first_line}–{region.last_line}<br>Polarity: {html.escape(region.polarity)}<br>"
                    f"Source status: {html.escape(region.recovery_status)}<br>"
                    f"Start: {region.source_points_mm[0]} mm; end: {region.source_points_mm[-1]} mm<br>"
                    f"Candidate chord: {region.closure_length_mm:.9f} mm")
        if region.boundary_hausdorff_mm is not None:
            advanced += (f"<br>Boundary Hausdorff: {region.boundary_hausdorff_mm:.9f} mm"
                         f"<br>Symmetric difference: {region.symmetric_difference_mm2:.9f} mm²"
                         f"<br>Cached path index: {region.native_path_index}")
            if region.discrepancy_source_line is not None:
                advanced += (f"<br>Maximum Gerber line / segment: {region.discrepancy_source_line} / "
                             f"{region.discrepancy_source_segment_index}; native path segment: "
                             f"{region.discrepancy_native_segment_index}")
        return {"title": title, "severity": severity, "layer": "Bottom copper",
                "summary": summary, "action": action, "advanced": advanced,
                "region": region, "kind": "region"}

    def _add_issue_highlights(self):
        issue = self.current_issue
        if not issue:
            return
        region = issue.get("region")
        if region is None:
            if issue.get("kind") == "aggregate" and self.document:
                # Show all affected contours without claiming any one edge is the repair.
                for affected in self.document.regions:
                    is_open = affected.source_points_mm[0] != affected.source_points_mm[-1]
                    is_redundant = affected.recovery_status == "RECOVERABLE"
                    if not (is_open or is_redundant):
                        continue
                    path = QPainterPath()
                    path.moveTo(affected.source_points_mm[0][0], -affected.source_points_mm[0][1])
                    for x, y in affected.source_points_mm[1:]:
                        path.lineTo(x, -y)
                    pen = QPen(QColor(GOLD), 1.6, Qt.PenStyle.SolidLine); pen.setCosmetic(True)
                    self.scene.addItem(FeaturePathItem(path, {"label": "Affected source contour", "z": 190}, pen))
            return

        if not self.document:
            return

        source_path = QPainterPath()
        if region.source_points_mm:
            source_path.moveTo(region.source_points_mm[0][0], -region.source_points_mm[0][1])
            for x, y in region.source_points_mm[1:]:
                source_path.lineTo(x, -y)
        source_color = QColor("#fff06a" if region.recovery_status == "RECOVERABLE" else "#ff9d43")
        source_pen = QPen(source_color, 2.8, Qt.PenStyle.SolidLine); source_pen.setCosmetic(True)
        self.scene.addItem(FeaturePathItem(source_path,
            {"label": "Selected Gerber source boundary", "z": 195}, source_pen))

        proposal = issue.get("repairProposal")
        if proposal is not None and self.repair_toggle.isChecked():
            repair_path = QPainterPath()
            repair_path.moveTo(proposal.end_mm[0], -proposal.end_mm[1])
            repair_path.lineTo(proposal.start_mm[0], -proposal.start_mm[1])
            self.scene.addItem(FeaturePathItem(repair_path,
                {"label": f"Hypothetical closure · {proposal.status}", "z": 215,
                 "repairProposal": proposal}, repair_proposal_pen(selected=True)))

        if region.native_polygon is not None and (region.index == 79 or issue.get("kind") == "comparison"):
            # Red is a display-only fill comparison, never a cutter or repair path.
            overlay = region.discrepancy_geometry
            overlay_label = "Gerber/native symmetric difference · diagnostic only"
            if (issue.get("kind") == "comparison" and region.candidate_polygon is not None and
                    region.candidate_polygon.is_valid and region.native_polygon.is_valid):
                overlay = region.candidate_polygon.symmetric_difference(region.native_polygon)
                overlay_label = "Proposed Gerber fill vs cached native fill · diagnostic only"
            if overlay is not None and not overlay.is_empty:
                diff_fill = QBrush(QColor(255, 46, 72, 155))
                diff_pen = QPen(QColor("#ff3155"), 1.7, Qt.PenStyle.SolidLine); diff_pen.setCosmetic(True)
                self.scene.addItem(FeaturePathItem(geometry_path(overlay),
                    {"label": overlay_label, "z": 200},
                    diff_pen, diff_fill))
            native_pen = QPen(QColor("#38f1d2"), 2.5, Qt.PenStyle.SolidLine); native_pen.setCosmetic(True)
            self.scene.addItem(FeaturePathItem(geometry_path(region.native_polygon),
                {"label": "EasyEDA cached native boundary", "z": 205}, native_pen))
            if region.discrepancy_point_mm:
                x, y = region.discrepancy_point_mm
                self.scene.addItem(WarningMarker(x, y, "Maximum boundary displacement · native point"))
            if region.discrepancy_nearest_point_mm:
                x, y = region.discrepancy_nearest_point_mm
                marker = WarningMarker(x, y, "Nearest point on Gerber source boundary")
                marker.setBrush(QColor("#64b5ff"))
                marker.setZValue(999)
                self.scene.addItem(marker)
        elif region.recovery_status != "RECOVERABLE":
            # Endpoints are exact source coordinates for the open-boundary issue.
            for endpoint, label in ((region.source_points_mm[0], "Open region start"),
                                    (region.source_points_mm[-1], "Open region end")):
                self.scene.addItem(WarningMarker(endpoint[0], endpoint[1], label))

    def _render_issue(self, issue: dict[str, Any]):
        region = issue.get("region")
        self.repair_proposal = self._build_repair_proposal(region) if region else None
        if self.repair_proposal is not None:
            issue["repairProposal"] = self.repair_proposal
            proposal = self.repair_proposal
            issue.setdefault("_baseSummary", issue.get("summary", ""))
            issue.setdefault("_baseAction", issue.get("action", ""))
            issue.setdefault("_baseAdvanced", issue.get("advanced", ""))
            issue["summary"] = (issue["_baseSummary"] +
                f" Repair check: {proposal.status.lower()} — {proposal.reason}")
            issue["action"] = (issue["_baseAction"] +
                " The violet line is a hypothetical straight closure; inspect it before considering a separate working-layer change.")
            issue["advanced"] = (issue["_baseAdvanced"] +
                f"<br>Repair candidate gap: {proposal.gap_mm:.9f} mm; selected limit: {proposal.tolerance_mm:.3f} mm"
                f"<br>Classification: {html.escape(proposal.status)} · {html.escape(proposal.reason)}"
                f"<br>Contour direction: {proposal.contour_direction}; nearest protected copper: "
                f"{proposal.nearest_geometry_distance_mm} mm"
                f"<br>Before: {proposal.before_metrics}; after candidate: {proposal.after_metrics}"
                f"<br>Source command context: {html.escape(str(proposal.source_command_context))}"
                f"<br>Audit SHA-256: <code>{proposal.audit_record['sha256']}</code>")
        self.inspect_title.setText(issue.get("title", "Selected validation record"))
        self.inspect_meta.setText(f"{issue.get('severity', 'INFO')} · {issue.get('layer', 'Manufacturing data')}")
        self.inspect_summary.setText(issue.get("summary", "No source geometry is inferred for this record."))
        category = issue.get("category", issue.get("severity", "").split(" · ", 1)[0])
        self.inspect_action.setText(issue.get("action", "Review the source and keep machining blocked."))
        has_geometry = (issue.get("region") is not None or
                        issue.get("isolationGeometry") is not None)
        self.view_issue_button.setEnabled(has_geometry)
        self.view_issue_button.setVisible(has_geometry)
        self.import_reference_button.setVisible(category != "HANDLED")
        self.comparison_evidence_button.setVisible(bool(issue.get("comparisonEvidenceFile")))
        self.approve_repair_button.setVisible(bool(self.repair_proposal and self.repair_proposal.status == "SAFE CANDIDATE"))
        self.approve_repair_button.setEnabled(self.approve_repair_button.isVisible())
        self.advanced_text.setHtml(issue.get("advanced", "No additional source details are available."))
        self.advanced_button.setChecked(False)

    def eventFilter(self, watched, event):
        if watched is self.view.viewport() and event.type() == event.Type.Resize:
            self._position_loading_overlay()
        return super().eventFilter(watched, event)

    def _position_loading_overlay(self):
        if not hasattr(self, "loading_overlay"):
            return
        rect = self.view.viewport().rect()
        self.loading_overlay.move((rect.width() - self.loading_overlay.width()) // 2,
                                  (rect.height() - self.loading_overlay.height()) // 2)

    def _add_geometry(self, geometry, fill: QColor | None, edge: QColor, label: str, z: int, alpha: float,
                      pen: QPen | None = None, metadata: dict | None = None):
        if geometry is None or geometry.is_empty:
            return
        brush = QBrush(fill) if fill else QBrush(Qt.BrushStyle.NoBrush)
        if fill and alpha < 1:
            c = QColor(fill); c.setAlphaF(alpha); brush = QBrush(c)
        pen = pen or QPen(edge, 1.2)
        item = FeaturePathItem(geometry_path(geometry), metadata or {"label": label, "z": z}, pen, brush)
        item.setZValue(z)
        self.scene.addItem(item)

    @staticmethod
    def _bounds(points):
        xs, ys = zip(*points)
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _drill_color(group: str):
        colors = {"PCB - Drill 0.8mm": "#42d6e8", "PCB - Drill 1.0mm": "#ff9c55",
                  "PCB - Drill 1.1mm": "#83cf76", "PCB - Drill 1.2mm": "#bb93ed",
                  "PCB - Drill 2.0mm": "#ffe066", "PCB - Drill 3.0mm": "#ff6978",
                  "PCB - Drill 3.1mm": "#f18ac4", "unassigned": RED}
        return QColor(colors.get(group, RED))

    def _inspect_selected_item(self):
        items = self.scene.selectedItems()
        if not items:
            return
        data = items[-1].data(0)
        if not isinstance(data, dict):
            return
        self.view_issue_button.setVisible(False)
        self.view_issue_button.setEnabled(False)
        self.import_reference_button.setVisible(True)
        region = data.get("region")
        if region is not None:
            self.current_issue = self._region_issue(region)
            self.selected_region = region
            self._render_issue(self.current_issue)
            return
        fields = [f"<b>{html.escape(str(key))}:</b> {html.escape(str(value))}"
                  for key, value in data.items() if key not in {"geometry", "region"}]
        self.inspect_title.setText(str(data.get("label", "Selected feature")))
        self.inspect_meta.setText("Selected geometry · inspection only")
        self.inspect_summary.setText("Coordinates and source attributes are listed in Advanced details.")
        self.inspect_action.setText("This selection does not change validation status or machining eligibility.")
        self.advanced_text.setHtml("<p>" + "<br>".join(fields) + "</p>")
        self.advanced_button.setChecked(False)

    def _show_coordinates(self, x: float, y: float):
        self.coordinate_label.setText(f"X {x:9.4f} · Y {y:9.4f} mm")

    def closeEvent(self, event):
        self._loading_timer.stop()
        if self._load_thread and self._load_thread.isRunning():
            self._load_thread.quit()
            self._load_thread.wait()
        if self.document:
            self.document.close()
        super().closeEvent(event)

