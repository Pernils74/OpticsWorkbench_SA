import os
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import gaussian_kde

import FreeCAD
import FreeCADGui as Gui
from FreeCADGui import activeDocument

from PySide import QtGui, QtCore

# Anpassa vid behov
try:
    from draftutils.translate import translate
except Exception:

    def translate(ctxt, txt):
        return txt


# Om du har global icon-dir definierad i workbench
try:
    _icondir_
except NameError:
    _icondir_ = os.path.join(os.path.dirname(__file__), "icons")


# =====================================================
# PlotRayHits COMMAND (FreeCAD Command-klass)
# =====================================================


class PlotRayHits:
    """
    FreeCAD command class
    """

    # ---- Detta är wrappern som externa moduler anropar ----
    @staticmethod
    def plot3D(selectedObjList):
        dlg = RayHitsDialog(selectedObjList)
        Gui._rayHitsDialog = dlg  # Förhindra garbage collection
        dlg.show()

    # ---- FreeCAD command API ----
    def Activated(self):
        selectedObjList = Gui.Selection.getSelection()
        PlotRayHits.plot3D(selectedObjList)

    def IsActive(self):
        return activeDocument() is not None

    def GetResources(self):
        return {
            "Pixmap": os.path.join(_icondir_, "scatter3D.svg"),
            "MenuText": translate("RayHits", "Scatter / Heatmap Plot"),
            "ToolTip": translate("RayHits", "Show ray hits in 2D/3D/Heatmap"),
        }


# =====================================================
# Dialog
# =====================================================

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure


