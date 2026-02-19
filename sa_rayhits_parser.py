# rayhits_parser.py

from collections import defaultdict


# NEW STRUCTURE:
# data[ray][bounceCnt][previousHit] = list of points


# Ray
#  ├── BounceCount = 0
#  │     ├── PrevHit = A
#  │     └── PrevHit = B
#  ├── BounceCount = 1
#  │     ├── PrevHit = A
#  │     └── PrevHit = B
#  └── BounceCount = 2
#    ├── PrevHit = A
#    └── PrevHit = B


def parse_rayinfo(cell):
    if not isinstance(cell, str):
        return None

    parts = {}
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
    except:
        return None


def read_sheet_rows(sheet):
    rows = []
    r = 2

    while True:
        try:
            a = sheet.get(f"A{r}")
        except:
            break

        if not a:
            break

        info = parse_rayinfo(sheet.get(f"B{r}"))

        try:
            x = float(sheet.get(f"C{r}"))
            y = float(sheet.get(f"D{r}"))
            z = float(sheet.get(f"E{r}"))
        except:
            r += 1
            continue

        try:
            en = float(sheet.get(f"F{r}"))
        except:
            en = None

        rows.append((x, y, z, info, en))
        r += 1

    return rows


def build_ray_tree(rows):
    """
    Returns:

    data[ray][bounceCnt][previousHit] = [points]
    """

    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for x, y, z, info, en in rows:
        if not info:
            continue

        ray = info["ray"]
        bounce = info["bounce"]
        prev = info["prev"]

        data[ray][bounce][prev].append((x, y, z, info, en))

    return data


#
#
# Bygg en struktur som grupperar alla träffar per Ray, och där varje träff har en unik ID-nyckel.
# För varje grupp (Ray + BounceCount + PreviousHit) beräknas ett "group_center" och "group_extent" (maxavstånd från center).
#


def build_ray_groups_by_id(rows):
    """
    Returns structure grouped by Ray, with unique ID keys:

    {
      ray_name : {
         id : {
            "x": float, "y": float, "z": float,
            "energy": float|None,
            "prev": str|None,
            "bounce": int|None,
            "ray": str|None,
            "info": dict|None,
            "group_center": (cx, cy, cz),
            "group_extent": float,
            "is_outlier": bool
         },
         ...
      }
    }
    """
    import math

    tree = build_ray_tree(rows)
    out = {}

    for ray, bdict in tree.items():
        out[ray] = {}

        for bounce, pdict in bdict.items():
            for prev, entries in pdict.items():

                xs = [e[0] for e in entries]
                ys = [e[1] for e in entries]
                zs = [e[2] for e in entries]

                if len(xs) >= 1:
                    cx = sum(xs) / len(xs)
                    cy = sum(ys) / len(ys)
                    cz = sum(zs) / len(zs)
                else:
                    cx = cy = cz = 0.0

                dmax = 0.0
                for x, y, z in zip(xs, ys, zs):
                    dx = x - cx
                    dy = y - cy
                    dz = z - cz
                    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
                    dmax = max(dmax, dist)

                # Enkel spridnings‑heuristik → "är gruppen utspretad?"
                is_outlier = dmax > 3.5 * (dmax / len(xs) if len(xs) > 1 else 0.1)

                for x, y, z, info, en in entries:
                    pid = info.get("id") if isinstance(info, dict) else None
                    if pid is None:
                        # Fallback om Id saknas: syntetisk, men stabil för sessionen
                        pid = id(info)

                    out[ray][pid] = {
                        "x": x,
                        "y": y,
                        "z": z,
                        "energy": en,
                        "prev": prev,
                        "bounce": bounce,
                        "ray": ray,
                        "info": info,
                        "group_center": (cx, cy, cz),
                        "group_extent": dmax,
                        "is_outlier": is_outlier,
                    }

    return out


def _find_sheet_by_name_or_label(sheet_name, doc=None):
    """
    Return a Spreadsheet::Sheet by Name or Label (case-insensitive).
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

    # 2) Sök via Name/Label (case-insensitive)
    for o in doc.Objects:
        try:
            if not o.isDerivedFrom("Spreadsheet::Sheet"):
                continue
            nm = (o.Name or "").casefold()
            lb = (o.Label or "").casefold()
            if nm == target or lb == target:
                return o
        except Exception:
            continue

    # 3) Ingen exakt träff → försök "börjar med"
    for o in doc.Objects:
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


def build_ray_groups_by_id_for_sheet(sheet_name, skip_outlier_groups=False, doc=None):
    """
    Convenience wrapper: read rows from sheet (by name/label), then build Ray->ID structure.

    :param sheet_name: Name or Label of the Spreadsheet::Sheet
    :param skip_outlier_groups: if True, drop IDs that belong to groups flagged as outlier
    :param doc: optional FreeCAD document; defaults to App.ActiveDocument
    :return: dict[ray][id] -> point/meta info
    """
    sheet = _find_sheet_by_name_or_label(sheet_name, doc=doc)
    rows = read_sheet_rows(sheet)
    by_id = build_ray_groups_by_id(rows)

    if not skip_outlier_groups:
        return by_id

    # Filtrera bort alla id-poster vars grupp markerats som outlier
    filtered = {}
    for ray, idmap in by_id.items():
        keep = {
            pid: pdata
            for pid, pdata in idmap.items()
            if not pdata.get("is_outlier", False)
        }
        filtered[ray] = keep
    return filtered
