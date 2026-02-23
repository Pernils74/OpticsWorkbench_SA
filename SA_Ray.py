# -*- coding: utf-8 -*-
# sa_Ray.py
__title__ = "Ray"
__author__ = "Christian Bergmann"
__license__ = "LGPL 3.0"

import os
import FreeCADGui as Gui
from FreeCAD import Vector, Rotation, Placement, activeDocument
import Part
import math
import traceback
from wavelength_to_rgb.gentable import wavelen2rgb
import sa_OpticalObject

import FreeCAD

translate = FreeCAD.Qt.translate

# def QT_TRANSLATE_NOOP(context, text):
#     return text


_icondir_ = os.path.join(os.path.dirname(__file__), "icons")
__doc__ = translate("Ray (monochrome)", "A single ray for raytracing")

INFINITY = 1677216
EPSILON = 1 / INFINITY


class RayState:
    def __init__(self, ray_id, bounce_count=0, last_hit="", prev_hit=None):
        self.ray_id = ray_id
        self.bounce_count = bounce_count
        # The last surface the ray hit, formatted as "Object|Base|FaceN"
        self.last_hit = last_hit
        # The surface hit *before* last_hit (None for the first hit)
        self.prev_hit = prev_hit

    def bounced(self, optical_obj, base_obj, face_index):
        new_hit = "{}|{}|Face{}".format(
            optical_obj.Name,
            getattr(base_obj, "Name", str(base_obj)),
            face_index,
        )

        return RayState(
            self.ray_id,
            self.bounce_count + 1,
            prev_hit=self.last_hit,  # store the previous hit
            last_hit=new_hit,  # update with the new surface hit
        )


