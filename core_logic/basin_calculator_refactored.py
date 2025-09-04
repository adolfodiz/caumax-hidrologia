# core_logic/basin_calculator_refactored.py

import numpy as np
# from osgeo import gdal, osr, ogr
try:
    from osgeo import gdal, osr, ogr
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False
    gdal = None
    osr = None
    ogr = None
from shapely.geometry import shape, mapping # <-- MEJORA 2: Importar mapping
from shapely.ops import transform as shapely_transform
import os
import math
import statistics
from collections import defaultdict
import json
from pyproj import Transformer
import fiona
from fiona.crs import from_epsg

class BasinCalculatorRefactored:
    def __init__(self, data_folder, layer_mapping):
        if GDAL_AVAILABLE:
            gdal.UseExceptions()
            gdal.AllRegister()
        
        self.data_folder = data_folder
        self.layer_mapping = layer_mapping

        mdt_path = os.path.join(self.data_folder, self.layer_mapping["MDT"])
        flowdirs_path = os.path.join(self.data_folder, self.layer_mapping["FLOWDIRS"])

        mdt_dataset = gdal.Open(mdt_path, gdal.GA_ReadOnly)
        if mdt_dataset is None:
            raise FileNotFoundError(f"Could not open MDT dataset at {mdt_path}")
        
        mdt_band = mdt_dataset.GetRasterBand(1)
        self.nodataMdt = mdt_band.GetNoDataValue()
        self.mdt = mdt_band.ReadAsArray()
        self.geoTransform = mdt_dataset.GetGeoTransform()
        self.crs_wkt = mdt_dataset.GetProjection()

        self.cellsize = self.geoTransform[1]
        self.cellarea = self.cellsize * self.cellsize

        flowdirs_dataset = gdal.Open(flowdirs_path, gdal.GA_ReadOnly)
        if flowdirs_dataset is None:
            raise FileNotFoundError(f"Could not open FLOWDIRS dataset at {flowdirs_path}")
        flowdirs_band = flowdirs_dataset.GetRasterBand(1)
        self.nodataDirs = flowdirs_band.GetNoDataValue()
        self.dirs = flowdirs_band.ReadAsArray()

        self.secondaryLayers = {}
        self.secondaryNodata = {}
        self.secondaryTransforms = {}

        self._open_secondary_layer(os.path.join(self.data_folder, self.layer_mapping["I1ID"]), "I1ID")
        self._open_secondary_layer(os.path.join(self.data_folder, self.layer_mapping["P0"]), "P0")

        self.rainFiles = {
            2: "RAIN_2", 5: "RAIN_5", 10: "RAIN_10",
            25: "RAIN_25", 100: "RAIN_100", 500: "RAIN_500",
        }
        for returnPeriod, rainFileKey in self.rainFiles.items():
            self._open_secondary_layer(os.path.join(self.data_folder, self.layer_mapping[rainFileKey]), returnPeriod)

        self._resetValues()

    def _open_secondary_layer(self, path, name):
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None:
            print(f"Warning: Could not open secondary layer dataset at {path}")
            return
        band = ds.GetRasterBand(1)
        self.secondaryLayers[name] = band.ReadAsArray()
        self.secondaryTransforms[name] = ds.GetGeoTransform()
        self.secondaryNodata[name] = band.GetNoDataValue()
        ds = None

    def _resetValues(self):
        self.maxH = -float('inf')
        self.minH = float('inf')
        self.area = 0
        self.maxDistance = 0
        self.concentrationTime = 0
        self.xMaxDistance = None
        self.yMaxDistance = None
        self.p0Values = []
        self.i1idValues = []
        self.rainValues = defaultdict(list)
        self.basinCells = np.zeros(self.mdt.shape, dtype=np.int8)
        self.visited_cells = set()
        self.basinGeometry = [] # <-- Geometría en WGS84 para el mapa
        self.basinGeometryUTM = [] # <-- MEJORA 2: Geometría en UTM para exportar

    def _mean(self, array):
        if not array:
            return None
        valid_values = [float(v) for v in array if v is not None]
        if not valid_values:
            return None
        return statistics.mean(valid_values)

    def calculate(self, pt_utm):
        self._resetValues()
        self.pt_utm = pt_utm

        inv_geoTransform = gdal.InvGeoTransform(self.geoTransform)
        if inv_geoTransform is None:
            raise Exception("Could not invert geotransform for MDT.")

        x_pixel, y_pixel = gdal.ApplyGeoTransform(inv_geoTransform, pt_utm[0], pt_utm[1])
        x_pixel, y_pixel = int(x_pixel), int(y_pixel)

        rows, cols = self.mdt.shape
        if not (0 <= y_pixel < rows and 0 <= x_pixel < cols):
            raise ValueError(f"Punto de salida ({pt_utm}) fuera de los límites del MDT raster.")

        initial_h = self.mdt[y_pixel, x_pixel]
        if initial_h == self.nodataMdt:
            raise ValueError(f"Punto de salida ({pt_utm}) en valor NoData del MDT.")

        self.minH = initial_h
        self.maxH = initial_h
        self.xMaxDistance, self.yMaxDistance = pt_utm[0], pt_utm[1]

        self._processCell(x_pixel, y_pixel, distance=0)

        self.i1id = self._mean(self.i1idValues)
        self.p0 = self._mean(self.p0Values)
        self.rain = {k: self._mean(v) for k, v in self.rainValues.items()}

        if self.maxDistance > 0:
            delta_h = self.maxH - self.minH
            if delta_h <= 0:
                self.concentrationTime = 0
            else:
                self.concentrationTime = 0.3 * (
                    (self.maxDistance / 1000.0)
                    / math.pow((delta_h / self.maxDistance), 0.25)
                )**0.76
        else:
            self.concentrationTime = 0

        self.computeBasinContour()

    def computeBasinContour(self):
        """
        Generates the basin polygon from the basinCells array, filtering to keep
        only the desired polygon, and transforms it to WGS84.
        """
        rows, cols = self.mdt.shape
        src_drv = gdal.GetDriverByName("MEM")
        src_ds = src_drv.Create("", cols, rows, 1, gdal.GDT_Byte)
        src_ds.SetGeoTransform(self.geoTransform)
        src_ds.SetProjection(self.crs_wkt)
        band = src_ds.GetRasterBand(1)
        band.WriteArray(self.basinCells)
        band.SetNoDataValue(0)

        dst_drv = ogr.GetDriverByName("Memory")
        dst_ds = dst_drv.CreateDataSource("basin_geometry")
        
        srs = osr.SpatialReference()
        srs.SetFromUserInput(self.crs_wkt)
        
        dst_layer = dst_ds.CreateLayer("basin", srs=srs, geom_type=ogr.wkbMultiPolygon)
        
        # --- MEJORA 1: Filtrar el polígono exterior ---
        # 1. Crear un campo para almacenar el valor del píxel del polígono
        field_defn = ogr.FieldDefn("DN", ogr.OFTInteger)
        dst_layer.CreateField(field_defn)
        
        # 2. Ejecutar Polygonize, guardando el valor del píxel en el campo 'DN' (índice 0)
        gdal.Polygonize(band, None, dst_layer, 0, [], callback=None)

        source_crs = srs.ExportToProj4()
        target_crs = "EPSG:4326"
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

        self.basinGeometry = []
        self.basinGeometryUTM = []
        
        # 3. Iterar y guardar solo el polígono con el valor correcto (DN=1)
        for feature in dst_layer:
            if feature.GetField("DN") == 1: # <-- Este es el filtro clave
                ogr_geom = feature.GetGeometryRef()
                if ogr_geom:
                    shapely_geom_utm = shape(json.loads(ogr_geom.ExportToJson()))
                    self.basinGeometryUTM.append(shapely_geom_utm)
                    
                    shapely_geom_wgs84 = shapely_transform(transformer.transform, shapely_geom_utm)
                    self.basinGeometry.append(shapely_geom_wgs84)
        # --- FIN DE LA MEJORA 1 ---

        src_ds = None
        dst_ds = None

    # --- MEJORA 2: FUNCIÓN DE EXPORTACIÓN MEJORADA ---
    def export_basin_to_shapefile(self, output_path):
        """
        Exports the calculated basin geometry to a Shapefile in its original CRS.
        """
        if not self.basinGeometryUTM:
            print("Warning: No basin geometry (UTM) to export.")
            return False

        schema = {'geometry': 'Polygon', 'properties': {'id': 'int'}}
        
        try:
            with fiona.open(
                output_path,
                'w',
                driver='ESRI Shapefile',
                crs=self.crs_wkt, # Usar el WKT original
                schema=schema
            ) as collection:
                for i, geom_utm in enumerate(self.basinGeometryUTM):
                    collection.write({
                        'geometry': mapping(geom_utm),
                        'properties': {'id': i + 1},
                    })
            return True
        except Exception as e:
            print(f"Error exporting shapefile to {output_path}: {e}")
            return False

    def _getValueAtCoordinate(self, x_utm, y_utm, layer_name_key):
        layer_data = self.secondaryLayers.get(layer_name_key)
        layer_gt = self.secondaryTransforms.get(layer_name_key)
        layer_nodata = self.secondaryNodata.get(layer_name_key)

        if layer_data is None or layer_gt is None:
            return None

        inv_layer_gt = gdal.InvGeoTransform(layer_gt)
        if inv_layer_gt is None:
            return None

        px, py = gdal.ApplyGeoTransform(inv_layer_gt, x_utm, y_utm)
        px, py = int(px), int(py)

        rows, cols = layer_data.shape
        if not (0 <= py < rows and 0 <= px < cols):
            return None

        val = layer_data[py, px]
        if val == layer_nodata:
            return None
        else:
            return val

    directions_to_check = [
        (-1, 0, 1), (-1, -1, 2), (0, -1, 4), (1, -1, 8),
        (1, 0, 16), (1, 1, 32), (0, 1, 64), (-1, 1, 128),
    ]

    def _processCell(self, x, y, distance=0):
        rows, cols = self.mdt.shape
        if not (0 <= y < rows and 0 <= x < cols):
            return
        if (x, y) in self.visited_cells:
            return
        self.visited_cells.add((x, y))

        self.basinCells[y, x] = 1

        coordx_utm, coordy_utm = gdal.ApplyGeoTransform(self.geoTransform, x + 0.5, y + 0.5)

        p0 = self._getValueAtCoordinate(coordx_utm, coordy_utm, "P0")
        if p0 is not None and p0 > 0:
            self.p0Values.append(p0)
        i1id = self._getValueAtCoordinate(coordx_utm, coordy_utm, "I1ID")
        if i1id is not None and i1id > 0:
            self.i1idValues.append(i1id)
        for returnPeriod_key in self.rainFiles.keys():
            rain = self._getValueAtCoordinate(coordx_utm, coordy_utm, returnPeriod_key)
            if rain is not None and rain > 0:
                self.rainValues[returnPeriod_key].append(rain)

        h = self.mdt[y, x]
        if h != self.nodataMdt:
            self.minH = min(self.minH, h)
            self.maxH = max(self.maxH, h)

            if distance > self.maxDistance:
                self.maxDistance = distance
                self.xMaxDistance, self.yMaxDistance = coordx_utm, coordy_utm
            elif distance == self.maxDistance and h > self.maxH:
                self.maxH = h
                self.xMaxDistance, self.yMaxDistance = coordx_utm, coordy_utm

        self.area += self.cellarea

        for dx, dy, direction_value_of_neighbor in self.directions_to_check:
            x2 = x + dx
            y2 = y + dy
            
            if 0 <= y2 < rows and 0 <= x2 < cols:
                if self.dirs[y2, x2] == direction_value_of_neighbor:
                    distToNextCell = 1 if (dx == 0 or dy == 0) else 1.414
                    self._processCell(x2, y2, distance + distToNextCell * self.cellsize)
