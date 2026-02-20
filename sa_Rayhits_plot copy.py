# -*- coding: utf-8 -*-
# sa_Rayhits_plot.py (refactored)

"""
RayHits Advanced Plot (Click Popup + Cluster Blobs)
---------------------------------------------------

NO hover
YES click → popup with full info
YES transparent cluster-blobs per (Ray,PrevHit,Bounce) group
YES checkbox to show/hide blobs

Uses:
    sa_rayhits_parser.py   (read_sheet_rows, build_ray_tree)

Plot encodings:
    Marker     = Ray
    FinalColor = colormap(plasma) by BounceCnt + alpha by PreviousHit
"""

from __future__ import annotations

import os
import math
from dataclasses import dataclass
from typing import Dict, List, Tuple, Any, Iterable, Optional

import FreeCAD as App
import FreeCADGui as Gui
from PySide2 import QtWidgets

# --- matplotlib embedding -----------------------------------------------------
import matplotlib

# Ensure Qt backend (FreeCAD embeds Qt)
try:
    matplotlib.use("Qt5Agg")
except Exception:
    # In case backend is already set or environment differs
    pass

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon
import matplotlib.cm as cm
import matplotlib.gridspec as gridspec

# External parser
from sa_rayhits_parser import read_sheet_rows, build_ray_tree


# =============================================================================
# Constants & Types
# =============================================================================

# Real marker chars (no HTML entities)
MARKERS: List[str] = ["o", "s", "^", "D", "P", "*", "x", "v", "<", ">"]

DEFAULT_FIGSIZE = (9, 7)
SCATTER_SIZE = 40

BLOB_FACE_ALPHA = 0.17
BLOB_EDGE_ALPHA = 0.35
BLOB_EDGE_LINEWIDTH = 1.3

HOVER_LINEWIDTH = 2.3
HOVER_EDGECOLOR = "yellow"


# tree typing: tree[ray][bounce][prev] = list[(x, y, z, info_dict, energy)]
RayTree = Dict[str, Dict[Any, Dict[Any, List[Tuple[float, float, float, dict, float]]]]]


@dataclass
class PlotConfig:
    plane_text: str
    flip_2d_axes: bool
    grid_on: bool
    equal_on: bool
    show_blobs: bool
    smooth_blobs: bool
    blob_strength: float

    @property
    def is3d(self) -> bool:
        return self.plane_text.startswith("XYZ")


# =============================================================================
# Geometry helpers
# =============================================================================


def get_sheets(doc) -> List[Any]:
    """Collect Spreadsheet::Sheet objects from a FreeCAD document."""
    return [o for o in doc.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]


def convex_hull_2d(
    xs: Iterable[float], ys: Iterable[float]
) -> List[Tuple[float, float]]:
    """Monotone chain convex hull in 2D."""
    pts = list({(float(x), float(y)) for x, y in zip(xs, ys)})
    if len(pts) <= 1:
        return pts

    pts.sort()

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


def smooth_polygon(
    points: List[Tuple[float, float]], iterations: int = 2
) -> List[Tuple[float, float]]:
    """Chaikin-like corner cutting to get a soft shape."""
    pts = points[:]
    for _ in range(iterations):
        new_pts: List[Tuple[float, float]] = []
        n = len(pts)
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            Q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            R = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new_pts.append(Q)
            new_pts.append(R)
        pts = new_pts
    return pts


def point_to_segment_dist(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    """Min distance between point and line segment."""
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    nx = x1 + t * dx
    ny = y1 + t * dy
    return math.hypot(px - nx, py - ny)


def offset_polygon_adaptive(
    points: List[Tuple[float, float]], strength: float = 0.35
) -> List[Tuple[float, float]]:
    """
    Adaptive outward offset based on local edge length.
    Ensures all original hull points remain inside after offset.
    """
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 3:
        return pts

    out: List[Tuple[float, float]] = []
    for i in range(n):
        # prev, current, next
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]

        # edge lengths
        L_prev = math.hypot(x1 - x0, y1 - y0)
        L_next = math.hypot(x2 - x1, y2 - y1)
        local = max(L_prev, L_next)

        # normals
        nx1, ny1 = y1 - y0, -(x1 - x0)
        d1 = math.hypot(nx1, ny1)
        if d1 > 1e-9:
            nx1 /= d1
            ny1 /= d1

        nx2, ny2 = y2 - y1, -(x2 - x1)
        d2 = math.hypot(nx2, ny2)
        if d2 > 1e-9:
            nx2 /= d2
            ny2 /= d2

        nx = nx1 + nx2
        ny = ny1 + ny2
        dn = math.hypot(nx, ny)
        if dn > 1e-9:
            nx /= dn
            ny /= dn

        margin = local * strength
        out.append((x1 + nx * margin, y1 + ny * margin))

    return out


