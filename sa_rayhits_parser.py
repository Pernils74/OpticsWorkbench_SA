# -*- coding: utf-8 -*-
# sa_rayhits_parser.py
#
# Bygger både datastruktur ("tree") och sammanställd gruppstatistik ("stats").
#
# TREE:
# tree[absorber][ray][bounce][prev] = [
#     {
#         "id": int,                     # original Id per träff
#         "x": float, "y": float, "z": float,
#         "energy": float|None,
#         "coords": {                    # färdiga projektioner för plotting
#             "XY": (x, y),
#             "XZ": (x, z),
#             "YZ": (y, z),
#             "3D": (x, y, z)
#         },
#         "prev": prev,
#         "bounce": bounce,
#         "ray": ray,
#         "absorber": absorber,
#         "info": dict|None,             # tolkad rayinfo
#         "sort_index": int,             # radindex från arket (bevarar ordning)
#         "group_id": (absorber, ray, bounce, prev)  # STABILT unikt grupp-ID (tuple)
#     },
#     ...
# ]
#
# STATS:
# stats[group_id] = {
#     "group_id": (absorber, ray, bounce, prev),
#     "absorber": absorber,
#     "ray": ray,
#     "bounce": bounce,
#     "prev": prev,
#     "count": int,
#     "centroid": {                     # oviktade centroider
#         "XY": (cx, cy),
#         "XZ": (cx, cz),
#         "YZ": (cy, cz),
#         "3D": (cx, cy, cz),
#     },
#     # Följande nycklar läggs ENDAST till om compute_weighted_3d=True:
#     # "centroid_weighted_3D": (wx, wy, wz),
#     # "centroid_weighted": {
#     #     "XY": (wx, wy),
#     #     "XZ": (wx, wz),
#     #     "YZ": (wy, wz),
#     # },
#     "first_index": int,               # min sort_index i gruppen
#     "last_index": int,                # max sort_index i gruppen
# }
#
# Topp-funktion:
#     get_tree_and_stats_for_sheet(sheet_name, doc=None, compute_weighted_3d=False)
# → Returnerar (tree, stats)
#
# -----------------------------------------------------------------------------

# Use case:

# from sa_rayhits_parser import get_tree_and_stats_for_sheet

# tree, stats = get_tree_and_stats_for_sheet("RayHits_Mirror003", compute_weighted_3d=False)

# # Exempel: iterera grupper
# for absorber, ray_dict in tree.items():
#     for ray, bounce_dict in ray_dict.items():
#         for bounce, prev_dict in bounce_dict.items():
#             for prev, entries in prev_dict.items():
#                 gid = (absorber, ray, bounce, prev)
#                 group_info = stats.get(gid, {})
#                 print(gid, "count:", group_info.get("count"), "centroid 2D XY:", group_info.get("centroid", {}).get("XY"))
# -----------------------------------------------------------------------------


from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple, Optional


# -------------------------------------------------------------
# Hjälpare: hitta sheet efter Name eller Label (case-insensitive)
# -------------------------------------------------------------
def _find_sheet_by_name_or_label(sheet_name: str, doc=None):
    """
    Returnerar Spreadsheet::Sheet efter Name eller Label (case-insensitive).
    Stöttar även "börjar med" om exakt träff saknas.
    """
    try:
        import FreeCAD as App
    except Exception:
        App = None

    if doc is None and App is not None:
        doc = App.ActiveDocument

    if doc is None:
        raise RuntimeError("No active FreeCAD document found.")

    target = (sheet_name or "").casefold().strip()
    if not target:
        raise ValueError("sheet_name is empty.")

    # 1) Direkt via Name
    obj = doc.getObject(sheet_name) if hasattr(doc, "getObject") else None
    if obj and obj.isDerivedFrom("Spreadsheet::Sheet"):
        return obj

    # 2) Sök via Name/Label (exakt, case-insensitive)
    for o in getattr(doc, "Objects", []):
        try:
            if not o.isDerivedFrom("Spreadsheet::Sheet"):
                continue
            nm = (o.Name or "").casefold()
            lb = (o.Label or "").casefold()
            if nm == target or lb == target:
                return o
        except Exception:
            continue

    # 3) "Börjar med" om exakt träff saknas
    for o in getattr(doc, "Objects", []):
        try:
            if not o.isDerivedFrom("Spreadsheet::Sheet"):
                continue
            nm = (o.Name or "").casefold()
            lb = (o.Label or "").casefold()
            if nm.startswith(target) or lb.startswith(target):
                return o
        except Exception:
            continue

    raise LookupError(f"Spreadsheet '{sheet_name}' not found (by Name or Label).")


