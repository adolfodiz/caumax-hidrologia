# dem25_tab.py (Versión Definitiva - Lógica Original Restaurada y Adaptada)

# ==============================================================================
# SECCIÓN 1: IMPORTS
# ==============================================================================
import streamlit as st
import geopandas as gpd
import folium
from streamlit_folium import st_folium
import os
import io
import requests
import pandas as pd
import json
import zipfile
import tempfile
from shapely.geometry import shape, Point, LineString, Polygon
from pyproj import CRS, Transformer
import base64
from PIL import Image
import traceback
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import numpy as np
from pysheds.grid import Grid # La librería original y correcta para esta lógica
import pyflwdir
from rasterio.mask import mask
from rasterio import features
import rasterio
from core_logic.gis_utils import get_local_path_from_url

# ==============================================================================
# SECCIÓN 2: CONSTANTES Y CONFIGURACIÓN
# ==============================================================================
HOJAS_MTN25_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MTN25_ACTUAL_ETRS89_Peninsula_Baleares_Canarias.zip"
DEM_NACIONAL_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MDT25_peninsula_UTM30N_COG.tif"
BUFFER_METROS = 5000
TARGET_CRS_DOWNLOAD = "EPSG:25830"

# ==============================================================================
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO (BASADA EN EL CÓDIGO ORIGINAL)
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

@st.cache_data(show_spinner="Ejecutando análisis hidrológico completo...")
def analisis_hidrologico_pysheds_pyflwdir(_dem_bytes, outlet_coords_wgs84, umbral_celdas):
    results = {"success": False, "message": ""}
    dem_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp:
            tmp.write(_dem_bytes); dem_path = tmp.name

        # --- 1. Procesamiento principal con PySheds (como en el original) ---
        grid = Grid.from_raster(dem_path)
        dem = grid.read_raster(dem_path)
        
        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        
        transformer = Transformer.from_crs("EPSG:4326", grid.crs.srs, always_xy=True)
        x_dem, y_dem = transformer.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_celdas, (x_dem, y_dem))
        
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        grid.clip_to(catch)
        clipped_catch = grid.view(catch)
        
        # --- 2. LFP con PySheds ---
        dist = grid.flow_distance(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        
        # --- 3. Geometrías (Cuenca, LFP, Punto) ---
        shapes = grid.polygonize()
        gdf_cuenca = gpd.GeoDataFrame.from_features(shapes, crs=grid.crs.srs)
        
        lfp_points = grid.longest_flow_path(x=x_snap, y=y_snap, fdir=flowdir, dist=dist, xytype='coordinate')
        gdf_lfp = gpd.GeoDataFrame([{'geometry': LineString(lfp_points)}], crs=grid.crs.srs)
        
        gdf_punto = gpd.GeoDataFrame([{'geometry': Point(x_snap, y_snap)}], crs=grid.crs.srs)

        # --- 4. Red Fluvial con PyFlwdir (usando los datos ya procesados) ---
        flw = pyflwdir.from_dem(data=grid.view(conditioned_dem), nodata=grid.nodata, transform=grid.affine, latlon=False)
        upa = flw.upstream_area(unit='cell')
        stream_mask = upa > umbral_celdas
        strord = flw.stream_order(mask=stream_mask, type='strahler')
        streams = flw.streams(mask=stream_mask, strord=strord)
        gdf_rios = gpd.GeoDataFrame.from_features(streams, crs=grid.crs.srs)

        # --- 5. Métricas ---
        area_km2 = gdf_cuenca.area.sum() / 1_000_000
        longitud_m = gdf_lfp.length.iloc[0]
        
        results.update({
            "success": True, "message": "Análisis completado.",
            "geometries_json": {
                "cuenca": gdf_cuenca.to_json(), "lfp": gdf_lfp.to_json(),
                "punto": gdf_punto.to_json(), "rios": gdf_rios.to_json()
            },
            "metrics": {"area_km2": area_km2, "lfp_longitud_m": longitud_m}
        })
        return results

    except Exception as e:
        results['message'] = f"Error en el análisis: {e}\n{traceback.format_exc()}"
        return results
    finally:
        if dem_path and os.path.exists(dem_path):
            os.remove(dem_path)

# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES
# ==============================================================================
@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    try:
        hojas_gdf = gpd.read_file(get_local_path_from_url(HOJAS_MTN25_PATH))
        cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
        buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs(TARGET_CRS_DOWNLOAD).buffer(BUFFER_METROS), crs=TARGET_CRS_DOWNLOAD)
        hojas_intersectadas = gpd.sjoin(hojas_gdf, buffer_gdf.to_crs(hojas_gdf.crs), how="inner", predicate="intersects").drop_duplicates(subset=['numero'])
        
        with rasterio.open(DEM_NACIONAL_PATH) as src:
            dem_recortado, trans_recortado = mask(dataset=src, shapes=buffer_gdf.to_crs(src.crs).geometry, crop=True, nodata=src.nodata or -32768)
            meta = src.meta.copy()
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado})
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst: dst.write(dem_recortado)
                buffer.seek(0); dem_bytes = buffer.read()
        
        return {
            "buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "dem_bytes": dem_bytes,
            "dem_array": dem_recortado, "hojas": hojas_intersectadas
        }
    except Exception as e:
        st.error(f"Error procesando la cuenca: {e}"); return None