# =============================================================================
# Color mixer (PrevHit -> alpha, Bounce -> plasma colormap)
# =============================================================================


class ColorMixer:
    """BounceCnt -> perceptual color; PrevHit -> alpha modulation."""

    def __init__(self, prevs: List[Any], bounces: List[Any]):
        self.prev_scale = self._build_prev_alpha(prevs)
        self.bounce_index, self.max_index = self._build_bounce_index(bounces)
        self.cmap = cm.get_cmap("plasma")

    @staticmethod
    def _norm(i: int, n: int) -> float:
        if n <= 1:
            return 1.0
        return i / float(n - 1)

    def _build_prev_alpha(self, prevs: List[Any]) -> Dict[Any, float]:
        return {p: 0.35 + 0.65 * self._norm(i, len(prevs)) for i, p in enumerate(prevs)}

    @staticmethod
    def _build_bounce_index(bounces: List[Any]) -> Tuple[Dict[Any, int], int]:
        bounce_list = sorted(bounces)
        max_index = max(len(bounce_list) - 1, 1)
        return {b: i for i, b in enumerate(bounce_list)}, max_index

    def color(self, prev: Any, bounce: Any) -> Tuple[float, float, float, float]:
        i = self.bounce_index.get(bounce, 0)
        t = i / self.max_index
        r, g, b, _ = self.cmap(t)
        alpha = self.prev_scale.get(prev, 1.0)
        return (r, g, b, alpha)


# =============================================================================
# Dialog
# =============================================================================