class RayHitsDialog(QtGui.QDialog):

    def __init__(self, selectedObjList=None, parent=None):
        super(RayHitsDialog, self).__init__(parent)

        self._preselectList = selectedObjList or []

        self.setWindowTitle("Ray Hits Analyzer")
        self.resize(1000, 700)

        self.icon_dir = os.path.join(os.path.dirname(__file__), "icons")

        self._cachedData = None

        self.buildUI()
        self.reloadObjects()
        self.updatePlot()

    def reloadObjects(self):

        self.objList.clear()

        doc = FreeCAD.ActiveDocument
        if not doc:
            return

        valid_objects = []

        for obj in doc.Objects:
            if any(a.startswith("HitCoordsFrom") for a in dir(obj)):
                valid_objects.append(obj)

                item = QtGui.QListWidgetItem(obj.Label)
                item.setData(QtCore.Qt.UserRole, obj)

                # -------- Ikon baserat på opticalType --------
                optical_type = getattr(obj, "OpticalType", "").lower()
                icon_file = None

                if optical_type == "absorber":
                    icon_file = os.path.join(self.icon_dir, "absorber.svg")
                elif optical_type == "mirror":
                    icon_file = os.path.join(self.icon_dir, "mirror.svg")
                elif optical_type == "lens":
                    icon_file = os.path.join(self.icon_dir, "lens.svg")
                elif optical_type == "grating":
                    icon_file = os.path.join(self.icon_dir, "grating.svg")

                if icon_file and os.path.exists(icon_file):
                    item.setIcon(QtGui.QIcon(icon_file))

                self.objList.addItem(item)

        if not valid_objects:
            return

        # ---- PRESELECT LOGIK ----
        if self._preselectList:
            for i in range(self.objList.count()):
                item = self.objList.item(i)
                obj = item.data(QtCore.Qt.UserRole)
                if obj in self._preselectList:
                    item.setSelected(True)
        else:
            # välj första objektet automatiskt
            self.objList.item(0).setSelected(True)

    def preselectObjects(self):

        if not self._preselectList:
            return

        for i in range(self.objList.count()):
            item = self.objList.item(i)
            obj = item.data(QtCore.Qt.UserRole)

            if obj in self._preselectList:
                item.setSelected(True)

    # -------------------------------------------------
    # UI
    # -------------------------------------------------

    def buildUI(self):

        mainLayout = QtGui.QHBoxLayout(self)

        # ---------------- LEFT PANEL ----------------
        controlWidget = QtGui.QWidget()
        controlLayout = QtGui.QVBoxLayout(controlWidget)

        self.objList = QtGui.QListWidget()
        self.objList.setSelectionMode(QtGui.QAbstractItemView.MultiSelection)
        controlLayout.addWidget(QtGui.QLabel("Objects"))
        controlLayout.addWidget(self.objList)

        self.reloadBtn = QtGui.QPushButton("Reload")
        controlLayout.addWidget(self.reloadBtn)

        controlLayout.addWidget(QtGui.QLabel("Plane"))
        self.planeCmb = QtGui.QComboBox()
        self.planeCmb.addItems(["Auto", "XY", "XZ", "YZ"])
        controlLayout.addWidget(self.planeCmb)

        controlLayout.addWidget(QtGui.QLabel("Graph Type"))
        self.graphCmb = QtGui.QComboBox()
        self.graphCmb.addItems(["3D", "2D", "Heatmap"])
        controlLayout.addWidget(self.graphCmb)

        self.bounceChk = QtGui.QCheckBox("Use Bounce Reduction")
        self.bounceChk.setChecked(True)
        controlLayout.addWidget(self.bounceChk)

        controlLayout.addWidget(QtGui.QLabel("Energy per Bounce (%)"))
        self.energySpin = QtGui.QSpinBox()
        self.energySpin.setRange(1, 100)
        self.energySpin.setValue(90)
        controlLayout.addWidget(self.energySpin)

        controlLayout.addWidget(QtGui.QLabel("Heatmap Intensity"))
        self.heatSlider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.heatSlider.setRange(1, 200)
        self.heatSlider.setValue(100)
        controlLayout.addWidget(self.heatSlider)

        # Log scale
        self.logChk = QtGui.QCheckBox("Log scale")
        self.logChk.setChecked(True)
        controlLayout.addWidget(self.logChk)

        # Resolution
        controlLayout.addWidget(QtGui.QLabel("Heatmap Resolution"))

        # Slider
        self.resSlider = QtGui.QSlider(QtCore.Qt.Horizontal)
        self.resSlider.setRange(20, 400)  # min/max bins
        self.resSlider.setValue(50)  # default
        self.resSlider.setTickInterval(10)
        self.resSlider.setTickPosition(QtGui.QSlider.TicksBelow)
        controlLayout.addWidget(self.resSlider)

        # Label för att visa nuvarande värde
        self.resLabel = QtGui.QLabel(str(self.resSlider.value()))
        controlLayout.addWidget(self.resLabel)

        # Auto normalize
        self.autoNormChk = QtGui.QCheckBox("Auto normalize")
        self.autoNormChk.setChecked(True)
        controlLayout.addWidget(self.autoNormChk)

        # ---------------- Colormap selection ----------------
        controlLayout.addWidget(QtGui.QLabel("Colormap"))
        self.cmapCmb = QtGui.QComboBox()
        self.cmapCmb.addItems(
            [
                "viridis",  # mörk→ljus
                "plasma",  # mörk→ljus
                "inferno",  # mörk→ljus
                "magma",  # mörk→ljus
                "cividis",  # mörk→ljus
                "hot",  # mörk→ljus röd→gul→vit
                "coolwarm",  # blå→vit→röd
                "YlOrRd",  # ljus→mörk röd-orange
                "pink",  # ljus rosa→mörk rosa
            ]
        )
        self.cmapCmb.setCurrentText("viridis")
        controlLayout.addWidget(self.cmapCmb)

        controlLayout.addStretch()
        mainLayout.addWidget(controlWidget, 1)

        # ---------------- PLOT PANEL ----------------
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        mainLayout.addWidget(self.canvas, 3)

        # -------- SIGNALS (LIVE UPDATE) --------
        self.reloadBtn.clicked.connect(self.reloadObjects)
        self.objList.itemSelectionChanged.connect(self.updatePlot)
        self.graphCmb.currentIndexChanged.connect(self.updatePlot)
        self.planeCmb.currentIndexChanged.connect(self.updatePlot)
        self.bounceChk.stateChanged.connect(self.updatePlot)
        self.energySpin.valueChanged.connect(self.updatePlot)
        self.heatSlider.valueChanged.connect(self.updatePlot)

        self.logChk.stateChanged.connect(self.updatePlot)
        self.autoNormChk.stateChanged.connect(self.updatePlot)
        self.cmapCmb.currentIndexChanged.connect(self.updatePlot)

        # Signal: uppdatera label när slider ändras
        self.resSlider.valueChanged.connect(lambda val: self.resLabel.setText(str(val)))
        self.resSlider.valueChanged.connect(self.updatePlot)

    # -------------------------------------------------
    # Data
    # -------------------------------------------------

    def collectData(self):

        coords_all = []
        bounce_all = []

        for item in self.objList.selectedItems():

            obj = item.data(QtCore.Qt.UserRole)
            attr_names = [a for a in dir(obj) if a.startswith("HitCoordsFrom")]

            for attr in attr_names:

                coords = getattr(obj, attr)
                coords_all.extend(coords)

                bname = "BounceCountFrom" + attr[13:]
                if hasattr(obj, bname):
                    bounce_all.extend(getattr(obj, bname))
                else:
                    bounce_all.extend([0] * len(coords))

        if not coords_all:
            return None

        return np.array(coords_all), np.array(bounce_all)

    # -------------------------------------------------
    # Plot Update
    # -------------------------------------------------

    def updatePlot(self):

        data = self.collectData()
        self.figure.clear()

        if data is None:
            self.canvas.draw()
            return

        coords, bounce = data
        x, y, z = coords[:, 0], coords[:, 1], coords[:, 2]

        # ----- Energy reduction -----
        if self.bounceChk.isChecked():
            reduction = self.energySpin.value() / 100.0
            energy = reduction**bounce
        else:
            energy = np.ones_like(bounce)

        # ----- Colormap -----
        cmap = self.cmapCmb.currentText()

        graph_type = self.graphCmb.currentText()

        # =====================================================
        # 3D
        # =====================================================
        if graph_type == "3D":

            ax = self.figure.add_subplot(111, projection="3d")
            sc = ax.scatter(x, y, z, c=energy, cmap=cmap, s=10)
            self.figure.colorbar(sc, ax=ax, label="Energy")

        # =====================================================
        # 2D
        # =====================================================
        elif graph_type == "2D":

            ax = self.figure.add_subplot(111)
            plane = self.planeCmb.currentText()

            if plane == "XZ":
                sc = ax.scatter(x, z, c=energy, cmap=cmap, s=10)
                ax.set_xlabel("X")
                ax.set_ylabel("Z")
            elif plane == "YZ":
                sc = ax.scatter(y, z, c=energy, cmap=cmap, s=10)
                ax.set_xlabel("Y")
                ax.set_ylabel("Z")
            else:
                sc = ax.scatter(x, y, c=energy, cmap=cmap, s=10)
                ax.set_xlabel("X")
                ax.set_ylabel("Y")

            self.figure.colorbar(sc, ax=ax, label="Energy")

        # =====================================================
        # HEATMAP (Density × Energy)
        # =====================================================
        elif graph_type == "Heatmap":

            ax = self.figure.add_subplot(111)

            plane = self.planeCmb.currentText()

            if plane == "XZ":
                px, py = x, z
                ax.set_xlabel("X")
                ax.set_ylabel("Z")
            elif plane == "YZ":
                px, py = y, z
                ax.set_xlabel("Y")
                ax.set_ylabel("Z")
            else:
                px, py = x, y
                ax.set_xlabel("X")
                ax.set_ylabel("Y")

            # ----- Histogram (density × energy) -----
            # bins = self.resSpin.value()
            bins = self.resSlider.value()  # använder slider istället för spinbox
            heat, xedges, yedges = np.histogram2d(px, py, bins=bins, weights=energy)

            # ----- Log scale -----
            if self.logChk.isChecked():
                heat = np.log1p(heat)  # stabil log

            # ----- Auto normalize -----
            if self.autoNormChk.isChecked():
                max_val = np.max(heat)
                if max_val > 0:
                    heat = heat / max_val

            # ----- Intensity fine tuning -----
            intensity = self.heatSlider.value() / 100.0
            heat *= intensity

            # ----- Colormap -----
            from matplotlib.colors import LinearSegmentedColormap

            if cmap == "optics":
                cmap_to_use = LinearSegmentedColormap.from_list(
                    "optics",
                    [
                        (0.0, "black"),
                        (0.3, "red"),
                        (0.6, "yellow"),
                        (1.0, "white"),
                    ],
                )
            else:
                cmap_to_use = cmap

            im = ax.imshow(
                heat.T,
                origin="lower",
                aspect="auto",
                extent=[xedges[0], xedges[-1], yedges[0], yedges[-1]],
                cmap=cmap_to_use,
            )

            self.figure.colorbar(im, ax=ax, label="Density × Energy")

        self.canvas.draw()


# =====================================================
# RayHits2CSV (oförändrad struktur)
# =====================================================


class RayHits2CSV:

    def Activated(self):
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.Hits2CSV()")

    def IsActive(self):
        return activeDocument() is not None

    def GetResources(self):
        return {
            "Pixmap": os.path.join(_icondir_, "ExportCSV.svg"),
            "MenuText": translate("Hits2CSV", "Ray Hits to Spreadsheet"),
            "ToolTip": translate("Hits2CSV", "Export Ray Hits to Spreadsheet"),
        }


# =====================================================
# Register Commands
# =====================================================

Gui.addCommand("sa_RayHits", PlotRayHits())
Gui.addCommand("sa_Hits2CSV", RayHits2CSV())