def export_gdf_to_zip(gdf, filename_base, target_crs=TARGET_CRS_DOWNLOAD):
    with tempfile.TemporaryDirectory() as tmpdir:
        gdf_out = gdf.to_crs(target_crs)
        shapefile_path = os.path.join(tmpdir, f"{filename_base}.shp")
        gdf_out.to_file(shapefile_path, driver='ESRI Shapefile', encoding='utf-8')
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    if file.startswith(filename_base): zf.write(os.path.join(root, file), arcname=file)
        zip_io.seek(0)
        return zip_io

@st.cache_data(show_spinner="Pre-calculando referencia de cauces...")
def precalcular_acumulacion(_dem_bytes):
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                flw = pyflwdir.from_dem(data=src.read(1), transform=src.transform, nodata=src.nodata, latlon=False)
                acc = flw.upstream_area(unit='cell')
        acc_limpio = np.nan_to_num(acc, nan=0.0) ** 0.2
        min_v, max_v = np.nanmin(acc_limpio), np.nanmax(acc_limpio)
        if max_v == min_v: return np.zeros_like(acc_limpio, dtype=np.uint8)
        img_acc = (255 * (np.nan_to_num(acc_limpio, nan=min_v) - min_v) / (max_v - min_v)).astype(np.uint8)
        return img_acc
    except Exception as e:
        st.error(f"Error en pre-cálculo: {e}"); return None

# ==============================================================================
# SECCIÓN 5: FUNCIÓN PRINCIPAL DEL FRONTEND
# ==============================================================================

