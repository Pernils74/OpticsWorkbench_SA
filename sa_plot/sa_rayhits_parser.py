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
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))  # absorber  # ray  # bounce  # prev -> [entries]

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

                    # Oviktade medel (centroid)
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

                    # ----------------------------------------------------------------
                    # 🔥 NYTT: Beräkna kluster-SPRIDNING (“spread”) i alla dimensioner
                    # ----------------------------------------------------------------
                    # Avstånd från centroid
                    dx = [e["x"] - cx for e in entries]
                    dy = [e["y"] - cy for e in entries]
                    dz = [e["z"] - cz for e in entries]

                    # Standardavvikelser
                    import math

                    std_x = math.sqrt(sum(d * d for d in dx) / count)
                    std_y = math.sqrt(sum(d * d for d in dy) / count)
                    std_z = math.sqrt(sum(d * d for d in dz) / count)

                    # Maxradius i 3D (bra för densitets-score)
                    radius_3d = max(math.sqrt(dx[i] ** 2 + dy[i] ** 2 + dz[i] ** 2) for i in range(count))

                    # Maxradius i 2D-plan
                    radius_xy = max(math.sqrt(dx[i] ** 2 + dy[i] ** 2) for i in range(count))
                    radius_xz = max(math.sqrt(dx[i] ** 2 + dz[i] ** 2) for i in range(count))
                    radius_yz = max(math.sqrt(dy[i] ** 2 + dz[i] ** 2) for i in range(count))

                    # Kovarianser (oviktat)
                    def cov(a, b):
                        return sum(a[i] * b[i] for i in range(count)) / count

                    stat["spread"] = {
                        "XY": {"std": (std_x, std_y), "radius": radius_xy, "cov": [[cov(dx, dx), cov(dx, dy)], [cov(dy, dx), cov(dy, dy)]]},
                        "XZ": {"std": (std_x, std_z), "radius": radius_xz, "cov": [[cov(dx, dx), cov(dx, dz)], [cov(dz, dx), cov(dz, dz)]]},
                        "YZ": {"std": (std_y, std_z), "radius": radius_yz, "cov": [[cov(dy, dy), cov(dy, dz)], [cov(dz, dy), cov(dz, dz)]]},
                        "3D": {
                            "std": (std_x, std_y, std_z),
                            "radius": radius_3d,
                            "cov": [
                                [cov(dx, dx), cov(dx, dy), cov(dx, dz)],
                                [cov(dy, dx), cov(dy, dy), cov(dy, dz)],
                                [cov(dz, dx), cov(dz, dy), cov(dz, dz)],
                            ],
                        },
                    }
                    # ----------------------------------------------------------------

                    # (Din befintliga energiviktning lämnas orörd)
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
def get_tree_and_stats_for_sheet(sheet_name: str, doc=None, compute_weighted_3d: bool = False):
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


# -------------------------------------------------------------
# EXPORT: skriv grupp-nivå "stats" till ett nytt Spreadsheet-blad
# -------------------------------------------------------------
def _unique_sheet_name(doc, base_name):
    """Returnera ett ledigt namn som börjar på base_name, t.ex. 'RayHits_Stats', 'RayHits_Stats001', ..."""
    existing = {o.Name for o in getattr(doc, "Objects", []) if o.isDerivedFrom("Spreadsheet::Sheet")}
    if base_name not in existing:
        return base_name
    i = 1
    while True:
        cand = f"{base_name}{i:03d}"
        if cand not in existing:
            return cand
        i += 1


