# -*- coding: utf-8 -*-
# sa_rayhits_quality_export.py

import math


def _nn_uniformity(entries):
    """Robust jämnhets-score baserad på nearest-neighbor-distanser. [0..1]."""
    pts = [(e["x"], e["y"], e["z"]) for e in entries]
    n = len(pts)
    if n < 2:
        return 1.0
    nn = []
    for i in range(n):
        x1, y1, z1 = pts[i]
        best = 1e99
        for j in range(n):
            if i == j:
                continue
            x2, y2, z2 = pts[j]
            d = math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2 + (z1 - z2) ** 2)
            if d < best:
                best = d
        nn.append(best)

    mean_d = sum(nn) / n
    if mean_d <= 0:
        return 0.0
    var = sum((d - mean_d) ** 2 for d in nn) / n
    std = math.sqrt(var)
    score = 1.0 - (std / mean_d)
    return max(0.0, min(1.0, score))


def export_group_quality(sheet_name, doc=None, compute_weighted_3d=False):
    """
    Läser radnivådata från 'sheet_name', bygger tree+stats (din parser),
    och skapar/ersätter ark 'RayHits_Quality' med en rad per grupp.
    Kolumner:
        A: Absorber
        B: Ray
        C: Bounce
        D: Previous
        E: Count
        F: Centroid_X
        G: Centroid_Y
        H: Centroid_Z
        I: Uniformity (NN-score 0..1)
        J: Spread_3D_Radius (max dist från centroid)
        K: StdX
        L: StdY
        M: StdZ
        N: QualityVersion
    """
    # ---- 1) Bygg tree + stats via din parser ----
    from sa_rayhits_parser import get_tree_and_stats_for_sheet

    tree, stats = get_tree_and_stats_for_sheet(sheet_name, doc=doc, compute_weighted_3d=compute_weighted_3d)

    # ---- 2) FreeCAD Spreadsheet setup ----
    try:
        import FreeCAD as App
    except Exception as ex:
        raise RuntimeError("FreeCAD is required") from ex

    if doc is None:
        doc = App.ActiveDocument
    if doc is None:
        raise RuntimeError("No active document")

    # Ta bort gammalt blad om det finns
    old = doc.getObject("RayHits_Quality")
    if old:
        doc.removeObject(old.Name)

    sheet = doc.addObject("Spreadsheet::Sheet", "RayHits_Quality")
    # Header
    headers = [
        ("A1", "Absorber"),
        ("B1", "Ray"),
        ("C1", "Bounce"),
        ("D1", "Previous"),
        ("E1", "Count"),
        ("F1", "Centroid_X"),
        ("G1", "Centroid_Y"),
        ("H1", "Centroid_Z"),
        ("I1", "Uniformity"),
        ("J1", "Spread_3D_Radius"),
        ("K1", "StdX"),
        ("L1", "StdY"),
        ("M1", "StdZ"),
        ("N1", "QualityVersion"),
    ]
    for addr, val in headers:
        sheet.set(addr, str(val))

    # ---- 3) Skriv rader (en per grupp) ----
    r = 2
    QUALITY_VERSION = "SA-1"
    for group_id, stat in stats.items():
        absorber, ray, bounce, prev = group_id
        cnt = stat["count"]
        cx, cy, cz = stat["centroid"]["3D"]

        # spread från tidigare patch i build_group_stats (om inte finns -> beräkna minimalt)
        spread = stat.get("spread")
        if spread is None:
            # Minimal fallback: bara radius/std från entries
            # Hämta entries via tree
            entries = []
            try:
                entries = tree[absorber][ray][bounce][prev]
            except KeyError:
                pass
            dxdy_dz = [(e["x"] - cx, e["y"] - cy, e["z"] - cz) for e in entries]
            if dxdy_dz:
                import math

                radius3d = max(math.sqrt(dx**2 + dy**2 + dz**2) for dx, dy, dz in dxdy_dz)
                stdx = math.sqrt(sum(dx * dx for dx, _, _ in dxdy_dz) / len(dxdy_dz))
                stdy = math.sqrt(sum(dy * dy for _, dy, _ in dxdy_dz) / len(dxdy_dz))
                stdz = math.sqrt(sum(dz * dz for _, _, dz in dxdy_dz) / len(dxdy_dz))
            else:
                radius3d = 0.0
                stdx = stdy = stdz = 0.0
        else:
            radius3d = spread["3D"]["radius"]
            stdx, stdy, stdz = spread["3D"]["std"]

        # Uniformity (NN) – robust mot outliers
        # Om du vill undvika att gå via tree här kan du spara entries i stats, men
        # för att hålla minnet nere använder vi tree.
        entries = []
        try:
            entries = tree[absorber][ray][bounce][prev]
        except KeyError:
            pass
        uniformity = _nn_uniformity(entries) if entries else 1.0

        # Skriv rad
        sheet.set(f"A{r}", str(absorber))
        sheet.set(f"B{r}", str(ray))
        sheet.set(f"C{r}", str(bounce))
        sheet.set(f"D{r}", str(prev if prev is not None else ""))

        sheet.set(f"E{r}", str(int(cnt)))
        sheet.set(f"F{r}", f"{cx}")
        sheet.set(f"G{r}", f"{cy}")
        sheet.set(f"H{r}", f"{cz}")

        sheet.set(f"I{r}", f"{uniformity:.6f}")
        sheet.set(f"J{r}", f"{radius3d:.6f}")

        sheet.set(f"K{r}", f"{stdx:.6f}")
        sheet.set(f"L{r}", f"{stdy:.6f}")
        sheet.set(f"M{r}", f"{stdz:.6f}")

        sheet.set(f"N{r}", QUALITY_VERSION)

        r += 1

    sheet.recompute()
    return sheet
