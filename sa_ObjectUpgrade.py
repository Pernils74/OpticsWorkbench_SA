# -*- coding: utf-8 -*-
# sa_ObjectUpgrade.py

from FreeCAD import activeDocument, Vector
import sa_Ray
import sa_OpticalObject as OpticalObject
import FreeCAD as App


from sa_OpticsWorkbench import WORKBENCH_ID


def _tag_new_object(fp):
    if not hasattr(fp, "WorkbenchId"):
        fp.addProperty(
            "App::PropertyString",
            "WorkbenchId",
            "Base",
            "Which workbench created this object",
        )
    fp.WorkbenchId = WORKBENCH_ID


def _rebuild_ray(obj):
    """Rebuilds a sa_
    Ray/Beam/Emitter using the SA workbench."""
    doc = activeDocument()

    fp = doc.addObject("Part::FeaturePython", obj.Name)
    _tag_new_object(fp)

    # Copy placement
    fp.Placement = obj.Placement

    # Safe property extraction
    spherical = getattr(obj, "Spherical", False)
    beamNrColumns = getattr(obj, "BeamNrColumns", 1)
    beamNrRows = getattr(obj, "BeamNrRows", 1)
    beamDistance = getattr(obj, "BeamDistance", 0.1)
    hideFirst = getattr(obj, "HideFirst", False)
    maxRayLength = getattr(obj, "MaxRayLength", 1000000)
    maxNrReflections = getattr(obj, "MaxNrReflections", 200)
    wavelength = getattr(obj, "Wavelength", 580)
    order = getattr(obj, "Order", 0)
    coneAngle = getattr(obj, "ConeAngle", 360)
    ignoredElements = getattr(obj, "IgnoredElements", [])
    baseShape = getattr(obj, "BaseShape", None)
    focalPoint = getattr(obj, "FocalPoint", Vector(0, 0, 100))
    rayBundleType = getattr(obj, "RayBundleType", "")

    # Build new SA-ray
    sa_Ray.RayWorker(
        fp,
        getattr(obj, "Power", True),
        spherical,
        beamNrColumns,
        beamNrRows,
        beamDistance,
        hideFirst,
        maxRayLength,
        maxNrReflections,
        wavelength,
        order,
        coneAngle,
        ignoredElements,
        baseShape,
        focalPoint,
        rayBundleType,
    )

    # Preserve old label  don't work
    fp.Label = obj.Label

    sa_Ray.RayViewProvider(fp.ViewObject)

    # Remove old object
    doc.removeObject(obj.Name)

    return fp


def _rebuild_optical(obj):
    """Rebuild Mirror/Lens/Absorber/Grating using SA-Workbench safely."""

    from sa_OpticalObject import OpticalObjectWorker, LensWorker, GratingWorker

    doc = activeDocument()

    otype = getattr(obj, "OpticalType", "mirror").lower()

    # Create new object with same name
    fp = doc.addObject("Part::FeaturePython", obj.Name)
    _tag_new_object(fp)

    # --- Safe extraction of common attributes ---
    base = []
    if hasattr(obj, "Base"):
        try:
            if isinstance(obj.Base, list):
                base = obj.Base
            else:
                base = [obj.Base]
        except Exception:
            base = []

    collectStatistics = getattr(obj, "collectStatistics", False)
    transparency = getattr(obj, "Transparency", 0)

    # COMMON MATERIAL PROPS (Lens + Grating)
    RefractionIndex = getattr(obj, "RefractionIndex", 1.0)
    Material = getattr(obj, "Material", "Quartz")
    Sellmeier = getattr(obj, "Sellmeier", [])

    # GRATING PROPS
    lpm = getattr(obj, "lpm", 500)
    GratingType = getattr(obj, "GratingType", "reflection")
    GratingLinesPlane = getattr(obj, "GratingLinesPlane", App.Vector(0, 1, 0))
    order = getattr(obj, "order", 1)
    ray_order_override = getattr(obj, "ray_order_override", False)

    # ---------- Build correct SA-object ----------
    if otype in ("mirror", "absorber"):
        OpticalObjectWorker(
            fp,
            base,
            type=otype,
            collectStatistics=collectStatistics,
            transparency=transparency,
        )

    elif otype == "lens":
        LensWorker(
            fp,
            base,
            RefractionIndex,
            Material,
            collectStatistics,
            transparency=transparency,
        )
        if Sellmeier:
            fp.Sellmeier = Sellmeier

    elif otype == "grating":
        GratingWorker(
            fp,
            base,
            RefractionIndex,
            Material,
            lpm,
            GratingType,
            GratingLinesPlane,
            order,
            ray_order_override,
            collectStatistics,
            transparency,
        )
        if Sellmeier:
            fp.Sellmeier = Sellmeier

    # Preserve old label  don't work
    fp.Label = obj.Label

    # --- ViewProvider ---
    try:
        from sa_OpticalObject import OpticalObjectViewProvider

        OpticalObjectViewProvider(fp.ViewObject)
    except Exception:
        pass

    # Copy placement
    fp.Placement = obj.Placement

    # Remove old object
    doc.removeObject(obj.Name)

    return fp


def upgrade_objects():
    doc = activeDocument()
    upgraded = []

    for obj in list(doc.Objects):

        # Skip already upgraded objects
        if hasattr(obj, "WorkbenchId") and obj.WorkbenchId == WORKBENCH_ID:
            continue

        # ---- RAY ----
        if hasattr(obj, "Power") and hasattr(obj, "BeamNrColumns"):
            try:
                new = _rebuild_ray(obj)
                upgraded.append(new)
            except Exception as e:
                print("sa_Ray upgrade failed for", obj.Name, e)
            continue

        # ---- OPTICAL ----
        try:
            # if sa_
            # Ray.isOpticalObject(obj):
            if hasattr(obj, "OpticalType"):
                try:
                    new = _rebuild_optical(obj)
                    upgraded.append(new)
                except Exception as e:
                    print("Optical upgrade failed for", obj.Name, e)
        except Exception:
            pass

    doc.recompute()
    return upgraded
