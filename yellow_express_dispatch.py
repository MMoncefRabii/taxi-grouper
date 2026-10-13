"""PySide6 desktop UI for Taxi Grouper - Yellow Express Dispatch."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.config import TAXI_COLUMN, UNKNOWN_ZONE
from src.adapters.exporter import export_like_historique
from src.core.grouper import group_agents, validate_dispatch
from src.core.ml_model import train_model_from_historique_excel
from src.core.preprocessing import detect_columns, filter_dataframe, load_dispatch_excel


APP_TITLE = "Taxi Grouper - Yellow Express Dispatch"


class YellowExpressDispatch(QMainWindow):
    """Desktop dashboard shell connected to the Taxi Grouper backend."""

    def __init__(self) -> None:
        super().__init__()
        self.selected_file: Path | None = None
        self.imported_df: pd.DataFrame | None = None
        self.grouped_df: pd.DataFrame | None = None
        self.grouping_warnings: list[str] = []
        self.training_file: Path | None = None
        self.setWindowTitle(APP_TITLE)
        self.resize(1200, 750)
        self.setMinimumSize(1000, 650)
        self.setAcceptDrops(True)
        self._build_ui()

    def _build_ui(self) -> None:
        self.setStyleSheet(STYLESHEET)
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_sidebar())
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_main_area())
        self.pages.addWidget(self._build_training_page())
        body_layout.addWidget(self.pages, stretch=1)

        root_layout.addWidget(body, stretch=1)
        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(28, 18, 28, 16)

        brand_box = QVBoxLayout()
        brand = QLabel("YELLOW EXPRESS")
        brand.setObjectName("Brand")
        tagline = QLabel("Automatic Taxi Dispatch System")
        tagline.setObjectName("Tagline")
        brand_box.addWidget(brand)
        brand_box.addWidget(tagline)

        contacts = QLabel("93 92 1 600    98 966 423    contact@yellowexpress.tn")
        contacts.setObjectName("Contacts")
        contacts.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout.addLayout(brand_box)
        layout.addStretch()
        layout.addWidget(contacts)
        return header

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(230)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 28, 16, 18)
        layout.setSpacing(12)

        self.nav_buttons: list[QPushButton] = []
        for index, label in enumerate(["Dashboard", "Import Excel", "Dispatch", "Results", "Training", "Settings"]):
            button = QPushButton(label)
            button.setObjectName("NavButtonActive" if index == 0 else "NavButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setCheckable(True)
            button.setChecked(index == 0)
            button.clicked.connect(lambda checked=False, idx=index: self._set_page(idx))
            self.nav_buttons.append(button)
            layout.addWidget(button)

        layout.addStretch()
        footer = QLabel("Desktop dispatch\nRule-based grouping active")
        footer.setObjectName("SidebarFooter")
        layout.addWidget(footer)
        return sidebar

    def _set_page(self, index: int) -> None:
        target_page = 1 if index == 4 else 0
        self.pages.setCurrentIndex(target_page)
        for button_index, button in enumerate(self.nav_buttons):
            is_active = button_index == index
            button.setChecked(is_active)
            button.setObjectName("NavButtonActive" if is_active else "NavButton")
            button.style().unpolish(button)
            button.style().polish(button)

    def _build_main_area(self) -> QWidget:
        main = QWidget()
        main.setObjectName("Main")
        layout = QVBoxLayout(main)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        title = QLabel("Taxi Dispatch Dashboard")
        title.setObjectName("PageTitle")
        subtitle = QLabel("Configure your dispatch operation and generate automatic taxi groups.")
        subtitle.setObjectName("PageSubtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        content = QHBoxLayout()
        content.setSpacing(22)
        content.addWidget(self._build_config_card(), stretch=5)
        content.addWidget(self._build_results_panel(), stretch=4)
        layout.addLayout(content, stretch=1)
        return main

    def _build_training_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("Main")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(22)

        title = QLabel("Train Dispatch Model")
        title.setObjectName("PageTitle")
        description = QLabel("Upload a historical Excel file using the same structure as Historique.xlsx so the system can learn from real taxi groupings.")
        description.setObjectName("PageSubtitle")
        description.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(description)

        card = QFrame()
        card.setObjectName("Card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(26, 24, 26, 24)
        card_layout.setSpacing(18)

        self.training_file_label = QLabel("No historical file selected")
        self.training_file_label.setObjectName("FileName")

        select_button = QPushButton("Select Historical Excel File")
        select_button.setObjectName("SecondaryButton")
        select_button.setCursor(Qt.PointingHandCursor)
        select_button.clicked.connect(self._choose_training_file)

        self.train_button = QPushButton("TRAIN MODEL")
        self.train_button.setObjectName("PrimaryButton")
        self.train_button.setCursor(Qt.PointingHandCursor)
        self.train_button.clicked.connect(self._run_training)

        card_layout.addWidget(select_button, alignment=Qt.AlignLeft)
        card_layout.addWidget(self.training_file_label)
        card_layout.addWidget(self.train_button)

        self.training_metrics_grid = QGridLayout()
        self.training_metrics_grid.setSpacing(12)
        card_layout.addLayout(self.training_metrics_grid)
        card_layout.addStretch()

        layout.addWidget(card, stretch=1)
        return page

    def _build_config_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(26, 24, 26, 24)
        layout.setSpacing(18)

        card_title = QLabel("Dispatch Configuration")
        card_title.setObjectName("CardTitle")
        layout.addWidget(card_title)

        layout.addWidget(self._field_label("Dispatch Type"))
        segmented = QHBoxLayout()
        self.ramassage_button = QPushButton("Ramassage")
        self.retour_button = QPushButton("Retour")
        for button in (self.ramassage_button, self.retour_button):
            button.setObjectName("SegmentButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            segmented.addWidget(button)
        self.dispatch_type_group = QButtonGroup(self)
        self.dispatch_type_group.setExclusive(True)
        self.dispatch_type_group.addButton(self.ramassage_button)
        self.dispatch_type_group.addButton(self.retour_button)
        self.ramassage_button.setChecked(True)
        layout.addLayout(segmented)

        self.location_combo = self._combo(["Lac 2", "Charguia", "Kram", "Alain Savary"])
        layout.addWidget(self._field_label("Call Center Location"))
        layout.addWidget(self.location_combo)

        self.time_combo = self._combo(["07:00", "17:30", "22:30"])
        layout.addWidget(self._field_label("Dispatch Time"))
        layout.addWidget(self.time_combo)

        layout.addWidget(self._build_import_box())
        layout.addStretch()

        self.dispatch_button = QPushButton("DISPATCH AUTOMATICALLY")
        self.dispatch_button.setObjectName("PrimaryButton")
        self.dispatch_button.setCursor(Qt.PointingHandCursor)
        self.dispatch_button.clicked.connect(self._run_dispatch)
        layout.addWidget(self.dispatch_button)
        return card

    def _build_import_box(self) -> QWidget:
        box = QFrame()
        box.setObjectName("UploadBox")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(8)

        title = QLabel("Import Excel File")
        title.setObjectName("UploadTitle")
        hint = QLabel("Drag or select your agent list file")
        hint.setObjectName("MutedText")
        formats = QLabel("Supported formats: .xlsx, .xls, .ods")
        formats.setObjectName("MutedText")
        self.file_label = QLabel("No file selected")
        self.file_label.setObjectName("FileName")
        self.file_status_label = QLabel("Click Browse or drop a spreadsheet file here.")
        self.file_status_label.setObjectName("MutedText")

        choose_button = QPushButton("Browse")
        choose_button.setObjectName("SecondaryButton")
        choose_button.setCursor(Qt.PointingHandCursor)
        choose_button.clicked.connect(self._choose_file)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(choose_button)
        buttons.addStretch()

        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(formats)
        layout.addSpacing(8)
        layout.addLayout(buttons)
        layout.addWidget(self.file_label)
        layout.addWidget(self.file_status_label)
        box.setCursor(Qt.PointingHandCursor)
        box.mousePressEvent = lambda event: self._choose_file()
        return box

    def _build_results_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Dispatch Results")
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        self.empty_results = QLabel("No dispatch generated yet.")
        self.empty_results.setObjectName("EmptyState")
        self.empty_results.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_results, stretch=1)

        self.summary_grid = QGridLayout()
        self.summary_grid.setSpacing(12)
        self.summary_container = QWidget()
        self.summary_container.setLayout(self.summary_grid)
        self.summary_container.hide()
        layout.addWidget(self.summary_container)

        self.results_table = QTableWidget(0, 6)
        self.results_table.setObjectName("ResultsTable")
        self.results_table.setHorizontalHeaderLabels(["Taxi", "Matricule", "Nom - Prenom", "Adresse", "Zone", "Heure"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.setShowGrid(False)
        self.results_table.hide()
        layout.addWidget(self.results_table, stretch=1)

        self.export_button = QPushButton("Export Excel")
        self.export_button.setObjectName("ExportButton")
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.clicked.connect(self._export_dispatched_excel)
        self.export_button.hide()
        layout.addWidget(self.export_button, alignment=Qt.AlignRight)
        return panel

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _combo(self, values: list[str]) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName("InputCombo")
        combo.addItems(values)
        combo.setCursor(Qt.PointingHandCursor)
        return combo

    def _choose_file(self) -> None:
        dialog = QFileDialog(self, "Choose Excel File")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Spreadsheet Files (*.xlsx *.xls *.ods)")
        dialog.setDirectory(self._desktop_directory())
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        selected = dialog.selectedFiles()
        path = selected[0] if selected else ""
        if not path:
            return
        self._import_excel(Path(path))

    def _choose_training_file(self) -> None:
        dialog = QFileDialog(self, "Select Historical Excel File")
        dialog.setFileMode(QFileDialog.ExistingFile)
        dialog.setNameFilter("Spreadsheet Files (*.xlsx *.xls *.ods)")
        dialog.setDirectory(self._desktop_directory())
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        selected = dialog.selectedFiles()
        if not selected:
            return
        self.training_file = Path(selected[0])
        self.training_file_label.setText(self.training_file.name)

    def _run_training(self) -> None:
        if self.training_file is None:
            QMessageBox.warning(self, "Training", "Please select Historique.xlsx first.")
            return
        self.train_button.setEnabled(False)
        self.train_button.setText("TRAINING...")
        QApplication.processEvents()
        try:
            report = train_model_from_historique_excel(str(self.training_file), "models")
        except Exception as exc:
            self.train_button.setEnabled(True)
            self.train_button.setText("TRAIN MODEL")
            QMessageBox.critical(self, "Training Error", f"Could not train the model.\n\n{exc}")
            return
        self.train_button.setEnabled(True)
        self.train_button.setText("TRAIN MODEL")
        self._show_training_metrics(report)
        QMessageBox.information(self, "Training Complete", "Model trained and saved to models/taxi_grouping_model.pkl")

    def _show_training_metrics(self, report: dict) -> None:
        while self.training_metrics_grid.count():
            item = self.training_metrics_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        cards = [
            (str(report.get("number_of_agents", 0)), "Agents"),
            (str(report.get("number_of_pair_examples", 0)), "Pair Examples"),
            (str(report.get("positive_pairs", 0)), "Positive Pairs"),
            (str(report.get("negative_pairs", 0)), "Negative Pairs"),
            (f"{report.get('accuracy', 0):.3f}", "Accuracy"),
            (f"{report.get('f1_score', 0):.3f}", "F1-score"),
            ("Saved", "Model Status"),
        ]
        for index, (number, label) in enumerate(cards):
            self.training_metrics_grid.addWidget(self._summary_card(number, label), index // 3, index % 3)

    def _import_excel(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.critical(self, "Import Excel", f"File not found:\n\n{path}")
            return
        if path.suffix.lower() not in {".xlsx", ".xls", ".ods"}:
            QMessageBox.warning(self, "Import Excel", "Please select a spreadsheet file with .xlsx, .xls, or .ods extension.")
            return
        if path.suffix.lower() == ".xls":
            QMessageBox.information(self, "Import Excel", ".xls files require the optional xlrd package. If this file fails, please save it as .xlsx.")
        self.selected_file = Path(path)
        try:
            self.imported_df = load_dispatch_excel(self.selected_file, read_all_sheets=True)
            if self.imported_df.empty:
                raise ValueError("The workbook has no agent rows.")
            detect_columns(self.imported_df)
        except Exception as exc:
            self.selected_file = None
            self.imported_df = None
            self.grouped_df = None
            self.file_label.setText("No file selected")
            self.file_status_label.setText("Could not import this Excel file.")
            QMessageBox.critical(self, "Import Excel", f"Could not import this Excel file.\n\n{exc}")
            return

        self.file_label.setText(self.selected_file.name)
        self.file_status_label.setText(f"{len(self.imported_df)} rows imported. Ready for real dispatch.")
        self.empty_results.setText("Excel file imported. Click dispatch to generate taxi groups.")

    def _run_dispatch(self) -> None:
        if self.imported_df is None or self.imported_df.empty:
            QMessageBox.warning(self, "Import Excel", "Please import an Excel file before dispatching.")
            return
        self.dispatch_button.setEnabled(False)
        self.dispatch_button.setText("DISPATCHING...")
        QTimer.singleShot(300, self._show_dispatch_results)

    def _show_dispatch_results(self) -> None:
        try:
            if self.imported_df is None:
                raise ValueError("No Excel file is imported.")
            columns = detect_columns(self.imported_df)
            dispatch_type = "Ramassage" if self.ramassage_button.isChecked() else "Retour"
            filtered = filter_dataframe(
                self.imported_df,
                columns,
                time_value=self.time_combo.currentText(),
                type_course=dispatch_type,
                operation=None,
            )
            if filtered.empty:
                filtered = self.imported_df.copy()
            grouped, warnings = group_agents(filtered, columns=detect_columns(filtered), use_ml=True)
            validation = validate_dispatch(grouped)
            if validation["errors"]:
                raise ValueError("\n".join(validation["errors"]))
            self.grouped_df = grouped
            self.grouping_warnings = [*warnings, *validation["warnings"]]
        except Exception as exc:
            self.dispatch_button.setEnabled(True)
            self.dispatch_button.setText("DISPATCH AUTOMATICALLY")
            QMessageBox.critical(self, "Dispatch Error", f"Could not dispatch this Excel file.\n\n{exc}")
            return

        self.dispatch_button.setEnabled(True)
        self.dispatch_button.setText("DISPATCH AUTOMATICALLY")
        self.empty_results.hide()
        self._populate_summary_cards()
        self._populate_table()
        self.summary_container.show()
        self.results_table.show()
        self.export_button.show()
        if self.grouping_warnings:
            QMessageBox.information(self, "Dispatch", "\n".join(self.grouping_warnings))

    def _populate_summary_cards(self) -> None:
        while self.summary_grid.count():
            item = self.summary_grid.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if self.grouped_df is None:
            return
        total_agents = len(self.grouped_df)
        total_taxis = int(self.grouped_df[TAXI_COLUMN].nunique()) if total_agents else 0
        unknown_count = int((self.grouped_df["Zone"] == UNKNOWN_ZONE).sum()) if "Zone" in self.grouped_df else 0
        average = round(total_agents / total_taxis, 1) if total_taxis else 0
        cards = [
            (str(total_agents), "Total Agents"),
            (str(total_taxis), "Total Taxis"),
            (str(unknown_count), "Unknown Addresses"),
            (str(average), "Average Agents / Taxi"),
        ]
        for index, (number, label) in enumerate(cards):
            self.summary_grid.addWidget(self._summary_card(number, label), index // 2, index % 2)

    def _summary_card(self, number: str, label: str) -> QWidget:
        card = QFrame()
        card.setObjectName("SummaryCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        value = QLabel(number)
        value.setObjectName("SummaryNumber")
        text = QLabel(label)
        text.setObjectName("SummaryLabel")
        layout.addWidget(value)
        layout.addWidget(text)
        return card

    def _populate_table(self) -> None:
        if self.grouped_df is None:
            return
        columns = detect_columns(self.grouped_df)
        matricule_col = self._find_column(self.grouped_df, ["Matricule", "ID", "Taxi ID"])
        rows = []
        for _, row in self.grouped_df.head(80).iterrows():
            rows.append(
                [
                    f"Taxi {self._cell_text(row, TAXI_COLUMN)}",
                    self._cell_text(row, matricule_col),
                    self._cell_text(row, columns.name),
                    self._cell_text(row, columns.address),
                    self._cell_text(row, "Zone"),
                    self._cell_text(row, columns.time) or self.time_combo.currentText(),
                ]
            )
        self.results_table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter if col_index in {0, 1, 4, 5} else Qt.AlignLeft | Qt.AlignVCenter)
                item.setForeground(QColor("#FFFFFF"))
                self.results_table.setItem(row_index, col_index, item)
        self.results_table.resizeRowsToContents()

    def _build_mock_dispatch_rows(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for index, record in enumerate(self.imported_rows, start=1):
            rows.append(
                {
                    "Taxi": f"Taxi {((index - 1) // 4) + 1}",
                    "Matricule": self._first_value(record, ["Matricule", "ID", "Taxi ID"], str(1000 + index)),
                    "Nom - Prenom": self._first_value(record, ["Nom - Prénom", "Nom - Prenom", "Nom", "Agent"], f"Agent {index}"),
                    "Adresse": self._first_value(record, ["Adresse", "Address", "Lieu", "Localisation", "Adresse Ramassage"], ""),
                    "Zone": self._mock_zone(index),
                    "Heure": self._first_value(record, ["Heure", "Heure d'arrivée", "Heure de départ", "Heure Ramassage", "Heure Retour"], self.time_combo.currentText()),
                }
            )
        return rows

    def _first_value(self, record: dict[str, str], candidates: list[str], fallback: str) -> str:
        normalized = {key.lower().replace("é", "e").replace("è", "e").strip(): value for key, value in record.items()}
        for candidate in candidates:
            value = normalized.get(candidate.lower().replace("é", "e").replace("è", "e").strip())
            if value:
                return value
        return fallback

    def _mock_zone(self, index: int) -> str:
        zones = ["K", "K", "H", "H", "J", "A", "B", "G", "UNKNOWN"]
        return zones[(index - 1) % len(zones)]

    def _find_column(self, df: pd.DataFrame, candidates: list[str]) -> str | None:
        normalized = {str(col).lower().strip(): str(col) for col in df.columns}
        for candidate in candidates:
            key = candidate.lower().strip()
            if key in normalized:
                return normalized[key]
        for candidate in candidates:
            key = candidate.lower().strip()
            for normalized_col, original_col in normalized.items():
                if key in normalized_col:
                    return original_col
        return None

    def _cell_text(self, row: pd.Series, column: str | None) -> str:
        if not column or column not in row:
            return ""
        value = row[column]
        if pd.isna(value):
            return ""
        return str(value)

    def _export_dispatched_excel(self) -> None:
        if self.grouped_df is None or self.grouped_df.empty:
            QMessageBox.warning(self, "Export Excel", "Please dispatch the imported file before exporting.")
            return

        default_name = "yellow_express_dispatched.xlsx"
        dialog = QFileDialog(self, "Export Dispatched Excel")
        dialog.setAcceptMode(QFileDialog.AcceptSave)
        dialog.setNameFilter("Excel Files (*.xlsx)")
        dialog.setDefaultSuffix("xlsx")
        dialog.setDirectory(self._desktop_directory())
        dialog.selectFile(default_name)
        dialog.setOption(QFileDialog.DontUseNativeDialog, True)
        if not dialog.exec():
            return
        selected = dialog.selectedFiles()
        path = selected[0] if selected else ""
        if not path:
            return
        output_path = Path(path)
        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")

        report_path = output_path.with_name(f"{output_path.stem}_validation_report.xlsx")
        export_like_historique(self.grouped_df, str(output_path), validation_report_path=str(report_path))
        QMessageBox.information(
            self,
            "Export Excel",
            f"Dispatched Excel file exported successfully:\n\n{output_path}\n\nValidation report:\n\n{report_path}",
        )

    def _desktop_directory(self) -> str:
        desktop = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        return desktop or str(Path.home())

    def dragEnterEvent(self, event) -> None:
        if self._event_has_excel_file(event):
            event.acceptProposedAction()
            self.file_status_label.setText("Drop to import this Excel file.")
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:
        if self.imported_df is None or self.imported_df.empty:
            self.file_status_label.setText("Click Browse or drop a spreadsheet file here.")
        event.accept()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if path.suffix.lower() in {".xlsx", ".xls", ".ods"}:
                self._import_excel(path)
                event.acceptProposedAction()
                return
        QMessageBox.warning(self, "Import Excel", "Please drop a spreadsheet file with .xlsx, .xls, or .ods extension.")
        event.ignore()

    def _event_has_excel_file(self, event) -> bool:
        if not event.mimeData().hasUrls():
            return False
        return any(Path(url.toLocalFile()).suffix.lower() in {".xlsx", ".xls", ".ods"} for url in event.mimeData().urls() if url.isLocalFile())


STYLESHEET = """
QMainWindow, QWidget#Main {
    background: #0A0A0A;
    color: #FFFFFF;
    font-family: Segoe UI, Arial, sans-serif;
    font-size: 14px;
}
QFrame#Header {
    background: #0A0A0A;
    border-bottom: 2px solid #F5E600;
}
QLabel#Brand {
    color: #F5E600;
    font-size: 24px;
    font-weight: 900;
    letter-spacing: 0px;
}
QLabel#Tagline, QLabel#Contacts, QLabel#MutedText, QLabel#SidebarFooter {
    color: #BDBDBD;
}
QLabel#Contacts {
    font-size: 13px;
}
QFrame#Sidebar {
    background: #111111;
    border-right: 1px solid #2A2A2A;
}
QPushButton#NavButton, QPushButton#NavButtonActive {
    border: 1px solid transparent;
    border-radius: 10px;
    padding: 13px 16px;
    text-align: left;
    font-weight: 700;
}
QPushButton#NavButton {
    background: transparent;
    color: #BDBDBD;
}
QPushButton#NavButton:hover {
    background: #1A1A1A;
    color: #FFFFFF;
    border-color: #2A2A2A;
}
QPushButton#NavButtonActive {
    background: #F5E600;
    color: #0A0A0A;
}
QLabel#SidebarFooter {
    line-height: 140%;
}
QLabel#PageTitle {
    color: #FFFFFF;
    font-size: 30px;
    font-weight: 900;
}
QLabel#PageSubtitle {
    color: #BDBDBD;
    font-size: 15px;
}
QFrame#Card {
    background: #111111;
    border: 1px solid #2A2A2A;
    border-radius: 18px;
}
QLabel#CardTitle {
    color: #FFFFFF;
    font-size: 20px;
    font-weight: 900;
}
QLabel#FieldLabel {
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 800;
}
QPushButton#SegmentButton {
    background: #1A1A1A;
    color: #FFFFFF;
    border: 1px solid #2A2A2A;
    border-radius: 10px;
    padding: 12px 16px;
    font-weight: 800;
}
QPushButton#SegmentButton:hover {
    border-color: #F5E600;
}
QPushButton#SegmentButton:checked {
    background: #F5E600;
    color: #0A0A0A;
    border-color: #F5E600;
}
QComboBox#InputCombo {
    background: #1A1A1A;
    color: #FFFFFF;
    border: 1px solid #2A2A2A;
    border-radius: 10px;
    padding: 11px 12px;
    min-height: 24px;
}
QComboBox#InputCombo:hover {
    border-color: #F5E600;
}
QComboBox QAbstractItemView {
    background: #111111;
    color: #FFFFFF;
    selection-background-color: #F5E600;
    selection-color: #0A0A0A;
    border: 1px solid #2A2A2A;
}
QFrame#UploadBox {
    background: #0A0A0A;
    border: 1px dashed #F5E600;
    border-radius: 16px;
}
QLabel#UploadTitle {
    color: #FFFFFF;
    font-size: 17px;
    font-weight: 900;
}
QLabel#FileName {
    color: #2ECC71;
    font-weight: 800;
}
QPushButton#SecondaryButton, QPushButton#ExportButton {
    background: #1A1A1A;
    color: #FFFFFF;
    border: 1px solid #2A2A2A;
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 800;
}
QPushButton#SecondaryButton:hover, QPushButton#ExportButton:hover {
    border-color: #F5E600;
    color: #F5E600;
}
QPushButton#PrimaryButton {
    background: #FFE600;
    color: #0A0A0A;
    border: none;
    border-radius: 14px;
    min-height: 52px;
    font-size: 16px;
    font-weight: 900;
}
QPushButton#PrimaryButton:hover {
    background: #F5E600;
}
QPushButton#PrimaryButton:disabled {
    background: #BDBDBD;
    color: #1A1A1A;
}
QLabel#EmptyState {
    color: #BDBDBD;
    background: #0A0A0A;
    border: 1px solid #2A2A2A;
    border-radius: 16px;
    font-size: 16px;
}
QFrame#SummaryCard {
    background: #1A1A1A;
    border: 1px solid #2A2A2A;
    border-radius: 14px;
}
QLabel#SummaryNumber {
    color: #F5E600;
    font-size: 28px;
    font-weight: 900;
}
QLabel#SummaryLabel {
    color: #FFFFFF;
    font-size: 13px;
    font-weight: 800;
}
QTableWidget#ResultsTable {
    background: #0A0A0A;
    color: #FFFFFF;
    border: 1px solid #2A2A2A;
    border-radius: 12px;
    gridline-color: #2A2A2A;
    selection-background-color: #F5E600;
    selection-color: #0A0A0A;
}
QHeaderView::section {
    background: #F5E600;
    color: #0A0A0A;
    border: none;
    padding: 9px;
    font-weight: 900;
}
QTableWidget::item {
    background: #111111;
    border-bottom: 1px solid #2A2A2A;
    padding: 8px;
}
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    window = YellowExpressDispatch()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
