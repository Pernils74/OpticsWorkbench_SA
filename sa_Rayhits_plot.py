# -*- coding: utf-8 -*-
# sa_Rayhits_plot.py — UI/Dialog + plot orchestration

from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, Any, Optional

import FreeCAD as App
import FreeCADGui as Gui

from PySide2 import QtWidgets
from PySide2.QtCore import Qt, QEvent


import matplotlib

try:
    matplotlib.use("Qt5Agg")
except Exception:
    pass

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

# Parser
from sa_rayhits_parser import get_tree_and_stats_for_sheet

# Plot core
from sa_plot_core import (
    ColorMixer,
    draw_points,
    draw_blobs_2d,
    draw_centroids,
    build_legends,
    compute_domains_for_legend,
)

MARKERS = ["o", "s", "^", "D", "P", "*", "x", "v", "<", ">"]
DEFAULT_FIGSIZE = (10, 7)
SCATTER_SIZE = 40

BLOB_FACE_ALPHA = 0.17
BLOB_EDGE_ALPHA = 0.35
BLOB_EDGE_LINEWIDTH = 1.3

HOVER_LINEWIDTH = 2.3
HOVER_EDGECOLOR = "yellow"


@dataclass
class PlotConfig:
    plane_text: str
    flip_2d_axes: bool
    grid_on: bool
    equal_on: bool
    show_blobs: bool
    smooth_blobs: bool
    blob_strength: float
    show_centroids: bool
    show_weighted_centroids: (
        bool  # om parsern levererar viktade (kan vara False initialt)
    )

    @property
    def is3d(self) -> bool:
        return self.plane_text.startswith("XYZ")


class RayHitsPlotDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        # --- Gör dialogen till ett "riktigt" fönster med min/max-knappar ---
        flags = self.windowFlags()
        flags |= Qt.WindowSystemMenuHint
        flags |= Qt.WindowMinimizeButtonHint
        flags |= Qt.WindowMaximizeButtonHint
        # (valfritt) se till att den inte är "Tool" (som saknar normal titelradbeteende)
        flags |= Qt.Window
        self.setWindowFlags(flags)

        # --- Säkerställ att den går att ändra storlek på ---
        self.setSizeGripEnabled(True)  # QDialog-specifik hjälp
        self.setMinimumSize(640, 480)  # ge rimlig minsta storlek

        self.setWindowTitle("RayHits Advanced Plot")
        self.resize(1400, 900)

        self.absorber_checkboxes: Dict[str, QtWidgets.QCheckBox] = {}
        self.ray_checkboxes: Dict[str, QtWidgets.QCheckBox] = {}

        self._highlighted_scatter = None
        self._pick_cid: Optional[int] = None

        self._init_ui()
        self._connect_signals()

        self.populate_sheets()
        self.reload_plot()

    # ---------------- UI ----------------
    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QtWidgets.QLabel("Sheet:"))
        self.cmbSheet = QtWidgets.QComboBox()
        top.addWidget(self.cmbSheet)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_plot)
        top.addWidget(btnReload)

        top.addSpacing(20)
        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ", "XYZ (3D)"])
        top.addWidget(self.cmbPlane)

        self.chkFlip = QtWidgets.QCheckBox("Flip axes (2D)")
        top.addWidget(self.chkFlip)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        self.chkGrid.setChecked(True)
        top.addWidget(self.chkGrid)

        self.chkEqual = QtWidgets.QCheckBox("Equal aspect")
        self.chkEqual.setChecked(True)
        top.addWidget(self.chkEqual)

        self.chkBlobs = QtWidgets.QCheckBox("Show blobs")
        self.chkBlobs.setChecked(True)
        top.addWidget(self.chkBlobs)

        self.chkBlobSmooth = QtWidgets.QCheckBox("Smooth hull")
        self.chkBlobSmooth.setChecked(True)
        top.addWidget(self.chkBlobSmooth)

        top.addWidget(QtWidgets.QLabel("Strength:"))
        self.spnBlobStrength = QtWidgets.QDoubleSpinBox()
        self.spnBlobStrength.setRange(0.01, 1.00)
        self.spnBlobStrength.setSingleStep(0.01)
        self.spnBlobStrength.setDecimals(3)
        self.spnBlobStrength.setValue(0.15)
        top.addWidget(self.spnBlobStrength)

        # NEW: centroid toggle(s)
        self.chkCentroids = QtWidgets.QCheckBox("Show centroids")
        self.chkCentroids.setChecked(True)
        top.addWidget(self.chkCentroids)

        # (valfritt) en ytterligare toggle om du aktiverar viktade i parsern:
        self.chkCentroidsWeighted = QtWidgets.QCheckBox("Energy-weighted 3D centroids")
        self.chkCentroidsWeighted.setChecked(False)
        top.addWidget(self.chkCentroidsWeighted)

        top.addStretch()

        # Absorber checkboxes
        self.absorberBox = QtWidgets.QGroupBox("Visible Absorbers")
        self.absorberLayout = QtWidgets.QVBoxLayout(self.absorberBox)
        root.addWidget(self.absorberBox)

        # Ray checkboxes
        self.rayBox = QtWidgets.QGroupBox("Visible Rays")
        self.rayLayout = QtWidgets.QVBoxLayout(self.rayBox)
        root.addWidget(self.rayBox)

        # Figure
        self.fig = plt.Figure(figsize=DEFAULT_FIGSIZE)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas)

        # Status
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

    def _connect_signals(self):
        widgets = [
            self.cmbSheet,
            self.cmbPlane,
            self.chkFlip,
            self.chkGrid,
            self.chkEqual,
            self.chkBlobs,
            self.chkBlobSmooth,
            self.spnBlobStrength,
            self.chkCentroids,
            self.chkCentroidsWeighted,
        ]
        for w in widgets:
            if hasattr(w, "stateChanged"):
                w.stateChanged.connect(self.reload_plot)
            elif hasattr(w, "currentIndexChanged"):
                w.currentIndexChanged.connect(self.reload_plot)
            elif hasattr(w, "valueChanged"):
                w.valueChanged.connect(self.reload_plot)

    # ---------------- Sheet utils ----------------
    def populate_sheets(self):
        doc = App.ActiveDocument
        if not doc:
            return
        sheets = [o for o in doc.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]

        def sort_key(s):
            n = s.Label or s.Name
            return (0 if (n or "").startswith("RayHits") else 1, (n or "").lower())

        sheets.sort(key=sort_key)

        self.cmbSheet.blockSignals(True)
        self.cmbSheet.clear()
        for s in sheets:
            self.cmbSheet.addItem(s.Label or s.Name)
        self.cmbSheet.blockSignals(False)

    def current_sheet_name(self) -> Optional[str]:
        return self.cmbSheet.currentText() or None

    # ---------------- Checkbox builders ----------------
    def _rebuild_absorber_checkboxes(self, tree):
        for cb in self.absorber_checkboxes.values():
            self.absorberLayout.removeWidget(cb)
            cb.deleteLater()
        self.absorber_checkboxes.clear()

        for absorber in sorted(tree.keys()):
            cb = QtWidgets.QCheckBox(absorber)
            cb.setChecked(True)
            cb.stateChanged.connect(self.reload_plot)
            self.absorberLayout.addWidget(cb)
            self.absorber_checkboxes[absorber] = cb

    def _rebuild_ray_checkboxes(self, rays_all):
        for cb in self.ray_checkboxes.values():
            self.rayLayout.removeWidget(cb)
            cb.deleteLater()
        self.ray_checkboxes.clear()

        for ray in sorted(rays_all):
            cb = QtWidgets.QCheckBox(ray)
            cb.setChecked(True)
            cb.stateChanged.connect(self.reload_plot)
            self.rayLayout.addWidget(cb)
            self.ray_checkboxes[ray] = cb

    # ---------------- Popup ----------------
    def _show_point_popup(self, info: Dict[str, Any]):
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("RayHit Info")
        dlg.setText(
            f"Absorber: {info.get('absorber')}\n"
            f"Ray: {info.get('ray')}\n"
            f"RayId: {info.get('id')}\n"
            f"PreviousHit: {info.get('prev')}\n"
            f"BounceCnt: {info.get('bounce')}\n\n"
            f"X = {info.get('x')}\n"
            f"Y = {info.get('y')}\n"
            f"Z = {info.get('z')}\n"
            f"Energy = {info.get('energy')}\n"
        )
        dlg.exec_()

    # ---------------- Plot reload ----------------
    def reload_plot(self):
        sheet_name = self.current_sheet_name()
        if not sheet_name:
            self.lblStatus.setText("No sheet selected.")
            return

        try:
            # Hämta tree + stats via parsern (weights avstängda som default)
            tree, stats = get_tree_and_stats_for_sheet(
                sheet_name, compute_weighted_3d=self.chkCentroidsWeighted.isChecked()
            )
            self.lblStatus.setText("Data loaded")

            # Checkbox sync
            if set(tree.keys()) != set(self.absorber_checkboxes.keys()):
                self._rebuild_absorber_checkboxes(tree)

            rays_all = {ray for absorber in tree for ray in tree[absorber].keys()}
            if set(rays_all) != set(self.ray_checkboxes.keys()):
                self._rebuild_ray_checkboxes(rays_all)

            # Figure layout
            self.fig.clear()
            gs = gridspec.GridSpec(
                nrows=2, ncols=1, height_ratios=[12, 2], figure=self.fig
            )

            cfg = PlotConfig(
                plane_text=self.cmbPlane.currentText(),
                flip_2d_axes=self.chkFlip.isChecked(),
                grid_on=self.chkGrid.isChecked(),
                equal_on=self.chkEqual.isChecked(),
                show_blobs=self.chkBlobs.isChecked(),
                smooth_blobs=self.chkBlobSmooth.isChecked(),
                blob_strength=float(self.spnBlobStrength.value()),
                show_centroids=self.chkCentroids.isChecked(),
                show_weighted_centroids=self.chkCentroidsWeighted.isChecked(),
            )

            ax = self.fig.add_subplot(gs[0, 0], projection="3d" if cfg.is3d else None)
            # Grid/aspect
            if cfg.is3d:
                ax.grid(cfg.grid_on)
                if cfg.equal_on and hasattr(ax, "set_box_aspect"):
                    ax.set_box_aspect([1, 1, 1])
            else:
                (
                    ax.grid(cfg.grid_on, linestyle="--", alpha=0.35)
                    if cfg.grid_on
                    else ax.grid(False)
                )
                ax.set_aspect("equal" if cfg.equal_on else "auto", adjustable="datalim")

            ax_leg = self.fig.add_subplot(gs[1, 0])
            ax_leg.set_axis_off()

            # Legend domains + mixer + marker map
            rays_sorted, bounces_sorted, prevs_sorted = compute_domains_for_legend(tree)
            ray_marker = {
                r: MARKERS[i % len(MARKERS)] for i, r in enumerate(rays_sorted)
            }
            mixer = ColorMixer(prevs_sorted, bounces_sorted)

            # Build visibility dicts
            absorber_on = {
                k: cb.isChecked() for k, cb in self.absorber_checkboxes.items()
            }
            ray_on = {k: cb.isChecked() for k, cb in self.ray_checkboxes.items()}

            # Plane key
            plane_key = "3D" if cfg.is3d else cfg.plane_text

            # Draw points
            scatters = draw_points(
                ax=ax,
                tree=tree,
                plane_key=plane_key,
                is3d=cfg.is3d,
                flip2d=cfg.flip_2d_axes,
                absorber_on=absorber_on,
                ray_on=ray_on,
                ray_marker=ray_marker,
                mixer=mixer,
                scatter_size=40,
            )

            # Blobs
            if cfg.show_blobs and not cfg.is3d:
                draw_blobs_2d(
                    ax=ax,
                    tree=tree,
                    plane_key=plane_key,
                    flip2d=cfg.flip_2d_axes,
                    absorber_on=absorber_on,
                    ray_on=ray_on,
                    mixer=mixer,
                    smooth=cfg.smooth_blobs,
                    strength=cfg.blob_strength,
                    face_alpha=0.17,
                    edge_alpha=0.35,
                    lw=1.3,
                )

            # Centroids

            if cfg.show_centroids:
                draw_centroids(
                    ax=ax,
                    stats=stats,
                    plane_key=plane_key,
                    is3d=cfg.is3d,
                    flip2d=cfg.flip_2d_axes,
                    absorber_on=absorber_on,
                    ray_on=ray_on,
                    size=160,
                    face="none",
                    edge="black",
                    lw=1.2,
                    weighted=cfg.show_weighted_centroids,
                )

            # Legends
            build_legends(
                ax_leg, rays_sorted, prevs_sorted, bounces_sorted, ray_marker, mixer
            )

            # Pick handler
            self._install_pick_handler(scatters)

            self.canvas.draw_idle()

        except Exception as e:
            self.lblStatus.setText(f"Error: {e}")
            print("RayHitsPlotDialog.reload_plot error:", e)

    # ---------------- Pick/highlight ----------------
    def _install_pick_handler(self, scatter_artists):
        if self._pick_cid is not None:
            try:
                self.fig.canvas.mpl_disconnect(self._pick_cid)
            except Exception:
                pass
            self._pick_cid = None

        def on_pick(event):
            artist = event.artist
            if not hasattr(artist, "_pointinfo"):
                return
            if not event.ind:
                return

            idx = event.ind[0]
            info = artist._pointinfo[idx]

            if self._highlighted_scatter is not None:
                try:
                    self._highlighted_scatter.set_edgecolors("none")
                    self._highlighted_scatter.set_linewidths(1)
                except Exception:
                    pass

            try:
                artist.set_edgecolors("yellow")
                artist.set_linewidths(2.3)
            except Exception as ex:
                print("Highlight error:", ex)

            self._highlighted_scatter = artist

            # Popup
            self._show_point_popup(info)
            self.canvas.draw_idle()

        self._pick_cid = self.fig.canvas.mpl_connect("pick_event", on_pick)


# ---------------- Public API ----------------
def RH_ShowAdvancedPlot():
    mw = Gui.getMainWindow()
    dlg = RayHitsPlotDialog(parent=mw)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    Gui._rayhits_plot_ref = dlg
    return dlg


class Rayhits_PlotCmd:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                os.path.dirname(__file__), "icons", "advanced_plot.svg"
            ),
            "MenuText": "RayHits Advanced Plot",
            "ToolTip": "Plot RayHits (absorber/ray filters, blobs, centroids, click)",
        }

    def Activated(self):
        RH_ShowAdvancedPlot()

    def IsActive(self):
        return True


Gui.addCommand("SA_Rayhits_Plot", Rayhits_PlotCmd())