def export_group_stats_to_sheet(
    sheet_name: str,
    doc=None,
    compute_weighted_3d: bool = False,
    target_prefix: str | None = None,
):
    """
    Läser radnivåblad 'sheet_name' (Name/Label eller prefix),
    bygger (tree, stats) och skriver ett *kompakt* gruppblad:
       <prefix>_Stats  (t.ex. 'RayHits_Stats')
    Kolumner:
       A: Absorber
       B: Ray
       C: Bounce
       D: Previous
       E: Count
       F: Centroid_X
       G: Centroid_Y
       H: Centroid_Z
       I: FirstIndex
       J: LastIndex
       K: Spread3D_Radius         (om spread finns)
       L: Spread3D_StdX
       M: Spread3D_StdY
       N: Spread3D_StdZ
    Returnerar det skapade Spreadsheet-objektet.
    """
    try:
        import FreeCAD as App
    except Exception as ex:
        raise RuntimeError("FreeCAD is required for spreadsheet export") from ex

    if doc is None:
        doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active FreeCAD document")

    # 1) Hämta tree + stats
    tree, stats = get_tree_and_stats_for_sheet(sheet_name, doc=doc, compute_weighted_3d=compute_weighted_3d)

    # 2) Bestäm prefix: om inte angivet → använd det användaren gav (trimma whitespace)
    base = (target_prefix if target_prefix else sheet_name or "").strip()
    if not base:
        base = "RayHits"

    # 3) Skapa nytt bladnamn som börjar på <prefix>_Stats
    out_base = f"{base}_Stats"
    out_name = _unique_sheet_name(doc, out_base)

    # 4) Skapa blad
    sheet_out = doc.addObject("Spreadsheet::Sheet", out_name)

    # 5) Header
    headers = [
        ("A1", "Absorber"),
        ("B1", "Ray"),
        ("C1", "Bounce"),
        ("D1", "Previous"),
        ("E1", "Ray Count"),
        ("F1", "Centroid_X"),
        ("G1", "Centroid_Y"),
        ("H1", "Centroid_Z"),
        ("I1", "FirstIndex"),
        ("J1", "LastIndex"),
        ("K1", "Spread3D_Radius"),
        ("L1", "Spread3D_StdX"),
        ("M1", "Spread3D_StdY"),
        ("N1", "Spread3D_StdZ"),
    ]
    for addr, text in headers:
        sheet_out.set(addr, text)

    # 6) Sortera grupper i samma ordning som dina rader (via first_index)
    items = list(stats.items())
    items.sort(key=lambda kv: kv[1].get("first_index", 10**9))

    r = 2
    for group_id, stat in items:
        absorber, ray, bounce, prev = group_id
        cnt = stat.get("count", 0)
        cx, cy, cz = stat.get("centroid", {}).get("3D", (0.0, 0.0, 0.0))
        first_idx = stat.get("first_index", "")
        last_idx = stat.get("last_index", "")

        # spread (om din tidigare patch är på plats)
        radius3d = ""
        stdx = stdy = stdz = ""
        spread = stat.get("spread")
        if spread and "3D" in spread:
            radius3d = spread["3D"]["radius"]
            (stdx, stdy, stdz) = spread["3D"]["std"]

        # skriv raden
        sheet_out.set(f"A{r}", str(absorber))
        sheet_out.set(f"B{r}", str(ray))
        sheet_out.set(f"C{r}", str(bounce))
        sheet_out.set(f"D{r}", "" if prev is None else str(prev))
        sheet_out.set(f"E{r}", str(int(cnt)))
        sheet_out.set(f"F{r}", f"{cx}")
        sheet_out.set(f"G{r}", f"{cy}")
        sheet_out.set(f"H{r}", f"{cz}")
        sheet_out.set(f"I{r}", str(first_idx))
        sheet_out.set(f"J{r}", str(last_idx))
        sheet_out.set(f"K{r}", "" if radius3d == "" else f"{radius3d}")
        sheet_out.set(f"L{r}", "" if stdx == "" else f"{stdx}")
        sheet_out.set(f"M{r}", "" if stdy == "" else f"{stdy}")
        sheet_out.set(f"N{r}", "" if stdz == "" else f"{stdz}")

        r += 1

    sheet_out.recompute()
    return sheet_out
