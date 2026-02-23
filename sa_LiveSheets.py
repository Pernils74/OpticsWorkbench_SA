# -*- coding: utf-8 -*-
# LiveSheets.py

"""
Live spreadsheet editor dock - SA version (standalone)
- Dynamic column count (no hard-coded A..D)
- Includes its own recompute_doc() with OpticsWB restart + view/plot refresh.
- No external import of recompute_doc required.
"""

import os
import time
import string

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets


DOCK_OBJECT_NAME = "SA_LiveSheetsDock"
DEFAULT_SHEET = "Spreadsheet"
MAX_SCAN_ROWS = 600

# How many columns to show (A..)
MAX_COLUMNS = 26
COLUMN_NAMES = list(string.ascii_uppercase)[:MAX_COLUMNS]


# ---------------------------------------------------------
# SA: FreeCAD view/optics refresh helpers (standalone)
# ---------------------------------------------------------


def _refresh_3d_view():
    """Force update the 3D view (best-effort)."""
    try:
        if Gui:
            Gui.updateGui()
    except Exception:
        pass
    try:
        if Gui and Gui.ActiveDocument:
            vw = Gui.ActiveDocument.ActiveView
            if vw:
                vw.update()
    except Exception:
        pass


def _restart_optics():
    """Restart OpticsWorkbench (best-effort)."""
    try:
        import OpticsWorkbench
    except Exception:
        return
    try:
        OpticsWorkbench.allOff()
        OpticsWorkbench.restartAll()
    except Exception:
        pass


def recompute_doc(doc, iter_index=None, note=None, restore_view=None):
    """Recompute the document, restart optics and refresh UI."""
    t0 = time.time()
    try:
        doc.recompute()
    except Exception as e:
        try:
            App.Console.PrintError(f"[OBA] recompute error: {e}\n")
        except Exception:
            pass

    _restart_optics()
    _refresh_3d_view()

    if restore_view:
        try:
            restore_view()
        except Exception:
            pass

    dt = time.time() - t0
    msg = "[OBA] recompute+optics+refresh {:.3f}s".format(dt)
    if iter_index is not None:
        msg += f" | iter={iter_index}"
    if note:
        msg += " | " + str(note)
    try:
        App.Console.PrintMessage(msg + "\n")
    except Exception:
        pass


# ---------------------------------------------------------
# Helper: get spreadsheet list (unchanged logic)
# ---------------------------------------------------------


def _get_sheets(doc):
    dn = DEFAULT_SHEET.casefold() if DEFAULT_SHEET else None

    def is_default(s):
        return dn and (((s.Name or "").casefold() == dn) or ((s.Label or "").casefold() == dn))

    def alpha_key(s):
        primary = s.Label if (s.Label and s.Label.strip()) else s.Name
        return (primary or "").casefold(), (s.Name or "").casefold()

    sheets = [o for o in doc.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]
    if not sheets:
        return None, None

    sorted_sheets = sorted(sheets, key=lambda s: (0 if is_default(s) else 1,) + alpha_key(s))
    default_idx = next((i for i, s in enumerate(sorted_sheets) if is_default(s)), None)

    return sorted_sheets, default_idx


