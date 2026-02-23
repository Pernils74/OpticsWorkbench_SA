# -*- coding: utf-8 -*-
# sa_OpticsWorkbench.py

import os
import FreeCAD
import FreeCADGui

from FreeCAD import Vector, Rotation, activeDocument

import sa_Ray
import sa_OpticalObject
import SunRay
from numpy import linspace
from importlib import reload
import rayhits_plot


# Global workbench ID for tagging created objects
WORKBENCH_ID = "sa_Workbench_v0.9"


def recompute():
    activeDocument().recompute()


def get_module_path():
    """Returns the current module path.
    Determines where this file is running from, so works regardless of whether
    the module is installed in the app's module directory or the user's app data folder.
    (The second overrides the first.)
    """
    return os.path.dirname(__file__)


def _tag_new_object(fp):
    if not hasattr(fp, "WorkbenchId"):
        fp.addProperty(
            "App::PropertyString",
            "WorkbenchId",
            "Base",
            "Which workbench created this object",
        )
    fp.WorkbenchId = WORKBENCH_ID


def makeRay(
    position=Vector(0, 0, 0),
    direction=Vector(1, 0, 0),
    power=True,
    beamNrColumns=1,
    beamNrRows=1,
    beamDistance=0.1,
    spherical=False,
    hideFirst=False,
    maxRayLength=1000000,
    maxNrReflections=200,
    wavelength=580,
    order=0,
    coneAngle=360,
    ignoredElements=[],
    baseShape=None,
    focalPoint=Vector(0, 0, 100),
    rayBundleType="",
):
    reload(sa_Ray)
    """Python command to create a light ray."""
    name = "sa_Ray"
    if beamNrColumns * beamNrRows > 1:
        name = "Beam"
    if baseShape:
        name = "Emitter"

    fp = activeDocument().addObject("Part::FeaturePython", name)
    _tag_new_object(fp)
    fp.Placement.Base = position
    fp.Placement.Rotation = Rotation(Vector(1, 0, 0), direction)
    sa_Ray.RayWorker(
        fp,
        power,
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
    sa_Ray.RayViewProvider(fp.ViewObject)
    recompute()
    return fp


def makeSunRay(
    position=Vector(0, 0, 0),
    direction=Vector(1, 0, 0),
    power=True,
    beamNrColumns=1,
    beamNrRows=1,
    beamDistance=0.1,
    spherical=False,
    hideFirst=False,
    maxRayLength=1000000,
    maxNrReflections=900,
    wavelength_from=450,
    wavelength_to=750,
    num_rays=70,
    order=1,
    ignoredElements=[],
):
    reload(SunRay)
    rays = []
    for l in linspace(wavelength_from, wavelength_to, num_rays):
        ray = makeRay(
            position=position,
            direction=direction,
            power=power,
            beamNrColumns=beamNrColumns,
            beamNrRows=beamNrRows,
            beamDistance=beamDistance,
            spherical=spherical,
            hideFirst=hideFirst,
            maxRayLength=maxRayLength,
            maxNrReflections=maxNrReflections,
            wavelength=l,
            order=order,
            ignoredElements=ignoredElements,
        )
        ray.ViewObject.LineWidth = 1
        rays.append(ray)

    fp = activeDocument().addObject("Part::FeaturePython", "SunRay")
    _tag_new_object(fp)

    SunRay.SunRayWorker(fp, rays)
    SunRay.SunRayViewProvider(fp.ViewObject)
    recompute()
    return fp

    # reload(sa_Ray)
    # doc = activeDocument()
    # rays = []
    # for l in linspace(wavelength_from, wavelength_to, num_rays):
    #     ray = makeRay(position = position,
    #         direction = direction,
    #         power = power,
    #         beamNrColumns=beamNrColumns,
    #         beamNrRows=beamNrRows,
    #         beamDistance=beamDistance,
    #         spherical=spherical,
    #         hideFirst = hideFirst,
    #         maxRayLength = maxRayLength,
    #         maxNrReflections = maxNrReflections,
    #         wavelength = l,
    #         order = order)
    #     ray.ViewObject.LineWidth = 1
    #     rays.append(ray)

    # group = doc.addObject('App::DocumentObjectGroup','SunRay')
    # group.Group = rays
    # recompute()


# def restartAll():
#     for obj in activeDocument().Objects:
#         if isRay(obj):
#             obj.Power = True
#             obj.touch()

#     recompute()


def restartAll():
    from PySide import QtWidgets
    import sa_ObjectUpgrade  # NEW

    doc = activeDocument()
    missing_id_objects = []  # saknar attributet WorkbenchId
    wrong_version_objects = []  # har WorkbenchId men fel värde

    # Check all objects
    for obj in doc.Objects:
        if isRay(obj) or sa_Ray.isOpticalObject(obj):
            if not hasattr(obj, "WorkbenchId"):
                missing_id_objects.append(obj)
            elif obj.WorkbenchId != WORKBENCH_ID:
                wrong_version_objects.append(obj)

    # Bygg meddelande om något behöver uppgraderas
    objects_to_upgrade = missing_id_objects + wrong_version_objects
    if objects_to_upgrade:
        lines = []

        if missing_id_objects:
            lines.append("The following objects were created in the ORIGINAL OpticsWorkBench:\n")
            for o in missing_id_objects:
                lines.append(f"- {o.Label}")
            lines.append("")  # tom rad

        if wrong_version_objects:
            lines.append("The following objects were created with an older/different version of the SA Workbench:\n")
            for o in wrong_version_objects:
                # visa även det detekterade id:t för tydlighet
                try:
                    wb_id = getattr(o, "WorkbenchId", None)
                except Exception:
                    wb_id = None
                lines.append(f"- {o.Label} (WorkbenchId={wb_id})")
            lines.append("")

        lines.append("Do you want to automatically rebuild them using the SA_Workbench?")
        msg = "\n".join(lines)

        reply = QtWidgets.QMessageBox.question(
            None,
            "SA Workbench Upgrade",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )

        if reply == QtWidgets.QMessageBox.Yes:
            sa_ObjectUpgrade.upgrade_objects()

    # Turn on rays
    for obj in activeDocument().Objects:
        if isRay(obj):
            obj.Power = True
            obj.touch()

    recompute()


def allOff():
    for obj in activeDocument().Objects:
        if isRay(obj):
            obj.Power = False

        elif sa_Ray.isOpticalObject(obj):
            for a in dir(obj):
                if (
                    a.startswith("HitsFrom")
                    or a.startswith("HitCoordsFrom")
                    or a.startswith("EnergyFrom")
                    # added properties for better ray tracking
                    or a.startswith("BounceCountFrom")
                    or a.startswith("RayIdFrom")
                    or a.startswith("BounceHistoryFrom")
                    or a.startswith("PreviousHitFrom")
                ):
                    obj.removeProperty(a)

    recompute()


def makeMirror(base=[], collectStatistics=False, transparency=0):
    # reload(sa_OpticalObject)
    """All FreeCAD objects in base will be optical mirrors."""
    fp = activeDocument().addObject("Part::FeaturePython", "Mirror")
    _tag_new_object(fp)

    sa_OpticalObject.OpticalObjectWorker(
        fp,
        base,
        type="mirror",
        collectStatistics=collectStatistics,
        transparency=transparency,
    )

    sa_OpticalObject.OpticalObjectViewProvider(fp.ViewObject)
    recompute()
    return fp


def makeAbsorber(base=[], collectStatistics=False, transparency=0):
    # reload(sa_OpticalObject)
    """All FreeCAD objects in base will be optical light absorbers."""
    fp = activeDocument().addObject("Part::FeaturePython", "Absorber")
    _tag_new_object(fp)

    sa_OpticalObject.OpticalObjectWorker(
        fp,
        base,
        type="absorber",
        collectStatistics=collectStatistics,
        transparency=transparency,
    )
    sa_OpticalObject.OpticalObjectViewProvider(fp.ViewObject)
    recompute()
    return fp


def makeLens(
    base=[],
    RefractionIndex=0,
    material="Quartz",
    collectStatistics=False,
    transparency=100,
):
    # reload(sa_OpticalObject)
    """All FreeCAD objects in base will be optical lenses."""
    fp = activeDocument().addObject("Part::FeaturePython", "Lens")
    _tag_new_object(fp)
    sa_OpticalObject.LensWorker(
        fp,
        base,
        RefractionIndex,
        material,
        collectStatistics,
        transparency=transparency,
    )
    sa_OpticalObject.OpticalObjectViewProvider(fp.ViewObject)
    recompute()
    return fp


def makeGrating(
    base=[],
    RefractionIndex=1,
    material="",
    lpm=500,
    GratingType="reflection",
    GratingLinesPlane=Vector(0, 1, 0),
    order=1,
    collectStatistics=False,
):
    # reload(sa_OpticalObject)
    """All FreeCAD objects in base will be diffraction gratings."""
    fp = activeDocument().addObject("Part::FeaturePython", "Grating")
    _tag_new_object(fp)
    sa_OpticalObject.GratingWorker(
        fp,
        base,
        RefractionIndex,
        material,
        lpm,
        GratingType,
        GratingLinesPlane,
        order,
        collectStatistics,
    )
    sa_OpticalObject.OpticalObjectViewProvider(fp.ViewObject)
    recompute()
    return fp


def isRay(obj):
    return hasattr(obj, "Power") and hasattr(obj, "BeamNrColumns")


def plot_xy(absorber):
    import numpy as np
    import matplotlib.pyplot as plt

    coords = []
    attr_names = [attr for attr in dir(absorber) if attr.startswith("HitCoordsFrom")]
    coords_per_beam = [getattr(absorber, attr) for attr in attr_names]
    all_coords = np.array([coord for coords in coords_per_beam for coord in coords])
    print("attr_names", attr_names)
    print("coords_per_beam", coords_per_beam)
    print("all_coords", all_coords)

    x = -all_coords[:, 1]
    y = all_coords[:, 2]

    if len(all_coords) > 0:
        plt.scatter(x, y)
        plt.show()


def drawPlot(selectedObjList):
    ## Create the list of selected absorbers; if none then skip
    rayhits_plot.PlotRayHits.plot3D(selectedObjList)


def Hits2CSV(sheet_name=None, setFocus=True):
    doc = activeDocument()

    # --- 1) Select or create sheet ---
    sheet = None
    if sheet_name and isinstance(sheet_name, str) and sheet_name.strip():
        target = None
        for obj in doc.Objects:
            if getattr(obj, "TypeId", "") == "Spreadsheet::Sheet":
                if obj.Name == sheet_name or getattr(obj, "Label", "") == sheet_name:
                    target = obj

        if target:
            sheet = target
            try:
                sheet.clearAll()
            except Exception:
                pass
        else:
            sheet = doc.addObject("Spreadsheet::Sheet", sheet_name)
            sheet.Label = sheet.Name
    else:
        sheet = doc.addObject("Spreadsheet::Sheet", "RayHits")
        sheet.Label = sheet.Name

    # --- 2) Headers ---
    sheet.set("A1", "Absorber")
    sheet.set("B1", "sa_Ray;Id;PreviousHit;BounceCnt")
    sheet.set("C1", "X-axis")
    sheet.set("D1", "Y-axis")
    sheet.set("E1", "Z-axis")
    sheet.set("F1", "Energy %")

    row = 1

    # --- 3) Data writing ---
    for eachObject in doc.Objects:
        if sa_Ray.isOpticalObject(eachObject):
            for attr in dir(eachObject):
                if attr.startswith("HitCoordsFrom"):
                    ray_name = attr[13:]  # after "HitCoordsFrom"
                    coords = getattr(eachObject, attr)

                    energy_attr = "EnergyFrom" + ray_name
                    bounce_attr = "BounceCountFrom" + ray_name
                    rayid_attr = "RayIdFrom" + ray_name
                    previous_attr = "PreviousHitFrom" + ray_name

                    #     f"Processing {eachObject.Label} - {ray_name} with {len(coords)} hits"
                    # )
                    print(f"Looking for attributes: {energy_attr}, {bounce_attr}, {rayid_attr}, {previous_attr}")

                    energy = getattr(eachObject, energy_attr, None)
                    bounces = getattr(eachObject, bounce_attr, None)
                    rayids = getattr(eachObject, rayid_attr, None)
                    previous = getattr(eachObject, previous_attr, None)

                    print(f"Found energy: {energy is not None}, bounces: {bounces is not None}, rayids: {rayids is not None}, previous: {previous is not None}")

                    for i, co in enumerate(coords):
                        row += 1

                        # A – absorber
                        sheet.set(f"A{row}", eachObject.Label)

                        # # B – RayName:RayId
                        # rid_val = int(rid_val)

                        sheet.set(
                            f"B{row}",
                            f"sa_Ray={ray_name};"
                            f"Id={rayids[i] if rayids is not None and i < len(rayids) else ''};"
                            f"PreviousHit={previous[i] if previous is not None and i < len(previous) else ''};"
                            f"BounceCnt={bounces[i] if bounces is not None and i < len(bounces) else ''}",
                        )

                        # if rayids is not None and i < len(rayids):
                        #     rid_val = rayids[i]
                        #     try:
                        #         rid_val = int(rid_val)
                        #     except:
                        #         pass
                        #     sheet.set(f"B{row}", f"{ray_name}:{rid_val}")
                        # else:
                        #     sheet.set(f"B{row}", ray_name)

                        # C–E – coordinates
                        sheet.set(f"C{row}", str(co[0]))
                        sheet.set(f"D{row}", str(co[1]))
                        sheet.set(f"E{row}", str(co[2]))

                        # F – energy
                        if energy is not None and i < len(energy):
                            sheet.set(f"F{row}", str(energy[i]))
                        else:
                            sheet.set(f"F{row}", "")

                        # G – bounce count
                        # if bounces is not None and i < len(bounces):
                        #     try:
                        #         b_val = int(bounces[i])
                        #     except:
                        #         b_val = bounces[i]
                        #     sheet.set(f"G{row}", str(b_val))
                        # else:
                        #     sheet.set(f"G{row}", "")

    sheet.recompute()
    if setFocus:
        sheet.ViewObject.doubleClicked()
