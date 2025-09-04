# app.py (Modificado para eliminar el perfil del cauce principal)

import streamlit as st
import json
import os
import numpy as np
import plotly.graph_objects as go
import folium
from streamlit_folium import st_folium
import io
import zipfile
import tempfile
#from osgeo import osr, gdal, ogr
try:
    from osgeo import osr, gdal, ogr
except ImportError:
    st.error("GDAL no disponible - algunas funciones limitadas")
    gdal = None
    ogr = None
    osr = None
from shapely.ops import unary_union
import pandas as pd
from pathlib import Path
import rasterio

# Importar lógica de negocio y las nuevas pestañas GIS
from core_logic.gis_utils import get_raster_value_at_point, get_vector_feature_at_point, get_layer_path, load_geojson_from_gpkg
from core_logic.basin_calculator_refactored import BasinCalculatorRefactored
from core_logic.hydrology_methods import (
    calculate_rational_method, calculate_gev_fit, calculate_tcev_fit, 
    get_flow_from_gev, get_flow_from_tcev, get_median_for_plot,
    interpolate_rainfall
)
 

from pyproj import Transformer, CRS
from pysheds.grid import Grid


import gis_tabs
# from tabs import gis_tabs # (línea nueva)
from dem25_tab import render_dem25_tab
# from tabs.dem25_tab import render_dem25_tab # (línea nueva)
from perfil_terreno_tab import render_perfil_terreno_tab
# from tabs.perfil_terreno_tab import render_perfil_terreno_tab # (línea nueva)

# --- Configuración de CRS ---
crs_utm30n = CRS("EPSG:25830")
crs_wgs84 = CRS("EPSG:4326")
transformer_wgs84_to_utm30n = Transformer.from_crs(crs_wgs84, crs_utm30n, always_xy=True)
transformer_utm30n_to_wgs84 = Transformer.from_crs(crs_utm30n, crs_wgs84, always_xy=True)

# --- Rutas y Mapeo de Capas ---
DATA_FOLDER = os.path.join(os.path.dirname(__file__), 'data')
LAYER_MAPPING = {
    "BASINS": "demarcaciones_hidrograficas.gpkg", "RIVERS": "red10km.gpkg",
    "ZONES": "regiones.gpkg", "MDT": "mdt.tif", "FLOWDIRS": "dir.tif",
    "I1ID": "i1id.tif", "P0": "p0.tif", "RAIN_2": "t2.tif", "RAIN_5": "t5.tif",
    "RAIN_10": "t10.tif", "RAIN_25": "t25.tif", "RAIN_100": "t100.tif",
    "RAIN_500": "t500.tif", "FLOW_2": "q2.tif", "FLOW_5": "q5.tif",
    "FLOW_10": "q10.tif", "FLOW_25": "q25.tif", "FLOW_100": "q100.tif",
    "FLOW_500": "q500.tif",
}
STANDARD_RETURN_PERIODS = [2, 5, 10, 25, 100, 500]
EXTRAPOLATION_PERIODS = [1000, 5000, 10000] # <-- ADICIÓN
TCEV_REGIONS = [72, 73, 84, 821, 822]

# --- Funciones en Caché y Auxiliares (CÓDIGO ORIGINAL INTOCADO) ---
@st.cache_data
def get_cached_geojson_layer(layer_key):
    try:
        gpkg_path = get_layer_path(layer_key)
        return load_geojson_from_gpkg(gpkg_path)
    except Exception as e:
        st.error(f"Error al cargar la capa {layer_key}: {e}")
        return None

