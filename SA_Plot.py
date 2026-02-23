import numpy as np
import matplotlib.pyplot as plt
import FreeCADGui as Gui
import FreeCAD
from FreeCAD import activeDocument
import os
import sa_Ray


translate = FreeCAD.Qt.translate


_icondir_ = os.path.join(os.path.dirname(__file__), "icons")


class PlotRayHits:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    @staticmethod
    def plot3D(selectedObjList):

        if len(selectedObjList) > 0:
            coords_per_beam = []
            bounce_per_beam = []

            absorber_ids = []  # absorber-ID per punkt
            current_id = 0  # starts from 0

            for eachObject in selectedObjList:
                try:
                    if sa_Ray.isOpticalObject(eachObject):

                        # Hitta alla HitCoordsFrom-beam-listor på det aktuella objektet
                        attr_names = [attr for attr in dir(eachObject) if attr.startswith("HitCoordsFrom")]

                        for attr in attr_names:
                            coords = getattr(eachObject, attr)
                            coords_per_beam.append(coords)

                            # Lägg in absorber-ID för varje träff
                            absorber_ids.extend([current_id] * len(coords))

                            # BounceCount om det finns
                            bname = "BounceCountFrom" + attr[13:]
                            if hasattr(eachObject, bname):
                                bounce_per_beam.append(getattr(eachObject, bname))
                            else:
                                bounce_per_beam.append([])

                        current_id += 1

                    else:
                        print("Ignoring:", eachObject.Label)

                except:
                    print("Ignoring:", eachObject.Label)

            # ----- Flatten numpy-arrayer -----
            all_coords = np.array([coord for coords in coords_per_beam for coord in coords])
            absorber_ids = np.array(absorber_ids)

            all_bounces = np.array([b for bl in bounce_per_beam for b in bl]) if bounce_per_beam else np.array([])

            # ----- Ingen träff hittades -----
            if len(all_coords) == 0:
                print("No ray hits were found")
                return

            # ----- X, Y, Z -----
            x = all_coords[:, 0]
            y = all_coords[:, 1]
            z = all_coords[:, 2]

            # ----- Kolla om alla tre dimensioner används -----
            xpresent = np.any(np.abs(x - x[0]) > Ray.EPSILON)
            ypresent = np.any(np.abs(y - y[0]) > Ray.EPSILON)
            zpresent = np.any(np.abs(z - z[0]) > Ray.EPSILON)

            fig = plt.figure()

            # ----- 3D-plot -----
            if xpresent and ypresent and zpresent:
                ax = fig.add_subplot(projection="3d")

                # FÄRGBASERAT PÅ ABSORBER
                sc = ax.scatter(x, y, z, c=absorber_ids, cmap="tab10")

                fig.colorbar(sc, ax=ax, label="Absorber ID", shrink=0.7)

                ax.set_xlabel("X-axis")
                ax.set_ylabel("Y-axis")
                ax.set_zlabel("Z-axis")

            # ----- 2D-fall -----
            else:
                ax = fig.add_subplot()

                if not zpresent:
                    sc = ax.scatter(x, y, c=absorber_ids, cmap="tab10")
                    ax.set_xlabel("X-axis")
                    ax.set_ylabel("Y-axis")

                elif not ypresent:
                    sc = ax.scatter(x, z, c=absorber_ids, cmap="tab10")
                    ax.set_xlabel("X-axis")
                    ax.set_ylabel("Z-axis")

                else:
                    sc = ax.scatter(y, z, c=absorber_ids, cmap="tab10")
                    ax.set_xlabel("Y-axis")
                    ax.set_ylabel("Z-axis")

                fig.colorbar(sc, ax=ax, label="Absorber ID", shrink=0.8)

            plt.show()

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to plot ray hits for selected absorber
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("selectedObjList = FreeCADGui.Selection.getSelection()")
        Gui.doCommand("sa_OpticsWorkbench.drawPlot(selectedObjList)")

    def IsActive(self):
        """Here you can define if the command must be active or not (greyed) if certain conditions
        are met or not. This function is optional."""
        if activeDocument():
            return True
        else:
            return False

    def GetResources(self):
        """Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown."""
        return {
            "Pixmap": os.path.join(_icondir_, "scatter3D.svg"),
            "Accel": "",
            "MenuText": translate("RayHits", "Scatter 3D Plot"),
            "ToolTip": translate("RayHits", "Show selected absorber ray hits in a 3D scatter plot"),
        }


class RayHits2CSV:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to plot ray hits for selected absorber
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.Hits2CSV()")

    def IsActive(self):
        """Here you can define if the command must be active or not (greyed) if certain conditions
        are met or not. This function is optional."""
        if activeDocument():
            return True
        else:
            return False

    def GetResources(self):
        """Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown."""
        return {
            "Pixmap": os.path.join(_icondir_, "ExportCSV.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Hits2CSV", "Ray Hits to Spreadsheet"),
            "ToolTip": translate("Hits2CSV", "Export Ray Hits to Spreadsheet"),
        }


Gui.addCommand("sa_RayHits", PlotRayHits())
Gui.addCommand("sa_Hits2CSV", RayHits2CSV())