class ReloadingComboBox(QtWidgets.QComboBox):
    def __init__(self, reload_fn=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._reload_fn = reload_fn

    def showPopup(self):
        try:
            if callable(self._reload_fn):
                self._reload_fn()
        except Exception as e:
            App.Console.PrintWarning(f"Reload sheet list failed: {e}\n")
        finally:
            super().showPopup()


# ---------------------------------------------------------
# Dock widget
# ---------------------------------------------------------
class SA_LiveSheetsDock(QtWidgets.QDockWidget):
    def __init__(self, parent=None):
        super().__init__("Live Spreadsheet (SA)", parent)
        self.setObjectName(DOCK_OBJECT_NAME)

        central = QtWidgets.QWidget(self)
        self.setWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Select sheet
        layout.addWidget(QtWidgets.QLabel("Select spreadsheet:"))

        self.cmbSheets = ReloadingComboBox(reload_fn=self._reload_sheet_list)
        layout.addWidget(self.cmbSheets)

        # Controls
        ctrl = QtWidgets.QHBoxLayout()
        self.chkAutoRecompute = QtWidgets.QCheckBox("Auto-recompute")
        self.chkAutoRecompute.setChecked(True)

        btn = QtWidgets.QPushButton("Recompute now")
        btn.clicked.connect(lambda: App.ActiveDocument and recompute_doc(App.ActiveDocument, note="Manual SA recompute"))

        ctrl.addWidget(self.chkAutoRecompute)
        ctrl.addStretch(1)
        ctrl.addWidget(btn)
        layout.addLayout(ctrl)

        # Table
        self.tbl = QtWidgets.QTableWidget()
        self.tbl.setColumnCount(MAX_COLUMNS)
        self.tbl.setHorizontalHeaderLabels(COLUMN_NAMES)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.tbl.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        layout.addWidget(self.tbl)

        self._loading = False

        # Initial load
        doc = App.ActiveDocument
        if not doc:
            QtGui.QMessageBox.warning(None, "LiveSheets", "No active document.")
            return

        sheets, def_idx = _get_sheets(doc)
        if not sheets:
            self.cmbSheets.addItem("(No spreadsheets found)")
            self.cmbSheets.setEnabled(False)
        else:
            for s in sheets:
                self.cmbSheets.addItem(s.Label or s.Name, userData=s)
            if def_idx is not None:
                self.cmbSheets.setCurrentIndex(def_idx)
            self._reload_sheet()

        self.cmbSheets.currentIndexChanged.connect(self._reload_sheet)
        self.tbl.itemChanged.connect(self._on_cell_edited)

    # -----------------------------------------------------
    # Helpers
    # -----------------------------------------------------

    def _current_sheet(self):
        return self.cmbSheets.currentData()

    def _used_rows(self, sheet):
        last = 0

        for r in range(1, MAX_SCAN_ROWS + 1):
            row_has_data = False

            for c in range(self.tbl.columnCount()):
                col = COLUMN_NAMES[c]
                addr = f"{col}{r}"

                try:
                    v = sheet.get(addr)
                except Exception:
                    return max(last, 10)

                if v not in ("", None, ""):
                    row_has_data = True

            if row_has_data:
                last = r + 5

        return max(last, 10)

    def _reload_sheet(self):
        sheet = self._current_sheet()
        if not sheet:
            return

        if self.chkAutoRecompute.isChecked():
            recompute_doc(App.ActiveDocument, note="Reload sheet")

        rows = self._used_rows(sheet)

        self._loading = True
        self.tbl.blockSignals(True)
        self.tbl.clearContents()
        self.tbl.setRowCount(rows)

        # Load data
        for r in range(rows):
            for c in range(self.tbl.columnCount()):
                col = COLUMN_NAMES[c]
                try:
                    val = sheet.get(f"{col}{r+1}")
                except Exception:
                    val = ""
                it = QtWidgets.QTableWidgetItem("" if val is None else str(val))
                self.tbl.setItem(r, c, it)

            self.tbl.setVerticalHeaderItem(r, QtWidgets.QTableWidgetItem(str(r + 1)))

        self.tbl.blockSignals(False)
        self._loading = False

    def _on_cell_edited(self, item):
        if self._loading:
            return

        sheet = self._current_sheet()
        if not sheet:
            return

        r = item.row()
        c = item.column()
        col = COLUMN_NAMES[c]
        val = item.text()

        try:
            sheet.set(f"{col}{r+1}", val)
            if self.chkAutoRecompute.isChecked():
                recompute_doc(App.ActiveDocument, note="SA_LiveSheets cell edit")
        except Exception as e:
            QtGui.QMessageBox.warning(self, "Spreadsheet", f"Could not write:\n{e}")

    def _reload_sheet_list(self):
        doc = App.ActiveDocument
        if not doc:
            return

        old = self._current_sheet()
        old_key = (old.Label or old.Name).casefold() if old else None

        sheets, def_idx = _get_sheets(doc)

        self.cmbSheets.blockSignals(True)
        self.cmbSheets.clear()

        if not sheets:
            self.cmbSheets.addItem("(No spreadsheets found)")
            self.cmbSheets.setEnabled(False)
        else:
            self.cmbSheets.setEnabled(True)
            match_idx = None

            for i, s in enumerate(sheets):
                label = s.Label or s.Name
                self.cmbSheets.addItem(label, userData=s)
                if old_key and label.casefold() == old_key:
                    match_idx = i

            self.cmbSheets.setCurrentIndex(match_idx if match_idx is not None else def_idx or 0)

        self.cmbSheets.blockSignals(False)
        self._reload_sheet()


# ---------------------------------------------------------
# Show dock
# ---------------------------------------------------------


def SA_ShowLiveSheetsDock():
    mw = Gui.getMainWindow()
    exist = mw.findChild(QtWidgets.QDockWidget, DOCK_OBJECT_NAME)

    if exist:
        area = mw.dockWidgetArea(exist)
        mw.removeDockWidget(exist)
        exist.deleteLater()
        dock = SA_LiveSheetsDock(mw)
        mw.addDockWidget(area, dock)
    else:
        dock = SA_LiveSheetsDock(mw)
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

    dock.show()
    dock.raise_()
    dock.activateWindow()

    Gui.SA_LiveSheetsDock_ref = dock
    return dock


# ---------------------------------------------------------
# FreeCAD Command
# ---------------------------------------------------------


class SA_LiveSheetsCmd:
    """FreeCAD command that opens the SA spreadsheet dock."""

    def GetResources(self):
        icon = os.path.join(os.path.dirname(__file__), "icons", "live_spreadsheet.svg")
        return {
            "Pixmap": icon,
            "MenuText": "Live Sheets (SA)",
            "ToolTip": "Open the live spreadsheet tool (SA)",
        }

    def Activated(self):
        SA_ShowLiveSheetsDock()

    def IsActive(self):
        return True


Gui.addCommand("sa_LiveSheets", SA_LiveSheetsCmd())