class RayHitsPlotDialog(QtWidgets.QDialog):
    """
    Huvuddialog för plottning av RayHits-data med:
      - klickbara punkter med popup
      - valbara Ray-spår (checkboxar)
      - 2D/3D vy
      - mjuka 'blobbar' (konvex-hull + smoothing)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("RayHits Advanced Plot (Click Popup + Blobs)")
        self.resize(1300, 900)

        self._ray_checkboxes: Dict[str, QtWidgets.QCheckBox] = {}
        self._highlighted_scatter = None
        self._pick_cid: Optional[int] = None

        self._init_ui()
        self._connect_signals()

        self.populate_sheets()
        self.reload_plot()

    # --------------------------------------------------------------------- UI

    def _init_ui(self):
        root = QtWidgets.QVBoxLayout(self)

        # Controls
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        # Sheet selector
        top.addWidget(QtWidgets.QLabel("Sheet:"))
        self.cmbSheet = QtWidgets.QComboBox()
        top.addWidget(self.cmbSheet)
        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_data)
        top.addWidget(btnReload)

        top.addSpacing(16)

        # Plane
        top.addWidget(QtWidgets.QLabel("Plane:"))
        self.cmbPlane = QtWidgets.QComboBox()
        self.cmbPlane.addItems(["XY", "XZ", "YZ", "XYZ (3D)"])
        top.addWidget(self.cmbPlane)

        # Toggles
        self.chkFlip = QtWidgets.QCheckBox("Flip axes (2D)")
        top.addWidget(self.chkFlip)

        self.chkGrid = QtWidgets.QCheckBox("Grid")
        self.chkGrid.setChecked(True)
        top.addWidget(self.chkGrid)

        self.chkEqual = QtWidgets.QCheckBox("Equal aspect")
        self.chkEqual.setChecked(True)
        top.addWidget(self.chkEqual)

        self.chkBlobs = QtWidgets.QCheckBox("Show group blobs")
        self.chkBlobs.setChecked(True)
        top.addWidget(self.chkBlobs)

        self.chkBlobSmooth = QtWidgets.QCheckBox("Smooth convex hull")
        self.chkBlobSmooth.setChecked(True)
        top.addWidget(self.chkBlobSmooth)

        top.addWidget(QtWidgets.QLabel("Strength:"))
        self.spnBlobStrength = QtWidgets.QDoubleSpinBox()
        self.spnBlobStrength.setRange(0.01, 1.00)
        self.spnBlobStrength.setSingleStep(0.01)
        self.spnBlobStrength.setValue(0.15)
        self.spnBlobStrength.setDecimals(3)
        self.spnBlobStrength.setToolTip(
            "Controls smooth convex-hull expansion.\n"
            "Lower = tighter; higher = wider/softer.\n"
            "Recommended: 0.10–0.25"
        )
        top.addWidget(self.spnBlobStrength)

        top.addStretch(1)

        # Ray checkboxes container
        self.rayBox = QtWidgets.QGroupBox("Visible Rays")
        self.rayLayout = QtWidgets.QVBoxLayout(self.rayBox)
        root.addWidget(self.rayBox)

        # Figure + Canvas
        self.fig = plt.Figure(figsize=DEFAULT_FIGSIZE)
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas)

        # Status
        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

    def _connect_signals(self):
        self.cmbSheet.currentIndexChanged.connect(self.reload_plot)
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.chkFlip.stateChanged.connect(self.reload_plot)
        self.chkGrid.stateChanged.connect(self.reload_plot)
        self.chkEqual.stateChanged.connect(self.reload_plot)
        self.chkBlobs.stateChanged.connect(self.reload_plot)
        self.chkBlobSmooth.stateChanged.connect(self.reload_plot)
        self.spnBlobStrength.valueChanged.connect(self.reload_plot)

    # --------------------------------------------------------------- Utilities

    def populate_sheets(self):
        doc = App.ActiveDocument
        if not doc:
            return
        sheets = get_sheets(doc)

        def sort_key(s):
            n = s.Label or s.Name
            return (0 if n.startswith("RayHits") else 1, n.lower())

        sheets.sort(key=sort_key)

        self.cmbSheet.blockSignals(True)
        self.cmbSheet.clear()
        for s in sheets:
            name = s.Label or s.Name
            self.cmbSheet.addItem(name, s)
        self.cmbSheet.blockSignals(False)

    def current_sheet(self):
        return self.cmbSheet.currentData()

    def _rebuild_ray_checkboxes(self, tree: RayTree):
        # clear old
        for cb in self._ray_checkboxes.values():
            self.rayLayout.removeWidget(cb)
            cb.deleteLater()
        self._ray_checkboxes.clear()

        for ray in sorted(tree.keys()):
            cb = QtWidgets.QCheckBox(ray)
            cb.setChecked(True)
            cb.stateChanged.connect(self.reload_plot)
            self.rayLayout.addWidget(cb)
            self._ray_checkboxes[ray] = cb

    def reload_data(self):
        self.populate_sheets()
        self.reload_plot()

    def _gather_config(self) -> PlotConfig:
        return PlotConfig(
            plane_text=self.cmbPlane.currentText(),
            flip_2d_axes=self.chkFlip.isChecked(),
            grid_on=self.chkGrid.isChecked(),
            equal_on=self.chkEqual.isChecked(),
            show_blobs=self.chkBlobs.isChecked(),
            smooth_blobs=self.chkBlobSmooth.isChecked(),
            blob_strength=float(self.spnBlobStrength.value()),
        )

    def _show_point_popup(self, info: Dict[str, Any]):
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("RayHit Info")
        dlg.setText(
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

    # ------------------------------------------------------------------- Plot

    def reload_plot(self):
        sheet = self.current_sheet()
        if not sheet:
            self.lblStatus.setText("No sheet selected.")
            return

        try:
            # read sheet & build tree
            rows = read_sheet_rows(sheet)
            tree: RayTree = build_ray_tree(rows)
            self.lblStatus.setText(f"{len(rows)} rows")

            # sync ray checkboxes
            if set(tree.keys()) != set(self._ray_checkboxes.keys()):
                self._rebuild_ray_checkboxes(tree)

            # build layout: 2 rows (plot + legends)
            self.fig.clear()
            gs = gridspec.GridSpec(
                nrows=2, ncols=1, height_ratios=[12, 2], figure=self.fig
            )

            cfg = self._gather_config()
            ax = self._build_axes(gs, cfg)
            ax_leg = self.fig.add_subplot(gs[1, 0])
            ax_leg.set_axis_off()

            # legend scaffolding
            rays = sorted(tree.keys())
            bounces = sorted({b for r in tree.values() for b in r.keys()})
            prevs = sorted(
                {
                    p
                    for r in tree.values()
                    for bounce_dict in r.values()
                    for p in bounce_dict.keys()
                },
                key=lambda s: (s is None, str(s)),
            )

            ray_marker = {r: MARKERS[i % len(MARKERS)] for i, r in enumerate(rays)}
            mixer = ColorMixer(prevs, bounces)

            # plot loop
            scatter_artists = self._draw_groups(ax, tree, ray_marker, mixer, cfg)

            # blobs (2D only)
            if cfg.show_blobs and not cfg.is3d:
                self._draw_blobs(ax, tree, ray_marker, mixer, cfg)

            # legends
            self._build_legends(ax_leg, rays, prevs, mixer, bounces, ray_marker)

            # pick handler (avoid duplicates)
            self._install_pick_handler(scatter_artists)

            self.canvas.draw_idle()

        except Exception as e:
            # Defensive: keep GUI responsive
            self.lblStatus.setText(f"Error: {e}")
            # Optional: print to Report View
            print("RayHitsPlotDialog.reload_plot error:", e)

    def _build_axes(self, gs, cfg: PlotConfig):
        ax = self.fig.add_subplot(gs[0, 0], projection="3d" if cfg.is3d else None)

        # Grid
        if cfg.is3d:
            ax.grid(cfg.grid_on)
            # Equal box aspect if supported
            if cfg.equal_on and hasattr(ax, "set_box_aspect"):
                ax.set_box_aspect([1, 1, 1])
        else:
            if cfg.grid_on:
                ax.grid(True, linestyle="--", alpha=0.35)
            else:
                ax.grid(False)

            # Aspect
            if cfg.equal_on:
                ax.set_aspect("equal", adjustable="datalim")
            else:
                ax.set_aspect("auto")
        return ax

    def _draw_groups(
        self,
        ax,
        tree: RayTree,
        ray_marker: Dict[str, str],
        mixer: ColorMixer,
        cfg: PlotConfig,
    ):
        scatter_artists = []
        for ray, bounce_dict in tree.items():
            cb = self._ray_checkboxes.get(ray)
            if not cb or not cb.isChecked():
                continue

            marker = ray_marker[ray]

            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    color = mixer.color(prev, bounce)

                    xs = [e[0] for e in entries]
                    ys = [e[1] for e in entries]
                    zs = [e[2] for e in entries]
                    infos = [e[3] for e in entries]
                    energies = [e[4] for e in entries]

                    if cfg.is3d:
                        sc = ax.scatter(
                            xs, ys, zs, marker=marker, color=color, s=SCATTER_SIZE
                        )
                    else:
                        px, py = (ys, xs) if cfg.flip_2d_axes else (xs, ys)
                        sc = ax.scatter(
                            px, py, marker=marker, color=color, s=SCATTER_SIZE
                        )

                    # click metadata
                    sc.set_picker(True)
                    sc._pointinfo = []
                    for i in range(len(entries)):
                        info = infos[i] if isinstance(infos[i], dict) else {}
                        sc._pointinfo.append(
                            {
                                "ray": ray,
                                "id": info.get("id"),
                                "prev": prev,
                                "bounce": bounce,
                                "x": xs[i],
                                "y": ys[i],
                                "z": zs[i],
                                "energy": energies[i],
                            }
                        )

                    scatter_artists.append(sc)

        return scatter_artists

    def _draw_blobs(
        self,
        ax,
        tree: RayTree,
        ray_marker: Dict[str, str],  # not used, but kept for parity/extension
        mixer: ColorMixer,
        cfg: PlotConfig,
    ):
        """Draw soft convex-hull blobs per (ray, bounce, prev) group in 2D."""
        # Accumulate per group to honor flip and per-group color
        for ray, bounce_dict in tree.items():
            cb = self._ray_checkboxes.get(ray)
            if not cb or not cb.isChecked():
                continue

            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    color = mixer.color(prev, bounce)
                    xs = [e[0] for e in entries]
                    ys = [e[1] for e in entries]

                    if cfg.flip_2d_axes:
                        px, py = ys, xs
                    else:
                        px, py = xs, ys

                    if len(px) < 1:
                        continue

                    face_rgba = (color[0], color[1], color[2], BLOB_FACE_ALPHA)
                    edge_rgba = (color[0], color[1], color[2], BLOB_EDGE_ALPHA)

                    hull = convex_hull_2d(px, py)
                    if len(hull) < 3:
                        continue

                    if cfg.smooth_blobs:
                        hull2 = offset_polygon_adaptive(
                            hull, strength=cfg.blob_strength
                        )
                        poly_pts = smooth_polygon(hull2, iterations=4)
                    else:
                        poly_pts = hull

                    poly = Polygon(
                        poly_pts,
                        closed=True,
                        facecolor=face_rgba,
                        edgecolor=edge_rgba,
                        linewidth=BLOB_EDGE_LINEWIDTH,
                    )
                    ax.add_patch(poly)

    def _build_legends(
        self,
        ax_leg,
        rays: List[str],
        prevs: List[Any],
        mixer: ColorMixer,
        bounces: List[Any],
        ray_marker: Dict[str, str],
    ):
        # Ray legend (marker)
        ray_handles = [
            Line2D(
                [0],
                [0],
                marker=ray_marker[r],
                linestyle="None",
                color="black",
                markersize=8,
                label=r,
            )
            for r in rays
        ]
        leg1 = ax_leg.legend(
            handles=ray_handles,
            labels=[h.get_label() for h in ray_handles],
            title="Ray (marker)",
            loc="center left",
            bbox_to_anchor=(0.05, 0.5),
            frameon=True,
        )
        ax_leg.add_artist(leg1)

        # PreviousHit (alpha indicated by red-ish intensity)
        prev_handles = [
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                color=(mixer.prev_scale[p], 0.1, 0.1, 0.6),
                markersize=8,
                label=str(p),
            )
            for p in prevs
        ]
        leg2 = ax_leg.legend(
            handles=prev_handles,
            labels=[h.get_label() for h in prev_handles],
            title="PreviousHit (R)",
            loc="center",
            bbox_to_anchor=(0.50, 0.5),
            frameon=True,
            fontsize=8,
        )
        ax_leg.add_artist(leg2)

        # Bounce (plasma colormap)
        bounce_list = sorted(bounces)
        max_index = max(len(bounce_list) - 1, 1)
        bounce_handles = []
        for i, b in enumerate(bounce_list):
            t = i / max_index
            r, g, bb, _ = cm.get_cmap("plasma")(t)
            bounce_handles.append(
                Line2D(
                    [0],
                    [0],
                    marker="o",
                    linestyle="None",
                    color=(r, g, bb, 0.9),
                    markersize=8,
                    label=f"Bounce {b}",
                )
            )
        ax_leg.legend(
            handles=bounce_handles,
            labels=[h.get_label() for h in bounce_handles],
            title="BounceCnt (B)",
            loc="center right",
            bbox_to_anchor=(0.95, 0.5),
            frameon=True,
        )

    # ------------------------------------------------------------- Pick/Popup

    def _install_pick_handler(self, scatter_artists: List[Any]):
        # Remove previous handler to avoid duplicates on reload
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

            # Un-highlight previous
            if self._highlighted_scatter is not None:
                try:
                    self._highlighted_scatter.set_edgecolors("none")
                    self._highlighted_scatter.set_linewidths(1)
                except Exception:
                    pass

            # Highlight current
            try:
                artist.set_edgecolors(HOVER_EDGECOLOR)
                artist.set_linewidths(HOVER_LINEWIDTH)
            except Exception as e:
                print("Highlight error:", e)

            self._highlighted_scatter = artist

            # Show popup
            self._show_point_popup(info)

            self.canvas.draw_idle()

        self._pick_cid = self.fig.canvas.mpl_connect("pick_event", on_pick)


# =============================================================================
# Public API
# =============================================================================


def RH_ShowAdvancedPlot():
    mw = Gui.getMainWindow()
    dlg = RayHitsPlotDialog(parent=mw)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    Gui._rayhits_plot_ref = dlg
    return dlg


# =============================================================================
# FreeCAD Command Registration
# =============================================================================


class Rayhits_PlotCmd:
    def GetResources(self):
        return {
            "Pixmap": os.path.join(
                os.path.dirname(__file__), "icons", "advanced_plot.svg"
            ),
            "MenuText": "RayHits Advanced Plot",
            "ToolTip": "Plot RayHits (click + popup + blobs)",
        }

    def Activated(self):
        RH_ShowAdvancedPlot()

    def IsActive(self):
        return True


Gui.addCommand("SA_Rayhits_Plot", Rayhits_PlotCmd())
