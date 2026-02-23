# -*- coding: utf-8 -*-
# plot_core.py — ren matplotlib-kärna för RayHits-plottning (ingen Qt)

from __future__ import annotations
from typing import Dict, Any, List, Tuple
import math

import matplotlib.cm as cm
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon


# --------------------------
# Geometrihjälpare (2D hull)
# --------------------------
def convex_hull_2d(xs, ys):
    pts = list({(float(a), float(b)) for a, b in zip(xs, ys)})
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
        new = []
        n = len(pts)
        for i in range(n):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            Q = (0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1])
            R = (0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1])
            new.append(Q)
            new.append(R)
        pts = new
    return pts


def offset_polygon_adaptive(points, strength=0.35):
    pts = [(float(x), float(y)) for x, y in points]
    n = len(pts)
    if n < 3:
        return pts

    out = []
    for i in range(n):
        x0, y0 = pts[i - 1]
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]

        L_prev = math.hypot(x1 - x0, y1 - y0)
        L_next = math.hypot(x2 - x1, y2 - y1)
        local = max(L_prev, L_next)

        nx1, ny1 = (y1 - y0), -(x1 - x0)
        d1 = math.hypot(nx1, ny1)
        if d1 > 1e-9:
            nx1 /= d1
            ny1 /= d1

        nx2, ny2 = (y2 - y1), -(x2 - x1)
        d2 = math.hypot(nx2, ny2)
        if d2 > 1e-9:
            nx2 /= d2
            ny2 /= d2

        nx = nx1 + nx2
        ny = ny1 + ny2
        d = math.hypot(nx, ny)
        if d > 1e-9:
            nx /= d
            ny /= d

        margin = local * strength
        out.append((x1 + nx * margin, y1 + ny * margin))

    return out


# --------------------------
# Färgmodell (Prev → alpha, Bounce → plasma)
# --------------------------
class ColorMixer:
    def __init__(self, prevs, bounces):
        self.prev_scale = {
            p: 0.35 + 0.65 * (i / max(1, len(prevs) - 1)) for i, p in enumerate(prevs)
        }
        self.bounce_index = {b: i for i, b in enumerate(sorted(bounces))}
        self.max_index = max(len(bounces) - 1, 1)
        self.cmap = cm.get_cmap("plasma")

    def color(self, prev, bounce):
        idx = self.bounce_index.get(bounce, 0)
        t = idx / self.max_index
        r, g, b, _ = self.cmap(t)
        a = self.prev_scale.get(prev, 1.0)
        return (r, g, b, a)


# --------------------------
# Plot-kärn-funktioner
# --------------------------
def compute_domains_for_legend(tree):
    bounces = set()
    prevs = set()
    rays = set()
    for absorber, ray_dict in tree.items():
        for ray, bounce_dict in ray_dict.items():
            rays.add(ray)
            for b, prev_dict in bounce_dict.items():
                bounces.add(b)
                prevs |= set(prev_dict.keys())
    return (
        sorted(rays),
        sorted(bounces),
        sorted(prevs, key=lambda s: (s is None, str(s))),
    )


def draw_points(
    ax,
    tree,
    plane_key: str,
    is3d: bool,
    flip2d: bool,
    absorber_on: Dict[str, bool],
    ray_on: Dict[str, bool],
    ray_marker: Dict[str, str],
    mixer: ColorMixer,
    scatter_size: int = 40,
):
    """Ritar punkter per (absorber→ray→bounce→prev). Returnerar listan av PathCollections för pick."""
    artists = []

    for absorber, ray_dict in tree.items():
        if absorber_on and not absorber_on.get(absorber, True):
            continue

        for ray, bounce_dict in ray_dict.items():
            if ray_on and not ray_on.get(ray, True):
                continue

            marker = ray_marker.get(ray, "o")

            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    color = mixer.color(prev, bounce)

                    coords = [e["coords"][plane_key] for e in entries]

                    if is3d:
                        xs = [c[0] for c in coords]
                        ys = [c[1] for c in coords]
                        zs = [c[2] for c in coords]
                        sc = ax.scatter(
                            xs, ys, zs, marker=marker, color=color, s=scatter_size
                        )
                    else:
                        xs = [c[0] for c in coords]
                        ys = [c[1] for c in coords]
                        if flip2d:
                            xs, ys = ys, xs
                        sc = ax.scatter(
                            xs, ys, marker=marker, color=color, s=scatter_size
                        )

                    # pick-metadata
                    sc.set_picker(True)
                    sc._pointinfo = [
                        {
                            "absorber": e.get("absorber"),
                            "ray": e.get("ray"),
                            "id": e.get("id"),
                            "prev": e.get("prev"),
                            "bounce": e.get("bounce"),
                            "x": e.get("x"),
                            "y": e.get("y"),
                            "z": e.get("z"),
                            "energy": e.get("energy"),
                        }
                        for e in entries
                    ]

                    artists.append(sc)

    return artists


