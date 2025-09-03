# dem25_tab.py

import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import os
import rasterio
from rasterio.mask import mask
import numpy as np
import io
import matplotlib.pyplot as plt
import pandas as pd
import json
import zipfile
import tempfile
from folium.plugins import Draw
from shapely.geometry import shape, Point, LineString
from pyproj import CRS, Transformer

# LA LIBRERÍA ORIGINAL, USADA DE LA FORMA CORRECTA Y COMPATIBLE
from pysheds.grid import Grid
# Importa estas librerías al principio de tu script
import pyflwdir
from pyflwdir import from_dem
import rasterio.features

import base64
from PIL import Image
import locale # Asegúrate de que esta línea está al principio del archivo
import platform # Y también esta


import sys # Asegúrate de que 'import sys' está al principio de tu script

# --- 1. CONFIGURACIÓN Y CONSTANTES ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HOJAS_MTN25_PATH = os.path.join(PROJECT_ROOT, "CNIG", "MTN25_ACTUAL_ETRS89_Peninsula_Baleares_Canarias.shp")
DEM_NACIONAL_PATH = os.path.join(PROJECT_ROOT, "MDT25_peninsula_UTM30N.tif")
BUFFER_METROS = 5000
LIMITE_AREA_KM2 = 15000


# Pega esta sección al principio de tu script, después de los imports.
# ---------------------------------------------------------------------

import subprocess
import tempfile
import base64
from pyproj import CRS, Transformer # Asegúrate de que pyproj está importado
import folium
from streamlit_folium import st_folium
import branca.colormap as cm


# --- INICIO: FUNCIÓN DE ORQUESTACIÓN MODIFICADA ---

# def ejecutar_calculo_externo(dem_bytes, outlet_coords_wgs84, umbral): # <-- 1. AÑADIDO 'umbral'
#     """
#     Ejecuta el script 'delinear_cuenca.py' en su propio entorno virtual
#     y captura los resultados.
#     """
#     # --- 1. Configuración de Rutas ---
#     python_executable_externo = os.path.join("Py2Env", "venv_pysheds", "Scripts", "python.exe")
#     script_path = os.path.join("Py2Env", "delinear_cuenca.py")
#     #script_path = os.path.join("scripts", "delinear_cuenca.py") # (línea nueva)
#     if not os.path.exists(python_executable_externo):
#         st.error(f"Error Crítico: No se encuentra el ejecutable de Python en '{python_executable_externo}'. Verifica la ruta.")
#         return None
#     if not os.path.exists(script_path):
#         st.error(f"Error Crítico: No se encuentra el script en '{script_path}'. Verifica la ruta.")
#         return None
# 
#     # --- 2. Transformación de Coordenadas ---
#     try:
#         transformer_wgs84_to_utm30n = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
#         x_utm, y_utm = transformer_wgs84_to_utm30n.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
#         outlet_coords_utm = {"x": x_utm, "y": y_utm}
#     except Exception as e:
#         st.error(f"Error al transformar coordenadas: {e}")
#         return None
# 
#     # --- 3. Ejecución del Subproceso ---
#     with tempfile.TemporaryDirectory() as tmpdir:
#         dem_input_path = os.path.join(tmpdir, "input_dem.tif")
#         with open(dem_input_path, 'wb') as f:
#             f.write(dem_bytes)
# 
#         comando = [
#             python_executable_externo,
#             script_path,
#             dem_input_path,
#             json.dumps(outlet_coords_utm),
#             str(umbral) # <-- 2. AÑADIDO el valor del umbral al comando
#         ]
# 
#         try:
#             with st.spinner("Ejecutando análisis hidrológico completo... Esto puede tardar varios segundos."):
#                 resultado = subprocess.run(
#                     comando, 
#                     capture_output=True, 
#                     text=True, 
#                     check=True,
#                     encoding='utf-8'
#                 )
#             return json.loads(resultado.stdout)
#         except subprocess.CalledProcessError as e:
#             st.error("Falló la ejecución del script externo. Detalles del error:")
#             st.code(e.stderr, language='bash')
#             return None
#         except json.JSONDecodeError:
#             st.error("El script externo no devolvió un JSON válido. Salida del script:")
#             st.code(resultado.stdout, language='bash')
#             return None
#         except Exception as e:
#             st.error(f"Ocurrió un error inesperado al llamar al subproceso: {e}")
#             return None


def ejecutar_calculo_externo(dem_bytes, outlet_coords_wgs84, umbral):
    """
    Ejecuta el script 'delinear_cuenca.py' en su propio entorno virtual
    de forma adaptable para Windows y Linux para producción web :: deploy
    """
    # --- 1. Detección del Sistema Operativo y Configuración de Rutas ---
    
    # Determinar el nombre de la carpeta del ejecutable ('Scripts' o 'bin')
    if sys.platform == "win32":
        # Estamos en Windows
        bin_folder = "Scripts"
        python_exe = "python.exe"
    else:
        # Asumimos Linux o macOS
        bin_folder = "bin"
        python_exe = "python"

    # Construir las rutas de forma dinámica
    base_path = "Py2Env"
    venv_path = os.path.join(base_path, "venv_pysheds")
    python_executable_externo = os.path.join(venv_path, bin_folder, python_exe)
    script_path = os.path.join(base_path, "delinear_cuenca.py")

    # Verificación de existencia de las rutas
    if not os.path.exists(python_executable_externo):
        st.error(f"Error Crítico: No se encuentra el ejecutable de Python en la ruta esperada: '{python_executable_externo}'.")
        return None
    if not os.path.exists(script_path):
        st.error(f"Error Crítico: No se encuentra el script en la ruta: '{script_path}'.")
        return None

    # --- 2. Transformación de Coordenadas (sin cambios) ---
    try:
        transformer_wgs84_to_utm30n = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
        x_utm, y_utm = transformer_wgs84_to_utm30n.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
        outlet_coords_utm = {"x": x_utm, "y": y_utm}
    except Exception as e:
        st.error(f"Error al transformar coordenadas: {e}")
        return None

    # --- 3. Ejecución del Subproceso (sin cambios) ---
    with tempfile.TemporaryDirectory() as tmpdir:
        dem_input_path = os.path.join(tmpdir, "input_dem.tif")
        with open(dem_input_path, 'wb') as f:
            f.write(dem_bytes)

        comando = [
            python_executable_externo,
            script_path,
            dem_input_path,
            json.dumps(outlet_coords_utm),
            str(umbral)
        ]

        try:
            with st.spinner("Ejecutando análisis hidrológico completo..."):
                resultado = subprocess.run(
                    comando, capture_output=True, text=True, check=True, encoding='utf-8'
                )
            return json.loads(resultado.stdout)
        except subprocess.CalledProcessError as e:
            st.error("Falló la ejecución del script externo. Detalles del error:")
            st.code(e.stderr, language='bash')
            return None
        except Exception as e:
            st.error(f"Ocurrió un error inesperado al llamar al subproceso: {e}")
            return None



# --- FIN: FUNCIÓN DE ORQUESTACIÓN MODIFICADA ---

