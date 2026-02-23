# -*- coding: utf-8 -*-
# example_herriott.py   (SA-version)

from pydoc import doc
import FreeCAD as App
import FreeCADGui as Gui

# import Part
# import Spreadsheet
import sa_LiveSheets

import sa_OpticsWorkbench
import sa_plot.sa_Rayhits_plot
from FreeCAD import Vector, Placement, Rotation
from PySide import QtWidgets
import os
import math

# Icon directory
_icondir_ = os.path.join(os.path.dirname(__file__), "..")


# ======================================================================
# MAIN FUNCTION – entire Herriott cell logic
# ======================================================================


def make_herriott():

    # Always create a NEW document when running this example
    doc = App.newDocument("HerriottCell")

    # ------------------------------------------------------------
    # 1. Spreadsheet values
    # ------------------------------------------------------------
    ss = doc.addObject("Spreadsheet::Sheet", "Spreadsheet")
    ss.set("A1", "Mirror radius (R)")
    ss.set("B1", "250 mm")

    ss.set("A2", "Distance between mirrors (D)")
    ss.set("B2", "230 mm")

    ss.set("A3", "Mirror diameter (W)")
    ss.set("B3", "100 mm")

    ss.set("A4", "Thickness (T)")
    ss.set("B4", "20 mm")

    ss.set("A5", "Hole radius")
    ss.set("B5", "10 mm")

    ss.set("A6", "Hole offset (X)")
    ss.set("B6", "60 mm")

    doc.recompute()

    # ------------------------------------------------------------
    # Create mirror base (concave)
    # ------------------------------------------------------------
    def create_mirror_base(name):
        cyl = doc.addObject("Part::Cylinder", name + "_Body")
        cyl.setExpression("Radius", "Spreadsheet.B3")
        cyl.setExpression("Height", "Spreadsheet.B4")

        sph = doc.addObject("Part::Sphere", name + "_Sphere")
        sph.setExpression("Radius", "Spreadsheet.B1")
        sph.setExpression("Placement.Base.z", "Spreadsheet.B1")

        cut = doc.addObject("Part::Cut", name + "_Concave")
        cut.Base = cyl
        cut.Tool = sph
        cyl.Visibility = False
        sph.Visibility = False
        return cut

    # ------------------------------------------------------------
    # 2. Mirror 1 with entrance hole
    # ------------------------------------------------------------
    m1_base = create_mirror_base("Mirror1_Base")

    hole_cyl = doc.addObject("Part::Cylinder", "BeamHole")
    hole_cyl.setExpression("Radius", "Spreadsheet.B5")
    hole_cyl.setExpression("Height", "Spreadsheet.B4 * 2")
    hole_cyl.setExpression("Placement.Base.x", "Spreadsheet.B6")
    hole_cyl.Placement.Base.z = -5

    mirror1 = doc.addObject("Part::Cut", "Mirror1")
    mirror1.Base = m1_base
    mirror1.Tool = hole_cyl
    m1_base.Visibility = False
    hole_cyl.Visibility = False

    # Slight transparency so ray path is visible
    mirror1.ViewObject.Transparency = 70
    mirror1.ViewObject.ShapeColor = (0.7, 0.7, 0.8)

    # ------------------------------------------------------------
    # 3. Mirror 2 (180° rotated)
    # ------------------------------------------------------------
    mirror2 = create_mirror_base("Mirror2")
    mirror2.Placement.Rotation = Rotation(Vector(1, 0, 0), 180)
    mirror2.setExpression("Placement.Base.z", "Spreadsheet.B2")

    # ------------------------------------------------------------
    # 4. Convert to optical objects
    # ------------------------------------------------------------
    sa_OpticsWorkbench.makeMirror([mirror1], collectStatistics=True)
    sa_OpticsWorkbench.makeMirror([mirror2])

    # ------------------------------------------------------------
    # 5. Ray configuration (Euler z-y-x)
    # ------------------------------------------------------------
    yaw_deg = 8.0
    pitch_deg = -4.0
    roll_deg = 11.0

    rotZ = Rotation(Vector(0, 0, 1), yaw_deg)
    rotY = Rotation(Vector(0, 1, 0), pitch_deg)
    rotX = Rotation(Vector(1, 0, 0), roll_deg)

    rot = rotZ * rotY * rotX
    dir_vector = rot.multVec(Vector(0, 0, 1))

    # ------------------------------------------------------------
    # 6. Create the ray
    # ------------------------------------------------------------
    ray = sa_OpticsWorkbench.makeRay(
        Vector(35, 0, 10),
        dir_vector,
        beamNrColumns=4,
        beamNrRows=4,
        rayBundleType="focal",
        beamDistance=0.5,
        maxRayLength=300,
        maxNrReflections=15,
        focalPoint=(0, 0, 5),
    )
    # ray.Label = "InputRay"

    ray.Placement = Placement(ray.Placement.Base, rot)
    ray.setExpression("Placement.Base.x", "Spreadsheet.B6")
    ray.Placement.Base.z = 10

    doc.recompute()

    # Small directional offset
    yaw2 = yaw_deg + 2.5
    pitch2 = pitch_deg - 1.5
    roll2 = roll_deg

    rotZ2 = Rotation(Vector(0, 0, 1), yaw2)
    rotY2 = Rotation(Vector(0, 1, 0), pitch2)
    rotX2 = Rotation(Vector(1, 0, 0), roll2)

    rot2 = rotZ2 * rotY2 * rotX2
    dir_vector2 = rot2.multVec(Vector(0, 0, 1))

    ray2 = sa_OpticsWorkbench.makeRay(
        Vector(35, 0, 10),  # same start point
        dir_vector2,
        beamNrColumns=2,  # fewer rays
        beamNrRows=2,
        rayBundleType="focal",
        beamDistance=0.5,
        maxRayLength=300,
        maxNrReflections=15,
        focalPoint=(0, 0, 5),
    )

    # ray2.Label = "InputRay_2"

    ray2.Placement = Placement(ray2.Placement.Base, rot2)
    ray2.setExpression("Placement.Base.x", "Spreadsheet.B6")
    ray2.Placement.Base.z = 10

    doc.recompute()

    # ------------------------------------------------------------
    # 7. Camera setup
    # ------------------------------------------------------------

    view = App.Gui.ActiveDocument.ActiveView

    # Predefined isometric quaternion
    iso_rot = Rotation(0.11591698929143902, 0.8804762329080508, 0.2798481572676507, -0.3647051737384002)
    view.setCameraOrientation(iso_rot.Q)
    view.fitAll()

    # ------------------------------------------------------------
    # 8. RayHits Export + Plot
    # ------------------------------------------------------------
    sa_OpticsWorkbench.Hits2CSV()
    sa_LiveSheets.SA_ShowLiveSheetsDock()

    sa_plot.sa_Rayhits_plot.RH_ShowAdvancedPlot()

    return True


# ======================================================================
# COMMAND CLASS (same structure as Example2D, Example3D)
# ======================================================================


class ExampleHerriottCell:
    """SA Optics Workbench – Herriott Cell Example"""

    def Activated(self):
        make_herriott()
        Gui.runCommand("Std_OrthographicCamera", 1)

    def IsActive(self):
        return True

    def GetResources(self):
        return {
            "Pixmap": os.path.join(_icondir_, "optics_workbench_icon.svg"),
            "Accel": "",
            "MenuText": "Herriott Cell Example",
            "ToolTip": "Build and simulate a Herriott multipass cell",
        }


# Register command
Gui.addCommand("sa_ExampleHerriottCell", ExampleHerriottCell())