def render_dem25_tab():
    st.header("Generador y Analizador de MDT25")
    st.info("Esta herramienta permite delinear una cuenca y analizar su morfometría a partir de un punto de desagüe seleccionado.")

    if not st.session_state.get('basin_geojson'):
        st.warning("⬅️ Por favor, primero calcule una cuenca en la Pestaña 1."); st.stop()

    if st.button("🗺️ Cargar Área de Análisis (Cuenca + Buffer)", use_container_width=True):
        results = procesar_datos_cuenca(st.session_state.basin_geojson)
        if results:
            st.session_state.cuenca_results = results
            st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes'])
            st.session_state.pop('analisis_results', None); st.session_state.pop('outlet_coords', None)
            st.session_state.show_dem25_content = True; st.rerun()
        else:
            st.session_state.show_dem25_content = False

    if not st.session_state.get('show_dem25_content'):
        st.info("Haga clic en el botón de arriba para empezar."); return

    # --- SECCIÓN DE RESULTADOS INICIALES (RESTAURADA) ---
    st.divider()
    st.subheader("Resultados del Área de Análisis (Cuenca + Buffer 5km)")
    cuenca_results = st.session_state.cuenca_results
    
    m_inicial = folium.Map(tiles="CartoDB positron")
    folium.GeoJson(cuenca_results['hojas'], name="Hojas MTN25", style_function=lambda x: {'color': '#ffc107', 'weight': 2, 'fillOpacity': 0.4}, tooltip=lambda f: f"Hoja: {f['properties']['numero']}").add_to(m_inicial)
    buffer_layer = folium.GeoJson(cuenca_results['buffer_gdf'], name="Área de Análisis", style_function=lambda x: {'color': 'tomato', 'fillOpacity': 0.1}).add_to(m_inicial)
    m_inicial.fit_bounds(buffer_layer.get_bounds()); folium.LayerControl().add_to(m_inicial)
    st_folium(m_inicial, key="mapa_inicial", use_container_width=True, height=400)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Hojas MTN25 intersectadas", len(cuenca_results['hojas']))
        df = pd.DataFrame({'ID': [h['numero'] for _, h in cuenca_results['hojas'].iterrows()]})
        st.dataframe(df, height=200)
        st.download_button("📥 Descargar Contorno Buffer (.zip)", export_gdf_to_zip(gpd.read_file(io.BytesIO(json.dumps(cuenca_results['buffer_gdf']).__geo_interface__)), "contorno_buffer"), "contorno_buffer.zip", use_container_width=True)
    with col2:
        fig, ax = plt.subplots(); dem_array = cuenca_results['dem_array'][0]
        nodata = dem_array.min(); plot_array = np.where(dem_array == nodata, np.nan, dem_array)
        im = ax.imshow(plot_array, cmap='terrain'); fig.colorbar(im, ax=ax, label='Elevación (m)'); ax.set_axis_off(); st.pyplot(fig)
        st.download_button("📥 Descargar DEM Recortado (.tif)", cuenca_results['dem_bytes'], "dem_recortado.tif", "image/tiff", use_container_width=True)

    # --- SECCIÓN DE ANÁLISIS INTERACTIVO ---
    st.divider()
    st.header("Análisis Hidrológico Interactivo")
    st.subheader("Paso 1: Seleccione un punto de salida (outlet)")
    
    map_select = folium.Map(tiles="CartoDB positron"); map_select.fit_bounds(buffer_layer.get_bounds())
    if st.session_state.get('lat_wgs84') and st.session_state.get('lon_wgs84'):
        folium.Marker([st.session_state.lat_wgs84, st.session_state.lon_wgs84], popup="Punto de Interés (Pestaña 1)", icon=folium.Icon(color="red", icon="info-sign")).add_to(map_select)
    if st.session_state.get('precalculated_acc') is not None:
        bounds = cuenca_results['buffer_gdf'].total_bounds
        img = Image.fromarray(st.session_state.precalculated_acc)
        buffered = io.BytesIO(); img.save(buffered, format="PNG"); img_str = base64.b64encode(buffered.getvalue()).decode()
        folium.raster_layers.ImageOverlay(image=f"data:image/png;base64,{img_str}", bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, name='Referencia de Cauces').add_to(map_select)
    if st.session_state.get('outlet_coords'):
        folium.Marker([st.session_state.outlet_coords['lat'], st.session_state.outlet_coords['lng']], popup="Punto de Salida", icon=folium.Icon(color='orange')).add_to(map_select)
    
    map_output = st_folium(map_select, key="map_select", use_container_width=True, height=500, returned_objects=['last_clicked'])

    if map_output.get("last_clicked") and st.session_state.get('outlet_coords') != map_output["last_clicked"]:
        st.session_state.outlet_coords = map_output["last_clicked"]
        st.session_state.pop('analisis_results', None); st.rerun()

    st.subheader("Paso 2: Ejecute el análisis")
    umbral_celdas = st.slider(label="Umbral de celdas para definir cauces", min_value=10, max_value=10000, value=1600, step=10)
    
    if st.button("🚀 Analizar Punto Seleccionado", use_container_width=True, type="primary", disabled=not st.session_state.get('outlet_coords')):
        results = analisis_hidrologico_pysheds_pyflwdir(st.session_state.cuenca_results['dem_bytes'], st.session_state.outlet_coords, umbral_celdas)
        if results['success']:
            st.session_state.analisis_results = results
            st.success("Análisis completado."); st.rerun()
        else:
            st.error("Falló el análisis."); st.code(results['message'])

    if st.session_state.get('analisis_results'):
        st.divider()
        st.header("Resultados del Análisis")
        
        res = st.session_state.analisis_results
        gdf_cuenca = gpd.read_file(res["geometries_json"]["cuenca"])
        gdf_lfp = gpd.read_file(res["geometries_json"]["lfp"])
        gdf_punto = gpd.read_file(res["geometries_json"]["punto"])
        gdf_rios = gpd.read_file(res["geometries_json"]["rios"])
        
        m_results = folium.Map(tiles="CartoDB positron")
        folium.GeoJson(gdf_cuenca.to_crs("EPSG:4326"), name="Cuenca", style_function=lambda x: {'color': '#FF0000', 'weight': 2, 'fillOpacity': 0.2}).add_to(m_results)
        folium.GeoJson(gdf_lfp.to_crs("EPSG:4326"), name="LFP", style_function=lambda x: {'color': '#FFFF00', 'weight': 4}).add_to(m_results)
        gdf_rios_recortado = gpd.clip(gdf_rios, gdf_cuenca)
        if not gdf_rios_recortado.empty:
            folium.GeoJson(gdf_rios_recortado.to_crs("EPSG:4326"), name="Red Fluvial", style_function=lambda f: {'color': 'blue', 'weight': f['properties']['strord'] / 2 + 1}).add_to(m_results)
        m_results.fit_bounds(gdf_cuenca.to_crs("EPSG:4326").total_bounds[[1, 0, 3, 2]].tolist()); folium.LayerControl().add_to(m_results)
        st_folium(m_results, key="results_map", use_container_width=True, height=500)

        st.subheader("Métricas y Descargas")
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric("Área de la Cuenca", f"{res['metrics']['area_km2']:.4f} km²")
            st.metric("Longitud LFP", f"{res['metrics']['lfp_longitud_m']:.2f} m")
        with m_col2:
            st.download_button("📥 Cuenca (.zip)", export_gdf_to_zip(gdf_cuenca, "cuenca"), "cuenca.zip", use_container_width=True)
            st.download_button("📥 LFP (.zip)", export_gdf_to_zip(gdf_lfp, "lfp"), "lfp.zip", use_container_width=True)
            st.download_button("📥 Punto de Salida (.zip)", export_gdf_to_zip(gdf_punto, "punto"), "punto.zip", use_container_width=True)
            st.download_button("📥 Red Fluvial (.zip)", export_gdf_to_zip(gdf_rios, "rios"), "rios.zip", use_container_width=True)