# import subprocess
# import tempfile
# import base64
# from pyproj import CRS, Transformer # Asegúrate de que pyproj está importado
# 
# # --- INICIO: FUNCIÓN DE ORQUESTACIÓN MODIFICADA ---
# 
# def ejecutar_calculo_externo(dem_bytes, outlet_coords_wgs84, umbral): # <-- 1. AÑADIDO 'umbral'
#     """
#     Ejecuta el script 'delinear_cuenca.py' en su propio entorno virtual
#     y captura los resultados.
#     """
#     # --- 1. Configuración de Rutas ---
#     python_executable_externo = os.path.join("Py2Env", "venv_pysheds", "Scripts", "python.exe")
#     script_path = os.path.join("Py2Env", "delinear_cuenca.py")
# 
#     if not os.path.exists(python_executable_externo):
#         st.error(f"Error Crítico: No se encuentra el ejecutable de Python en '{python_executable_externo}'. Verifica la ruta.")
#         return None
#     if not os.path.exists(script_path):
#         st.error(f"Error Crítico: No se encuentra el script en '{script_path}'. Verifica la ruta.")
#         return None
# 
#     # --- 2. Transformación de Coordenadas ---
#     try:
#         transformer_wgs84_to_utm30n = Transformer.from_crs("EPSG:4326", "EPSG:25830", always_xy=True)
#         x_utm, y_utm = transformer_wgs84_to_utm30n.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
#         outlet_coords_utm = {"x": x_utm, "y": y_utm}
#     except Exception as e:
#         st.error(f"Error al transformar coordenadas: {e}")
#         return None
# 
#     # --- 3. Ejecución del Subproceso ---
#     with tempfile.TemporaryDirectory() as tmpdir:
#         dem_input_path = os.path.join(tmpdir, "input_dem.tif")
#         with open(dem_input_path, 'wb') as f:
#             f.write(dem_bytes)
# 
#         comando = [
#             python_executable_externo,
#             script_path,
#             dem_input_path,
#             json.dumps(outlet_coords_utm),
#             str(umbral) # <-- 2. AÑADIDO el valor del umbral al comando
#         ]
# 
#         try:
#             with st.spinner("Ejecutando análisis hidrológico completo... Esto puede tardar varios segundos."):
#                 resultado = subprocess.run(
#                     comando, 
#                     capture_output=True, 
#                     text=True, 
#                     check=True,
#                     encoding='utf-8'
#                 )
#             return json.loads(resultado.stdout)
#         except subprocess.CalledProcessError as e:
#             st.error("Falló la ejecución del script externo. Detalles del error:")
#             st.code(e.stderr, language='bash')
#             return None
#         except json.JSONDecodeError:
#             st.error("El script externo no devolvió un JSON válido. Salida del script:")
#             st.code(resultado.stdout, language='bash')
#             return None
#         except Exception as e:
#             st.error(f"Ocurrió un error inesperado al llamar al subproceso: {e}")
#             return None
# 
# # --- FIN: FUNCIÓN DE ORQUESTACIÓN MODIFICADA ---


# --- 2. FUNCIONES DE LÓGICA (BACKEND) ---

def encontrar_hojas(geometry_gdf):
    hojas_gdf = gpd.read_file(HOJAS_MTN25_PATH)
    geom_para_interseccion = geometry_gdf.to_crs(hojas_gdf.crs)
    return gpd.sjoin(hojas_gdf, geom_para_interseccion, how="inner", predicate="intersects").drop_duplicates(subset=['numero'])

def generar_dem(geometry_gdf):
    with rasterio.open(DEM_NACIONAL_PATH) as src:
        geom_recorte_gdf = geometry_gdf.to_crs(src.crs)
        try:
            dem_recortado, trans_recortado = mask(dataset=src, shapes=geom_recorte_gdf.geometry, crop=True, nodata=src.nodata or -32768)
            meta = src.meta.copy(); meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado})
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst: dst.write(dem_recortado)
                buffer.seek(0)
                return buffer.read(), dem_recortado
        except ValueError: return None, None

def export_gdf_to_zip(gdf, filename_base):
    with tempfile.TemporaryDirectory() as tmpdir:
        if gdf.crs is None:
            gdf.set_crs("EPSG:4326", inplace=True)
        gdf.to_file(os.path.join(tmpdir, f"{filename_base}.shp"), driver='ESRI Shapefile', encoding='utf-8')
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    if file.startswith(filename_base): zf.write(os.path.join(root, file), arcname=file)
        zip_io.seek(0)
        return zip_io

# --- 3. CAJAS NEGRAS DE PROCESAMIENTO ---

