import requests
import io
import tempfile
import os
# --- ¡¡¡ESTE IMPORT FALTABA Y ES LA CAUSA DEL ERROR!!! ---
import streamlit as st 
# --- ¡¡¡AHORA SÍ ESTÁ!!! ---
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
    "MDT": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/mdt_COG.tif",
    "FLOWDIRS": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/dir_COG.tif",
    "I1ID": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/i1id_COG.tif",
    "P0": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/p0_COG.tif",
    "RAIN_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t2_COG.tif",
    "RAIN_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t5_COG.tif",
    "RAIN_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t10_COG.tif",
    "RAIN_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t25_COG.tif",
    "RAIN_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t100_COG.tif",
    "RAIN_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/t500_COG.tif",
    "FLOW_2": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q2_COG.tif",
    "FLOW_5": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q5_COG.tif",
    "FLOW_10": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q10_COG.tif",
    "FLOW_25": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q25_COG.tif",
    "FLOW_100": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q100_COG.tif",
    "FLOW_500": "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/q500_COG.tif",
}

_temp_dir = tempfile.TemporaryDirectory()

@st.cache_resource(ttl=3600)
def get_local_path_from_url(url):
    """
    Toma una URL, descarga el archivo a un directorio temporal persistente
    y devuelve la RUTA LOCAL a ese archivo.
    """
    try:
        filename = os.path.basename(url)
        local_path = os.path.join(_temp_dir.name, filename)

        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return local_path

        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        if os.path.getsize(local_path) == 0:
            return None

        return local_path
    except Exception as e:
        print(f"Error crítico durante la descarga del archivo {url}: {e}")
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
    # Esta función SÍ debe usar la lectura directa de URL para COGs grandes
    if raster_path_url.endswith(('_COG.tif', '_cog.tif', '.tif')) and raster_path_url.startswith('http'):
        path_to_open = f"/vsicurl/{raster_path_url}" # Usamos /vsicurl/ para lectura directa
    else:
        path_to_open = get_local_path_from_url(raster_path_url) # Para otros tipos (gpkg)
    
    if not path_to_open: return None
    try:
        with rasterio.open(path_to_open) as src:
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
    except Exception as e:
        print(f"ERROR: Fallo al obtener valor de raster en {raster_path_url} para punto {point_utm}: {e}")
        return None

def get_vector_feature_at_point(vector_path_url, point_utm):
    # Para vectores (gpkg) siempre descargamos
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
    except Exception as e:
        print(f"ERROR: Fallo al obtener feature vectorial en {vector_path_url} para punto {point_utm}: {e}")
        return None
    
    
# --- INICIO: NUEVA FUNCIÓN DE DESCARGA FORZADA ---
# Usamos un decorador de caché diferente para esta función para evitar conflictos
@cache_resource(ttl=3600)
def force_download_to_local_path(url):
    """
    Toma una URL, SIEMPRE descarga el archivo a un directorio temporal
    y devuelve la RUTA LOCAL. Esta función es para las librerías
    antiguas que no pueden leer URLs directamente.
    """
    try:
        filename = os.path.basename(url)
        local_path = os.path.join(_temp_dir.name, filename)

        # Si el archivo ya existe, lo usamos.
        if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
            return local_path

        # Si no, lo descargamos.
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(local_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        if os.path.getsize(local_path) == 0:
            return None

        return local_path
    except Exception as e:
        print(f"Error crítico durante la descarga forzada del archivo {url}: {e}")
        return None
# --- FIN: NUEVA FUNCIÓN ---