class RayWorker:

    def __init__(
        self,
        fp,  # an instance of Part::FeaturePython
        power=True,
        spherical=False,
        beamNrColumns=1,
        beamNrRows=1,
        beamDistance=0.1,
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

        fp.addProperty("App::PropertyBool", "Power", "Ray", translate("Ray", "On or Off")).Power = power
        fp.addProperty(
            "App::PropertyIntegerConstraint",
            "BeamNrColumns",
            "Ray",
            translate("Ray", "number of rays in a beam"),
        ).BeamNrColumns = beamNrColumns
        fp.addProperty(
            "App::PropertyIntegerConstraint",
            "BeamNrRows",
            "Ray",
            translate("Ray", "number of rays in a beam"),
        ).BeamNrRows = beamNrRows
        fp.addProperty(
            "App::PropertyFloat",
            "BeamDistance",
            "Ray",
            translate("Ray", "distance between two beams"),
        ).BeamDistance = beamDistance
        fp.addProperty(
            "App::PropertyBool",
            "HideFirstPart",
            "Ray",
            translate("Ray", "hide the first part of every ray"),
        ).HideFirstPart = hideFirst
        fp.addProperty(
            "App::PropertyFloat",
            "MaxRayLength",
            "Ray",
            translate("Ray", "maximum length of a ray"),
        ).MaxRayLength = maxRayLength
        fp.addProperty(
            "App::PropertyIntegerConstraint",
            "MaxNrReflections",
            "Ray",
            translate("Ray", "maximum number of reflections"),
        ).MaxNrReflections = maxNrReflections
        fp.addProperty(
            "App::PropertyFloat",
            "Wavelength",
            "Ray",
            translate("Ray", "Wavelength of the ray in nm"),
        ).Wavelength = wavelength
        fp.addProperty(
            "App::PropertyIntegerConstraint",
            "Order",
            "Ray",
            translate("Ray", "Order of the ray"),
        ).Order = order
        fp.addProperty(
            "App::PropertyFloat",
            "ConeAngle",
            "Ray",
            translate("Ray", "Angle of ray in case of Cone in degrees"),
        ).ConeAngle = coneAngle
        fp.addProperty(
            "App::PropertyLinkList",
            "IgnoredOpticalElements",
            "Ray",
            translate("Ray", "Optical Objects to ignore in raytracing"),
        ).IgnoredOpticalElements = ignoredElements

        self.addNewProperties(fp)
        fp.Base = baseShape
        fp.FocalPoint = focalPoint

        if rayBundleType == "":
            if spherical:
                fp.RayBundleType = "spherical"
            else:
                fp.RayBundleType = "parallel"
        else:
            fp.RayBundleType = rayBundleType

        fp.Proxy = self

        self._init_runtime_state()

    def _init_runtime_state(self):
        # Runtime-only state (not stored in document)
        self.lastRefIdx = []
        self.iter = 0
        self.ray_counter = 0
        self.stats_buffer = {}  # buffer for statistics collection, keyed by ray_id, to avoid per-hit property appends

        # self.last_hit_per_ray = {}  # ray_id -> (obj, part, point, energy, bounce)

    def addNewProperties(self, fp):
        # backwards compatiblity
        if not hasattr(fp, "Base"):
            fp.addProperty(
                "App::PropertyLinkSub",
                "Base",
                "Ray",
                translate("Ray", "FreeCAD object used as optical emitter"),
            )

        if not hasattr(fp, "FocalPoint"):
            fp.addProperty(
                "App::PropertyVector",
                "FocalPoint",
                "Ray",
                translate("Ray", "Optional focal point for directed beams"),
            ).FocalPoint = Vector(0, 0, 100)

        if not hasattr(fp, "RayBundleType"):
            fp.addProperty(
                "App::PropertyEnumeration",
                "RayBundleType",
                "Ray",
                translate("Ray", "Shape of ray bundle"),
            ).RayBundleType = ["parallel", "spherical", "focal"]

            if hasattr(fp, "Spherical") and fp.Spherical:
                fp.RayBundleType = "spherical"

    def onDocumentRestored(self, fp):
        self.addNewProperties(fp)
        self._init_runtime_state()

    def execute(self, fp):
        """Do something when doing a recomputation, this method is mandatory"""
        self.redrawRay(fp)

    def onChanged(self, fp, prop):
        """Do something when a property has changed"""
        pass

    def redrawRay(self, fp):
        hitname = "HitsFrom" + fp.Label
        hitcoordsname = "HitCoordsFrom" + fp.Label
        energyname = "EnergyFrom" + fp.Label
        bouncename = "BounceCountFrom" + fp.Label
        rayId = "RayIdFrom" + fp.Label
        previoushitname = "PreviousHitFrom" + fp.Label

        self.ray_counter = 0

        for optobj in activeDocument().Objects:
            if hasattr(optobj, hitname):
                setattr(optobj, hitname, 0)
            if hasattr(optobj, hitcoordsname):
                setattr(optobj, hitcoordsname, [])
            if hasattr(optobj, energyname):
                setattr(optobj, energyname, [])
            if hasattr(optobj, bouncename):
                setattr(optobj, bouncename, [])
            if hasattr(optobj, rayId):
                setattr(optobj, rayId, [])
            if hasattr(optobj, previoushitname):
                setattr(optobj, previoushitname, [])

        try:  # check if the beam has the parameter coneAngle, this is a legacy check.
            coneAngle = float(fp.ConeAngle)
            if coneAngle > 360:
                coneAngle = 360  # cone angles larger than 360 are not possible, this is a sphere
        except:
            coneAngle = 360

        pl = fp.Placement
        posdirarray = []
        sunObj = None

        if fp.Base:
            fp.Placement = Placement()
            faces = []
            if len(fp.Base[1]) == 0:
                faces += fp.Base[0].Shape.Faces
            else:
                for sub in fp.Base[1]:
                    sobj = fp.Base[0].getSubObject(sub)
                    faces.append(sobj)

            sunObj = Part.makeCompound(faces)
            r2 = Rotation(fp.Placement.Rotation)
            r2.invert()
            sunObj.Placement.Rotation = r2

            posdirarray = self.getPosDirFromFaces(sunObj.Faces, fp.BeamNrRows, fp.BeamNrColumns)

        # if a spherical 3d ray is requested create an evenly spaced ray bundle in 3d
        elif fp.RayBundleType == "spherical":
            # make spherical beam pattern that has equally spaced rays.
            # code based from a paper by Markus Deserno from the Max-Plank_Institut fur PolymerForschung,
            # link https://www.cmu.edu/biolphys/deserno/pdf/sphere_equi.pdf
            Ncount = 0  # create counter to check how many beams actually are generated
            N = int(fp.BeamNrColumns * fp.BeamNrRows)  # N = number of rays
            if N == 0:
                return
            r = 1  # use a unit circle with radius 1 to determine the direction vector of each ray
            # required surface area for each ray for a unit circle, by dividing the surface area of the unit circle by the number of rays
            a = 2 * math.pi * (1 - math.cos(math.radians(coneAngle / 2))) / N
            d = math.sqrt(a)  # dont know but it works :-p
            # Angle step between the circles on which the points are projected
            M_angle1 = math.radians(coneAngle / 2) / d
            # Quote from paper: Regular equidistribution can be achieved by choosing circles of latitude at constant intervals d_angle1 and on these circles points with distance d_angle2, such that d_angle1 roughly equal to d_angle2 and that d_angle1*d_angle2 equals the average area per point. This then gives the following algorithm:

            # calculate the distance between the circles of the latitude
            d_angle1 = math.radians(coneAngle / 2) / M_angle1
            # calculate the distance between the points on the circumference of the circle
            d_angle2 = a / d_angle1
            pos = Vector(0, 0, 0)
            for m in range(0, math.ceil(M_angle1)):
                r = Rotation()
                r.Axis = Vector(0, 0, 1)
                angle1 = math.radians(coneAngle / 2) * (m) / M_angle1
                M_angle2 = round(2 * math.pi * math.sin(angle1) / d_angle2)
                # if the beam is 2d, create only two points on the each projecting circle
                if int(fp.BeamNrRows) == 1:
                    M_angle2 = 2
                if M_angle2 == 0:  # if angle is 0 then set one ray in the vertical position
                    angle2 = 0
                    dir = Vector(
                        math.sin(angle1) * math.cos(angle2),
                        math.sin(angle1) * math.sin(angle2),
                        math.cos(angle1),
                    )
                    Ncount = Ncount + 1
                    posdirarray.append((pos, dir))

                for n in range(0, M_angle2):
                    angle2 = 2 * math.pi * n / M_angle2
                    dir = Vector(
                        math.sin(angle1) * math.cos(angle2),
                        math.sin(angle1) * math.sin(angle2),
                        math.cos(angle1),
                    )
                    Ncount = Ncount + 1

                    posdirarray.append((pos, dir))
            # print("Number of rays created = ",Ncount)

        else:
            if fp.RayBundleType == "focal":
                for row in range(fp.BeamNrRows):
                    for col in range(fp.BeamNrColumns):
                        pos = Vector(
                            fp.BeamDistance * (col - (fp.BeamNrColumns - 1) / 2),
                            fp.BeamDistance * (row - (fp.BeamNrRows - 1) / 2),
                            0,
                        )
                        # Transform position relative to placement
                        pos = pl.Rotation.multVec(pos)
                        dir = (fp.FocalPoint - pos).normalize()
                        posdirarray.append((pos, dir))
            else:
                for row in range(0, int(fp.BeamNrRows)):
                    for n in range(0, int(fp.BeamNrColumns)):
                        if fp.RayBundleType == "parallel":
                            # pos = pl.Rotation.multVec(Vector(0, fp.BeamDistance * n, fp.BeamDistance * row))
                            pos_local = Vector(fp.BeamDistance * row, fp.BeamDistance * n, 0)

                            pos = pl.Rotation.multVec(pos_local)
                            # Changed intial vector to be in z direction, so that the rotation of the ray object is more intuitive, especially for the cone ray bundle type. The old code created the initial vector in x direction and then rotated it to the correct position, which caused some confusion when using the cone ray bundle type with a non-zero cone angle, because the rays were not rotating around the z axis as expected. With the new code, the initial vector is in z direction and then rotated to the correct position, which makes it easier to understand and use the cone ray bundle type with different cone angles.

                            dir = Vector(0, 0, 1)
                            # dir = Vector(1, 0, 0)
                        else:
                            r = Rotation()
                            r.Axis = Vector(0, 0, 1)
                            r.Angle = n * 2 * math.pi / fp.BeamNrColumns * coneAngle / 360
                            pos = Vector(0, 0, 0)
                            dir1 = r.multVec(Vector(1, 0, 0))

                            if row % 2 == 0:
                                r.Axis = Vector(0, 1, 0)
                            else:
                                r.Axis = Vector(1, 0, 0)

                            r.Angle = row * math.pi / fp.BeamNrRows
                            dir = r.multVec(dir1)

                        posdirarray.append((pos, dir))

        linearray = self.makeInitialRay(fp, posdirarray)

        for line in linearray:
            self.substractPlacement(fp, line)

        if sunObj:
            linearray.append(sunObj)

        # transform global ray coordinate to local
        if fp.Parents:
            ray_placement_matrix = fp.getGlobalPlacement().inverse().Matrix
            ray_placement_matrix *= fp.Placement.Matrix
            for line in linearray:
                line.transformShape(ray_placement_matrix)
        fp.Shape = Part.makeCompound(linearray)
        if fp.Power == False:
            fp.ViewObject.LineColor = (0.5, 0.5, 0.0)
        else:
            try:
                rgb = wavelen2rgb(fp.Wavelength)
            except ValueError:
                # set color to white if outside of visible range
                rgb = (255, 255, 255)
            r = rgb[0] / 255.0
            g = rgb[1] / 255.0
            b = rgb[2] / 255.0
            fp.ViewObject.LineColor = (float(r), float(g), float(b), (0.0))

    def substractPlacement(self, fp, obj):
        r2 = Rotation(fp.Placement.Rotation)
        r2.invert()
        obj.Placement.Rotation = r2
        obj.Placement.Base = r2.multVec(obj.Placement.Base - fp.Placement.Base)

    def getPosDirFromFaces(self, subShapes, BeamNrRows, BeamNrColumns):
        posdirarray = []
        for face in subShapes:
            for row in range(0, int(BeamNrRows)):
                for col in range(0, int(BeamNrColumns)):
                    if len(face.ParameterRange) == 4:
                        param1 = face.ParameterRange[0] + (face.ParameterRange[1] - face.ParameterRange[0]) * (row + 0.5) / BeamNrRows
                        param2 = face.ParameterRange[2] + (face.ParameterRange[3] - face.ParameterRange[2]) * (col + 0.5) / BeamNrColumns
                        newdir = face.normalAt(param1, param2)
                        newpos = face.valueAt(param1, param2)
                        v = Part.Vertex(newpos)
                        if face.distToShape(v)[0] < EPSILON:
                            posdirarray.append((newpos, newdir))
                    elif len(face.ParameterRange) == 2:
                        param1 = face.ParameterRange[0] + (face.ParameterRange[1] - face.ParameterRange[0]) * (row + 0.5) / BeamNrRows
                        try:
                            newdir = face.normalAt(param1)
                        except:
                            newdir = Vector(1, 0, 0)

                        newpos = face.valueAt(param1)
                        posdirarray.append((newpos, newdir))

        return posdirarray

    def get_subelement_name(self, nearest_obj, subshape):
        """
        Returnera t.ex. 'Face7' / 'Edge3' / 'Vertex1' för subshape som tillhör nearest_obj.Shape
        """
        shp = nearest_obj.Shape
        # Testa faces först
        for i, f in enumerate(shp.Faces, start=1):
            try:
                if f.isSame(subshape):
                    return f"Face{i}"
            except Exception:
                pass
        # Kant/edge?
        for i, e in enumerate(shp.Edges, start=1):
            try:
                if e.isSame(subshape):
                    return f"Edge{i}"
            except Exception:
                pass
        # Vertex?
        for i, v in enumerate(shp.Vertexes, start=1):
            try:
                if v.isSame(subshape):
                    return f"Vertex{i}"
            except Exception:
                pass
        return None

    def makeInitialRay(self, fp, posdirarray):
        # initialize ray in global coordinate
        pl = fp.getGlobalPlacement()
        linearray = []
        for pos, dir in posdirarray:
            ppos = pos + pl.Base
            pdir = pl.Rotation.multVec(dir)
            if fp.Power == True:
                self.iter = fp.MaxNrReflections
                firstLine = Part.makeLine(ppos, ppos + pdir * fp.MaxRayLength / pdir.Length)

                self.lastRefIdx = []

                try:
                    # tracedLines = self.traceRay(fp, (firstLine, 100))
                    self.ray_counter += 1
                    ray_id = self.ray_counter

                    state = RayState(ray_id)  # Initiera state med ray_id =0  och bounce_count=0
                    tracedLines = self.traceRay(fp, firstLine, 100, state)
                    # tracedLines = self.traceRay(fp, (firstLine, 100, 0, ray_id))

                    if fp.HideFirstPart:
                        # Remove/hide first line.
                        tracedLines = tracedLines[1:]

                    linearray.extend(tracedLines)

                except Exception as ex:
                    print(ex)
                    traceback.print_exc()
            else:
                linearray.append(Part.makeLine(ppos, ppos + pdir))

        return linearray

    def getIntersections(self, fp, line):
        """returns [(OpticalObject, [(edge/face, intersection point, ...metadata)])]"""
        isec_struct = []

        # Globalt CS
        origin = PointVec(line.Vertexes[0])
        dir = PointVec(line.Vertexes[1]) - origin

        for optobj in activeDocument().Objects:
            if not isRelevantOptic(fp, optobj):
                continue

            isec_parts = []
            for obj in optobj.Base:
                bb = obj.Shape.BoundBox
                if not (bb.isValid() and bb.intersect(origin, dir)):
                    continue

                # --- EDGES (Sketch/2D) ---
                if len(obj.Shape.Solids) == 0 and len(obj.Shape.Shells) == 0:
                    for i, edge in enumerate(obj.Shape.Edges, start=1):
                        # normal i globalt CS
                        if len(edge.Vertexes) == 2:
                            edgedir = PointVec(edge.Vertexes[1]) - PointVec(edge.Vertexes[0])
                        else:
                            edgedir = edge.valueAt(0) - edge.valueAt(0.5)

                        normal = dir.cross(edgedir)
                        if normal.Length <= EPSILON:
                            continue

                        plane = Part.Plane(origin, normal)
                        # linje och edge i GLOBALT CS
                        isec = line.Curve.intersect2d(edge.Curve, plane)
                        if not isec:
                            continue

                        for u, v in isec:
                            p2 = plane.value(u, v)
                            dist = p2 - origin
                            vert = Part.Vertex(p2)
                            if dist.Length > EPSILON and vert.distToShape(edge)[0] < EPSILON and vert.distToShape(line)[0] < EPSILON:
                                # Lägg INTE transformera edge in-place
                                # Om du vill spara en kopia:
                                # edge_copy = Part.Edge(edge)
                                # isec_parts.append((edge_copy, PointVec(p2), obj, i))
                                isec_parts.append((edge, PointVec(p2), obj, i))

                # --- FACES (om det finns) ---
                for i, face in enumerate(obj.Shape.Faces, start=1):
                    if not face.BoundBox.intersect(origin, dir):
                        continue

                    isec = line.Curve.intersect(face.Surface)
                    if not isec:
                        continue

                    for p in isec[0]:
                        dist = Vector(p.X - origin.x, p.Y - origin.y, p.Z - origin.z)
                        vert = Part.Vertex(p)
                        if dist.Length > EPSILON and vert.distToShape(face)[0] < EPSILON and vert.distToShape(line)[0] < EPSILON:
                            # Spara face (globalt). Kopia om du vill:
                            # face_global = face.transformed(FreeCAD.Base.Matrix())  # identitet
                            # isec_parts.append((face_global, PointVec(p), obj, i))
                            isec_parts.append((face, PointVec(p), obj, i))

            if isec_parts:
                isec_struct.append((optobj, isec_parts))

        return isec_struct

    def getIntersections_old(self, fp, line):
        """returns [(OpticalObject, [(edge/face, intersection point)] )]"""
        isec_struct = []
        for optobj in activeDocument().Objects:
            if isRelevantOptic(fp, optobj):
                # transform ray to optobj coordinate to prevent transforming all shapes to global coordinate
                optobj_placement_matrix = optobj.getGlobalPlacement().Matrix
                optobj_line = line.transformed(optobj_placement_matrix.inverse())
                origin = PointVec(optobj_line.Vertexes[0])
                dir = PointVec(optobj_line.Vertexes[1]) - origin
                isec_parts = []
                for obj in optobj.Base:
                    obj_boundbox = obj.Shape.BoundBox
                    if obj_boundbox.isValid() and obj_boundbox.intersect(origin, dir):
                        if len(obj.Shape.Solids) == 0 and len(obj.Shape.Shells) == 0:
                            # for be able to collect last hitted face
                            # for edge in obj.Shape.Edges:
                            for i, edge in enumerate(obj.Shape.Edges, start=1):

                                # get a normal to the plane where the edge is lying in
                                if len(edge.Vertexes) == 2:
                                    edgedir = PointVec(edge.Vertexes[1]) - PointVec(edge.Vertexes[0])
                                else:
                                    # workaround for circles
                                    edgedir = edge.valueAt(0) - edge.valueAt(0.5)

                                normal = dir.cross(edgedir)
                                if normal.Length > EPSILON:
                                    plane = Part.Plane(origin, normal)
                                    isec = optobj_line.Curve.intersect2d(edge.Curve, plane)
                                    if isec:
                                        for p in isec:
                                            p2 = plane.value(p[0], p[1])
                                            dist = p2 - origin
                                            vert = Part.Vertex(p2)
                                            if dist.Length > EPSILON and vert.distToShape(edge)[0] < EPSILON and vert.distToShape(optobj_line)[0] < EPSILON:
                                                # transform edge and ray back to global coordinate
                                                vert.transformShape(optobj_placement_matrix)
                                                p2 = PointVec(vert)
                                                edge.transformShape(optobj_placement_matrix)
                                                # isec_parts.append((edge, p2))
                                                # For be able to get the last hitted face id
                                                # isec_parts.append(
                                                #     (edge, p2, obj, f"Edge{i}")
                                                # )
                                                isec_parts.append((edge, p2, obj))

                        # for face in obj.Shape.Faces:
                        for i, face in enumerate(obj.Shape.Faces, start=1):

                            if face.BoundBox.intersect(origin, dir):
                                isec = optobj_line.Curve.intersect(face.Surface)
                                if isec:
                                    for p in isec[0]:
                                        dist = Vector(
                                            p.X - origin.x,
                                            p.Y - origin.y,
                                            p.Z - origin.z,
                                        )
                                        vert = Part.Vertex(p)
                                        if dist.Length > EPSILON and vert.distToShape(face)[0] < EPSILON and vert.distToShape(optobj_line)[0] < EPSILON:
                                            # transform face and ray back to global coordinate
                                            p.transform(optobj_placement_matrix)
                                            # face.transformShape(optobj_placement_matrix)
                                            # face = face.transformed(
                                            #     optobj_placement_matrix
                                            # )

                                            # For be able to get the last hitted face id
                                            # isec_parts.append((face, PointVec(p)))
                                            # isec_parts.append(
                                            #     (face, PointVec(p), obj, f"Face{i}")
                                            # )
                                            # isec_parts.append((face, PointVec(p), obj))
                                            face_global = face.transformed(optobj_placement_matrix)
                                            isec_parts.append((face_global, PointVec(p), obj, i))

                if len(isec_parts) > 0:
                    isec_struct.append((optobj, isec_parts))

        return isec_struct

    def _append_property(self, obj, name, value, ptype, group, doc):
        """
        Robust helper for writing values to FreeCAD properties.

        Behavior:
        - If the property does not exist, it is created using the specified ptype.
          * List-type properties are initialized to an empty list.
          * Single-value properties are left unset until the assignment below.

        - If the property exists:
          * If it is a list-type property, the value is appended.
          * If it is a single-value property, the value overwrites the existing one.
        """

        # Create property if missing
        if not hasattr(obj, name):
            obj.addProperty(ptype, name, group, doc)
            # Initialize list-type properties to an empty list
            if ptype in (
                "App::PropertyStringList",
                "App::PropertyIntegerList",
                "App::PropertyFloatList",
                "App::PropertyVectorList",
                "App::PropertyLinkList",
            ):
                setattr(obj, name, [])
            # Non-list types are assigned directly below

        current = getattr(obj, name)

        # List property → append value
        if isinstance(current, list):
            new_list = current + [value]
            setattr(obj, name, new_list)
        else:
            # Single-value property → overwrite
            setattr(obj, name, value)

    def collectStatistics(
        self,
        fp,
        nearest_obj,
        neworigin,
        energy,
        state,
    ):

        label = fp.Label

        # --- Hit counter: HitsFrom<RayLabel> ---
        hitsfromname = "HitsFrom" + label

        # Fetch previous hit-count and increment by 1 (robust to missing or invalid values)
        try:
            current_hits = int(getattr(nearest_obj, hitsfromname)) + 1
        except Exception:
            current_hits = 1

        self._append_property(
            nearest_obj,
            hitsfromname,
            current_hits,
            "App::PropertyQuantity",
            "OpticalObject",
            "[Ray] Number of hits from this ray",
        )

        # Names of data-collection properties
        hitcoordsname = "HitCoordsFrom" + label
        energyname = "EnergyFrom" + label
        bouncecountname = "BounceCountFrom" + label
        rayidname = "RayIdFrom" + label
        previoushitname = "PreviousHitFrom" + label

        # Record hit position
        self._append_property(
            nearest_obj,
            hitcoordsname,
            neworigin,
            "App::PropertyVectorList",
            "OpticalObject",
            "Hit coordinates from rays",
        )

        # Record energy at hit
        self._append_property(
            nearest_obj,
            energyname,
            float(energy),
            "App::PropertyFloatList",
            "OpticalObject",
            "Energy carried by the ray at impact",
        )

        # Record bounce count
        self._append_property(
            nearest_obj,
            bouncecountname,
            int(state.bounce_count),
            "App::PropertyIntegerList",
            "OpticalObject",
            "Number of bounces before this hit",
        )

        # Record ray ID
        self._append_property(
            nearest_obj,
            rayidname,
            int(state.ray_id),
            "App::PropertyIntegerList",
            "OpticalObject",
            "Ray ID",
        )

        # Record the previous surface that the ray hit
        self._append_property(
            nearest_obj,
            previoushitname,
            str(state.prev_hit) if state.prev_hit else "",
            "App::PropertyStringList",
            "OpticalObject",
            "Surface last hit before this impact (Object|Base|FaceN)",
        )

    def traceLens(self, fp, nearest_obj, ray1, normal, isec_struct, origin):
        if len(self.lastRefIdx) == 0:
            oldRefIdx = 1
        else:
            oldRefIdx = self.lastRefIdx[len(self.lastRefIdx) - 1]

        if len(self.lastRefIdx) < 2:
            newRefIdx = 1
        else:
            newRefIdx = self.lastRefIdx[len(self.lastRefIdx) - 2]

        if len(nearest_obj.Sellmeier) == 6:
            n = sa_OpticalObject.refraction_index_from_sellmeier(fp.Wavelength, nearest_obj.Sellmeier)
        else:
            n = nearest_obj.RefractionIndex

        if self.isInsideLens(isec_struct, origin, nearest_obj):
            # print("leave " + nearest_obj.Label)
            oldRefIdx = n
            if len(self.lastRefIdx) > 0:
                self.lastRefIdx.pop(len(self.lastRefIdx) - 1)
            # print()
        else:
            # print("enter " + nearest_obj.Label)
            newRefIdx = n
            self.lastRefIdx.append(n)

        return self.snellsLaw(ray1, oldRefIdx, newRefIdx, normal)

    def traceGrating(self, fp, nearest_obj, ray1, normal, isec_struct, origin):
        g = None
        doLens = False

        if len(self.lastRefIdx) == 0:
            oldRefIdx = 1
        else:
            oldRefIdx = self.lastRefIdx[len(self.lastRefIdx) - 1]

        if len(self.lastRefIdx) < 2:
            newRefIdx = 1
        else:
            newRefIdx = self.lastRefIdx[len(self.lastRefIdx) - 2]

        if len(nearest_obj.Sellmeier) == 6:
            n = sa_OpticalObject.refraction_index_from_sellmeier(fp.Wavelength, nearest_obj.Sellmeier)
        else:
            n = nearest_obj.RefractionIndex

        lpm = nearest_obj.lpm
        grating_lines_plane = nearest_obj.GratingLinesPlane

        if nearest_obj.ray_order_override == True:
            order = nearest_obj.order
        else:
            order = fp.Order

        if nearest_obj.GratingType == "reflection":
            grating_type = 0
        elif nearest_obj.GratingType == "transmission - diffraction at 2nd surface":
            grating_type = 1
        else:
            grating_type = 2

        if grating_type == 0:  # reflection grating
            g = self.grating_calculation(
                grating_type,
                order,
                fp.Wavelength,
                lpm,
                ray1,
                normal,
                grating_lines_plane,
                oldRefIdx,
                oldRefIdx,
            )

        elif grating_type == 2:  # transmission grating with diffraction at first surface
            if self.isInsideLens(isec_struct, origin, nearest_obj):
                doLens = True
                # print("leave t-grating 1s " + nearest_obj.Label)
                oldRefIdx = n
                # print("old RefIdx: ", oldRefIdx, "new RefIdx: ", newRefIdx)
                if len(self.lastRefIdx) > 0:
                    self.lastRefIdx.pop(len(self.lastRefIdx) - 1)
            else:
                newRefIdx = n
                self.lastRefIdx.append(n)
                # print("enter t-grating 1s " + nearest_obj.Label)
                # print("old RefIdx: ", oldRefIdx, "new RefIdx: ", newRefIdx)
                g = self.grating_calculation(
                    grating_type,
                    order,
                    fp.Wavelength,
                    lpm,
                    ray1,
                    normal,
                    grating_lines_plane,
                    oldRefIdx,
                    newRefIdx,
                )

        elif grating_type == 1:  # transmission grating with diffraction at second surface
            if self.isInsideLens(isec_struct, origin, nearest_obj):
                # print("leave t-grating 2s " + nearest_obj.Label)
                oldRefIdx = n
                # print("old RefIdx: ", oldRefIdx, "new RefIdx: ", newRefIdx)
                g = self.grating_calculation(
                    grating_type,
                    order,
                    fp.Wavelength,
                    lpm,
                    ray1,
                    normal,
                    grating_lines_plane,
                    oldRefIdx,
                    newRefIdx,
                )
            else:
                doLens = True
                newRefIdx = n
                self.lastRefIdx.append(n)
                # print("enter t-grating 2s " + nearest_obj.Label)
                # print("old RefIdx: ", oldRefIdx, "new RefIdx: ", newRefIdx)

        if doLens:
            return self.snellsLaw(ray1, oldRefIdx, newRefIdx, normal)

        return (g, False)

    def counts_as_bounce(self, nearest_obj):
        # Default: bara speglar räknas. Utöka gärna med en flagga på objektet.
        return getattr(nearest_obj, "OpticalType", "") == "mirror"

    def traceRay(self, fp, line, energy, state):
        nearest = Vector(INFINITY, INFINITY, INFINITY)
        nearest_parts = []
        origin = PointVec(line.Vertexes[0])

        # Intersections along the current segment
        isec_struct = self.getIntersections(fp, line)
        for isec in isec_struct:
            for ipoints in isec[1]:
                if len(ipoints) < 4:
                    continue

                face_global = ipoints[0]
                point_global = ipoints[1]
                base_obj = ipoints[2]
                face_index = ipoints[3]

                dist = point_global - origin
                if dist.Length <= nearest.Length + EPSILON:
                    np = (point_global, face_global, isec[0], base_obj, face_index)

                    if abs(dist.Length - nearest.Length) < EPSILON:
                        if isec[0].OpticalType == "absorber":
                            nearest_parts = [np]
                        elif len(nearest_parts) == 0 or nearest_parts[0][2].OpticalType == "absorber":
                            nearest_parts.append(np)
                    else:
                        nearest_parts = [np]

                    nearest = dist

        # No hit → return current line
        if len(nearest_parts) == 0:
            return [line]

        # Keep the single nearest hit
        if len(nearest_parts) > 1:
            nearest_parts = [nearest_parts[0]]

        # Unpack nearest hit
        neworigin, nearest_part, nearest_obj, nearest_base, face_index = nearest_parts[0]

        # Segment at the hit point
        shortline = Part.makeLine(origin, neworigin)
        ret = [shortline]

        # Advance ray state
        new_state = state.bounced(nearest_obj, nearest_base, face_index)

        # Log hit immediately
        if isRelevantOptic(fp, nearest_obj) and getattr(nearest_obj, "collectStatistics", False):
            self.collectStatistics(fp, nearest_obj, neworigin, energy, new_state)

        # Stop condition after logging
        self.iter -= 1
        if self.iter == 0:
            return ret

        # Compute outgoing rays
        dRay = neworigin - origin
        ray1 = dRay / dRay.Length

        if hasattr(nearest_obj, "Transparency"):
            P_pass = energy * (nearest_obj.Transparency) / 100.0
            P_reflect = energy * (100 - nearest_obj.Transparency) / 100.0
        else:
            P_pass, P_reflect = energy, 0

        normal = self.getNormal(nearest_obj, nearest_part, origin, neworigin)
        if normal.Length == 0:
            return ret

        dNewRays = []  # (direction_vec, energy_next, counts_as_bounce)

        if nearest_obj.OpticalType == "mirror":
            if nearest_obj.Transparency < 100:
                dNewRays.append((self.mirror(dRay, normal), P_reflect, True))
            if nearest_obj.Transparency > 0:
                if self.isInsideSolid(origin, nearest_obj):
                    P_pass = energy
                dNewRays.append((-dRay, P_pass, False))

        elif nearest_obj.OpticalType == "lens":
            (newray, totalReflection) = self.traceLens(fp, nearest_obj, ray1, normal, isec_struct, origin)
            if self.isInsideLens(isec_struct, origin, nearest_obj):
                P_pass = energy
            elif nearest_obj.Transparency < 100 and not totalReflection:
                dNewRays.append((self.mirror(dRay, normal), P_reflect, True))
            dNewRays.append((newray, P_pass, False))

        elif nearest_obj.OpticalType == "grating":
            (newray, totalReflection) = self.traceGrating(fp, nearest_obj, ray1, normal, isec_struct, origin)
            dNewRays.append((newray, P_pass, False))

        elif nearest_obj.OpticalType == "absorber":
            # Energifördelning: absorber släpper bara igenom (ingen reflex)
            if hasattr(nearest_obj, "Transparency"):
                P_pass = energy * (nearest_obj.Transparency) / 100.0
                P_abs = energy * (100 - nearest_obj.Transparency) / 100.0
            else:
                P_pass = 0.0
                P_abs = energy

            # Logga träffen (räknare/koord/energi) – du gör detta redan ovan
            # self.collectStatistics(fp, nearest_obj, neworigin, energy, new_state)
            # (du kallar collectStatistics redan innan grenen väljs, så det
            #  behövs normalt inte extra här)

            # Om inget ska passera → stoppa strålen
            if P_pass <= 0:
                return ret

            # Bestäm utgående riktning vid pass-through:
            # För absorber: enkel “genomgång” längs -dRay (samma som du gör
            # för Mirror när Transparency > 0)
            dRay = neworigin - origin
            new_dir = -dRay

            # Skapa nästa segment och fortsätt spåra
            nl = Part.makeLine(neworigin, neworigin - new_dir * fp.MaxRayLength / new_dir.Length)
            ret.extend(self.traceRay(fp, nl, P_pass, new_state))
            return ret

        else:
            return ret

        # Recurse
        for dvec, energy_next, _ in dNewRays:
            nl = Part.makeLine(neworigin, neworigin - dvec * fp.MaxRayLength / dvec.Length)
            ret.extend(self.traceRay(fp, nl, energy_next, new_state))

        return ret

    def getNormal(self, nearest_obj, nearest_part, origin, neworigin):
        dRay = neworigin - origin
        if hasattr(nearest_part, "Curve"):
            param = nearest_part.Curve.parameter(neworigin)
            tangent = nearest_part.tangentAt(param)
            normal1 = dRay.cross(tangent)
            normal = tangent.cross(normal1)
            if normal.Length < EPSILON:
                return Vector(0, 0, 0)
            normal = normal / normal.Length

        elif hasattr(nearest_part, "Surface"):
            uv = nearest_part.Surface.parameter(neworigin)
            normal = nearest_part.normalAt(uv[0], uv[1])
        else:
            return Vector(0, 0, 0)

        cosangle = dRay * normal / (dRay.Length * normal.Length)
        if cosangle < 0:
            normal = -normal

        return normal

    def mirror(self, dRay, normal):
        return 2 * normal * (dRay * normal) - dRay

    def snellsLaw(self, ray, n1, n2, normal):
        root = 1 - n1 / n2 * n1 / n2 * normal.cross(ray) * normal.cross(ray)
        if root < 0:  # total reflection
            return (self.mirror(ray, normal), True)

        refractedRay = -n1 / n2 * normal.cross((-normal).cross(ray)) - normal * math.sqrt(root)

        return (refractedRay, False)

    def grating_calculation(self, grating_type, order, wavelength, lpm, ray, normal, g_g_p_vector, n1, n2):  # from Ludwig 1970
        # get parameters
        wavelength = wavelength / 1000
        ray = ray / ray.Length
        surf_norma = -normal  # the normal seems to be in ray direction so change this
        surf_norma = surf_norma / surf_norma.Length  # normalize the surface normal
        # hypothetical first vector determining the orientation of the grating rules. This vector is normal to a plane that would cause the rules by intersection with the surface of the grating.
        g_g_p_vector = g_g_p_vector / g_g_p_vector.Length

        # print("Grating normal = ", normal)
        # print("ray = ", ray[0], ray[1], ray[2])
        # print("Grating normal = ", surf_norma)
        # print("wavelength= ", wavelength)
        # print("g_g_p_vector = ", g_g_p_vector)

        P = g_g_p_vector.cross(surf_norma)
        P = P / P.Length
        # print("P",P)
        D = surf_norma.cross(P)
        # print("D", D)
        D = D / D.Length
        mu = n1 / n2
        # print("mu", mu)
        d = 1000 / lpm
        # print("d",d)
        T = (order * wavelength) / (n1 * d)
        # print("T", T)
        # print("ray", ray[0], ray[1], ray[2])
        V = (mu * (ray[0] * surf_norma[0] + ray[1] * surf_norma[1] + ray[2] * surf_norma[2])) / surf_norma.dot(surf_norma)
        # print("V", V)
        W = (mu**2 - 1 + T**2 - 2 * mu * T * (ray[0] * D[0] + ray[1] * D[1] + ray[2] * D[2])) / surf_norma.dot(surf_norma)
        # print("W", W)
        # print("calc_test ", (ray[0]*D[0]+ray[1]*D[1]+ray[2]*D[2]))
        # print ("W>V**2? ", W>V**2)
        Q = (
            (-2 * V + ((2 * V) ** 2 - 4 * W) ** 0.5) / 2,
            (-2 * V - ((2 * V) ** 2 - 4 * W) ** 0.5) / 2,
        )
        # print("Q",Q)

        if grating_type == 0:  # reflection grating
            # S_ = mu*ray_trans-T*D+max(Q)*surf_norma_trans
            S_0 = mu * ray[0] - T * D[0] + max(Q) * surf_norma[0]
            S_1 = mu * ray[1] - T * D[1] + max(Q) * surf_norma[1]
            S_2 = mu * ray[2] - T * D[2] + max(Q) * surf_norma[2]
            S_ = Vector(S_0, S_1, S_2)
        else:  # transmission grating
            # S_ = mu*ray-T*D+min(Q)*surf_norma
            S_0 = mu * ray[0] - T * D[0] + min(Q) * surf_norma[0]
            S_1 = mu * ray[1] - T * D[1] + min(Q) * surf_norma[1]
            S_2 = mu * ray[2] - T * D[2] + min(Q) * surf_norma[2]
            S_ = Vector(S_0, S_1, S_2)

        S_ = -S_
        # print("S_", S_)
        return S_

    def check2D(self, objlist):
        nvec = Vector(1, 1, 1)
        for obj in objlist:
            bbox = obj.BoundBox
            if bbox.XLength > EPSILON:
                nvec.x = 0
            if bbox.YLength > EPSILON:
                nvec.y = 0
            if bbox.ZLength > EPSILON:
                nvec.z = 0

        return nvec

    def isInsideSolid(self, origin, lens):
        lens_placement_matrix = lens.getGlobalPlacement().Matrix
        origin = lens_placement_matrix.inverse().multVec(origin)
        for b in lens.Base:
            for sol in b.Shape.Solids:
                if sol.isInside(origin, EPSILON, True):
                    return True

        return False

    def isInsideLens(self, isec_struct, origin, lens):
        lens_placement_matrix = lens.getGlobalPlacement().Matrix
        origin = lens_placement_matrix.inverse().multVec(origin)
        nr_solids = 0
        for b in lens.Base:
            for sol in b.Shape.Solids:
                nr_solids += 1
                if sol.isInside(origin, EPSILON, True):
                    return True

        if nr_solids == 0:
            for isec in isec_struct:
                if lens == isec[0]:
                    return len(isec[1]) % 2 == 1

        return False


def PointVec(p):
    # OCC gp_Pnt (versaler)
    if hasattr(p, "X") and hasattr(p, "Y") and hasattr(p, "Z"):
        return Vector(p.X, p.Y, p.Z)

    # Part.Vertex -> .Point är en Base.Vector
    if hasattr(p, "Point"):
        v = p.Point
        return Vector(v.x, v.y, v.z)

    # FreeCAD/Base.Vector (gemener)
    if hasattr(p, "x") and hasattr(p, "y") and hasattr(p, "z"):
        return Vector(p.x, p.y, p.z)

    # tuple/list fallback
    if isinstance(p, (tuple, list)) and len(p) >= 3:
        return Vector(p[0], p[1], p[2])

    raise TypeError(f"Unsupported point type: {type(p)}")


# def isOpticalObject(obj):
#     return (
#         obj.TypeId == "Part::FeaturePython"
#         and hasattr(obj, "OpticalType")
#         and hasattr(obj, "Base")
#     )


def isOpticalObject(obj):
    return hasattr(obj, "OpticalType") and hasattr(obj, "Base") and (obj.isDerivedFrom("App::FeaturePython") or obj.isDerivedFrom("Part::FeaturePython"))


def isRelevantOptic(fp, obj):
    """Determine if given object is a workbench optical component and if it should be considered in the ray calculation"""
    if hasattr(fp, "IgnoredOpticalElements"):
        return isOpticalObject(obj) and (obj not in fp.IgnoredOpticalElements)

    # for older documents where rays do not have the IgnoredOpticalElements field we
    # will just return the old function, which checks only if the object is of "OpticalType"
    return isOpticalObject(obj)


class RayViewProvider:

    def __init__(self, vobj):
        """Set this object to the proxy object of the actual view provider"""
        vobj.Proxy = self
        self.Object = vobj.Object

    def getIcon(self):
        """Return the icon which will appear in the tree view. This method is optional and if not defined a default icon is shown."""
        if self.Object.Base:
            return os.path.join(_icondir_, "emitter.svg")
        elif self.Object.RayBundleType == "spherical":
            return os.path.join(_icondir_, "sun.svg")
        elif self.Object.RayBundleType == "focal":
            return os.path.join(_icondir_, "raygridfocal.svg")
        else:
            if self.Object.BeamNrColumns * self.Object.BeamNrRows <= 1:
                return os.path.join(_icondir_, "ray.svg")
            else:
                return os.path.join(_icondir_, "rayarray.svg")

    def attach(self, vobj):
        """Setup the scene sub-graph of the view provider, this method is mandatory"""
        self.Object = vobj.Object
        self.onChanged(vobj, "Power")

    def updateData(self, fp, prop):
        """If a property of the handled feature has changed we have the chance to handle this here"""
        pass

    def claimChildren(self):
        """Return a list of objects that will be modified by this feature"""
        if not self.Object.Base:
            return []

        return self.Object.Base

    def onDelete(self, feature, subelements):
        """Here we can do something when the feature will be deleted"""
        return True

    def onChanged(self, fp, prop):
        """Here we can do something when a single property got changed"""
        pass

    def __getstate__(self):
        """When saving the document this object gets stored using Python's json module.\
                Since we have some un-serializable parts here -- the Coin stuff -- we must define this method\
                to return a tuple of all serializable objects or None."""
        return None

    def __setstate__(self, state):
        """When restoring the serialized object from document we have the chance to set some internals here.\
                Since no data were serialized nothing needs to be done here."""
        return None


class Ray:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.makeRay()")

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
            "Pixmap": os.path.join(_icondir_, "ray.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Ray (monochrome)", "Ray (monochrome)"),
            "ToolTip": __doc__,
        }