@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
    buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs("EPSG:25830").buffer(BUFFER_METROS), crs="EPSG:25830")
    hojas = encontrar_hojas(buffer_gdf); dem_bytes, dem_array = generar_dem(buffer_gdf)
    if dem_bytes is None: return None
    shp_zip_bytes = export_gdf_to_zip(buffer_gdf, "contorno_cuenca_buffer")
    return { "cuenca_gdf": cuenca_gdf, "buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "hojas": hojas, "dem_bytes": dem_bytes, "dem_array": dem_array, "shp_zip_bytes": shp_zip_bytes }

@st.cache_data(show_spinner="Procesando el polígono dibujado...")
def procesar_datos_poligono(polygon_geojson_str):
    poly_gdf = gpd.read_file(polygon_geojson_str).set_crs("EPSG:4326")
    area_km2 = poly_gdf.to_crs("EPSG:25830").area.iloc[0] / 1_000_000
    if area_km2 > LIMITE_AREA_KM2: return {"error": f"El área ({area_km2:,.0f} km²) supera los límites de {LIMITE_AREA_KM2:,.0f} km²."}
    hojas = encontrar_hojas(poly_gdf)
    dem_bytes, dem_array = generar_dem(poly_gdf)
    if dem_bytes is None: return None
    shp_zip_bytes = export_gdf_to_zip(poly_gdf, "contorno_poligono_manual")
    return { "poligono_gdf": poly_gdf, "hojas": hojas, "dem_bytes": dem_bytes, "dem_array": dem_array, "shp_zip_bytes": shp_zip_bytes, "area_km2": area_km2 }

# --- MOTOR HIDROLÓGICO BASADO EN EL FLUJO DEL VÍDEO ---

# @st.cache_data(show_spinner="Pre-calculando referencia de cauces...")
# def precalcular_acumulacion(_dem_bytes):
#     tmp_path = None
#     try:
#         with tempfile.NamedTemporaryFile(suffix='.tif', delete=False) as tmp:
#             tmp_path = tmp.name
#             tmp.write(_dem_bytes)
#         
#         grid = Grid.from_raster(tmp_path)
#         dem = grid.read_raster(tmp_path).astype(np.float32)
#         
#         filled_dem = grid.fill_depressions(dem)
#         flats_resolved = grid.resolve_flats(filled_dem)
#         fdir = grid.flowdir(flats_resolved)
#         acc = grid.accumulation(fdir)
#         
#         acc_np = np.asarray(acc)
#         log_acc = np.log1p(acc_np)
#         min_val, max_val = log_acc.min(), log_acc.max()
#         if max_val == min_val:
#             img_acc = np.zeros_like(log_acc, dtype=np.uint8)
#         else:
#             img_acc = (255 * (log_acc - min_val) / (max_val - min_val)).astype(np.uint8)
#         return img_acc
#     except Exception as e:
#         st.error(f"Error en el pre-cálculo: {e}")
#         return None
#     finally:
#         if tmp_path and os.path.exists(tmp_path):
#             os.remove(tmp_path)
@st.cache_data(show_spinner="Pre-calculando referencia de cauces (pyflwdir)...")
def precalcular_acumulacion(_dem_bytes):
    """
    Calcula la acumulación de flujo usando pyflwdir y la prepara para visualización.
    """
    try:
        # 1. Abrir el DEM en memoria
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_array = src.read(1).astype(np.float32)
                nodata = src.meta.get('nodata')
                if nodata is not None:
                    dem_array[dem_array == nodata] = np.nan
                transform = src.transform

        # 2. Calcular las direcciones de flujo y la acumulación con pyflwdir
        flwdir = pyflwdir.from_dem(data=dem_array, transform=transform, nodata=np.nan)
        acc = flwdir.upstream_area(unit='cell')

        # 3. Procesar el array de acumulación para una mejor visualización
        # Se usa una transformación logarítmica para resaltar los cauces principales
        # log_acc = np.log1p(acc)
        # --- INICIO DE LA SOLUCIÓN DEFINITIVA ---
        # La documentación confirma que 'acc' puede contener np.nan.
        # Los reemplazamos por 0 ANTES de cualquier cálculo matemático.
        acc_limpio = np.nan_to_num(acc, nan=0.0)

        # Por seguridad, también nos aseguramos de que no haya negativos.
        acc_limpio = np.where(acc_limpio < 0, 0, acc_limpio)
        
        # Ahora, calculamos el logaritmo sobre el array limpio y seguro.
        log_acc = np.log1p(acc_limpio)
        # --- FIN DE LA SOLUCIÓN DEFINITIVA ---

        min_val, max_val = np.nanmin(log_acc), np.nanmax(log_acc)
        
        if max_val == min_val:
            # Evitar división por cero si el ráster es plano
            img_acc = np.zeros_like(log_acc, dtype=np.uint8)
        else:
            # Normalizar los valores a un rango de 0-255 para crear una imagen en escala de grises
            log_acc_nan_as_zero = np.nan_to_num(log_acc, nan=min_val)
            img_acc = (255 * (log_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        
        return img_acc

    except Exception as e:
        st.error(f"Error en el pre-cálculo con pyflwdir: {e}")
        import traceback
        st.code(traceback.format_exc()) # Muestra más detalles del error
        return None


# ==============================================================================
# BLOQUE 1: FUNCIÓN DE CÁLCULO HIDROLÓGICO ANULADA
# Se comenta toda la función porque ya no será llamada desde ninguna parte.
# ==============================================================================
# @st.cache_data(show_spinner="Calculando cuenca y red fluvial (pyflwdir)...")
# def calcular_cuenca_y_rios_pysheds(_dem_bytes, outlet_coords, umbral_celdas):
#     try:
#         # --- PASO 1: CARGAR EL DEM ---
#         with rasterio.io.MemoryFile(_dem_bytes) as memfile:
#             with memfile.open() as src:
#                 meta = src.meta.copy()
#                 dem_array = src.read(1).astype(np.float32)
#                 nodata = meta.get('nodata')
#                 if nodata is not None:
#                     dem_array[dem_array == nodata] = np.nan
#                 transform = src.transform
#                 crs = src.crs

#         # --- PASO 2: CALCULAR DIRECCIONES DE FLUJO ---
#         flwdir = pyflwdir.from_dem(data=dem_array, transform=transform, nodata=np.nan)

#         # --- PASO 3: CALCULAR ACUMULACIÓN ---
#         acc = flwdir.upstream_area(unit='cell')

#         # --- PASO 4: OBTENER ÍNDICE DEL OUTLET (LÓGICA DE COORDENADAS CORREGIDA) ---
#         source_crs = CRS.from_epsg(4326) 
#         target_crs = CRS.from_epsg(crs.to_epsg())
#         transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
#         x_utm, y_utm = transformer.transform(outlet_coords['lng'], outlet_coords['lat'])
#         row, col = rasterio.transform.rowcol(transform, x_utm, y_utm)
        
#         # --- PASO 5: DELINEAR CUENCA ---
#         basin_mask = flwdir.basins(
#             pits=[(row, col)], 
#             streams=acc > umbral_celdas,
#             snap_to_stream='dist',
#             snap_dist=2500 
#         )

#         if np.sum(basin_mask) == 0:
#             return {"error": "No se pudo delinear una cuenca. El punto seleccionado está demasiado lejos de un cauce. Pruebe en otro lugar."}

#         # --- PASO 6: EXTRAER RED FLUVIAL ---
#         stream_generator = flwdir.streams(acc > umbral_celdas)
#         all_linear_indices = []
#         for network in stream_generator:
#             if 'idx_stream' in network:
#                 all_linear_indices.append(network['idx_stream'])

#         if not all_linear_indices:
#             streams_mask_np = np.zeros(flwdir.shape, dtype=bool)
#         else:
#             linear_indices = np.concatenate(all_linear_indices).astype(np.intp)
#             row_cols = np.unravel_index(linear_indices, flwdir.shape)
#             streams_mask_np = np.zeros(flwdir.shape, dtype=bool)
#             streams_mask_np[row_cols] = True

#         # --- PASO 7: CONVERTIR A GEODATAFRAMES ---
#         shapes_cuenca = rasterio.features.shapes(basin_mask.astype(np.uint8), mask=(basin_mask > 0), transform=transform)
#         geoms_cuenca = [{'geometry': geom, 'properties': {}} for geom, val in shapes_cuenca if val == 1]
#         cuenca_gdf = gpd.GeoDataFrame.from_features(geoms_cuenca, crs=crs)

#         final_rios_mask = (streams_mask_np & basin_mask).astype(bool)
#         shapes_rios = rasterio.features.shapes(streams_mask_np.astype(np.uint8), mask=final_rios_mask, transform=transform)
#         geoms_rios = [{'geometry': geom, 'properties': {}} for geom, val in shapes_rios if val == 1]
        
#         if geoms_rios:
#             rios_gdf = gpd.GeoDataFrame.from_features(geoms_rios, crs=crs)
#         else:
#             rios_gdf = gpd.GeoDataFrame({'geometry': []}, crs=crs.to_wkt())
#             st.warning("No se encontraron cauces con el umbral seleccionado. Pruebe un valor más bajo.")
            
#         return {
#             "cuenca_gdf": cuenca_gdf.to_crs("EPSG:4326"),
#             "rios_gdf": rios_gdf.to_crs("EPSG:4326")
#         }

#     except Exception as e:
#         import traceback
#         st.error(f"Error en pyflwdir: {e}\n{traceback.format_exc()}")
#         return {"error": str(e)}


# --- 4. FUNCIÓN PRINCIPAL DEL FRONTEND ---

def render_dem25_tab():
    st.header("Generador de Modelos Digitales del Terreno (MDT25)"); st.subheader("(from NASA’s Earth Observing System Data and Information System -EOSDIS)")
    st.info("Esta herramienta identifica las hojas del MTN25 y genera un DEM recortado para la cuenca (con buffer de 5km) o para un área dibujada manualmente.")

    if 'basin_geojson' not in st.session_state: st.warning("⬅️ Por favor, primero calcule una cuenca en la Pestaña 1."); st.stop()

    # if st.button("🗺️ Analizar Hojas y DEM para la Cuenca Actual", use_container_width=True):
    #     results = procesar_datos_cuenca(st.session_state.basin_geojson)
    #     if results:
    #         st.session_state.cuenca_results = results; st.session_state.processed_basin_id = st.session_state.basin_geojson
    #         st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes'])
    #         st.session_state.pop('poligono_results', None); st.session_state.pop('user_drawn_geojson', None); st.session_state.pop('polygon_error_message', None)
    #         st.session_state.pop('hidro_results', None); st.session_state.pop('outlet_coords', None)
    #     else: st.error("No se pudo procesar la cuenca.")
    #     st.session_state.show_dem25_content = True; st.rerun()

    if st.button("🗺️ Analizar Hojas y DEM para la Cuenca Actual", use_container_width=True):
            results = procesar_datos_cuenca(st.session_state.basin_geojson)
            if results:
                st.session_state.cuenca_results = results
                st.session_state.processed_basin_id = st.session_state.basin_geojson
                st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes'])
                
                # Limpiamos los resultados de análisis anteriores, pero NADA MÁS
                st.session_state.pop('poligono_results', None)
                st.session_state.pop('user_drawn_geojson', None)
                st.session_state.pop('polygon_error_message', None)
                st.session_state.pop('hidro_results_externo', None) # Usamos la nueva clave de resultados
                # La línea que borraba 'outlet_coords' ha sido eliminada de aquí.
                
            else: 
                st.error("No se pudo procesar la cuenca.")
                
            st.session_state.show_dem25_content = True
            st.rerun()

    if not st.session_state.get('show_dem25_content'): st.stop()
    
    st.subheader("Mapa de Situación")
    m = folium.Map(tiles="CartoDB positron"); folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m)
    cuenca_results = st.session_state.cuenca_results
    folium.GeoJson(cuenca_results['cuenca_gdf'], name="Cuenca", style_function=lambda x: {'color': 'white', 'weight': 2.5}).add_to(m)
    buffer_layer = folium.GeoJson(cuenca_results['buffer_gdf'], name="Buffer Cuenca (5km)", style_function=lambda x: {'color': 'tomato', 'fillOpacity': 0.1}).add_to(m)
    folium.GeoJson(cuenca_results['hojas'], name="Hojas (Cuenca)", style_function=lambda x: {'color': '#ffc107', 'weight': 2, 'fillOpacity': 0.4}).add_to(m)
    m.fit_bounds(buffer_layer.get_bounds())
    if st.session_state.get('user_drawn_geojson'): folium.GeoJson(json.loads(st.session_state.user_drawn_geojson), name="Polígono Dibujado", style_function=lambda x: {'color': 'magenta', 'weight': 3, 'fillOpacity': 0.2, 'dashArray': '5, 5'}).add_to(m)
    if 'poligono_results' in st.session_state and "error" not in st.session_state.poligono_results: folium.GeoJson(st.session_state.poligono_results['hojas'], name="Hojas (Polígono)", style_function=lambda x: {'color': 'magenta', 'weight': 2.5, 'fillOpacity': 0.5}).add_to(m)
    if st.session_state.get("drawing_mode_active"): Draw(export=True, filename='data.geojson', position='topleft', draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False, 'polygon': {'shapeOptions': {'color': 'magenta', 'weight': 3, 'fillOpacity': 0.2}}}, edit_options={'edit': False}).add_to(m)
    folium.LayerControl().add_to(m)
    map_output = st_folium(m, use_container_width=True, height=800, returned_objects=['all_drawings'])
    if st.session_state.get("drawing_mode_active") and map_output.get("all_drawings"):
        st.session_state.user_drawn_geojson = json.dumps(map_output["all_drawings"][0]['geometry']); st.session_state.drawing_mode_active = False; st.rerun()

    with st.expander("📝 Herramientas de Dibujo para un área personalizada"):
        c1, c2, c3 = st.columns([2, 2, 3])
        if c1.button("Iniciar / Reiniciar Dibujo", use_container_width=True): 
            st.session_state.drawing_mode_active = True; st.session_state.pop('user_drawn_geojson', None); st.session_state.pop('poligono_results', None); st.session_state.pop('polygon_error_message', None); st.rerun()
        if c2.button("Cancelar Dibujo", use_container_width=True): st.session_state.drawing_mode_active = False; st.rerun()
        if st.session_state.get('user_drawn_geojson'):
            if c3.button("▶️ Analizar Polígono Dibujado", use_container_width=True):
                results = procesar_datos_poligono(st.session_state.user_drawn_geojson)
                if "error" in results: st.session_state.polygon_error_message = results["error"]; st.session_state.pop('poligono_results', None)
                else: st.session_state.poligono_results = results; st.session_state.pop('polygon_error_message', None)
                st.rerun()

    if st.session_state.get('polygon_error_message'):
        st.markdown(f"<p style='font-size: 20px; color: tomato; font-weight: bold;'>⚠️ {st.session_state.get('polygon_error_message')}</p>", unsafe_allow_html=True)

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Resultados (Cuenca + Buffer)")
        st.metric("Hojas intersectadas", len(cuenca_results['hojas']))
        df = pd.DataFrame({'Nombre Archivo (CNIG)': [f"MDT25-ETRS89-H{h['huso']}-{h['numero']}-COB2.tif" for _, h in cuenca_results['hojas'].sort_values(by=['huso', 'numero']).iterrows()]}); st.dataframe(df)
    with col2:
        st.subheader("DEM Compuesto (Cuenca)")
        fig, ax = plt.subplots(); dem_array = cuenca_results['dem_array'][0]
        nodata = dem_array.min(); plot_array = np.where(dem_array == nodata, np.nan, dem_array)
        im = ax.imshow(plot_array, cmap='terrain'); fig.colorbar(im, ax=ax, label='Elevación (m)'); ax.set_axis_off(); st.pyplot(fig)
        st.download_button("📥 **Descargar DEM de Cuenca (.tif)**", cuenca_results['dem_bytes'], "dem_cuenca_buffer.tif", "image/tiff", use_container_width=True)
        st.download_button("📥 **Descargar Contorno Buffer (.zip)**", cuenca_results['shp_zip_bytes'], "contorno_cuenca_buffer.zip", "application/zip", use_container_width=True)

    if 'poligono_results' in st.session_state and "error" not in st.session_state.poligono_results:
        st.divider()

        poly_results = st.session_state.poligono_results
        col_p1, col_p2 = st.columns(2)
        with col_p1:
            st.subheader("Resultados (Polígono Manual)")
            st.metric("Área del Polígono", f"{poly_results['area_km2']:,.2f} km²")
            st.metric("Hojas intersectadas", len(poly_results['hojas']))
            df_poly = pd.DataFrame({'Nombre Archivo (CNIG)': [f"MDT25-ETRS89-H{h['huso']}-{h['numero']}-COB2.tif" for _, h in poly_results['hojas'].sort_values(by=['huso', 'numero']).iterrows()]}); st.dataframe(df_poly)
        with col_p2:
            st.subheader("DEM Compuesto (Polígono)")
            fig, ax = plt.subplots(); dem_array = poly_results['dem_array']
            nodata = dem_array[0].min(); plot_array = np.where(dem_array[0] == nodata, np.nan, dem_array[0])
            im = ax.imshow(plot_array, cmap='terrain'); fig.colorbar(im, ax=ax, label='Elevación (m)'); ax.set_axis_off(); st.pyplot(fig)
            st.download_button("📥 **Descargar DEM de Polígono (.tif)**", poly_results['dem_bytes'], "dem_poligono_manual.tif", "image/tiff", use_container_width=True)
            st.download_button("📥 **Descargar Contorno Polígono (.zip)**", poly_results['shp_zip_bytes'], "contorno_poligono_manual.zip", "application/zip", use_container_width=True)
    
    st.divider(); st.header("Análisis Hidrológico (Cuenca y Red Fluvial)")
    
    st.subheader("Paso 1: Seleccione un punto de salida (outlet) en el mapa")
    # st.info("Haga clic en el mapa para definir el punto de desagüe. Puede usar la capa de referencia (semitransparente) para localizar los cauces principales.\nSe recomienda hacer zoom hasta nivel de pixel para garantizar la precisión del punto en el cauce. Evite confluencias o puntos cercanos con cauces que no pertenecen a su red.")
    st.info("""
    Haga clic en el mapa para definir el punto de desagüe. Puede usar la capa de referencia (semitransparente) para localizar los cauces principales.
    
    Se recomienda hacer zoom hasta nivel de pixel para garantizar la precisión del punto en el cauce. Evite confluencias o puntos cercanos con cauces que no pertenecen a su red.
    """)
    map_select = folium.Map(tiles="CartoDB positron", zoom_start=10)
    folium.TileLayer('OpenStreetMap').add_to(map_select)
    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(map_select)

    buffer_gdf = st.session_state.cuenca_results['buffer_gdf']
    buffer_layer_select = folium.GeoJson(buffer_gdf, name="Área de Análisis")
    buffer_layer_select.add_to(map_select)
    map_select.fit_bounds(buffer_layer_select.get_bounds())
    


    if st.session_state.get('basin_geojson'):
        folium.GeoJson(json.loads(st.session_state.basin_geojson), name="Cuenca (Pestaña 1)", style_function=lambda x: {'color': 'darkorange', 'weight': 2.5, 'fillOpacity': 0.1, 'dashArray': '5, 5'}).add_to(map_select)
    if st.session_state.get('lat_wgs84') and st.session_state.get('lon_wgs84'):
        folium.Marker([st.session_state.lat_wgs84, st.session_state.lon_wgs84], popup="Punto de Interés (Pestaña 1)", icon=folium.Icon(color="red", icon="info-sign")).add_to(map_select)

    # if 'precalculated_acc' in st.session_state and st.session_state.precalculated_acc is not None:
    #     acc_raster = st.session_state.precalculated_acc; bounds = buffer_gdf.total_bounds
    #     folium.raster_layers.ImageOverlay(image=acc_raster, bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, name='Referencia de Cauces (Acumulación)').add_to(map_select)

    if 'precalculated_acc' in st.session_state and st.session_state.precalculated_acc is not None:
        acc_raster = st.session_state.precalculated_acc
        bounds = buffer_gdf.total_bounds
    
        # --- INICIO DEL NUEVO BLOQUE DE CÓDIGO ROBUSTO ---
    
        # 1. Convertir el array de NumPy a una imagen PIL
        img = Image.fromarray(acc_raster)
    
        # 2. Guardar la imagen en un buffer en memoria en formato PNG
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
    
        # 3. Codificar la imagen en Base64
        img_str = base64.b64encode(buffered.getvalue()).decode()
    
        # 4. Crear la URL de datos para la imagen
        img_url = f"data:image/png;base64,{img_str}"
    
        # --- FIN DEL NUEVO BLOQUE ---
    
        # Añadir la imagen al mapa usando la URL de datos
        folium.raster_layers.ImageOverlay(
            image=img_url, # Usamos la URL en lugar del array
            bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]],
            opacity=0.6,
            name='Referencia de Cauces (Acumulación)'
        ).add_to(map_select)


    if 'outlet_coords' in st.session_state:
        coords = st.session_state.outlet_coords
        folium.Marker([coords['lat'], coords['lng']], popup="Punto de Salida Seleccionado", icon=folium.Icon(color='orange')).add_to(map_select)
    
    folium.LayerControl().add_to(map_select)
    map_output_select = st_folium(map_select, key="map_select", use_container_width=True, height=800, returned_objects=['last_clicked'])




    if map_output_select.get("last_clicked"):
        if st.session_state.get('outlet_coords') != map_output_select["last_clicked"]:
            st.session_state.outlet_coords = map_output_select["last_clicked"]
            st.rerun()



