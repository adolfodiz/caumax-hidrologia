# dem25_tab.py (Versión con CRS de Descarga Corregido)

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
from pysheds.grid import Grid
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
TARGET_CRS_DOWNLOAD = "EPSG:25830" # CRS para todas las descargas

# ==============================================================================
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO (Estable y Corregida)
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

@st.cache_data(show_spinner="Ejecutando análisis hidrológico principal (Cuenca y LFP)...")
def paso1_delinear_y_calcular_lfp(_dem_bytes, outlet_coords_wgs84, umbral_rio_export):
    results = {"success": False, "message": ""}
    dem_path_for_pysheds = None
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_crs = src.crs
                out_transform = src.transform
                no_data_value = src.nodata or -32768
                transformer_wgs84_to_dem_crs = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
                x_dem_crs, y_dem_crs = transformer_wgs84_to_dem_crs.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])

                with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_dem_pysheds:
                    tmp_dem_pysheds.write(_dem_bytes)
                    dem_path_for_pysheds = tmp_dem_pysheds.name

        grid = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        dem = grid.read_raster(dem_path_for_pysheds, nodata=no_data_value)
        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_rio_export, (x_dem_crs, y_dem_crs))
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")
        dist = grid._d8_flow_distance(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        dist_catch = np.where(catch, dist, -1)
        start_row, start_col = np.unravel_index(np.argmax(dist_catch), dist_catch.shape)
        
        lfp_coords = []
        if np.any(dist_catch > 0):
            dirmap = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1), 32:(-1,-1), 64:(-1,0), 128:(-1,1)}
            current_row, current_col = start_row, start_col
            while catch[current_row, current_col]:
                x_coord, y_coord = grid.affine * (current_col + 0.5, current_row + 0.5)
                lfp_coords.append((x_coord, y_coord))
                direction = flowdir[current_row, current_col]
                if direction == 0: break
                row_move, col_move = dirmap[direction]; current_row += row_move; current_col += col_move
        
        shapes_cuenca_clip = features.shapes(catch.astype(np.uint8), mask=catch, transform=out_transform)
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom_clip]}, crs=dem_crs)
        gdf_lfp = gpd.GeoDataFrame({'id': [1], 'geometry': [LineString(lfp_coords)] if lfp_coords else None}, crs=dem_crs)
        gdf_punto = gpd.GeoDataFrame({'id': [1], 'geometry': [Point(x_snap, y_snap)]}, crs=dem_crs)

        profile_elevations = [conditioned_dem[grid.nearest_cell(x, y, snap='center')] for x, y in lfp_coords]
        profile_distances = [0] + np.cumsum([np.sqrt((x2-x1)**2 + (y2-y1)**2) for (x1,y1), (x2,y2) in zip(lfp_coords, lfp_coords[1:])]).tolist()
        
        longitud_total_m = profile_distances[-1] if profile_distances else 0
        cota_ini, cota_fin = (profile_elevations[-1], profile_elevations[0]) if profile_elevations else (0,0)
        desnivel = abs(cota_fin - cota_ini)
        pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
        tc_h = (0.87 * (longitud_total_m**2 / (1000 * desnivel))**0.385) if desnivel > 0 else 0

        results.update({
            "success": True, "message": "Análisis principal completado.",
            "geometries_json": {
                "cuenca": gdf_cuenca.to_json(), "lfp": gdf_lfp.to_json(), "punto": gdf_punto.to_json()
            },
            "metrics": {
                "area_km2": cuenca_geom_clip.area / 1_000_000,
                "lfp_metrics": {"longitud_m": longitud_total_m, "pendiente_media": pendiente_media, "tc_h": tc_h}
            },
            "data_for_step2": {
                "conditioned_dem": conditioned_dem, "catch": catch, "out_transform": out_transform,
                "nodata": no_data_value, "grid_extent": grid.extent, "acc": acc, "flowdir": flowdir, "dem_crs": dem_crs
            }
        })
        return results
    except Exception as e:
        results['message'] = f"Error en el análisis principal: {e}\n{traceback.format_exc()}"
        return results
    finally:
        if dem_path_for_pysheds and os.path.exists(dem_path_for_pysheds):
            os.remove(dem_path_for_pysheds)

