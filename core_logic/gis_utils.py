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
    "BASINS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/demarcaciones_hidrograficas.gpkg",
    "RIVERS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/red10km.gpkg",
    "ZONES": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/regiones.gpkg",
    "MDT": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/mdt.tif",
    "FLOWDIRS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/dir.tif",
    "I1ID": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/i1id.tif",
    "P0": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/p0.tif",
    "RAIN_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t2.tif",
    "RAIN_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t5.tif",
    "RAIN_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t10.tif",
    "RAIN_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t25.tif",
    "RAIN_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t100.tif",
    "RAIN_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t500.tif",
    "FLOW_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q2.tif",
    "FLOW_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q5.tif",
    "FLOW_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q10.tif",
    "FLOW_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q25.tif",
    "FLOW_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q100.tif",
    "FLOW_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q500.tif",
}

_temp_dir = tempfile.TemporaryDirectory()

@cache_resource(ttl=3600)
def get_local_path_from_url(url):
    """
    Toma una URL, descarga el archivo a un directorio temporal persistente
    y devuelve la RUTA LOCAL a ese archivo. Usa el cache de Streamlit
    para asegurar que cada archivo solo se descarga una vez por sesión.
    """
    try:
        filename = os.path.basename(url)
        local_path = os.path.join(_temp_dir.name, filename)

        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            print(f"DEBUG: Usando archivo cacheado '{filename}' de {os.path.getsize(local_path)} bytes.")
            return local_path

        print(f"DEBUG: Descargando archivo '{filename}' desde {url}...")
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        # --- ¡AQUÍ ESTÁ LA LÍNEA DE DEPURACIÓN CLAVE! ---
        file_size = os.path.getsize(local_path)
        print(f"DEBUG: Descarga completa. Tamaño final de '{filename}' en disco: {file_size} bytes.")

        # Si el archivo está vacío, es un error.
        if file_size == 0:
            print(f"ERROR: El archivo descargado '{filename}' está vacío (0 bytes).")
            return None

        return local_path
    except Exception as e:
        print(f"Error crítico durante la descarga o verificación del archivo {url}: {e}")
        return None

def get_layer_path(layer_key):
    return LAYER_MAPPING.get(layer_key)

def load_geojson_from_gpkg(local_gpkg_path):
    features = []
    try:
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

def get_raster_value_at_point(raster_path_url, point_utm):
    # --- ¡CORRECCIÓN APLICADA AQUÍ! ---
    local_raster_path = get_local_path_from_url(raster_path_url)
    if not local_raster_path: return None
    try:
        with rasterio.open(local_raster_path) as src:
            point_crs = CRS("EPSG:25830")
            raster_crs = CRS(src.crs)
            if point_crs != raster_crs:
                transformer = Transformer.from_crs(point_crs, raster_crs, always_xy=True)
                point_x, point_y = transformer.transform(point_utm[0], point_utm[1])
            else:
                point_x, point_y = point_utm
            row, col = src.index(point_x, point_y)
            if not (0 <= row < src.height and 0 <= col < src.width): return None
            value = src.read(1)[row, col]
            if src.nodata is not None and value == src.nodata: return None
            return value
    except Exception:
        return None

def get_vector_feature_at_point(vector_path_url, point_utm):
    # --- ¡CORRECCIÓN APLICADA AQUÍ! ---
    local_vector_path = get_local_path_from_url(vector_path_url)
    if not local_vector_path: return None
    point_shapely = Point(point_utm)
    try:
        with fiona.open(local_vector_path, 'r') as source:
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
    except Exception:
        return None
