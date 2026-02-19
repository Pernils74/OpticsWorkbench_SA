# -*- coding: utf-8 -*-

# sa_Rayhits_plot.py

"""
RayHits Advanced Plot (Click Popup + Cluster Blobs)
---------------------------------------------------

NO hover
YES click → popup with full info
YES transparent cluster-blobs per (Ray,PrevHit,Bounce) group
YES checkbox to show/hide blobs

Uses:
    rayhits_parser.py   (read_sheet_rows, build_ray_tree)

Plot encodings:
    Marker     = Ray
    FinalColor = RGB mix based on PrevHit (R) + BounceCnt (B) with transparency

Layout:
    Row 0 = main plot
    Row 1 = legends (Ray / PreviousHit / Bounce)
"""

import os
import FreeCAD as App
import FreeCADGui as Gui
from PySide2 import QtWidgets
import math

# matplotlib
import matplotlib

matplotlib.use("Qt5Agg")

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

# External parser
from sa_rayhits_parser import read_sheet_rows, build_ray_tree

# -------------------------------------------------------
# Helpers
# -------------------------------------------------------


def get_sheets(doc):
    return [o for o in doc.Objects if o.isDerivedFrom("Spreadsheet::Sheet")]


# FIX: REAL marker chars
MARKERS = ["o", "s", "^", "D", "P", "*", "x", "v", "<", ">"]


def convex_hull_2d(xs, ys):
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


def smooth_polygon(points, iterations=2):
    pts = points[:]
    for _ in range(iterations):
        new_pts = []
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


def point_to_segment_dist(px, py, x1, y1, x2, y2):
    """Min distance between point and line segment."""
    dx, dy = x2 - x1, y2 - y1
    if dx == dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    nx = x1 + t * dx
    ny = y1 + t * dy
    return math.hypot(px - nx, py - ny)


def offset_polygon_auto(points, all_points=None, K=0.35, M=0.20):
    """
    AUTO–OFFSET polygon:
    - Guarantees ALL original points stay inside after smoothing.
    - Computes margin automatically based on hull tightness.

    points = hull polygon [(x,y)...]
    all_points = all original group points (px,py)
    """

    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 3:
        return pts

    # --- 1) measure hull “tightness” ---
    if all_points:
        min_dist = float("inf")
        for px, py in all_points:
            for i in range(n):
                x1, y1 = pts[i]
                x2, y2 = pts[(i + 1) % n]
                d = point_to_segment_dist(px, py, x1, y1, x2, y2)
                min_dist = min(min_dist, d)
    else:
        min_dist = 0.0

    # --- 2) measure hull size ---
    edge_lengths = [
        math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])
        for i in range(n)
    ]
    avg_len = sum(edge_lengths) / len(edge_lengths)

    # --- 3) Auto margin ---
    #    (higher of “tightness-based” and “scale-based”)
    margin = max(min_dist * K, avg_len * M)

    # --- 4) Expand polygon using averaged normals (corrected version) ---
    out = []
    for i in range(n):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]

        # First normal
        ex1 = x1 - x0
        ey1 = y1 - y0
        nx1 = ey1
        ny1 = -ex1
        d1 = math.hypot(nx1, ny1)
        if d1 > 1e-9:
            nx1 /= d1
            ny1 /= d1

        # Second normal
        ex2 = x2 - x1
        ey2 = y2 - y1
        nx2 = ey2
        ny2 = -ex2
        d2 = math.hypot(nx2, ny2)
        if d2 > 1e-9:
            nx2 /= d2
            ny2 /= d2

        # Combined normal
        nx = nx1 + nx2
        ny = ny1 + ny2
        dn = math.hypot(nx, ny)
        if dn > 1e-9:
            nx /= dn
            ny /= dn

        out.append((x1 + nx * margin, y1 + ny * margin))

    return out


def offset_polygon_adaptive(points, strength=0.35):
    """
    Adaptive outward offset based on local edge length.
    Ensures all points remain inside (used after convex hull).
    """
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 3:
        return pts

    out = []
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
        nx1 = y1 - y0
        ny1 = -(x1 - x0)
        d1 = math.hypot(nx1, ny1)
        if d1 > 1e-9:
            nx1 /= d1
            ny1 /= d1

        nx2 = y2 - y1
        ny2 = -(x2 - x1)
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

        margin = local * strength  # << ADAPTIVT!
        out.append((x1 + nx * margin, y1 + ny * margin))

    return out


