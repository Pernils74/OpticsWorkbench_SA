# -*- coding: utf-8 -*-
# initGui.py


# from Rayhits_plotMed import PlotPointsMedCmd
import FreeCAD
import FreeCADGui
import os
from FreeCADGui import Workbench

# Use FreeCAD's built-in translation system instead of translate
translate = FreeCAD.Qt.translate


class OpticsWorkbench_SA(Workbench):
    """Custom SA version of the Optics Workbench"""

    def __init__(self):
        import sa_OpticsWorkbench

        translations_path = os.path.join(sa_OpticsWorkbench.get_module_path(), "translations")
        FreeCADGui.addLanguagePath(translations_path)
        FreeCADGui.updateLocale()

        self.__class__.MenuText = "Optics_SA"
        self.__class__.ToolTip = FreeCAD.Qt.translate("Workbench", "Ray Tracing Simulation SA version")
        self.__class__.Icon = os.path.join(sa_OpticsWorkbench.get_module_path(), "optics_workbench_icon.svg")

    def Initialize(self):
        """This function is executed when FreeCAD starts"""
        # import here all the needed files that create your FreeCAD commands
        import sa_Ray
        import sa_OpticalObject
        import sa_Plot
        import sa_LiveSheets
        import sa_plot.sa_Rayhits_plot

        # Import new dock command so it registers the FreeCADGui command
        import sa_Dock as DockCmd

        from examples_sa import (
            example2D,
            example3D,
            example_dispersion,
            example_candle,
            example_semi,
            example_hierarchy2D,
            example_hierarchy3D,
            herriott_cell,
        )

        rays = [
            FreeCAD.Qt.translate("Workbench", "sa_Ray (monochrome)"),
            FreeCAD.Qt.translate("Workbench", "sa_Ray (sun light)"),
            FreeCAD.Qt.translate("Workbench", "sa_Beam"),
            FreeCAD.Qt.translate("Workbench", "sa_2D Radial Beam"),
            FreeCAD.Qt.translate("Workbench", "sa_Spherical Beam"),
            FreeCAD.Qt.translate("Workbench", "sa_Grid Focal Beam"),
        ]

        optics = [
            FreeCAD.Qt.translate("Workbench", "sa_Emitter"),
            FreeCAD.Qt.translate("Workbench", "sa_Mirror"),
            FreeCAD.Qt.translate("Workbench", "sa_Grating"),
            FreeCAD.Qt.translate("Workbench", "sa_Absorber"),
            FreeCAD.Qt.translate("Workbench", "sa_Lens"),
        ]

        actions = [
            FreeCAD.Qt.translate("Workbench", "sa_Off"),
            FreeCAD.Qt.translate("Workbench", "sa_Start"),
        ]

        analysis = [
            FreeCAD.Qt.translate("Workbench", "sa_RayHits"),
            FreeCAD.Qt.translate("Workbench", "sa_Hits2CSV"),
            FreeCAD.Qt.translate("Workbench", "sa_LiveSheets"),
            FreeCAD.Qt.translate("Workbench", "sa_Rayhits_Plot"),
        ]

        #
        # New dock command
        #
        optics_dock = ["sa_Dock"]
        separator = ["Separator"]

        examples = [
            FreeCAD.Qt.translate("Workbench", "sa_Example2D"),
            FreeCAD.Qt.translate("Workbench", "sa_Example3D"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleDispersion"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleCandle"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleSemi"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleHierarchy2D"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleHierarchy3D"),
            FreeCAD.Qt.translate("Workbench", "sa_ExampleHerriottCell"),
        ]

        #
        # Adding of the new dock command
        #
        self.list = optics_dock + rays + separator + optics + separator + actions + separator + analysis  # A list of command names created in the line above
        self.menu = self.list + separator + examples

        #
        # Send commandlist to dock panel, remove it self from list to avoid duplication
        #
        DockCmd.set_command_lists(self.list, self.menu, remove_command="sa_Dock")

        self.appendToolbar(self.__class__.MenuText, self.list)  # creates a new toolbar with your commands
        self.appendMenu(self.__class__.MenuText, self.menu)  # creates a new menu

        # DockCmd.create_or_show_dock()

    def Activated(self):
        """This function is executed when the workbench is activated"""
        return

    def Deactivated(self):
        """This function is executed when the workbench is deactivated"""
        return

    def ContextMenu(self, recipient):
        """This is executed whenever the user right-clicks on screen"""
        # 'recipient' will be either 'view' or 'tree'
        self.appendContextMenu(self.__class__.MenuText, self.list)  # add commands to the context menu

    def GetClassName(self):
        # this function is mandatory if this is a full python workbench
        return "Gui::PythonWorkbench"


FreeCADGui.addWorkbench(OpticsWorkbench_SA())
