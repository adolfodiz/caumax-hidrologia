# core_logic/gis_utils.py (Versión Final y Correcta)
import requests
import io
import tempfile
import os
from streamlit import cache_resource
import rasterio
import fiona
from shapely.geometry import shape, Point
import json
from pyproj import CRS, Transformer

LAYER_MAPPING = {
    "BASINS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/demarcaciones_hidrograficas.gpkg",
    "RIVERS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/red10km.gpkg",
    "ZONES": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/regiones.gpkg",
    "MDT": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/mdt.tif",
    "FLOWDIRS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/dir.tif",
    "I1ID": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/i1id.tif",
    "P0": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/p0.tif",
    "RAIN_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t2.tif",
    "RAIN_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t5.tif",
    "RAIN_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t10.tif",
    "RAIN_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t25.tif",
    "RAIN_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t100.tif",
    "RAIN_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/t500.tif",
    "FLOW_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q2.tif",
    "FLOW_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q5.tif",
    "FLOW_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q10.tif",
    "FLOW_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q25.tif",
    "FLOW_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q100.tif",
    "FLOW_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/q500.tif",
}

_temp_dir = tempfile.TemporaryDirectory()

@cache_resource(ttl=3600)
def get_local_path_from_url(url):
    try:
        filename = os.path.basename(url)
        local_path = os.path.join(_temp_dir.name, filename)
        if os.path.exists(local_path):
            return local_path
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        return local_path
    except Exception as e:
        print(f"Error crítico descargando el archivo {url}: {e}")
        return None

def get_layer_path(layer_key):
    return LAYER_MAPPING.get(layer_key)

def load_geojson_from_gpkg(local_gpkg_path):
    """
    Carga todos los objetos de un archivo GPKG desde una RUTA LOCAL TEMPORAL
    y los devuelve como un GeoJSON FeatureCollection transformado a WGS84.
    """
    features = []
    try:
        # --- ¡AQUÍ ESTÁ LA CORRECCIÓN! ---
        # Ya no usamos requests.get. Abrimos directamente la ruta local que nos han pasado.
        with fiona.open(local_gpkg_path, 'r') as source:
            source_crs = CRS(source.crs)
            target_crs = CRS("EPSG:4326")
            transformer = None
            if source_crs != target_crs:
                transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
            for feature in source:
                geom = shape(feature['geometry'])
                if transformer:
                    from shapely.ops import transform
                    geom = transform(transformer.transform, geom)
                feature_dict = {
                    "type": "Feature",
                    "properties": dict(feature['properties']),
                    "geometry": geom.__geo_interface__
                }
                features.append(feature_dict)
        return {"type": "FeatureCollection", "features": features}
    except Exception as e:
        print(f"Error crítico cargando GeoJSON desde la ruta local {local_gpkg_path}: {e}")
        return None

def get_raster_value_at_point(raster_path, point_utm):
    """
    Lee un valor de un ráster en un punto UTM (x, y) dado.
    El raster_path puede ser una ruta local O una URL.
    Devuelve None si el punto está fuera o es NoData.
    """
    try:
        with rasterio.open(raster_path) as src:
            if not isinstance(point_utm, (list, tuple)) or len(point_utm) != 2:
                raise ValueError("point_utm debe ser una tupla o lista de dos floats (x, y).")

            # Convierte las coordenadas del punto al CRS del ráster si es necesario
            # (Esta es una mejora de robustez, asumiendo que point_utm está en EPSG:25830)
            point_crs = CRS("EPSG:25830")
            raster_crs = CRS(src.crs)
            if point_crs != raster_crs:
                transformer = Transformer.from_crs(point_crs, raster_crs, always_xy=True)
                point_x, point_y = transformer.transform(point_utm[0], point_utm[1])
            else:
                point_x, point_y = point_utm

            row, col = src.index(point_x, point_y)
            
            if not (0 <= row < src.height and 0 <= col < src.width):
                return None

            value = src.read(1)[row, col]
            
            if src.nodata is not None and value == src.nodata:
                return None
            return value
    except Exception as e:
        # En un entorno de producción, es mejor usar logging en lugar de print
        # import logging
        # logging.error(f"Error leyendo el ráster {raster_path} en {point_utm}: {e}")
        return None

def get_vector_feature_at_point(vector_path, point_utm):
    """
    Encuentra el primer objeto vectorial en un punto UTM (x, y) dado.
    El vector_path puede ser una ruta local O una URL.
    Devuelve el objeto como un diccionario o None si no se encuentra.
    """
    point_shapely = Point(point_utm)
    try:
        with fiona.open(vector_path, 'r') as source:
            # Transforma el punto al CRS de la capa si es necesario
            source_crs = CRS(source.crs)
            point_crs = CRS("EPSG:25830")
            if source_crs != point_crs:
                transformer = Transformer.from_crs(point_crs, source_crs, always_xy=True)
                from shapely.ops import transform
                point_shapely = transform(transformer.transform, point_shapely)

            for feature in source:
                geom_shapely = shape(feature['geometry'])
                if geom_shapely.contains(point_shapely):
                    return feature
            return None
    except Exception as e:
        # import logging
        # logging.error(f"Error consultando la capa vectorial {vector_path} en {point_utm}: {e}")
        return None

