# core_logic/basin_calculator_refactored.py

import numpy as np
# --- CAMBIO 1: Volvemos a importar la función original ---
from .gis_utils import get_local_path_from_url, LAYER_MAPPING
try:
    from osgeo import gdal, osr, ogr
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False
# try:
#     from osgeo import gdal, osr, ogr
#     GDAL_AVAILABLE = True
# except ImportError:
#     GDAL_AVAILABLE = False
#     gdal = None
#     osr = None
#     ogr = None
from shapely.geometry import shape, mapping
from shapely.ops import transform as shapely_transform
import os
import math
import statistics
from collections import defaultdict
import json
from pyproj import Transformer
import fiona

# Define un área de 100km x 100km alrededor del punto para procesar.
# Esto evita cargar el DEM nacional completo en la memoria.
PROCESSING_BUFFER_METERS = 50000 

class BasinCalculatorRefactored:
    def __init__(self, data_folder_unused, layer_mapping_from_app):
        if not GDAL_AVAILABLE:
            raise ImportError("GDAL no está disponible.")
        
        gdal.UseExceptions()
        gdal.AllRegister()

        # El constructor ahora solo prepara las rutas virtuales para GDAL.
        # No abre archivos ni consume RAM.
        self.gdal_raster_paths = {}
        for key, url in layer_mapping_from_app.items():
            if url.endswith(('.tif', '_COG.tif', '_cog.tif')):
                path_or_url = get_local_path_from_url(url)
                self.gdal_raster_paths[key] = f"/vsicurl/{path_or_url}"

    def _open_secondary_layer(self, path, name):
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None:
            print(f"Warning: Could not open secondary layer dataset at {path}")
            return
        band = ds.GetRasterBand(1)
        # Leemos los rásters secundarios completos porque son pequeños y es más eficiente.
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
        self.basinCells = None
        self.visited_cells = set()
        self.basinGeometry = []
        self.basinGeometryUTM = []

    def _mean(self, array):
        if not array: return None
        valid_values = [float(v) for v in array if v is not None]
        if not valid_values: return None
        return statistics.mean(valid_values)

    def calculate(self, pt_utm):
        self._resetValues()

        mdt_dataset = gdal.Open(self.gdal_raster_paths["MDT"], gdal.GA_ReadOnly)
        flowdirs_dataset = gdal.Open(self.gdal_raster_paths["FLOWDIRS"], gdal.GA_ReadOnly)
        if mdt_dataset is None or flowdirs_dataset is None:
            raise ConnectionError("No se pudieron abrir los datasets ráster principales desde la URL.")

        global_geoTransform = mdt_dataset.GetGeoTransform()
        self.crs_wkt = mdt_dataset.GetProjection()
        inv_global_geoTransform = gdal.InvGeoTransform(global_geoTransform)

        min_x = pt_utm[0] - PROCESSING_BUFFER_METERS
        max_x = pt_utm[0] + PROCESSING_BUFFER_METERS
        min_y = pt_utm[1] - PROCESSING_BUFFER_METERS
        max_y = pt_utm[1] + PROCESSING_BUFFER_METERS

        ul_x, ul_y = gdal.ApplyGeoTransform(inv_global_geoTransform, min_x, max_y)
        lr_x, lr_y = gdal.ApplyGeoTransform(inv_global_geoTransform, max_x, min_y)
        
        px_start, py_start = int(ul_x), int(ul_y)
        px_width, py_height = int(lr_x - ul_x), int(lr_y - ul_y)

        mdt_band = mdt_dataset.GetRasterBand(1)
        self.mdt = mdt_band.ReadAsArray(px_start, py_start, px_width, py_height)
        self.nodataMdt = mdt_band.GetNoDataValue()

        flowdirs_band = flowdirs_dataset.GetRasterBand(1)
        self.dirs = flowdirs_band.ReadAsArray(px_start, py_start, px_width, py_height)
        self.nodataDirs = flowdirs_band.GetNoDataValue()
        
        mdt_dataset, flowdirs_dataset = None, None

        self.geoTransform = list(global_geoTransform)
        self.geoTransform[0], self.geoTransform[3] = min_x, max_y
        self.geoTransform = tuple(self.geoTransform)
        
        self.cellsize = self.geoTransform[1]
        self.cellarea = self.cellsize * self.cellsize
        self.basinCells = np.zeros(self.mdt.shape, dtype=np.int8)

        inv_local_geoTransform = gdal.InvGeoTransform(self.geoTransform)
        x_pixel, y_pixel = gdal.ApplyGeoTransform(inv_local_geoTransform, pt_utm[0], pt_utm[1])
        x_pixel, y_pixel = int(x_pixel), int(y_pixel)
        
        self.secondaryLayers = {}
        self.secondaryNodata = {}
        self.secondaryTransforms = {}
        
        self._open_secondary_layer(self.gdal_raster_paths["I1ID"], "I1ID")
        self._open_secondary_layer(self.gdal_raster_paths["P0"], "P0")

        self.rainFiles = {
            2: "RAIN_2", 5: "RAIN_5", 10: "RAIN_10",
            25: "RAIN_25", 100: "RAIN_100", 500: "RAIN_500",
        }
        for returnPeriod, rainFileKey in self.rainFiles.items():
            self._open_secondary_layer(self.gdal_raster_paths[rainFileKey], returnPeriod)

        rows, cols = self.mdt.shape
        if not (0 <= y_pixel < rows and 0 <= x_pixel < cols):
            raise ValueError(f"Punto de salida ({pt_utm}) fuera de los límites del área de procesamiento.")

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
            if delta_h <= 0: self.concentrationTime = 0
            else: self.concentrationTime = 0.3 * ((self.maxDistance / 1000.0) / math.pow((delta_h / self.maxDistance), 0.25))**0.76
        else:
            self.concentrationTime = 0

        self.computeBasinContour()

    def computeBasinContour(self):
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
        srs = osr.SpatialReference(); srs.SetFromUserInput(self.crs_wkt)
        dst_layer = dst_ds.CreateLayer("basin", srs=srs, geom_type=ogr.wkbMultiPolygon)
        
        field_defn = ogr.FieldDefn("DN", ogr.OFTInteger)
        dst_layer.CreateField(field_defn)
        gdal.Polygonize(band, None, dst_layer, 0, [], callback=None)

        source_crs = srs.ExportToProj4()
        target_crs = "EPSG:4326"
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

        self.basinGeometry, self.basinGeometryUTM = [], []
        for feature in dst_layer:
            if feature.GetField("DN") == 1:
                ogr_geom = feature.GetGeometryRef()
                if ogr_geom:
                    shapely_geom_utm = shape(json.loads(ogr_geom.ExportToJson()))
                    self.basinGeometryUTM.append(shapely_geom_utm)
                    shapely_geom_wgs84 = shapely_transform(transformer.transform, shapely_geom_utm)
                    self.basinGeometry.append(shapely_geom_wgs84)
        src_ds, dst_ds = None, None

    def export_basin_to_shapefile(self, output_path):
        if not self.basinGeometryUTM: return False
        schema = {'geometry': 'Polygon', 'properties': {'id': 'int'}}
        try:
            with fiona.open(output_path, 'w', driver='ESRI Shapefile', crs=self.crs_wkt, schema=schema) as c:
                for i, geom_utm in enumerate(self.basinGeometryUTM):
                    c.write({'geometry': mapping(geom_utm), 'properties': {'id': i + 1}})
            return True
        except Exception as e:
            print(f"Error exporting shapefile: {e}")
            return False

    # def _getValueAtCoordinate(self, x_utm, y_utm, layer_name_key):
    #     layer_data = self.secondaryLayers.get(layer_name_key)
    #     layer_gt = self.secondaryTransforms.get(layer_name_key)
    #     layer_nodata = self.secondaryNodata.get(layer_name_key)
    # 
    #     if layer_data is None or layer_gt is None:
    #         return None
    # 
    #     inv_layer_gt = gdal.InvGeoTransform(layer_gt)
    #     if inv_layer_gt is None:
    #         return None
    # 
    #     px, py = gdal.ApplyGeoTransform(inv_layer_gt, x_utm, y_utm)
    #     px, py = int(px), int(py)
    # 
    #     rows, cols = layer_data.shape
    #     if not (0 <= py < rows and 0 <= px < cols):
    #         return None
    # 
    #     val = layer_data[py, px]
    #     if val == layer_nodata:
    #         return None
    #     else:
    #         return val

    def _getValueAtCoordinate(self, x_utm, y_utm, layer_name_key):
        layer_data = self.secondaryLayers.get(layer_name_key)
        layer_gt = self.secondaryTransforms.get(layer_name_key)
        layer_nodata = self.secondaryNodata.get(layer_name_key)
        if layer_data is None or layer_gt is None: return None
        inv_layer_gt = gdal.InvGeoTransform(layer_gt)
        if inv_layer_gt is None: return None
        px, py = gdal.ApplyGeoTransform(inv_layer_gt, x_utm, y_utm)
        px, py = int(px), int(py)
        rows, cols = layer_data.shape
        if not (0 <= py < rows and 0 <= px < cols): return None
        val = layer_data[py, px]
        return None if val == layer_nodata else val

    directions_to_check = [
        (-1, 0, 1), (-1, -1, 2), (0, -1, 4), (1, -1, 8),
        (1, 0, 16), (1, 1, 32), (0, 1, 64), (-1, 1, 128),
    ]

    def _processCell(self, x, y, distance=0):
        rows, cols = self.mdt.shape
        if not (0 <= y < rows and 0 <= x < cols) or (x, y) in self.visited_cells:
            return
        self.visited_cells.add((x, y))
        self.basinCells[y, x] = 1
        coordx_utm, coordy_utm = gdal.ApplyGeoTransform(self.geoTransform, x + 0.5, y + 0.5)

        p0 = self._getValueAtCoordinate(coordx_utm, coordy_utm, "P0")
        if p0 is not None and p0 > 0: self.p0Values.append(p0)
        i1id = self._getValueAtCoordinate(coordx_utm, coordy_utm, "I1ID")
        if i1id is not None and i1id > 0: self.i1idValues.append(i1id)
        for rp_key in self.rainFiles.keys():
            rain = self._getValueAtCoordinate(coordx_utm, coordy_utm, rp_key)
            if rain is not None and rain > 0: self.rainValues[rp_key].append(rain)

        h = self.mdt[y, x]
        if h != self.nodataMdt:
            self.minH = min(self.minH, h)
            if h > self.maxH: self.maxH = h
            if distance > self.maxDistance:
                self.maxDistance = distance
                self.xMaxDistance, self.yMaxDistance = coordx_utm, coordy_utm

        self.area += self.cellarea
        for dx, dy, dir_val in self.directions_to_check:
            x2, y2 = x + dx, y + dy
            if 0 <= y2 < rows and 0 <= x2 < cols and self.dirs[y2, x2] == dir_val:
                distToNext = self.cellsize if (dx == 0 or dy == 0) else self.cellsize * 1.4142
                self._processCell(x2, y2, distance + distToNext)