# -------------------------------------------------------------
# Parse RayInfo-string: "sa_Ray=Beam;Id=1;PreviousHit=A;BounceCnt=2"
# -------------------------------------------------------------
def parse_rayinfo(cell: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(cell, str):
        return None

    parts: Dict[str, str] = {}
    for p in cell.split(";"):
        if "=" in p:
            k, v = p.split("=", 1)
            parts[k.strip()] = v.strip()

    try:
        return {
            "ray": parts.get("sa_Ray"),
            "id": int(parts["Id"]) if "Id" in parts else None,
            "prev": parts.get("PreviousHit"),
            "bounce": int(parts["BounceCnt"]) if "BounceCnt" in parts else None,
        }
    except Exception:
        return None


# -------------------------------------------------------------
# Läs data-rader ur sheet → list of (absorber, x,y,z, info, energy, row_index)
# -------------------------------------------------------------
def read_sheet_rows(
    sheet,
) -> List[Tuple[Any, float, float, float, dict, Optional[float], int]]:
    rows: List[Tuple[Any, float, float, float, dict, Optional[float], int]] = []
    r = 2  # hoppa header (rad 1)

    while True:
        try:
            absorber = sheet.get(f"A{r}")
        except Exception:
            break

        if not absorber:
            break

        info = parse_rayinfo(sheet.get(f"B{r}"))

        try:
            x = float(sheet.get(f"C{r}"))
            y = float(sheet.get(f"D{r}"))
            z = float(sheet.get(f"E{r}"))
        except Exception:
            r += 1
            continue

        try:
            en = float(sheet.get(f"F{r}"))
        except Exception:
            en = None

        rows.append((absorber, x, y, z, info, en, r))
        r += 1

    return rows


# -------------------------------------------------------------
# Bygg TREE: absorber → ray → bounce → prev → entries[]
#  + lägg till stabilt group_id (tuple) på varje entry
# -------------------------------------------------------------
def build_ray_tree(rows):
    """
    Skapar hierarki och bevarar radordning via 'sort_index'.
    Lägger till 'group_id' = (absorber, ray, bounce, prev) på varje entry.
    """
    data = defaultdict(  # absorber
        lambda: defaultdict(  # ray
            lambda: defaultdict(  # bounce
                lambda: defaultdict(list)  # prev -> [entries]
            )
        )
    )

    for absorber, x, y, z, info, en, row_idx in rows:
        if not info:
            continue

        ray = info["ray"]
        pid = info["id"]
        prev = info["prev"]
        bounce = info["bounce"]

        group_id = (absorber, ray, bounce, prev)  # STABILT unikt grupp-ID

        coords = {
            "XY": (x, y),
            "XZ": (x, z),
            "YZ": (y, z),
            "3D": (x, y, z),
        }

        entry = {
            "id": pid,
            "x": x,
            "y": y,
            "z": z,
            "energy": en,
            "coords": coords,
            "prev": prev,
            "bounce": bounce,
            "ray": ray,
            "absorber": absorber,
            "info": info,
            "sort_index": row_idx,
            "group_id": group_id,
        }

        data[absorber][ray][bounce][prev].append(entry)

    return data


# -------------------------------------------------------------
# Bygg STATS per grupp:
#  - samma group_id (tuple) som på entries
#  - oviktade centroider i XY/XZ/YZ/3D alltid
#  - (valfritt) energiviktad 3D-centroid med projicerade planvärden
# -------------------------------------------------------------
def build_group_stats(tree, compute_weighted_3d: bool = False):
    stats: Dict[Tuple[Any, Any, Any, Any], Dict[str, Any]] = {}

    for absorber, ray_dict in tree.items():
        for ray, bounce_dict in ray_dict.items():
            for bounce, prev_dict in bounce_dict.items():
                for prev, entries in prev_dict.items():
                    if not entries:
                        continue

                    group_id = (absorber, ray, bounce, prev)
                    count = len(entries)

                    # Oviktade medel
                    sum_x = sum(e["x"] for e in entries)
                    sum_y = sum(e["y"] for e in entries)
                    sum_z = sum(e["z"] for e in entries)
                    cx = sum_x / count
                    cy = sum_y / count
                    cz = sum_z / count

                    first_idx = min(e.get("sort_index", 10**9) for e in entries)
                    last_idx = max(e.get("sort_index", -(10**9)) for e in entries)

                    stat = {
                        "group_id": group_id,
                        "absorber": absorber,
                        "ray": ray,
                        "bounce": bounce,
                        "prev": prev,
                        "count": count,
                        "centroid": {
                            "XY": (cx, cy),
                            "XZ": (cx, cz),
                            "YZ": (cy, cz),
                            "3D": (cx, cy, cz),
                        },
                        "first_index": first_idx,
                        "last_index": last_idx,
                    }

                    # Valfritt: energiviktad 3D-centroid + projicerade plan
                    if compute_weighted_3d:
                        total_w = 0.0
                        wx = wy = wz = 0.0
                        for e in entries:
                            w = e["energy"] if e["energy"] is not None else 1.0
                            wx += e["x"] * w
                            wy += e["y"] * w
                            wz += e["z"] * w
                            total_w += w
                        if total_w > 0:
                            wx /= total_w
                            wy /= total_w
                            wz /= total_w
                        else:
                            wx, wy, wz = cx, cy, cz

                        stat["centroid_weighted_3D"] = (wx, wy, wz)
                        stat["centroid_weighted"] = {
                            "XY": (wx, wy),
                            "XZ": (wx, wz),
                            "YZ": (wy, wz),
                        }

                    stats[group_id] = stat

    return stats


# -------------------------------------------------------------
# TOPP-FUNKTION: ta sheetname och returnera (tree, stats)
# -------------------------------------------------------------
def get_tree_and_stats_for_sheet(
    sheet_name: str, doc=None, compute_weighted_3d: bool = False
):
    """
    :param sheet_name: Name eller Label för Spreadsheet::Sheet (case-insensitive)
    :param doc: FreeCAD-dokument (default App.ActiveDocument)
    :param compute_weighted_3d: om True, lägg till energiviktade centroider i stats
    :return: (tree, stats)
             tree  = data[absorber][ray][bounce][prev] = [entry, ...]
             stats = dict[group_id(tuple)] -> stat-dict
    """
    sheet = _find_sheet_by_name_or_label(sheet_name, doc=doc)
    rows = read_sheet_rows(sheet)
    tree = build_ray_tree(rows)
    stats = build_group_stats(tree, compute_weighted_3d=compute_weighted_3d)
    return tree, stats
