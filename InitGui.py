# -*- coding: utf-8 -*-
# initGui.py


# from Rayhits_plotMed import PlotPointsMedCmd
import FreeCAD
import FreeCADGui
import os
from FreeCADGui import Workbench


class OpticsWorkbench_SA(Workbench):
    """Custom SA version of the Optics Workbench"""

    def __init__(self):

        import sa_OpticsWorkbench

        translate = FreeCAD.Qt.translate

        translations_path = os.path.join(
            sa_OpticsWorkbench.get_module_path(), "translations"
        )

        self.__class__.MenuText = "Optics_SA"
        self.__class__.ToolTip = translate(
            "Workbench", "Ray Tracing Simulation SA version"
        )
        self.__class__.Icon = os.path.join(
            sa_OpticsWorkbench.get_module_path(), "optics_workbench_icon.svg"
        )

        FreeCADGui.addLanguagePath(translations_path)
        FreeCADGui.updateLocale()

    def Initialize(self):
        """This function is executed when FreeCAD starts"""
        # import here all the needed files that create your FreeCAD commands
        # from .SA_workbench import Ray
        # from .SA_workbench import OpticalObject
        # from .SA_workbench import Plot
        # from .SA_workbench import LiveSheets

        import sa_Ray
        import sa_OpticalObject
        import sa_Plot
        import sa_LiveSheets
        import sa_Rayhits_plot

        #
        # Import new dock command so it registers the FreeCADGui command
        #
        import sa_Dock as DockCmd

        # from Rayhits_plotMed import PlotPointsMedCmd

        #
        #

        # PlotPointsMedCmd(initial_sheet_name="RayHits")

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

        # from PySide2.QtCore import QT_TRANSLATE_NOOP

        # Use FreeCAD's built-in translation system instead of translate
        translate = FreeCAD.Qt.translate

        rays = [
            translate("Workbench", "SA_Ray (monochrome)"),
            translate("Workbench", "SA_Ray (sun light)"),
            translate("Workbench", "SA_Beam"),
            translate("Workbench", "SA_2D Radial Beam"),
            translate("Workbench", "SA_Spherical Beam"),
            translate("Workbench", "SA_Grid Focal Beam"),
        ]
        optics = [
            translate("Workbench", "SA_Emitter"),
            translate("Workbench", "SA_Mirror"),
            translate("Workbench", "SA_Grating"),
            translate("Workbench", "SA_Absorber"),
            translate("Workbench", "SA_Lens"),
        ]
        actions = [
            translate("Workbench", "SA_Off"),
            translate("Workbench", "SA_Start"),
        ]

        analysis = [
            translate("Workbench", "SA_RayHits"),
            translate("Workbench", "SA_Hits2CSV"),
            translate("Workbench", "SA_LiveSheets"),
            translate("Workbench", "SA_Rayhits_Plot"),
        ]

        #
        # New dock command
        #
        optics_dock = ["SA_Dock"]

        separator = ["Separator"]
        examples = [
            translate("Workbench", "sa_Example2D"),
            translate("Workbench", "sa_Example3D"),
            translate("Workbench", "sa_ExampleDispersion"),
            translate("Workbench", "sa_ExampleCandle"),
            translate("Workbench", "sa_ExampleSemi"),
            translate("Workbench", "sa_ExampleHierarchy2D"),
            translate("Workbench", "sa_ExampleHierarchy3D"),
            translate("Workbench", "sa_ExampleHerriottCell"),
        ]

        #
        # Adding of the new dock command
        #
        self.list = (
            optics_dock
            + rays
            + separator
            + optics
            + separator
            + actions
            + separator
            + analysis
        )  # A list of command names created in the line above
        self.menu = self.list + separator + examples

        #
        # Send commandlist to dock panel, remove it self from list to avoid duplication
        #
        DockCmd.set_command_lists(self.list, self.menu, remove_command="SA_Dock")

        self.appendToolbar(
            self.__class__.MenuText, self.list
        )  # creates a new toolbar with your commands
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
        self.appendContextMenu(
            self.__class__.MenuText, self.list
        )  # add commands to the context menu

    def GetClassName(self):
        # this function is mandatory if this is a full python workbench
        return "Gui::PythonWorkbench"


Gui.addWorkbench(OpticsWorkbench_SA())