def create_all_download_zips(basin_calculator, outlet_coords):
    if not basin_calculator.basinGeometryUTM:
        return None, None, None, None
    with tempfile.TemporaryDirectory() as tmpdir:
        basin_shp_path = os.path.join(tmpdir, "cuenca_mask.shp")
        if not basin_calculator.export_basin_to_shapefile(basin_shp_path):
            return None, None, None, None
        basin_zip_io = io.BytesIO()
        with zipfile.ZipFile(basin_zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                if any(f.startswith("cuenca_mask") for f in files):
                    for file in files:
                        if file.startswith("cuenca_mask"): zf.write(os.path.join(root, file), arcname=file.replace("cuenca_mask", "cuenca_calculada"))
        basin_zip_io.seek(0)
        rivers_zip_io = None
        try:
            rivers_path = get_layer_path("RIVERS")
            rios_recortados_path = os.path.join(tmpdir, "rios_recortados.shp")
            options = gdal.VectorTranslateOptions(format='ESRI Shapefile', clipSrc=basin_shp_path)
            gdal.VectorTranslate(rios_recortados_path, rivers_path, options=options)
            rivers_zip_io = io.BytesIO()
            with zipfile.ZipFile(rivers_zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                    if any(f.startswith("rios_recortados") for f in files):
                        for file in files:
                            if file.startswith("rios_recortados"): zf.write(os.path.join(root, file), arcname=file.replace("rios_recortados", "rios_cuenca"))
            rivers_zip_io.seek(0)
        except Exception: pass
        dem_zip_io = None
        try:
            dem_path = get_layer_path("MDT")
            dem_tif_path_out = os.path.join(tmpdir, "mdt_recortado.tif")
            options_dem = gdal.WarpOptions(format='GTiff', cutlineDSName=basin_shp_path, cropToCutline=True, dstNodata=-9999)
            gdal.Warp(dem_tif_path_out, dem_path, options=options_dem)
            if os.path.exists(dem_tif_path_out) and os.path.getsize(dem_tif_path_out) > 0:
                dem_zip_io = io.BytesIO()
                with zipfile.ZipFile(dem_zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.write(dem_tif_path_out, arcname="mdt_cuenca.tif")
                dem_zip_io.seek(0)
        except Exception as e: st.error(f"Error técnico al recortar el DEM: {e}")
        point_zip_io = None
        try:
            point_shp_path = os.path.join(tmpdir, "punto_desague.shp")
            driver = ogr.GetDriverByName("ESRI Shapefile")
            out_ds = driver.CreateDataSource(point_shp_path)
            srs = osr.SpatialReference(); srs.ImportFromWkt(basin_calculator.crs_wkt)
            out_layer = out_ds.CreateLayer("punto_desague", srs, geom_type=ogr.wkbPoint)
            feature = ogr.Feature(out_layer.GetLayerDefn())
            point = ogr.Geometry(ogr.wkbPoint); point.AddPoint(outlet_coords[0], outlet_coords[1])
            feature.SetGeometry(point)
            out_layer.CreateFeature(feature)
            feature = None; out_ds = None
            point_zip_io = io.BytesIO()
            with zipfile.ZipFile(point_zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                     if any(f.startswith("punto_desague") for f in files):
                        for file in files:
                            if file.startswith("punto_desague"): zf.write(os.path.join(root, file), arcname=file)
            point_zip_io.seek(0)
        except Exception as e: st.warning(f"No se pudo crear el shapefile del punto de desagüe: {e}")
        return basin_zip_io, rivers_zip_io, dem_zip_io, point_zip_io

# --- INICIO: SECCIÓN ELIMINADA ---
# Las funciones create_river_profile_plot y create_profile_csv ya no se usan en este script,
# pero se mantienen aquí por si fueran necesarias en el futuro o en otras partes de la app.
# No es necesario eliminarlas del archivo, solo sus llamadas.
def create_river_profile_plot(rivers_shp_path, dem_tif_path, outlet_coords_utm):
    try:
        driver = ogr.GetDriverByName("ESRI Shapefile")
        rivers_ds = driver.Open(rivers_shp_path, 0)
        if rivers_ds is None: return None, None, None
        rivers_layer = rivers_ds.GetLayer()
        outlet_point = ogr.Geometry(ogr.wkbPoint); outlet_point.AddPoint(outlet_coords_utm[0], outlet_coords_utm[1])
        start_geom, start_geom_fid, min_dist, all_geoms = None, -1, float('inf'), {}
        for i in range(rivers_layer.GetFeatureCount()):
            feature = rivers_layer.GetFeature(i)
            geom = feature.GetGeometryRef()
            if geom and geom.GetGeometryName() == 'LINESTRING':
                all_geoms[i] = geom.Clone()
                dist = geom.Distance(outlet_point)
                if dist < min_dist: min_dist, start_geom, start_geom_fid = dist, geom.Clone(), i
        if start_geom is None: return None, None, None
        if start_geom_fid in all_geoms: del all_geoms[start_geom_fid]
        def reverse_linestring(geom):
            points = geom.GetPoints();
            if not points: return None
            new_line = ogr.Geometry(ogr.wkbLineString)
            for point in points[::-1]: new_line.AddPoint(point[0], point[1])
            return new_line
        points = start_geom.GetPoints()
        start_point_geom, end_point_geom = ogr.Geometry(ogr.wkbPoint), ogr.Geometry(ogr.wkbPoint)
        start_point_geom.AddPoint(points[0][0], points[0][1])
        end_point_geom.AddPoint(points[-1][0], points[-1][1])
        if end_point_geom.Distance(outlet_point) < start_point_geom.Distance(outlet_point): start_geom = reverse_linestring(start_geom)
        ordered_path_segments = [start_geom]
        current_head_coords = start_geom.GetPoints()[-1]
        current_head = ogr.Geometry(ogr.wkbPoint); current_head.AddPoint(current_head_coords[0], current_head_coords[1])
        found_next = True
        while found_next:
            found_next = False
            for fid, geom in list(all_geoms.items()):
                if geom.GetGeometryName() != 'LINESTRING': continue
                points = geom.GetPoints()
                seg_start_node, seg_end_node = points[0], points[-1]
                seg_start_geom, seg_end_geom = ogr.Geometry(ogr.wkbPoint), ogr.Geometry(ogr.wkbPoint)
                seg_start_geom.AddPoint(seg_start_node[0], seg_start_node[1])
                seg_end_geom.AddPoint(seg_end_node[0], seg_end_node[1])
                next_segment, current_head_coords = None, None
                if current_head.Distance(seg_start_geom) < 1e-5:
                    next_segment, current_head_coords = geom, seg_end_node
                elif current_head.Distance(seg_end_geom) < 1e-5:
                    rev_geom = reverse_linestring(geom)
                    if rev_geom: next_segment, current_head_coords = rev_geom, rev_geom.GetPoints()[-1]
                if next_segment:
                    ordered_path_segments.append(next_segment)
                    current_head.AddPoint(current_head_coords[0], current_head_coords[1])
                    del all_geoms[fid]
                    found_next = True
                    break
        final_points = []
        if not ordered_path_segments: return None, None, None
        final_points.extend(ordered_path_segments[0].GetPoints())
        for segment in ordered_path_segments[1:]:
            points_in_segment = segment.GetPoints()
            if points_in_segment: final_points.extend(points_in_segment[1:])
        dem_ds = gdal.Open(dem_tif_path)
        if dem_ds is None: return None, None, None
        gt, inv_gt, rb = dem_ds.GetGeoTransform(), gdal.InvGeoTransform(dem_ds.GetGeoTransform()), dem_ds.GetRasterBand(1)
        nodata_value, width, height = rb.GetNoDataValue(), dem_ds.RasterXSize, dem_ds.RasterYSize
        distances, elevations, total_distance = [], [], 0.0
        for i, point in enumerate(final_points):
            x, y = point[0], point[1]
            if i > 0: total_distance += ((x - final_points[i-1][0])**2 + (y - final_points[i-1][1])**2)**0.5
            distances.append(total_distance)
            px, py = int(inv_gt[0] + inv_gt[1] * x + inv_gt[2] * y), int(inv_gt[3] + inv_gt[4] * x + inv_gt[5] * y)
            if 0 <= px < width and 0 <= py < height:
                elev_data = rb.ReadAsArray(px, py, 1, 1)
                if elev_data is not None: elevations.append(np.nan if nodata_value is not None and elev_data[0][0] == nodata_value else elev_data[0][0])
                else: elevations.append(np.nan)
            else: elevations.append(np.nan)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=distances, y=elevations, mode='lines', line=dict(color='tomato', width=2), name='Perfil', connectgaps=False))
        fig.update_layout(title='Perfil Longitudinal del Río Principal', xaxis_title='Distancia al punto de desagüe (m)', yaxis_title='Elevación (msnm)', template='plotly_white', xaxis=dict(autorange='reversed'))
        main_channel_geom = ogr.Geometry(ogr.wkbLineString)
        for point in final_points: main_channel_geom.AddPoint(point[0], point[1])
        profile_data = {'distances_m': distances, 'elevations_m': elevations}
        rivers_ds, dem_ds = None, None
        return fig, main_channel_geom, profile_data
    except Exception as e:
        st.error(f"Se produjo un error inesperado al generar el perfil del río: {e}")
        import traceback
        traceback.print_exc()
        return None, None, None

def create_profile_csv(profile_data):
    if not profile_data or 'distances_m' not in profile_data or 'elevations_m' not in profile_data: return None
    df = pd.DataFrame({'distancia_m': profile_data['distances_m'], 'cota_terreno_m': profile_data['elevations_m']})
    df['distancia (km)'] = (df['distancia_m'] / 1000).round(3)
    df['cota terreno (m)'] = df['cota_terreno_m'].round(3)
    final_df = df[['distancia (km)', 'cota terreno (m)']]
    return final_df.to_csv(index=False, sep=';').encode('utf-8')
# --- FIN: SECCIÓN ELIMINADA ---

def export_geometry_to_zip(geometry, filename_base, crs_wkt):
    if not geometry: return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            shp_path = os.path.join(tmpdir, f"{filename_base}.shp")
            driver = ogr.GetDriverByName("ESRI Shapefile")
            out_ds = driver.CreateDataSource(shp_path)
            srs = osr.SpatialReference(); srs.ImportFromWkt(crs_wkt)
            geom_type = geometry.GetGeometryType()
            out_layer = out_ds.CreateLayer(filename_base, srs, geom_type=geom_type)
            feature_defn = out_layer.GetLayerDefn()
            feature = ogr.Feature(feature_defn)
            feature.SetGeometry(geometry)
            out_layer.CreateFeature(feature)
            feature = None; out_ds = None
            zip_io = io.BytesIO()
            with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(tmpdir):
                    for file in files:
                        if file.startswith(filename_base): zf.write(os.path.join(root, file), arcname=file)
            zip_io.seek(0)
            return zip_io
    except Exception as e:
        st.warning(f"No se pudo crear el shapefile para {filename_base}: {e}")
        return None

# --- Interfaz de Usuario de Streamlit ---
st.set_page_config(layout="wide", page_title="Calculadora Hidrológica y GIS")

if 'lon_wgs84' not in st.session_state:
    st.session_state.lon_wgs84 = -3.703790
    st.session_state.lat_wgs84 = 40.416775
    x_utm_init, y_utm_init = transformer_wgs84_to_utm30n.transform(st.session_state.lon_wgs84, st.session_state.lat_wgs84)
    st.session_state.x_utm, st.session_state.y_utm = round(x_utm_init, 3), round(y_utm_init, 3)
    st.session_state.calculation_triggered = False
    st.session_state.results = None
    st.session_state.basin_geojson = None
    st.session_state.max_dist_point_wgs84 = None
    st.session_state.last_calculated_x = None
    st.session_state.last_calculated_y = None
    st.session_state.last_calculated_rp = None
    st.session_state.map_zoom = 6
    st.session_state.map_center = [st.session_state.lat_wgs84, st.session_state.lon_wgs84]
    st.session_state.shapefile_zip_io = None
    st.session_state.fit_bounds_on_next_run = None
    st.session_state.rivers_zip_io = None
    st.session_state.dem_zip_io = None
    st.session_state.last_processed_click = None
    st.session_state.final_delineation_point_wgs84 = None
    # --- INICIO: LÍNEAS ELIMINADAS ---
    # st.session_state.main_channel_zip_io = None
    # st.session_state.main_channel_geojson = None
    # st.session_state.profile_csv_str = None
    # --- FIN: LÍNEAS ELIMINADAS ---


def update_coords_from_wgs84():
    lon, lat = st.session_state.lon_wgs84_input, st.session_state.lat_wgs84_input
    x_utm, y_utm = transformer_wgs84_to_utm30n.transform(lon, lat)
    st.session_state.x_utm, st.session_state.y_utm = round(x_utm, 3), round(y_utm, 3)
    st.session_state.lon_wgs84, st.session_state.lat_wgs84 = lon, lat
    st.session_state.map_center = [lat, lon]

def update_coords_from_utm():
    x_utm, y_utm = st.session_state.x_utm_input, st.session_state.y_utm_input
    lon, lat = transformer_utm30n_to_wgs84.transform(x_utm, y_utm)
    st.session_state.lon_wgs84, st.session_state.lat_wgs84 = round(lon, 6), round(lat, 6)
    st.session_state.x_utm, st.session_state.y_utm = x_utm, y_utm
    st.session_state.map_center = [lat, lon]

with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", use_container_width=True)
    else:
        st.info("No se encontró 'logo.png'. Coloque su logo en la misma carpeta que el script.")
    st.title("Panel de Control")
    st.header("Entrada de Datos")
    st.markdown("Haga clic en el mapa o introduzca coordenadas:")
    st.number_input("X UTM (ETRS89 Huso 30N):", key="x_utm_input", value=st.session_state.x_utm, format="%.3f", on_change=update_coords_from_utm)
    st.number_input("Y UTM (ETRS89 Huso 30N):", key="y_utm_input", value=st.session_state.y_utm, format="%.3f", on_change=update_coords_from_utm)
    st.number_input("Longitud (WGS84):", key="lon_wgs84_input", value=st.session_state.lon_wgs84, format="%.6f", on_change=update_coords_from_wgs84)
    st.number_input("Latitud (WGS84):", key="lat_wgs84_input", value=st.session_state.lat_wgs84, format="%.6f", on_change=update_coords_from_wgs84)
    return_period_user = st.number_input("Periodo de Retorno (años):", value=100, min_value=2, max_value=20000, step=1)
    if st.button("Calcular Caudal", type="primary"):
        st.session_state.calculation_triggered = True
        st.session_state.current_x_utm, st.session_state.current_y_utm = st.session_state.x_utm_input, st.session_state.y_utm_input
        st.session_state.current_return_period = return_period_user
        st.session_state.show_dem25_map = False
        st.rerun()
    st.header("Visibilidad de Capas")
    st.checkbox("Demarcaciones Hidrográficas", value=True, key="show_demarcaciones")
    st.checkbox("Regiones Hidrológicas", value=True, key="show_regiones")
    st.checkbox("Red Fluvial (10km)", value=True, key="show_rios")
    st.checkbox("Cuenca Calculada", value=bool(st.session_state.basin_geojson), key="show_cuenca", disabled=not st.session_state.basin_geojson)
    st.checkbox("Punto Más Alejado", value=bool(st.session_state.max_dist_point_wgs84), key="show_max_dist_point", disabled=not st.session_state.max_dist_point_wgs84)
    st.checkbox("Punto de Interés", value=True, key="show_point")
    # --- INICIO: LÍNEA ELIMINADA ---
    # st.checkbox("Cauce Principal Calculado", value=True, key="show_main_channel", disabled=not st.session_state.main_channel_geojson)
    # --- FIN: LÍNEA ELIMINADA ---
    st.header("Información de la Región")
    if st.session_state.results and st.session_state.results.get('region_info'):
        region_info = st.session_state.results['region_info']
        
        tmco_val = region_info.get('tmco')
        cv_text = "N/A" 
        if tmco_val is not None and isinstance(tmco_val, (int, float)):
            cv_val = tmco_val / 5
            cv_text = f"{cv_val:.2f}"
        
        st.markdown(f"**Región:** {region_info.get('id', 'N/A')} | **Beta Media:** {region_info.get('betamedio', 'N/A')}")
        st.markdown(f"**TMCO:** {region_info.get('tmco', 'N/A')} años | **CV:** {cv_text}")
        st.markdown("**Intervalos Confianza Beta:** "
                    f"50%: {region_info.get('IC50', 'N/A')} | "
                    f"67%: {region_info.get('IC67', 'N/A')} | "
                    f"90%: {region_info.get('IC90', 'N/A')}")
    else:
        st.markdown("Seleccione un punto y calcule para ver la información.")

st.title("Calculadora Hidrológica CAUMAX y Herramientas GIS")
st.header("Mapa Interactivo")
st.info("💡 **Consejo:** Para obtener los mejores resultados, haga clic directamente sobre o muy cerca de los cauces azules (Red Fluvial) superpuestos en el mapa.")
m = folium.Map(location=st.session_state.map_center, zoom_start=st.session_state.map_zoom, tiles='OpenStreetMap')
folium.TileLayer('CartoDB positron', name='CartoDB Positron').add_to(m)
folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Esri World Imagery').add_to(m)
if st.session_state.show_regiones and get_cached_geojson_layer("ZONES"): folium.GeoJson(get_cached_geojson_layer("ZONES"), name="Regiones", style_function=lambda x: {'color': 'darkorange', 'weight': 1, 'fillOpacity': 0.2}).add_to(m)
if st.session_state.show_demarcaciones and get_cached_geojson_layer("BASINS"): folium.GeoJson(get_cached_geojson_layer("BASINS"), name="Demarcaciones", style_function=lambda x: {'color': 'black', 'weight': 1, 'fillOpacity': 0.1}).add_to(m)
if st.session_state.basin_geojson and st.session_state.show_cuenca: folium.GeoJson(json.loads(st.session_state.basin_geojson), name="Cuenca Calculada", style_function=lambda x: {'color': 'red', 'weight': 3, 'fillOpacity': 0.3}).add_to(m)
if st.session_state.show_rios and get_cached_geojson_layer("RIVERS"): folium.GeoJson(get_cached_geojson_layer("RIVERS"), name="Red Fluvial", style_function=lambda x: {'color': 'cyan', 'weight': 2.0}).add_to(m)
# --- INICIO: LÍNEA ELIMINADA ---
# if st.session_state.main_channel_geojson and st.session_state.show_main_channel: folium.GeoJson(json.loads(st.session_state.main_channel_geojson), name="Cauce Principal Calculado", style_function=lambda x: {'color': 'blue', 'weight': 3.5, 'opacity': 0.9}).add_to(m)
# --- FIN: LÍNEA ELIMINADA ---
if st.session_state.max_dist_point_wgs84 and st.session_state.show_max_dist_point: folium.CircleMarker([st.session_state.max_dist_point_wgs84['lat'], st.session_state.max_dist_point_wgs84['lon']], radius=5, color='green', fill=True, fill_color='green', popup="Punto Más Alejado").add_to(m)
if st.session_state.show_point: folium.Marker([st.session_state.lat_wgs84, st.session_state.lon_wgs84], popup="Punto de Interés", icon=folium.Icon(color="red", icon="info-sign")).add_to(m)
folium.LayerControl().add_to(m)
if st.session_state.get("fit_bounds_on_next_run"):
    m.fit_bounds(st.session_state.fit_bounds_on_next_run)
    st.session_state.fit_bounds_on_next_run = None
st_map_output = st_folium(m, key="folium_map", returned_objects=["last_clicked"], width=None, height=600)
if st_map_output and st_map_output.get("last_clicked") is not None:
    st.session_state.lon_wgs84, st.session_state.lat_wgs84 = st_map_output["last_clicked"]["lng"], st_map_output["last_clicked"]["lat"]
    st.session_state.map_center = [st.session_state.lat_wgs84, st.session_state.lon_wgs84]
    x_utm, y_utm = transformer_wgs84_to_utm30n.transform(st.session_state.lon_wgs84, st.session_state.lat_wgs84)
    st.session_state.x_utm, st.session_state.y_utm = round(x_utm, 3), round(y_utm, 3)
    st.rerun()

tab1, tab2, tab3, tab4 = st.tabs(["Cálculo de Caudal (CAUMAX)", "Generador DEM CNIG", "Perfil de Terreno", "Analizador HEC-HMS"])

with tab1:
    if st.session_state.calculation_triggered and (st.session_state.current_x_utm, st.session_state.current_y_utm, st.session_state.current_return_period) != (st.session_state.get('last_calculated_x'), st.session_state.get('last_calculated_y'), st.session_state.get('last_calculated_rp')):
        with st.spinner("Calculando cuenca y realizando doble ajuste de curva..."):
            try:
                x_utm, y_utm, return_period = st.session_state.current_x_utm, st.session_state.current_y_utm, st.session_state.current_return_period
                results, warnings = {}, []
                
                region_feature = get_vector_feature_at_point(get_layer_path("ZONES"), (x_utm, y_utm))
                if not region_feature:
                    st.error("Punto fuera de las regiones hidrográficas."); st.session_state.calculation_triggered = False; st.stop()
                region_props = region_feature['properties']
                region_id = region_props.get('region') or region_props.get('ID') or region_props.get('id', "Desconocida")
                results['region_info'] = {k: region_props.get(k) for k in ['tmco', 'cp0t2', 'cp0t5', 'cp0t10', 'cp0t25', 'cp0t100', 'cp0t500', 'betamedio', 'IC50', 'IC67', 'IC90']}
                results['region_info']['id'] = region_id

                basin_calc = BasinCalculatorRefactored(DATA_FOLDER, LAYER_MAPPING)
                basin_calc.calculate((x_utm, y_utm))
                area_km2 = basin_calc.area / 1_000_000
                results['basin_properties'] = {"area_km2": round(area_km2, 3), "concentration_time_h": round(basin_calc.concentrationTime, 3), "max_distance_m": round(basin_calc.maxDistance, 0), "max_h_msnm": round(basin_calc.maxH, 3), "min_h_msnm": round(basin_calc.minH, 3)}
                st.session_state.basin_geojson = json.dumps(basin_calc.basinGeometry[0].__geo_interface__) if basin_calc.basinGeometry else None
                
                st.session_state.shapefile_zip_io, st.session_state.rivers_zip_io, st.session_state.dem_zip_io, st.session_state.point_zip_io = create_all_download_zips(basin_calc, (x_utm, y_utm))
                
                # --- INICIO: BLOQUE ELIMINADO ---
                # Se elimina toda la lógica para generar el perfil del cauce principal.
                # profile_fig, main_channel_geom, profile_data = None, None, None
                # with tempfile.TemporaryDirectory() as tmpdir:
                #     try:
                #         rivers_path, basin_shp_path = get_layer_path("RIVERS"), os.path.join(tmpdir, "cuenca_mask.shp")
                #         basin_calc.export_basin_to_shapefile(basin_shp_path)
                #         rivers_shp_path_out = os.path.join(tmpdir, "rios_recortados.shp")
                #         gdal.VectorTranslate(rivers_shp_path_out, rivers_path, options=gdal.VectorTranslateOptions(format='ESRI Shapefile', clipSrc=basin_shp_path))
                #         if os.path.exists(rivers_shp_path_out):
                #             profile_fig, main_channel_geom, profile_data = create_river_profile_plot(rivers_shp_path_out, get_layer_path("MDT"), (x_utm, y_utm))
                #     except Exception as e: st.warning(f"No se pudo generar el cauce principal o el perfil: {e}")
                
                # st.session_state.profile_plot = profile_fig
                # if main_channel_geom:
                #     st.session_state.main_channel_zip_io = export_geometry_to_zip(main_channel_geom, "cauce_principal", basin_calc.crs_wkt)
                #     source_srs, target_srs = osr.SpatialReference(), osr.SpatialReference()
                #     source_srs.ImportFromWkt(basin_calc.crs_wkt); target_srs.ImportFromEPSG(4326)
                #     coord_transform = osr.CoordinateTransformation(source_srs, target_srs)
                #     main_channel_geom.Transform(coord_transform)
                #     st.session_state.main_channel_geojson = main_channel_geom.ExportToJson()
                # else: st.session_state.main_channel_geojson, st.session_state.main_channel_zip_io = None, None
                # st.session_state.profile_csv_str = create_profile_csv(profile_data) if profile_data else None
                # --- FIN: BLOQUE ELIMINADO ---

                if basin_calc.xMaxDistance is not None:
                    lon_md, lat_md = transformer_utm30n_to_wgs84.transform(basin_calc.xMaxDistance, basin_calc.yMaxDistance)
                    st.session_state.max_dist_point_wgs84 = {"lon": lon_md, "lat": lat_md}
                if basin_calc.basinGeometry:
                    bounds = unary_union(basin_calc.basinGeometry).bounds
                    st.session_state.fit_bounds_on_next_run = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

                # --- INICIO DE LA LÓGICA DE CÁLCULO HIDROLÓGICO (MANTENIENDO LA ORIGINAL) ---
                flows_for_fitting, rains_for_fitting, r_periods_for_fitting, intermediate_variables = [], [], [], {}
                if area_km2 < 50:
                    method_used = "Método Racional"
                    valid_rps = [rp for rp in STANDARD_RETURN_PERIODS if basin_calc.rain.get(rp) is not None]
                    valid_rains = [basin_calc.rain[rp] for rp in valid_rps]
                    for i, rp in enumerate(valid_rps):
                        flow, _ = calculate_rational_method(area_km2, basin_calc.concentrationTime, basin_calc.i1id, basin_calc.p0, region_props.get('betamedio', 1.0), region_props.get(f'cp0t{rp}', 1.0), valid_rains[i])
                        if flow is not None and flow >= 0: flows_for_fitting.append(flow); r_periods_for_fitting.append(rp); rains_for_fitting.append(valid_rains[i])
                    user_rainfall_mm = interpolate_rainfall(return_period, valid_rps, valid_rains)
                    if user_rainfall_mm is None: warnings.append(f"Advertencia: No se pudo interpolar la precipitación para T={return_period} años."); user_rainfall_mm = 0
                    user_p0_corrector_rp = region_props.get(f'cp0t{int(return_period)}', 1.0) if return_period in STANDARD_RETURN_PERIODS else 1.0
                    _, intermediate_variables = calculate_rational_method(area_km2, basin_calc.concentrationTime, basin_calc.i1id, basin_calc.p0, region_props.get('betamedio', 1.0), user_p0_corrector_rp, user_rainfall_mm)
                    intermediate_variables['rainfall_mm_for_T'] = round(user_rainfall_mm, 2)
                else:
                    method_used = "Interpolación de Cuantiles"
                    for rp in STANDARD_RETURN_PERIODS:
                        flow_val = get_raster_value_at_point(get_layer_path(f"FLOW_{rp}"), (x_utm, y_utm))
                        rain_val = get_raster_value_at_point(get_layer_path(f"RAIN_{rp}"), (x_utm, y_utm))
                        if flow_val not in [None, 99999] and rain_val not in [None, 99999] and flow_val > 0 and rain_val > 0:
                            flows_for_fitting.append(flow_val); rains_for_fitting.append(rain_val); r_periods_for_fitting.append(rp)
                
                results['method_used'] = method_used
                use_tcev = region_id in TCEV_REGIONS
                fit_type = "TCEV" if use_tcev else "GEV"
                formula_img = "tcev_formula.jpg" if use_tcev else "gev_formula.jpg"
                
                flow_fit_params, rain_fit_params = None, None
                results['flow_fit_info'], results['rain_fit_info'] = None, None
                fit_func = calculate_tcev_fit if use_tcev else calculate_gev_fit
                value_func = get_flow_from_tcev if use_tcev else get_flow_from_gev
                
                if len(flows_for_fitting) >= 3:
                    flow_fit_params = fit_func(flows_for_fitting, r_periods_for_fitting)
                    params = {}
                    if use_tcev:
                        params = {"alpha1": round(flow_fit_params[0], 4), "alpha2": round(flow_fit_params[1], 4), "lambda1": round(flow_fit_params[2], 4), "lambda2": round(flow_fit_params[3], 4)}
                    else: 
                        params = {"u": round(flow_fit_params[1], 4), "alpha": round(flow_fit_params[0], 4), "k": round(flow_fit_params[2], 4)}
                    results['flow_fit_info'] = {"type": fit_type, "params": params}
                else:
                    warnings.append("No hay suficientes datos de caudal para un ajuste de curva fiable.")
    
                if len(rains_for_fitting) >= 3:
                    rain_fit_params = fit_func(rains_for_fitting, r_periods_for_fitting)
                    params = {}
                    if use_tcev:
                        params = {"alpha1": round(rain_fit_params[0], 4), "alpha2": round(rain_fit_params[1], 4), "lambda1": round(rain_fit_params[2], 4), "lambda2": round(rain_fit_params[3], 4)}
                    else:
                        params = {"u": round(rain_fit_params[1], 4), "alpha": round(rain_fit_params[0], 4), "k": round(rain_fit_params[2], 4)}
                    results['rain_fit_info'] = {"type": fit_type, "params": params}
                else:
                    warnings.append("No hay suficientes datos de lluvia para un ajuste de curva fiable.")

                derived_quantiles = []
                tmco_period = results['region_info'].get('tmco')
                all_rps = sorted(list(set(STANDARD_RETURN_PERIODS + EXTRAPOLATION_PERIODS + [return_period] + ([tmco_period] if tmco_period else []))))

                for rp in all_rps:
                    if rp == 0: continue
                    row = {"Periodo (años)": rp}
                    row["Lluvia P24máx (mm)"] = round(value_func(rp, rain_fit_params), 2) if rain_fit_params is not None else 'N/A'
                    row["Caudal (m³/s)"] = round(value_func(rp, flow_fit_params), 2) if flow_fit_params is not None else 'N/A'
                    closest_rp = min(STANDARD_RETURN_PERIODS, key=lambda x:abs(x-rp))
                    p0_val = results['region_info'].get(f'cp0t{closest_rp}')
                    row["Coef. P0"] = f"{p0_val:.3f}" if p0_val else "N/A"
                    derived_quantiles.append(row)
                
                results['derived_quantiles_table'] = pd.DataFrame(derived_quantiles).set_index("Periodo (años)")
                results['rain_user_rp'] = round(value_func(return_period, rain_fit_params), 2) if rain_fit_params is not None else 'N/A'
                results['flow_user_rp'] = round(value_func(return_period, flow_fit_params), 2) if flow_fit_params is not None else 'N/A'
                results['flow_tmco'] = round(value_func(tmco_period, flow_fit_params), 2) if flow_fit_params is not None and tmco_period else 'N/A'
                
                def prepare_plot_data(fit_params, data_points, rp_points, user_rp, tmco_rp):
                    if fit_params is None: return None
                    max_ext_rp = max(EXTRAPOLATION_PERIODS)
                    curve_fit_rps = np.logspace(np.log10(min(rp_points)), np.log10(max(rp_points)), 100)
                    curve_ext_rps = np.logspace(np.log10(max(rp_points)), np.log10(max_ext_rp + 1), 100)
                    return {
                        "fit_periods": curve_fit_rps, "fit_values": [value_func(p, fit_params) for p in curve_fit_rps],
                        "ext_periods": curve_ext_rps, "ext_values": [value_func(p, fit_params) for p in curve_ext_rps],
                        "points_rp": rp_points, "points_values": data_points,
                        "ext_points_rp": EXTRAPOLATION_PERIODS, "ext_points_values": [value_func(p, fit_params) for p in EXTRAPOLATION_PERIODS],
                        "user_rp": user_rp, "user_val": value_func(user_rp, fit_params),
                        "tmco_rp": tmco_rp, "tmco_val": value_func(tmco_rp, fit_params) if tmco_rp else 0
                    }
                results['flow_plot_data'] = prepare_plot_data(flow_fit_params, flows_for_fitting, r_periods_for_fitting, return_period, tmco_period)
                results['rain_plot_data'] = prepare_plot_data(rain_fit_params, rains_for_fitting, r_periods_for_fitting, return_period, tmco_period)

                results['warnings'] = warnings
                results['intermediate_variables'] = intermediate_variables
                st.session_state.results = results
                st.session_state.last_calculated_x, st.session_state.last_calculated_y, st.session_state.last_calculated_rp = x_utm, y_utm, return_period
                st.session_state.calculation_triggered = False
                st.rerun()

            except Exception as e:
                st.error(f"Error fatal en el cálculo: {e}")
                import traceback
                st.error(traceback.format_exc())
                st.session_state.calculation_triggered = False

    if st.session_state.results:
        results = st.session_state.results
        st.subheader("Resultados Finales")
        st.write(f"**Para T={st.session_state.current_return_period} años: Lluvia máxima diaria: {results.get('rain_user_rp', 'N/A')} mm | "
                 f"Caudal: {results.get('flow_user_rp', 'N/A')} m³/s | "
                 f"Caudal Máximo Ordinario (MCO): {results.get('flow_tmco', 'N/A')} m³/s para T = {region_info.get('tmco', 'N/A')} años**")
        for warning in results.get('warnings', []): st.warning(warning)
        st.markdown(f'<p style="color:darkorange;"><strong>Método de cálculo aplicado: {results.get("method_used", "No determinado").upper()}</strong></p>', unsafe_allow_html=True)      
        st.subheader("Parámetros Característicos de la Cuenca")
        bp = results['basin_properties']
        if bp['max_distance_m'] > 0: slope_text = f"| **Pdte. Med.:** {((bp['max_h_msnm'] - bp['min_h_msnm']) / bp['max_distance_m']):.4f} m/m"
        else: slope_text = ""
        st.markdown(f"**Área:** {bp['area_km2']} km² | **Lmax:** {bp['max_distance_m']} m | **Tc:** {bp['concentration_time_h']} h | **Hmax:** {bp['max_h_msnm']} msnm | **Hmin:** {bp['min_h_msnm']} msnm {slope_text}")
        st.subheader("Descargas GIS")
        # --- INICIO: MODIFICACIÓN DE COLUMNAS ---
        dl_col1, dl_col2, dl_col3, dl_col4 = st.columns(4)
        # --- FIN: MODIFICACIÓN DE COLUMNAS ---
        with dl_col1:
            if st.session_state.get("shapefile_zip_io"): st.download_button("📥 Cuenca (.zip)", st.session_state.shapefile_zip_io, f"cuenca_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.zip", "application/zip", use_container_width=True)
        with dl_col2:
            if st.session_state.get("rivers_zip_io"): st.download_button("📥 Ríos (.zip)", st.session_state.rivers_zip_io, f"rios_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.zip", "application/zip", use_container_width=True)
        with dl_col3:
            if st.session_state.get("dem_zip_io"): st.download_button("📥 DEM (.zip)", st.session_state.dem_zip_io, f"mdt_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.zip", "application/zip", use_container_width=True)
        with dl_col4:
            if st.session_state.get("point_zip_io"): st.download_button("📥 Punto (.zip)", st.session_state.point_zip_io, f"punto_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.zip", "application/zip", use_container_width=True)
        # --- INICIO: COLUMNA ELIMINADA ---
        # with dl_col5:
        #     if st.session_state.get("main_channel_zip_io"): st.download_button("📥 Cauce (.zip)", st.session_state.main_channel_zip_io, f"cauce_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.zip", "application/zip", use_container_width=True)
        # --- FIN: COLUMNA ELIMINADA ---
        
        # --- INICIO: BLOQUE ELIMINADO ---
        # Se elimina la visualización del perfil y su botón de descarga
        # st.info("Utilidad para HEC-HMS...", icon="ℹ️")
        # if st.session_state.get("profile_plot"):
        #     st.plotly_chart(st.session_state.profile_plot, use_container_width=True)
        #     if st.session_state.get("profile_csv_str"): st.download_button(label="📥 Descargar Perfil (.csv)", data=st.session_state.profile_csv_str, file_name=f"perfil_rio_{st.session_state.current_x_utm}_{st.session_state.current_y_utm}.csv", mime='text/csv')
        # --- FIN: BLOQUE ELIMINADO ---
        
        if 'derived_quantiles_table' in results and not results['derived_quantiles_table'].empty:
            st.subheader("Tabla de Cuantiles Derivados (incluye extrapolación)")
            st.dataframe(results['derived_quantiles_table'].style.format(formatter={"Periodo (años)": "{:.2f}", "Lluvia P24máx (mm)": "{:.2f}", "Caudal (m³/s)": "{:.2f}"}), use_container_width=True)

        st.subheader("Ley de Frecuencia y Parámetros de Ajuste")
        
        st.markdown("<style>.stKatex { font-size: 2.5em; }</style>", unsafe_allow_html=True)
        
        fit_info_general = results.get('flow_fit_info') or results.get('rain_fit_info')
        if fit_info_general:
            fit_type = fit_info_general.get('type')
            if fit_type == 'GEV':
                st.latex(r'''F(q) = e^{-\left[ 1 - k \left( \frac{q-u}{\alpha} \right) \right]^{1/k}}''')
            elif fit_type == 'TCEV':
                st.latex(r'''F(q) = e^{\left[ \alpha_1 e^{-q \lambda_1} - \alpha_2 e^{-q \lambda_2} \right]}''')
        
        col_fit1, col_fit2 = st.columns(2)
        
        with col_fit1:
            if 'flow_fit_info' in results and results['flow_fit_info']:
                fit_info = results['flow_fit_info']
                st.markdown(f"**Ajuste de Caudal ({fit_info.get('type', 'N/A')})**")
                st.write("**Parámetros de Ajuste:**")
                if 'params' in fit_info and isinstance(fit_info['params'], dict):
                    params_html = ""
                    for key, value in fit_info['params'].items():
                        params_html += f"<li>{key}: {value}</li>"
                    st.markdown(f"<ul>{params_html}</ul>", unsafe_allow_html=True)
        
        with col_fit2:
            if 'rain_fit_info' in results and results['rain_fit_info']:
                fit_info = results['rain_fit_info']
                st.markdown(f"**Ajuste de Lluvia ({fit_info.get('type', 'N/A')})**")
                st.write("**Parámetros de Ajuste:**")
                if 'params' in fit_info and isinstance(fit_info['params'], dict):
                    params_html = ""
                    for key, value in fit_info['params'].items():
                        params_html += f"<li>{key}: {value}</li>"
                    st.markdown(f"<ul>{params_html}</ul>", unsafe_allow_html=True)
        
        st.divider()

        def create_frequency_plot(plot_data, title, y_axis_title):
            if not plot_data: return None
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=plot_data['fit_periods'], y=plot_data['fit_values'], mode='lines', line=dict(color='royalblue'), name='Curva de Ajuste'))
            fig.add_trace(go.Scatter(x=plot_data['ext_periods'], y=plot_data['ext_values'], mode='lines', line=dict(color='grey', dash='dash'), name='Curva Extrapolada'))
            fig.add_trace(go.Scatter(x=plot_data['points_rp'], y=plot_data['points_values'], mode='markers', name='Datos Base', marker=dict(color='red', size=8)))
            fig.add_trace(go.Scatter(x=plot_data['ext_points_rp'], y=plot_data['ext_points_values'], mode='markers', name='Puntos Extrapolados', marker=dict(color='black', size=9, symbol='cross')))
            fig.add_trace(go.Scatter(x=[plot_data['user_rp']], y=[plot_data['user_val']], mode='markers', name=f'T Usuario ({int(plot_data["user_rp"])} años)', marker=dict(color='green', size=12, symbol='star')))
            if 'tmco_val' in plot_data and plot_data['tmco_val'] > 0: fig.add_trace(go.Scatter(x=[plot_data['tmco_rp']], y=[plot_data['tmco_val']], mode='markers', name='TMCO', marker=dict(color='purple', size=12, symbol='diamond')))
            fig.update_layout(title=title, xaxis_title='Periodo de retorno (años)', yaxis_title=y_axis_title, xaxis_type='log', yaxis_type="linear", legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            return fig
        if results.get('flow_plot_data'):
            st.subheader("Gráfico de Ajuste de Caudales")
            st.plotly_chart(create_frequency_plot(results['flow_plot_data'], 'Ley de Frecuencia de Caudal', 'Caudal (m³/s)'), use_container_width=True)
        if results.get('rain_plot_data'):
            st.subheader("Gráfico de Ajuste de Lluvias")
            st.plotly_chart(create_frequency_plot(results['rain_plot_data'], 'Ley de Frecuencia de Lluvia', 'Lluvia P24máx (mm)'), use_container_width=True)
        st.warning("""**Aviso sobre la Extrapolación:** Los valores y gráficos para períodos de retorno superiores a 500 años son el resultado de una extrapolación matemática; se aconseja un estudio más detallado en estos casos.""")
        if results.get('intermediate_variables'):
            st.subheader(f"Variables Intermedias ({results.get('method_used', '').upper()})")
            intermediate_vars = results['intermediate_variables']
            ORDERED_KEYS = ["Area (A) (km²)", "Tiempo de concentración (h)", "Factor reductor por área", "Factor de intensidad", "Factor de torrencialidad (I1/Id)", "Intensidad (I) (mm/h)", "P0 (mm)", "P0 corregido (mm)", "rainfall_mm_for_T", "Precipitación corregida (mm)", "Coeficiente de uniformidad (K)", "Coeficiente de escorrentía (C)"]
            PRETTY_NAMES = {"Area (A) (km²)": "Área (A)", "Tiempo de concentración (h)": "Tiempo de concentración (T<sub>c</sub>)", "Factor reductor por área": "Factor reductor por área (F<sub>a</sub>)", "Factor de intensidad": "Factor de intensidad (F<sub>i</sub>)", "Factor de torrencialidad (I1/Id)": "Factor de torrencialidad (I<sub>1</sub>/I<sub>d</sub>)", "Intensidad (I) (mm/h)": "Intensidad (I)", "P0 (mm)": "P<sub>0</sub>", "P0 corregido (mm)": "P<sub>0</sub> corregido", "rainfall_mm_for_T": "Precipitación para T", "Precipitación corregida (mm)": "Precipitación corregida", "Coeficiente de uniformidad (K)": "Coeficiente de uniformidad (K)", "Coeficiente de escorrentía (C)": "Coeficiente de escorrentía (C)"}
            UNITS = {"Area (A) (km²)": "km<sup>2</sup>", "Tiempo de concentración (h)": "h", "Intensidad (I) (mm/h)": "mm/h", "P0 (mm)": "mm", "P0 corregido (mm)": "mm", "rainfall_mm_for_T": "mm", "Precipitación corregida (mm)": "mm"}
            col_a, col_b = st.columns(2)
            midpoint = len(ORDERED_KEYS) // 2 + len(ORDERED_KEYS) % 2
            html_col_a, html_col_b = "", ""
            for i, key in enumerate(ORDERED_KEYS):
                value = intermediate_vars.get(key)
                if value is not None:
                    val_str = f"{value:.3f}" if isinstance(value, (int, float)) else str(value)
                    html_line = f'<li><strong>{PRETTY_NAMES.get(key, key)}:</strong> <code>{val_str} {UNITS.get(key, "")}</code></li>'
                    if i < midpoint: html_col_a += html_line
                    else: html_col_b += html_line
            with col_a: st.markdown(f"<ul>{html_col_a}</ul>", unsafe_allow_html=True)
            with col_b: st.markdown(f"<ul>{html_col_b}</ul>", unsafe_allow_html=True)
            st.divider()
            with st.expander("ℹ️ Ver explicación teórica de las variables"):
                st.markdown(""" (Explicación teórica original) """)
    else:
        st.info("Seleccione un punto en el mapa y haga clic en 'Calcular Caudal' en el panel izquierdo.")

with tab2: render_dem25_tab()
with tab3: render_perfil_terreno_tab()
with tab4: gis_tabs.render_hms_tab()