class RaySun:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.makeSunRay()")

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
            "Pixmap": os.path.join(_icondir_, "raysun.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Ray (sun light)", "Ray (sun light)"),
            "ToolTip": translate(
                "Ray (sun light)",
                "A bunch of rays with different wavelengths of visible light",
            ),
        }


class Beam2D:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand('sa_OpticsWorkbench.makeRay(beamNrColumns=50, beamDistance=0.1, rayBundleType="parallel")')

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
            "Pixmap": os.path.join(_icondir_, "rayarray.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Beam", "2D Beam"),
            "ToolTip": translate("Beam", "A row of multiple rays for raytracing"),
        }


class RadialBeam2D:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand('sa_OpticsWorkbench.makeRay(beamNrColumns=64, rayBundleType="spherical")')

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
            "Pixmap": os.path.join(_icondir_, "sun.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("2D Radial Beam", "2D Radial Beam"),
            "ToolTip": translate(
                "2D Radial Beam",
                "Rays coming from one point going to all directions in a 2D plane",
            ),
        }


class SphericalBeam:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand('sa_OpticsWorkbench.makeRay(beamNrColumns=8, beamNrRows=8, rayBundleType="spherical")')

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
            "Pixmap": os.path.join(_icondir_, "sun3D.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Spherical Beam", "Spherical Beam"),
            "ToolTip": translate("Spherical Beam", "Rays coming from one point going to all directions"),
        }