# -------------------------------------------------------
# Color mixer (PrevHit -> red, Bounce -> blue)
# -------------------------------------------------------


def build_color_mixer(prevs, bounces):
    """
    NEW COLOR SYSTEM
    ----------------
    BounceCnt -> colormap (plasma)
    PrevHit   -> alpha modulation

    Gives much stronger visual separation between bounce levels.
    """

    import matplotlib.cm as cm

    # Normalize helper
    def norm(i, n):
        if n <= 1:
            return 1.0
        return i / (n - 1)

    # --- PrevHit controls alpha ---
    prev_scale = {p: 0.35 + 0.65 * norm(i, len(prevs)) for i, p in enumerate(prevs)}

    # --- Bounce uses perceptual colormap ---
    bounce_list = sorted(bounces)
    max_index = max(len(bounce_list) - 1, 1)

    bounce_cmap = cm.get_cmap("plasma")

    bounce_index = {b: i for i, b in enumerate(bounce_list)}

    def mix(prev, bounce):
        i = bounce_index.get(bounce, 0)
        t = i / max_index

        r, g, b, _ = bounce_cmap(t)

        alpha = prev_scale.get(prev, 1.0)

        return (r, g, b, alpha)

    return mix, prev_scale, bounce_index


# -------------------------------------------------------
# Main Dialog
# -------------------------------------------------------


class RayHitsPlotDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("RayHits Advanced Plot (Click Popup + Blobs)")
        self.resize(1300, 900)

        root = QtWidgets.QVBoxLayout(self)

        # -----------------------------
        # Controls
        # -----------------------------
        top = QtWidgets.QHBoxLayout()
        root.addLayout(top)

        top.addWidget(QtWidgets.QLabel("Sheet:"))
        self.cmbSheet = QtWidgets.QComboBox()
        top.addWidget(self.cmbSheet)

        btnReload = QtWidgets.QPushButton("Reload")
        btnReload.clicked.connect(self.reload_data)
        top.addWidget(btnReload)

        top.addSpacing(16)
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

        ### BLOB FEATURE: show/hide transparent cluster blobs
        self.chkBlobs = QtWidgets.QCheckBox("Show group blobs")
        self.chkBlobs.setChecked(True)
        top.addWidget(self.chkBlobs)

        # --- Smooth convex-hull blob toggle ---
        self.chkBlobSmooth = QtWidgets.QCheckBox("Smooth convex hull")
        self.chkBlobSmooth.setChecked(True)
        top.addWidget(self.chkBlobSmooth)

        # --- Strength spinbox ---
        top.addWidget(QtWidgets.QLabel("Strength:"))
        self.spnBlobStrength = QtWidgets.QDoubleSpinBox()
        self.spnBlobStrength.setRange(0.01, 1.00)
        self.spnBlobStrength.setSingleStep(0.01)
        self.spnBlobStrength.setValue(0.15)  # default
        self.spnBlobStrength.setDecimals(3)
        top.addWidget(self.spnBlobStrength)
        self.spnBlobStrength.setToolTip(
            "Controls how much the smooth convex-hull blob expands.\n"
            "Lower values = tighter blob (closer to the points).\n"
            "Higher values = wider, softer, more Gaussian-like blob.\n"
            "Recommended range: 0.10–0.25"
        )

        # Knyt signaler
        self.chkBlobSmooth.stateChanged.connect(self.reload_plot)
        self.spnBlobStrength.valueChanged.connect(self.reload_plot)

        top.addStretch(1)

        # -----------------------------
        # Ray checkboxes
        # -----------------------------
        self.rayBox = QtWidgets.QGroupBox("Visible Rays")
        self.rayLayout = QtWidgets.QVBoxLayout(self.rayBox)
        root.addWidget(self.rayBox)
        self.ray_checkboxes = {}

        # -----------------------------
        # Figure + Canvas
        # -----------------------------
        self.fig = plt.Figure(figsize=(9, 7))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        root.addWidget(self.toolbar)
        root.addWidget(self.canvas)

        self.lblStatus = QtWidgets.QLabel("")
        root.addWidget(self.lblStatus)

        # Signals
        self.cmbSheet.currentIndexChanged.connect(self.reload_plot)
        self.cmbPlane.currentIndexChanged.connect(self.reload_plot)
        self.chkFlip.stateChanged.connect(self.reload_plot)
        self.chkGrid.stateChanged.connect(self.reload_plot)
        self.chkEqual.stateChanged.connect(self.reload_plot)
        self.chkBlobs.stateChanged.connect(self.reload_plot)

        self.populate_sheets()
        self.reload_plot()

        self._highlighted_scatter = None

    # -------------------------------------------------------
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

    # -------------------------------------------------------
    def rebuild_ray_checkboxes(self, tree):
        for cb in self.ray_checkboxes.values():
            self.rayLayout.removeWidget(cb)
            cb.deleteLater()

        self.ray_checkboxes.clear()

        for ray in sorted(tree.keys()):
            cb = QtWidgets.QCheckBox(ray)
            cb.setChecked(True)
            cb.stateChanged.connect(self.reload_plot)
            self.rayLayout.addWidget(cb)
            self.ray_checkboxes[ray] = cb

    def reload_data(self):
        self.populate_sheets()
        self.reload_plot()

    # -------------------------------------------------------
    def show_point_popup(self, info):
        dlg = QtWidgets.QMessageBox(self)
        dlg.setWindowTitle("RayHit Info")
        dlg.setText(
            f"Ray: {info['ray']}\n"
            f"RayId: {info['id']}\n"
            f"PreviousHit: {info['prev']}\n"
            f"BounceCnt: {info['bounce']}\n\n"
            f"X = {info['x']}\n"
            f"Y = {info['y']}\n"
            f"Z = {info['z']}\n"
            f"Energy = {info['energy']}\n"
        )
        dlg.exec_()

    # -------------------------------------------------------
    # MAIN PLOT
    # -------------------------------------------------------

    def reload_plot(self):
        sheet = self.current_sheet()
        if not sheet:
            return

        # 1) Läs data och bygg träd: tree[ray][bounce][prev] = [(x,y,z,info,en)]
        rows = read_sheet_rows(sheet)
        tree = build_ray_tree(rows)

        self.lblStatus.setText(f"{len(rows)} rows")

        # Synka Ray-checkboxar (om rays ändrats)
        if set(tree.keys()) != set(self.ray_checkboxes.keys()):
            self.rebuild_ray_checkboxes(tree)

        # 2) Layout: två rader (plott överst, legender underst)
        self.fig.clear()
        import matplotlib.gridspec as gridspec

        gs = gridspec.GridSpec(nrows=2, ncols=1, height_ratios=[12, 2], figure=self.fig)

        plane = self.cmbPlane.currentText()
        is3d = plane.startswith("XYZ")
        ax = self.fig.add_subplot(gs[0, 0], projection="3d" if is3d else None)
        # ax.grid(self.chkGrid.isChecked(), linestyle="--", alpha=0.35)

        # =======================
        # GRID HANDLING (2D/3D)
        # =======================
        grid_on = self.chkGrid.isChecked()
        equal_on = self.chkEqual.isChecked()

        if is3d:
            # --- GRID ---
            ax.grid(grid_on)

            # --- ASPECT ---
            if equal_on and hasattr(ax, "set_box_aspect"):
                ax.set_box_aspect([1, 1, 1])

        else:
            # --- GRID ---
            if grid_on:
                ax.grid(True, linestyle="--", alpha=0.35)
            else:
                ax.grid(False)

            # --- ASPECT ---
            if equal_on:
                ax.set_aspect("equal", adjustable="datalim")
            else:
                ax.set_aspect("auto")

        ax_leg = self.fig.add_subplot(gs[1, 0])
        ax_leg.set_axis_off()

        flip = self.chkFlip.isChecked()
        # equal = self.chkEqual.isChecked()
        show_blobs = self.chkBlobs.isChecked()

        # 3) Legend-underlag (matchar ray -> bounce -> prev)
        rays = sorted(tree.keys())
        # nivå 2 = bounce
        bounces = sorted({b for r in tree.values() for b in r.keys()})
        # nivå 3 = prev
        prevs = sorted(
            {
                p
                for r in tree.values()
                for bounce_dict in r.values()
                for p in bounce_dict.keys()
            },
            key=lambda s: (s is None, str(s)),
        )

        # Stilmappar
        ray_marker = {r: MARKERS[i % len(MARKERS)] for i, r in enumerate(rays)}
        mix_color, prev_scale, bounce_scale = build_color_mixer(prevs, bounces)

        scatter_artists = []
        group_points_2D = []  # (px, py, rgba, prev, bounce) för blobbar

        # 4) Plott-loop: Ray -> Bounce -> Prev
        for ray, bounce_dict in tree.items():
            cb = self.ray_checkboxes.get(ray)
            if not cb or not cb.isChecked():
                continue

            marker = ray_marker[ray]

            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    # Färg från (prev, bounce)
                    color = mix_color(prev, bounce)  # (r,g,b,alpha)

                    # Packa koordinater + metadata
                    xs = [e[0] for e in entries]
                    ys = [e[1] for e in entries]
                    zs = [e[2] for e in entries]
                    infos = [e[3] for e in entries]  # dict med ray/id/prev/bounce
                    energies = [e[4] for e in entries]  # OBS: energy ligger på index 4

                    if is3d:
                        sc = ax.scatter(xs, ys, zs, marker=marker, color=color, s=40)
                    else:
                        px, py = (ys, xs) if flip else (xs, ys)
                        sc = ax.scatter(px, py, marker=marker, color=color, s=40)

                        # Spara för blobritning (2D)
                        if show_blobs:
                            group_points_2D.append((px, py, color, prev, bounce))

                    # Klickbar + metadata för popups
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

        # ------------------------------------
        # Soft convex hull blobs (2D only)
        # ------------------------------------
        if show_blobs and not is3d:
            do_smooth = self.chkBlobSmooth.isChecked()
            strength_val = self.spnBlobStrength.value()

            for px, py, base_color, prev, bounce in group_points_2D:
                if len(px) < 1:
                    continue

                # Colors
                face_rgba = (base_color[0], base_color[1], base_color[2], 0.17)
                edge_rgba = (base_color[0], base_color[1], base_color[2], 0.35)

                # Step 1: convex hull
                hull = convex_hull_2d(px, py)
                if len(hull) < 3:
                    # fallback för 1–2 punkter
                    continue

                # Step 2: offset
                if do_smooth:
                    hull2 = offset_polygon_adaptive(hull, strength=strength_val)
                    # Step 3: smoothing
                    smooth = smooth_polygon(hull2, iterations=4)
                    poly_pts = smooth
                else:
                    # raw hull only
                    poly_pts = hull

                # Step 4: draw blob polygon
                poly = Polygon(
                    poly_pts,
                    closed=True,
                    facecolor=face_rgba,
                    edgecolor=edge_rgba,
                    linewidth=1.3,
                )
                ax.add_patch(poly)

        # 7) Legender (under plotten, tre block)
        # Ray (marker)
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

        # PreviousHit (R)
        prev_handles = [
            Line2D(
                [0],
                [0],
                marker="o",
                linestyle="None",
                color=(prev_scale[p], 0.1, 0.1, 0.6),
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

        import matplotlib.cm as cm

        bounce_cmap = cm.get_cmap("plasma")

        bounce_list = sorted(bounces)
        max_index = max(len(bounce_list) - 1, 1)

        bounce_handles = []

        for i, b in enumerate(bounce_list):
            t = i / max_index
            r, g, bb, _ = bounce_cmap(t)

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

        leg3 = ax_leg.legend(
            handles=bounce_handles,
            labels=[h.get_label() for h in bounce_handles],
            title="BounceCnt (B)",
            loc="center right",
            bbox_to_anchor=(0.95, 0.5),
            frameon=True,
        )

        # 8) Klick-hanterare: highlight av grupp + popup
        def on_pick(event):
            artist = event.artist
            idx = event.ind[0]
            info = artist._pointinfo[idx]

            # Avmarkera tidigare highlight
            if self._highlighted_scatter is not None:
                try:
                    self._highlighted_scatter.set_edgecolors("none")
                    self._highlighted_scatter.set_linewidths(1)
                except Exception:
                    pass

            # Highlighta denna grupp
            try:
                artist.set_edgecolors("yellow")
                artist.set_linewidths(2.3)
            except Exception as e:
                print("Highlight error:", e)

            self._highlighted_scatter = artist

            # Visa popup
            self.show_point_popup(info)

            self.canvas.draw_idle()

        self.fig.canvas.mpl_connect("pick_event", on_pick)

        # 9) Rendera
        self.canvas.draw_idle()


# -------------------------------------------------------
# SHOW DIALOG
# -------------------------------------------------------


def RH_ShowAdvancedPlot():
    mw = Gui.getMainWindow()
    dlg = RayHitsPlotDialog(parent=mw)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    Gui._rayhits_plot_ref = dlg
    return dlg


# -------------------------------------------------------
# REGISTER FREECAD COMMAND
# -------------------------------------------------------


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