def draw_blobs_2d(
    ax,
    tree,
    plane_key: str,
    flip2d: bool,
    absorber_on: Dict[str, bool],
    ray_on: Dict[str, bool],
    mixer: ColorMixer,
    smooth: bool,
    strength: float,
    face_alpha: float = 0.17,
    edge_alpha: float = 0.35,
    lw: float = 1.3,
):
    """Ritar mjuka convex-hull-blobs per grupp (2D)."""
    for absorber, ray_dict in tree.items():
        if absorber_on and not absorber_on.get(absorber, True):
            continue

        for ray, bounce_dict in ray_dict.items():
            if ray_on and not ray_on.get(ray, True):
                continue

            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    color = mixer.color(prev, bounce)
                    coords = [e["coords"][plane_key] for e in entries]
                    xs = [c[0] for c in coords]
                    ys = [c[1] for c in coords]
                    if flip2d:
                        xs, ys = ys, xs
                    if len(xs) < 3:
                        continue

                    hull = convex_hull_2d(xs, ys)
                    if len(hull) < 3:
                        continue

                    if smooth:
                        hull2 = offset_polygon_adaptive(hull, strength=strength)
                        poly_pts = smooth_polygon(hull2, iterations=4)
                    else:
                        poly_pts = hull

                    face_rgba = (color[0], color[1], color[2], face_alpha)
                    edge_rgba = (color[0], color[1], color[2], edge_alpha)
                    ax.add_patch(
                        Polygon(
                            poly_pts,
                            closed=True,
                            facecolor=face_rgba,
                            edgecolor=edge_rgba,
                            linewidth=lw,
                        )
                    )


def draw_centroids(
    ax,
    stats: Dict[tuple, dict],
    plane_key: str,
    is3d: bool,
    flip2d: bool,
    absorber_on: Dict[str, bool],
    ray_on: Dict[str, bool],
    size: int = 160,
    face="none",
    edge="black",
    lw: float = 1.2,
    weighted: bool = False,
):
    """
    Ritar centroider per grupp. Om weighted=True och viktade centroider finns i stats,
    projiceras den viktade 3D-centroiden till planet, annars används oviktad.
    """
    for gid, s in stats.items():
        absorber = s["absorber"]
        ray = s["ray"]
        if absorber_on and not absorber_on.get(absorber, True):
            continue
        if ray_on and not ray_on.get(ray, True):
            continue

        if weighted and "centroid_weighted_3D" in s:
            wx, wy, wz = s["centroid_weighted_3D"]
            if plane_key == "3D" and is3d:
                cx, cy, cz = wx, wy, wz
            elif plane_key == "XY":
                cx, cy = wx, wy
                cz = None
            elif plane_key == "XZ":
                cx, cy = wx, wz
                cz = None
            elif plane_key == "YZ":
                cx, cy = wy, wz
                cz = None
            else:
                cx = cy = cz = None
        else:
            # oviktad centroid
            c = s["centroid"]
            if plane_key == "3D" and is3d:
                cx, cy, cz = c["3D"]
            else:
                cx, cy = c[plane_key]
                cz = None

        if cx is None:
            continue

        if is3d and cz is not None:
            ax.scatter(
                [cx],
                [cy],
                [cz],
                s=size,
                marker="o",
                facecolor=face,
                edgecolor=edge,
                linewidth=lw,
            )
        else:
            if flip2d:
                cx, cy = cy, cx
            ax.scatter(
                [cx],
                [cy],
                s=size,
                marker="o",
                facecolor=face,
                edgecolor=edge,
                linewidth=lw,
            )


def build_legends(
    ax_leg, rays_sorted, prevs_sorted, bounces_sorted, ray_marker, mixer: ColorMixer
):
    # Rays
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
        for r in rays_sorted
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

    # PreviousHit (alpha hint)
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
        for p in prevs_sorted
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

    # Bounce (plasma)
    cmap = cm.get_cmap("plasma")
    bounce_list = bounces_sorted
    max_index = max(len(bounce_list) - 1, 1)
    bounce_handles = []
    for i, b in enumerate(bounce_list):
        t = i / max_index
        r, g, bb, _ = cmap(t)
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