# # Reemplaza la sección "Paso 2" dentro de tu función render_dem25_tab()
# # con el siguiente bloque de código.
# # ---------------------------------------------------------------------------
# 
#     st.subheader("Paso 2: Calcule el análisis")
#     # Activamos el slider
#     umbral_celdas = st.slider("Definición de cauce (umbral de celdas)", 0, 10000, 5000, 100, disabled=False)
# 
#     if st.button("Calcular Cuenca y Red Fluvial", use_container_width=True, disabled='outlet_coords' not in st.session_state):
#         if 'hidro_results_externo' in st.session_state:
#             del st.session_state['hidro_results_externo']
# 
#         # Llamar a la función orquestadora pasando el valor del slider
#         results = ejecutar_calculo_externo(
#             st.session_state.cuenca_results['dem_bytes'],
#             st.session_state.outlet_coords,
#             umbral_celdas # <-- 3. AÑADIDO el valor del slider aquí
#         )
#         
#         if results and results.get("success"):
#             st.session_state.hidro_results_externo = results
#             st.success(results.get("message", "Cálculo completado."))
#         elif results:
#             st.error(f"El script externo reportó un error:")
#             st.code(results.get("message", "Error desconocido."), language='bash')        
#         # No es necesario un rerun(), Streamlit actualizará la UI al final del script.
# 
# 
#     # --- NUEVA SECCIÓN DE VISUALIZACIÓN DE RESULTADOS ---
#     if 'hidro_results_externo' in st.session_state:
#         results = st.session_state.hidro_results_externo
#         
#         st.divider()
#         st.header("Resultados del Análisis Externo")
# 
#         # --- Visualización de Gráficos ---
#         st.subheader("Gráficos Generados")
#         
#         if "grafico_1_mosaico" in results["plots"]:
#             st.image(
#                 io.BytesIO(base64.b64decode(results["plots"]["grafico_1_mosaico"])),
#                 caption="Características de la Cuenca",
#                 use_container_width=True
#             )
#         
#         if "grafico_4_perfil_lfp" in results["plots"]:
#             st.image(
#                 io.BytesIO(base64.b64decode(results["plots"]["grafico_4_perfil_lfp"])),
#                 caption="Perfil Longitudinal del LFP",
#                 use_container_width=True
#             )
#         
#         # --- Botones de Descarga ---
#         st.subheader("Descargas GIS y Datos")
#         
#         col1, col2, col3, col4 = st.columns(4)
# 
#         with col1:
#             if "cuenca" in results["downloads"]:
#                 gdf = gpd.read_file(results["downloads"]["cuenca"])
#                 zip_io = export_gdf_to_zip(gdf, "cuenca_delineada")
#                 st.download_button("📥 Cuenca (.zip)", zip_io, "cuenca_delineada.zip", "application/zip", use_container_width=True)
# 
#         with col2:
#             if "rios" in results["downloads"]:
#                 gdf = gpd.read_file(results["downloads"]["rios"])
#                 zip_io = export_gdf_to_zip(gdf, "red_fluvial")
#                 st.download_button("📥 Red Fluvial (.zip)", zip_io, "red_fluvial.zip", "application/zip", use_container_width=True)
#         
#         with col3:
#             if "lfp" in results["downloads"]:
#                 gdf = gpd.read_file(results["downloads"]["lfp"])
#                 zip_io = export_gdf_to_zip(gdf, "lfp")
#                 st.download_button("📥 LFP (.zip)", zip_io, "lfp.zip", "application/zip", use_container_width=True)
# 
#         with col4:
#             if "punto_salida" in results["downloads"]:
#                 gdf = gpd.read_file(results["downloads"]["punto_salida"])
#                 zip_io = export_gdf_to_zip(gdf, "punto_salida")
#                 st.download_button("📥 Punto Salida (.zip)", zip_io, "punto_salida.zip", "application/zip", use_container_width=True)
# 
#         # Descarga del perfil LFP en CSV
#         if results.get("lfp_profile_data"):
#             df_perfil = pd.DataFrame(results["lfp_profile_data"])
#             csv_perfil = df_perfil.to_csv(index=False, sep=';').encode('utf-8')
#             st.download_button(
#                 "📥 Descargar Perfil LFP (.csv)",
#                 csv_perfil,
#                 "perfil_lfp.csv",
#                 "text/csv",
#                 use_container_width=True
#             )