@st.cache_data(show_spinner="Generando red fluvial y gráficos...")
def paso2_generar_visuales(_data_from_step1, umbral_rio_export):
    results = {"success": False, "message": ""}
    try:
        conditioned_dem = _data_from_step1["conditioned_dem"]; catch = _data_from_step1["catch"]
        out_transform = _data_from_step1["out_transform"]; nodata = _data_from_step1["nodata"]
        grid_extent = _data_from_step1["grid_extent"]; acc = _data_from_step1["acc"]
        flowdir = _data_from_step1["flowdir"]; dem_crs = _data_from_step1["dem_crs"]

        flw = pyflwdir.from_dem(data=conditioned_dem, nodata=nodata, transform=out_transform, latlon=False)
        upa = flw.upstream_area(unit='cell')
        stream_mask_strahler = upa > umbral_rio_export
        strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=dem_crs)

        plots = {}
        dem_view = np.where(catch, conditioned_dem, np.nan)
        fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes[0, 0].imshow(np.where(catch, 1, np.nan), extent=grid_extent, cmap='Reds_r'); axes[0, 0].set_title("Extensión de la Cuenca")
        im_dem = axes[0, 1].imshow(dem_view, extent=grid_extent, cmap='terrain'); axes[0, 1].set_title("Elevación")
        fig1.colorbar(im_dem, ax=axes[0, 1], label='Elevación (m)', shrink=0.7)
        axes[1, 0].imshow(np.where(catch, flowdir, np.nan), extent=grid_extent, cmap='twilight'); axes[1, 0].set_title("Dirección de Flujo")
        im_acc = axes[1, 1].imshow(np.where(catch, acc, 0), extent=grid_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.max())); axes[1, 1].set_title("Acumulación de Flujo")
        fig1.colorbar(im_acc, ax=axes[1, 1], label='Nº celdas', shrink=0.7)
        plt.tight_layout(); plots['grafico_mosaico'] = fig_to_base64(fig1)

        results.update({
            "success": True, "message": "Visuales generados.",
            "plots": plots,
            "rios_strahler_json": gdf_streams_full.to_json()
        })
        return results
    except Exception as e:
        results['message'] = f"Error generando visuales: {e}\n{traceback.format_exc()}"
        return results

# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES (CON CORRECCIÓN EN EXPORTACIÓN)
# ==============================================================================
@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    try:
        local_zip_path = get_local_path_from_url(HOJAS_MTN25_PATH)
        if not local_zip_path:
            st.error("No se pudo obtener el archivo de hojas del MTN25."); return None
        hojas_gdf = gpd.read_file(local_zip_path)
        cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
        buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs(TARGET_CRS_DOWNLOAD).buffer(BUFFER_METROS), crs=TARGET_CRS_DOWNLOAD)
        
        with rasterio.open(DEM_NACIONAL_PATH) as src:
            geom_recorte_gdf = buffer_gdf.to_crs(src.crs)
            dem_recortado, trans_recortado = mask(dataset=src, shapes=geom_recorte_gdf.geometry, crop=True, nodata=src.nodata or -32768)
            meta = src.meta.copy()
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado, "compress": "NONE"})
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst:
                    dst.write(dem_recortado)
                buffer.seek(0)
                dem_bytes = buffer.read()
        
        shp_zip_bytes = export_gdf_to_zip(buffer_gdf, "contorno_cuenca_buffer")
        return { "cuenca_gdf": cuenca_gdf, "buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "dem_bytes": dem_bytes }
    except Exception as e:
        st.error(f"Error inesperado procesando la cuenca: {e}"); st.exception(e); return None

# --- ¡¡¡FUNCIÓN DE EXPORTACIÓN CORREGIDA!!! ---
def export_gdf_to_zip(gdf, filename_base, target_crs=TARGET_CRS_DOWNLOAD):
    """
    Exporta un GeoDataFrame a un archivo ZIP de Shapefile, asegurando el CRS de salida.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        # Asegura que el GDF de salida esté en el CRS deseado
        gdf_out = gdf.to_crs(target_crs)
        
        shapefile_path = os.path.join(tmpdir, f"{filename_base}.shp")
        gdf_out.to_file(shapefile_path, driver='ESRI Shapefile', encoding='utf-8')
        
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    if file.startswith(filename_base):
                        zf.write(os.path.join(root, file), arcname=file)
        zip_io.seek(0)
        return zip_io

@st.cache_data(show_spinner="Pre-calculando referencia de cauces...")
def precalcular_acumulacion(_dem_bytes):
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_array = src.read(1).astype(np.float32)
                nodata = src.meta.get('nodata')
                if nodata is not None: dem_array[dem_array == nodata] = np.nan
                transform = src.transform
        
        flwdir = pyflwdir.from_dem(data=dem_array, transform=transform, nodata=np.nan)
        acc = flwdir.upstream_area(unit='cell')
        acc_limpio = np.nan_to_num(acc, nan=0.0)
        power_factor = 0.2
        scaled_acc_for_viz = acc_limpio ** power_factor
        min_val, max_val = np.nanmin(scaled_acc_for_viz), np.nanmax(scaled_acc_for_viz)
        if max_val == min_val: img_acc = np.zeros_like(scaled_acc_for_viz, dtype=np.uint8)
        else:
            scaled_acc_nan_as_zero = np.nan_to_num(scaled_acc_for_viz, nan=min_val)
            img_acc = (255 * (scaled_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        return img_acc
    except Exception as e:
        st.error(f"Error en pre-cálculo de acumulación: {e}"); return None

# ==============================================================================
# SECCIÓN 5: FUNCIÓN PRINCIPAL DEL FRONTEND (RENDERIZADO FINAL)
# ==============================================================================

def render_dem25_tab():
    st.header("Generador y Analizador de MDT25")
    st.info("Esta herramienta permite delinear una cuenca y analizar su morfometría a partir de un punto de desagüe seleccionado.")

    if not st.session_state.get('basin_geojson'):
        st.warning("⬅️ Por favor, primero calcule una cuenca en la Pestaña 1 para definir un área de interés."); st.stop()

    if st.button("🗺️ Cargar Área de Análisis (Cuenca + Buffer)", use_container_width=True):
        with st.spinner("Procesando recorte del DEM..."):
            results = procesar_datos_cuenca(st.session_state.basin_geojson)
        if results:
            st.session_state.cuenca_results = results
            st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes'])
            st.session_state.pop('resultados_paso1', None); st.session_state.pop('resultados_paso2', None)
            st.session_state.pop('outlet_coords', None); st.session_state.show_dem25_content = True
            st.rerun()
        else:
            st.error("No se pudo procesar el área de la cuenca."); st.session_state.show_dem25_content = False

    if not st.session_state.get('show_dem25_content'):
        st.info("Haga clic en el botón de arriba para empezar."); return

    st.divider()
    st.header("Análisis Hidrológico Interactivo")
    st.subheader("Paso 1: Seleccione un punto de salida (outlet)")
    
    cuenca_results = st.session_state.cuenca_results
    map_select = folium.Map(tiles="CartoDB positron")
    buffer_layer = folium.GeoJson(cuenca_results['buffer_gdf'], name="Buffer (Área de Análisis)", style_function=lambda x: {'color': 'tomato', 'fillOpacity': 0.1}).add_to(map_select)
    map_select.fit_bounds(buffer_layer.get_bounds())
    if st.session_state.get('precalculated_acc') is not None:
        bounds = cuenca_results['buffer_gdf'].total_bounds
        img = Image.fromarray(st.session_state.precalculated_acc)
        buffered = io.BytesIO(); img.save(buffered, format="PNG"); img_str = base64.b64encode(buffered.getvalue()).decode()
        folium.raster_layers.ImageOverlay(image=f"data:image/png;base64,{img_str}", bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, name='Referencia de Cauces').add_to(map_select)
    if st.session_state.get('outlet_coords'):
        folium.Marker([st.session_state.outlet_coords['lat'], st.session_state.outlet_coords['lng']], popup="Punto de Salida", icon=folium.Icon(color='orange')).add_to(map_select)
    
    map_output_select = st_folium(map_select, key="map_select", use_container_width=True, height=500, returned_objects=['last_clicked'])

    if map_output_select.get("last_clicked") and st.session_state.get('outlet_coords') != map_output_select["last_clicked"]:
        st.session_state.outlet_coords = map_output_select["last_clicked"]
        st.session_state.pop('resultados_paso1', None); st.session_state.pop('resultados_paso2', None)
        st.rerun()

    st.subheader("Paso 2: Ejecute el análisis")
    umbral_celdas = st.slider(label="Umbral de celdas para definir cauces", min_value=10, max_value=10000, value=1600, step=10)
    
    b_col1, b_col2 = st.columns(2)
    with b_col1:
        if st.button("1. Delinear Cuenca y Calcular LFP", use_container_width=True, disabled=not st.session_state.get('outlet_coords')):
            results = paso1_delinear_y_calcular_lfp(st.session_state.cuenca_results['dem_bytes'], st.session_state.outlet_coords, umbral_celdas)
            if results['success']:
                st.session_state.resultados_paso1 = results
                st.session_state.pop('resultados_paso2', None)
                st.success("Paso 1 completado."); st.rerun()
            else: st.error("Falló el Paso 1."); st.code(results['message'])
    with b_col2:
        if st.button("2. Generar Red Fluvial y Gráficos", use_container_width=True, disabled=not st.session_state.get('resultados_paso1')):
            results = paso2_generar_visuales(st.session_state.resultados_paso1['data_for_step2'], umbral_celdas)
            if results['success']:
                st.session_state.resultados_paso2 = results
                st.success("Paso 2 completado."); st.rerun()
            else: st.error("Falló el Paso 2."); st.code(results['message'])

    if st.session_state.get('resultados_paso1'):
        st.divider()
        st.header("Resultados del Análisis")
        
        resultados_paso1 = st.session_state.resultados_paso1
        # Leer los GDFs desde el GeoJSON almacenado (que está en UTM)
        gdf_cuenca_utm = gpd.read_file(resultados_paso1["geometries_json"]["cuenca"])
        gdf_lfp_utm = gpd.read_file(resultados_paso1["geometries_json"]["lfp"])
        gdf_punto_utm = gpd.read_file(resultados_paso1["geometries_json"]["punto"])
        
        m_results = folium.Map(tiles="CartoDB positron")
        # Para el mapa, transformar a WGS84
        folium.GeoJson(gdf_cuenca_utm.to_crs("EPSG:4326"), name="Cuenca Delineada", style_function=lambda x: {'color': '#FF0000', 'weight': 2, 'fillOpacity': 0.2}).add_to(m_results)
        folium.GeoJson(gdf_lfp_utm.to_crs("EPSG:4326"), name="LFP", style_function=lambda x: {'color': '#FFFF00', 'weight': 4}).add_to(m_results)
        
        if st.session_state.get('resultados_paso2'):
            resultados_paso2 = st.session_state.resultados_paso2
            gdf_rios_utm = gpd.read_file(resultados_paso2["rios_strahler_json"])
            gdf_rios_recortado = gpd.clip(gdf_rios_utm, gdf_cuenca_utm)
            if not gdf_rios_recortado.empty:
                folium.GeoJson(gdf_rios_recortado.to_crs("EPSG:4326"), name="Red Fluvial", style_function=lambda f: {'color': 'blue', 'weight': f['properties']['strord'] / 2 + 1}).add_to(m_results)

        m_results.fit_bounds(gdf_cuenca_utm.to_crs("EPSG:4326").total_bounds[[1, 0, 3, 2]].tolist()); folium.LayerControl().add_to(m_results)
        st_folium(m_results, key="results_map", use_container_width=True, height=500)

        st.subheader("Métricas y Descargas")
        m_col1, m_col2 = st.columns(2)
        with m_col1:
            st.metric("Área de la Cuenca", f"{resultados_paso1['metrics']['area_km2']:.4f} km²")
            metrics_lfp = resultados_paso1['metrics']['lfp_metrics']
            st.metric("Longitud LFP", f"{metrics_lfp.get('longitud_m', 0):.2f} m")
            st.metric("Pendiente Media LFP", f"{metrics_lfp.get('pendiente_media', 0):.4f} m/m")
        with m_col2:
            # Para descargar, usar los GDFs originales en UTM
            st.download_button("📥 Cuenca (.zip)", export_gdf_to_zip(gdf_cuenca_utm, "cuenca_delineada"), "cuenca_delineada.zip", use_container_width=True)
            st.download_button("📥 LFP (.zip)", export_gdf_to_zip(gdf_lfp_utm, "lfp"), "lfp.zip", use_container_width=True)
            st.download_button("📥 Punto de Salida (.zip)", export_gdf_to_zip(gdf_punto_utm, "punto_salida"), "punto_salida.zip", use_container_width=True)
            if st.session_state.get('resultados_paso2'):
                st.download_button("📥 Red Fluvial (.zip)", export_gdf_to_zip(gdf_rios_utm, "red_fluvial_strahler"), "red_fluvial_strahler.zip", use_container_width=True)

        if st.session_state.get('resultados_paso2'):
            st.subheader("Gráficos de Análisis")
            plots = st.session_state.resultados_paso2["plots"]
            st.image(io.BytesIO(base64.b64decode(plots['grafico_mosaico'])), caption="Características de la Cuenca", use_container_width=True)