class RedrawAll:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.restartAll()")

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
            "Pixmap": os.path.join(_icondir_, "Anonymous_Lightbulb_Lit.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Start", "(Re)start simulation"),
            "ToolTip": translate("Start", "(Re)start simulation"),
        }


class AllOff:
    """This class will be loaded when the workbench is activated in FreeCAD. You must restart FreeCAD to apply changes in this class"""

    def Activated(self):
        """Will be called when the feature is executed."""
        # Generate commands in the FreeCAD python console to create Ray
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand("sa_OpticsWorkbench.allOff()")

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
            "Pixmap": os.path.join(_icondir_, "Anonymous_Lightbulb_Off.svg"),
            "Accel": "",  # a default shortcut (optional)
            "MenuText": translate("Off", "Switch off lights"),
            "ToolTip": translate("Off", "Switch off all rays and beams"),
        }


class GridToFocalBeam:
    """A grid of rays converging toward a focal point"""

    def Activated(self):
        Gui.doCommand("import sa_OpticsWorkbench")
        Gui.doCommand('r = sa_OpticsWorkbench.makeRay(beamNrColumns=10, beamNrRows=3, beamDistance=1.0, rayBundleType="focal", focalPoint=FreeCAD.Vector(0, 0, 100))')

    def IsActive(self):
        return activeDocument() is not None

    def GetResources(self):
        return {
            "Pixmap": os.path.join(_icondir_, "raygridfocal.svg"),  # You can add your own icon
            "Accel": "",
            "MenuText": translate("Grid Focal Beam", "Grid Focal Beam"),
            "ToolTip": translate("Grid Focal Beam", "Grid of rays all directed toward a focal point"),
        }


Gui.addCommand("sa_Ray (monochrome)", Ray())
Gui.addCommand("sa_Ray (sun light)", RaySun())
Gui.addCommand("sa_Beam", Beam2D())
Gui.addCommand("sa_2D Radial Beam", RadialBeam2D())
Gui.addCommand("sa_Spherical Beam", SphericalBeam())
Gui.addCommand("sa_Start", RedrawAll())
Gui.addCommand("sa_Off", AllOff())
Gui.addCommand("sa_Grid Focal Beam", GridToFocalBeam())