# Reemplaza la sección "Paso 2" dentro de tu función render_dem25_tab()
# con el siguiente bloque de código.
# ---------------------------------------------------------------------------

    # st.subheader("Paso 2: Calcule el análisis")
    # # Activamos el slider
    # umbral_celdas = st.slider("Definición de cauce (umbral de celdas)", 10, 10000, 5000, 100, disabled=False)

    st.subheader("Paso 2: Cálculos GIS y Análisis de precisión")
    
    # --- INICIO: SLIDER CON CÁLCULO DE ÁREA ---
    
    # Constante para la conversión de celdas a km² (1 celda = 25m * 25m)
    CELL_AREA_KM2 = 0.000625

    # Límites para el slider
    min_celdas = 10
    max_celdas = 10000
    default_celdas = 5000
    step_celdas = 10

    # Crear la etiqueta principal que incluye los límites en km²
    slider_label = f"Umbral de celdas (Mín: {min_celdas*CELL_AREA_KM2:.4f} km² - Máx: {max_celdas*CELL_AREA_KM2:.2f} km²)"

    # Crear el slider con la nueva etiqueta
    umbral_celdas = st.slider(
        label=slider_label,
        min_value=min_celdas,
        max_value=max_celdas,
        value=default_celdas,
        step=step_celdas
    )

    # Mostrar el valor seleccionado en celdas y su equivalencia en km² justo debajo
    area_seleccionada_km2 = umbral_celdas * CELL_AREA_KM2
    st.info(f"**Valor seleccionado:** {umbral_celdas} celdas  ➡️  **Área de drenaje mínima:** {area_seleccionada_km2:.4f} km²")
    
    # --- FIN: SLIDER CON CÁLCULO DE ÁREA ---



    if st.button("Calcular Cuenca y Red Fluvial", use_container_width=True, disabled='outlet_coords' not in st.session_state):
        if 'hidro_results_externo' in st.session_state:
            del st.session_state['hidro_results_externo']

        # Llamar a la función orquestadora pasando el valor del slider
        results = ejecutar_calculo_externo(
            st.session_state.cuenca_results['dem_bytes'],
            st.session_state.outlet_coords,
            umbral_celdas # <-- 3. AÑADIDO el valor del slider aquí
        )
        
        if results and results.get("success"):
            st.session_state.hidro_results_externo = results
            st.success(results.get("message", "Cálculo completado."))
        elif results:
            st.error(f"El script externo reportó un error:")
            st.code(results.get("message", "Error desconocido."), language='bash')
        
    # # --- NUEVA SECCIÓN DE VISUALIZACIÓN DE RESULTADOS ---
    # if 'hidro_results_externo' in st.session_state:
    #     results = st.session_state.hidro_results_externo
    #     
    #     st.divider()
    #     st.header("Resultados del Análisis Externo")
    # 
    #     # --- INICIO: NUEVO MAPA DE RESULTADOS ---
    #     st.subheader("Mapa de Resultados GIS")
    #     
    #     try:
    #         # Cargar los GeoDataFrames desde el JSON de resultados
    #         gdf_cuenca = gpd.read_file(results["downloads"]["cuenca"])
    #         gdf_lfp = gpd.read_file(results["downloads"]["lfp"])
    #         gdf_punto = gpd.read_file(results["downloads"]["punto_salida"])
    #         
    #         # Reproyectar todo a WGS84 para Folium
    #         gdf_cuenca_wgs84 = gdf_cuenca.to_crs("EPSG:4326")
    #         gdf_lfp_wgs84 = gdf_lfp.to_crs("EPSG:4326")
    #         gdf_punto_wgs84 = gdf_punto.to_crs("EPSG:4326")
    # 
    #         # Crear el mapa base
    #         m = folium.Map(tiles="CartoDB positron")
    #         folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m)
    # 
    #         # Añadir capa de la cuenca (rojo semitransparente)
    #         folium.GeoJson(
    #             gdf_cuenca_wgs84,
    #             name="Cuenca Delineada",
    #             style_function=lambda x: {'color': '#FF0000', 'weight': 2.5, 'fillColor': '#FF0000', 'fillOpacity': 0.2}
    #         ).add_to(m)
    # 
    #         # Añadir capa del LFP (amarillo intenso)
    #         folium.GeoJson(
    #             gdf_lfp_wgs84,
    #             name="Longest Flow Path (LFP)",
    #             style_function=lambda x: {'color': '#FFFF00', 'weight': 4, 'opacity': 0.9}
    #         ).add_to(m)
    # 
    #         # Añadir capa de ríos Strahler (azules por orden)
    #         if "rios_strahler" in results["downloads"]:
    #             gdf_rios_strahler = gpd.read_file(results["downloads"]["rios_strahler"]).to_crs("EPSG:4326")
    #             
    #             # Crear una paleta de colores para los órdenes de Strahler
    #             min_order = gdf_rios_strahler['strord'].min()
    #             max_order = gdf_rios_strahler['strord'].max()
    #             colormap = cm.LinearColormap(colors=['lightblue', 'blue', 'darkblue'], vmin=min_order, vmax=max_order)
    #             
    #             folium.GeoJson(
    #                 gdf_rios_strahler,
    #                 name="Red Fluvial (Strahler)",
    #                 style_function=lambda feature: {
    #                     'color': colormap(feature['properties']['strord']),
    #                     'weight': feature['properties']['strord'] / 2 + 1, # Hacer los ríos de mayor orden más gruesos
    #                     'opacity': 0.8,
    #                 }
    #             ).add_to(m)
    #             m.add_child(colormap) # Añadir la leyenda de color al mapa
    # 
    #         # Añadir punto de desagüe (verde claro)
    #         lat, lon = gdf_punto_wgs84.geometry.iloc[0].y, gdf_punto_wgs84.geometry.iloc[0].x
    #         folium.Marker(
    #             [lat, lon],
    #             popup="Punto de Desagüe",
    #             icon=folium.Icon(color='green', icon='tint', prefix='fa')
    #         ).add_to(m)
    # 
    #         # Ajustar el zoom y añadir control de capas
    #         m.fit_bounds(gdf_cuenca_wgs84.total_bounds[[1, 0, 3, 2]].tolist())
    #         folium.LayerControl().add_to(m)
    #         
    #         # Mostrar el mapa
    #         st_folium(m, use_container_width=True, height=800)
    # 
    #     except Exception as e:
    #         st.warning(f"No se pudo generar el mapa de resultados GIS: {e}")
    # 
    #     # --- FIN: NUEVO MAPA DE RESULTADOS ---
    # --- NUEVA SECCIÓN DE VISUALIZACIÓN DE RESULTADOS ---
    if 'hidro_results_externo' in st.session_state:
        results = st.session_state.hidro_results_externo
        
        st.divider()
        st.header("Resultados del Análisis sobre MDT25 en entorno GIS")

        # --- Bloque único para mostrar todos los resultados (mapa, métricas, etc.) ---
        try:
            # --- INICIO: NUEVO MAPA DE RESULTADOS ---
            st.subheader("Visor de Resultados GIS ::: Estas capas están disponibles en 'Descargas GIS y Datos' al final de la sección de Resultados")
            
            # Cargar los GeoDataFrames desde el JSON de resultados
            gdf_cuenca = gpd.read_file(results["downloads"]["cuenca"])
            gdf_lfp = gpd.read_file(results["downloads"]["lfp"])
            gdf_punto = gpd.read_file(results["downloads"]["punto_salida"])
            
            # Reproyectar todo a WGS84 para Folium
            gdf_cuenca_wgs84 = gdf_cuenca.to_crs("EPSG:4326")
            gdf_lfp_wgs84 = gdf_lfp.to_crs("EPSG:4326")
            gdf_punto_wgs84 = gdf_punto.to_crs("EPSG:4326")

            # Crear el mapa base
            m = folium.Map(tiles="CartoDB positron")
            folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m)

            # Añadir capa de la cuenca (rojo semitransparente)
            folium.GeoJson(
                gdf_cuenca_wgs84,
                name="Cuenca Delineada",
                style_function=lambda x: {'color': '#FF0000', 'weight': 2.5, 'fillColor': '#FF0000', 'fillOpacity': 0.2}
            ).add_to(m)

            # Añadir capa del LFP (amarillo intenso)
            folium.GeoJson(
                gdf_lfp_wgs84,
                name="Longest Flow Path (LFP)",
                style_function=lambda x: {'color': '#FFFF00', 'weight': 4, 'opacity': 0.9}
            ).add_to(m)

            if "rios_strahler" in results["downloads"]:
                gdf_rios_strahler = gpd.read_file(results["downloads"]["rios_strahler"]).to_crs("EPSG:4326")
                
                # ▼▼▼ LA SOLUCIÓN ESTÁ AQUÍ ▼▼▼
                # Comprobamos que el GeoDataFrame no esté vacío Y que la columna 'strord' exista
                if not gdf_rios_strahler.empty and 'strord' in gdf_rios_strahler.columns:
                    min_order = gdf_rios_strahler['strord'].min()
                    max_order = gdf_rios_strahler['strord'].max()
                    colormap = cm.LinearColormap(colors=['lightblue', 'blue', 'darkblue'], vmin=min_order, vmax=max_order)
                    
                    folium.GeoJson(
                        gdf_rios_strahler,
                        name="Red Fluvial (Strahler)",
                        style_function=lambda feature: {
                            'color': colormap(feature['properties']['strord']),
                            'weight': feature['properties']['strord'] / 2 + 1,
                            'opacity': 0.8,
                        },
                        tooltip=lambda feature: f"Orden: {feature['properties']['strord']}"
                    ).add_to(m)
                    m.add_child(colormap)

            # Añadir punto de desagüe (verde claro)
            lat, lon = gdf_punto_wgs84.geometry.iloc[0].y, gdf_punto_wgs84.geometry.iloc[0].x
            folium.Marker(
                [lat, lon],
                popup="Punto de Desagüe",
                icon=folium.Icon(color='green', icon='tint', prefix='fa')
            ).add_to(m)

            # Ajustar el zoom y añadir control de capas
            m.fit_bounds(gdf_cuenca_wgs84.total_bounds[[1, 0, 3, 2]].tolist())
            folium.LayerControl().add_to(m)
            
            # Mostrar el mapa
            st_folium(m, use_container_width=True, height=800)

            # --- INICIO: BLOQUE DE MÉTRICAS DE LA CUENCA ---
            st.subheader("Métricas de la Cuenca Delineada")
            
            # Cargar los datos necesarios (gdf_cuenca ya está cargado)
            gdf_rios = gpd.read_file(results["downloads"]["rios"]) 

            # Reproyectar a un CRS métrico para cálculos precisos
            cuenca_utm = gdf_cuenca.to_crs("EPSG:25830")
            rios_utm = gdf_rios.to_crs("EPSG:25830")

            # Calcular las métricas
            area_cuenca_km2 = cuenca_utm.area.sum() / 1_000_000
            longitud_total_km = rios_utm.length.sum() / 1000 if not rios_utm.empty else 0
            densidad_drenaje = (longitud_total_km / area_cuenca_km2) if area_cuenca_km2 > 0 else 0
            area_drenaje_minima_km2 = umbral_celdas * (25*25) / 1_000_000

            # Mostrar las métricas en 4 columnas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Umbral", f"{umbral_celdas} celdas")
                st.caption(f"Área drenaje mín.: {area_drenaje_minima_km2:.4f} km²")
            with col2:
                st.metric("Área Cuenca", f"{area_cuenca_km2:.4f} km²")
            with col3:
                st.metric("Longitud Cauces", f"{longitud_total_km:.2f} km")
            with col4:
                st.metric("Densidad Drenaje", f"{densidad_drenaje:.2f} km/km²")
            # --- PASO 3: Añadir la explicación de la Densidad de Drenaje ---
            st.info(
                """
                **¿Qué es la Densidad de Drenaje (Dd)?**
                
                La Densidad de Drenaje es una medida de la eficiencia con la que una cuenca es drenada por su red de cauces. Se calcula como:
                
                **Dd = Longitud Total de los Cauces (km) / Área Total de la Cuenca (km²)**
                
                - **Valores altos (> 0.5):** Indican un paisaje muy diseccionado por ríos, con pendientes fuertes y suelos poco permeables. La respuesta de la cuenca a la lluvia (escorrentía) es muy rápida.
                - **Valores bajos (< 0.5):** Sugieren un terreno con pendientes suaves, suelos más permeables y menos cauces definidos. La respuesta de la cuenca es más lenta.
                """,
                icon="ℹ️"
            )            
            # --- FIN: BLOQUE DE MÉTRICAS DE LA CUENCA ---

            # --- INICIO: BLOQUE DE MÉTRICAS DEL LFP (NUEVO) ---
            if "lfp_metrics" in results:
                st.subheader("Métricas del Camino de Flujo Principal (LFP - Longuest Flow Path)")
                metrics = results["lfp_metrics"]
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Cota Inicio (Salida)", f"{metrics.get('cota_ini_m', 0):.2f} m")
                    st.metric("Cota Fin (Divisoria)", f"{metrics.get('cota_fin_m', 0):.2f} m")
                with col2:
                    st.metric("Longitud LFP", f"{metrics.get('longitud_m', 0):.2f} m")
                    st.metric("Pendiente Media", f"{metrics.get('pendiente_media', 0):.4f} m/m")
                with col3:
                    st.metric("Tiempo Concentración", f"{metrics.get('tc_h', 0):.3f} h")
                    st.caption(f"Equivalente a {metrics.get('tc_min', 0):.2f} minutos")
            # --- FIN: BLOQUE DE MÉTRICAS DEL LFP (NUEVO) ---

            st.markdown("---") # Separador visual
            
            # --- Visualización de Gráficos ---
            st.subheader("Gráficos Generados")
            
            with st.expander("Ver todos los gráficos generados", expanded=True):
                plots = results.get("plots", {})
                if not plots:
                    st.warning("El script externo no generó ningún gráfico.")
                
                # Diccionario actualizado con la nueva clave del gráfico unificado
                plot_titles = {
                    "grafico_1_mosaico": "Características de la Cuenca",
                    "grafico_3_7_lfp_strahler": "LFP y Red Fluvial por Orden de Strahler", # <-- CLAVE NUEVA
                    "grafico_4_perfil_lfp": "Perfil Longitudinal del LFP",
                    "grafico_5_6_histo_hipso": "Histograma de Elevaciones y Curva Hipsométrica",
                    "grafico_11_llanuras": "Índices de Elevación (HAND y Llanuras de Inundación)"
                }
                
                # El bucle simple ahora funciona perfectamente para todos los gráficos
                for key, title in plot_titles.items():
                    if key in plots and plots[key]:
                        st.image(
                            io.BytesIO(base64.b64decode(plots[key])),
                            caption=title,
                            use_container_width=True
                        )                        
                        
            
            # --- Botones de Descarga ---
            st.subheader("Descargas GIS y Datos")
            
            downloads = results.get("downloads", {})
            if not downloads:
                st.warning("El script externo no generó ningún archivo para descargar.")
    
            # Fila 1 de descargas
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if "cuenca" in downloads:
                    gdf = gpd.read_file(downloads["cuenca"])
                    zip_io = export_gdf_to_zip(gdf, "cuenca_delineada")
                    st.download_button("📥 Cuenca (.zip)", zip_io, "cuenca_delineada.zip", "application/zip", use_container_width=True)
            with col2:
                if "rios" in downloads:
                    gdf = gpd.read_file(downloads["rios"])
                    zip_io = export_gdf_to_zip(gdf, "red_fluvial")
                    st.download_button("📥 Red Fluvial (.zip)", zip_io, "red_fluvial.zip", "application/zip", use_container_width=True)
            with col3:
                if "lfp" in downloads:
                    gdf = gpd.read_file(downloads["lfp"])
                    zip_io = export_gdf_to_zip(gdf, "lfp")
                    st.download_button("📥 LFP (.zip)", zip_io, "lfp.zip", "application/zip", use_container_width=True)
            with col4:
                if "punto_salida" in downloads:
                    gdf = gpd.read_file(downloads["punto_salida"])
                    zip_io = export_gdf_to_zip(gdf, "punto_salida")
                    st.download_button("📥 Punto Salida (.zip)", zip_io, "punto_salida.zip", "application/zip", use_container_width=True)
    
            # Fila 2 de descargas
            st.markdown("---") # Separador visual
            col5, col6, col7 = st.columns(3)
            with col5:
                 if "rios_strahler" in downloads:
                    gdf = gpd.read_file(downloads["rios_strahler"])
                    zip_io = export_gdf_to_zip(gdf, "rios_strahler")
                    st.download_button("📥 Ríos Strahler (.zip)", zip_io, "rios_strahler.zip", "application/zip", use_container_width=True)
            with col6:
                if results.get("lfp_profile_data"):
                    #st.markdown("---") # Separador visual
                    df_perfil = pd.DataFrame(results["lfp_profile_data"])
                    csv_perfil = df_perfil.to_csv(index=False, sep=';').encode('utf-8')
                    st.download_button(
                        "📥 Descargar Perfil LFP (.csv)",
                        csv_perfil,
                        "perfil_lfp.csv",
                        "text/csv",
                        use_container_width=True
                    )
                # if "subcuencas_strahler" in downloads:
                #     gdf = gpd.read_file(downloads["subcuencas_strahler"])
                #     zip_io = export_gdf_to_zip(gdf, "subcuencas_strahler")
                #     st.download_button("📥 Subcuencas Strahler (.zip)", zip_io, "subcuencas_strahler.zip", "application/zip", use_container_width=True)
            with col7:
                # ▼▼▼ BLOQUE AÑADIDO ▼▼▼
                if results.get("hypsometric_data"):
                    df_hipso = pd.DataFrame(results["hypsometric_data"])
                    csv_hipso = df_hipso.to_csv(index=False, sep=';').encode('utf-8')
                    st.download_button(
                        "📥 Descargar Curva Hipsométrica (.csv)",
                        csv_hipso,
                        "curva_hipsometrica.csv",
                        "text/csv",
                        use_container_width=True
                    )
                # if "puntos_strahler" in downloads:
                #     gdf = gpd.read_file(downloads["puntos_strahler"])
                #     zip_io = export_gdf_to_zip(gdf, "puntos_strahler")
                #     st.download_button("📥 Puntos Strahler (.zip)", zip_io, "puntos_strahler.zip", "application/zip", use_container_width=True)
            

            st.info(
                """
                Estas descargas le permitirán, entre otras muchas cosas, cargar en **HEC-HMS** el **Terreno** ya georreferenciado (Terrain Data Manager) y en el **Map Layers** el Punto de Salida y la Cuenca, dándole pleno dominio sobre dónde hacer click para situar el 'Sink'
                
                """,
                icon="ℹ️"
            )
    
            # # Fila 3 para el CSV
            # if results.get("lfp_profile_data"):
            #     st.markdown("---") # Separador visual
            #     df_perfil = pd.DataFrame(results["lfp_profile_data"])
            #     csv_perfil = df_perfil.to_csv(index=False, sep=';').encode('utf-8')
            #     st.download_button(
            #         "📥 Descargar Perfil LFP (.csv)",
            #         csv_perfil,
            #         "perfil_lfp.csv",
            #         "text/csv",
            #         use_container_width=True
            #     )
            
            # # Fila 3 para los CSV
            # if results.get("lfp_profile_data") or results.get("hypsometric_data"):
            #     st.markdown("---") # Separador visual
            #     csv_col1, csv_col2 = st.columns(2)
            # 
            #     with csv_col1:
            #         if results.get("lfp_profile_data"):
            #             df_perfil = pd.DataFrame(results["lfp_profile_data"])
            #             csv_perfil = df_perfil.to_csv(index=False, sep=';').encode('utf-8')
            #             st.download_button(
            #                 "📥 Descargar Perfil LFP (.csv)",
            #                 csv_perfil,
            #                 "perfil_lfp.csv",
            #                 "text/csv",
            #                 use_container_width=True
            #             )
            #     
            #     with csv_col2:
            #         # ▼▼▼ BLOQUE AÑADIDO ▼▼▼
            #         if results.get("hypsometric_data"):
            #             df_hipso = pd.DataFrame(results["hypsometric_data"])
            #             csv_hipso = df_hipso.to_csv(index=False, sep=';').encode('utf-8')
            #             st.download_button(
            #                 "📥 Descargar Curva Hipsométrica (.csv)",
            #                 csv_hipso,
            #                 "curva_hipsometrica.csv",
            #                 "text/csv",
            #                 use_container_width=True
            #             )
    
        except Exception as e:
            st.warning(f"Se produjo un error al mostrar los resultados: {e}")
    st.divider()
    st.markdown("##### Consejos para el Ajuste del Umbral de la Red Fluvial en HEC-HMS con un terreno MDT25 ")
    st.info("**Defina la red:**\n1. Umbral (nº de celdas) = Área de Drenaje Deseada (m²) / Área de una Celda (m²)\n2. Área de una Celda (m²) = 25 m x 25 m = 625 m² (en un MDT25)\n3. Área de Drenaje (km²) = Umbral (nº de celdas) x Área de una Celda (0.000625 km²)\n4. Areas < 0.03 km² (50 celdas) pueden generar cierto ruido, con una red excesivamente densa\n5. Areas > 3 km² (5000 celdas) puede eliminar cauces de interes, saliendo una red demasiado preponderante\n6. Empiece probando cauces que drenan 100 hectáreas (1 km² = 1600 celdas)")
