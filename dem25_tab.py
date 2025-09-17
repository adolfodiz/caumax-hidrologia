# dem25_tab.py (Versión Definitiva con PyFlwdir y Correcciones)

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
# Se elimina PySheds para evitar conflictos. Todo se hará con PyFlwdir y Rasterio.
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
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO (REESCRITA CON PYFLWDIR)
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- FUNCIÓN DE ANÁLISIS UNIFICADA Y ROBUSTA ---
@st.cache_data(show_spinner="Ejecutando análisis hidrológico completo con PyFlwdir...")
def analisis_hidrologico_completo_pyflwdir(_dem_bytes, outlet_coords_wgs84, umbral_celdas):
    results = {"success": False, "message": ""}
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_array = src.read(1)
                dem_crs = src.crs
                transform = src.transform
                nodata = src.nodata or -32768
                
                # Cargar DEM en PyFlwdir
                flw = pyflwdir.from_dem(data=dem_array, transform=transform, nodata=nodata, latlon=False)
                
                # Correcciones hidrológicas
                dem_filled = flw.fill_depressions(dem=dem_array)
                flw = flw.flwdir(dem=dem_filled, out_dtype=np.uint8)
                
                # Acumulación de flujo
                upa = flw.upstream_area(unit='cell')
                
                # Transformar punto de salida y ajustarlo (snap)
                transformer = Transformer.from_crs("EPSG:4628", dem_crs, always_xy=True)
                x_dem, y_dem = transformer.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
                
                # Snap al cauce más cercano con acumulación mayor al umbral
                xy_snap = flw.snap((x_dem, y_dem), mask=upa > umbral_celdas, max_dist=1000)
                
                # Delinear cuenca
                catchment_mask = flw.catchment(xy=xy_snap)
                
                # Trazar el río principal (LFP)
                river_geom = flw.main_river(xy=xy_snap)
                gdf_lfp = gpd.GeoDataFrame(geometry=[river_geom], crs=dem_crs)
                
                # Extraer geometría de la cuenca
                shapes = features.shapes(catchment_mask.astype(np.uint8), mask=catchment_mask, transform=transform)
                cuenca_geom = [Polygon(s['coordinates'][0]) for s, v in shapes if v == 1][0]
                gdf_cuenca = gpd.GeoDataFrame(geometry=[cuenca_geom], crs=dem_crs)
                
                # Red fluvial de Strahler
                stream_mask = upa > umbral_celdas
                strord = flw.stream_order(mask=stream_mask, type='strahler')
                streams = flw.streams(mask=stream_mask, strord=strord)
                gdf_rios = gpd.GeoDataFrame.from_features(streams, crs=dem_crs)
                
                # Métricas del LFP
                lfp_coords = list(river_geom.coords)
                profile_elevations = [dem_filled[flw.xy_to_idx(xy)] for xy in lfp_coords]
                profile_distances = [0] + np.cumsum([np.sqrt((x2-x1)**2 + (y2-y1)**2) for (x1,y1), (x2,y2) in zip(lfp_coords, lfp_coords[1:])]).tolist()
                
                longitud_total_m = profile_distances[-1] if profile_distances else 0
                cota_ini, cota_fin = (profile_elevations[-1], profile_elevations[0]) if profile_elevations else (0,0)
                desnivel = abs(cota_fin - cota_ini)
                pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
                
                # Gráfico Mosaico
                fig, axes = plt.subplots(1, 2, figsize=(12, 6))
                ext = flw.extent
                dem_view = np.where(catchment_mask, dem_filled, np.nan)
                im_dem = axes[0].imshow(dem_view, extent=ext, cmap='terrain'); axes[0].set_title("Elevación en la Cuenca")
                fig.colorbar(im_dem, ax=axes[0], label='Elevación (m)', shrink=0.7)
                im_acc = axes[1].imshow(np.where(catchment_mask, upa, 0), extent=ext, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=upa.max())); axes[1].set_title("Acumulación de Flujo")
                fig.colorbar(im_acc, ax=axes[1], label='Nº celdas', shrink=0.7)
                plt.tight_layout()
                plot_mosaico_b64 = fig_to_base64(fig)

        results.update({
            "success": True, "message": "Análisis completado con éxito.",
            "geometries_json": {
                "cuenca": gdf_cuenca.to_json(), "lfp": gdf_lfp.to_json(),
                "punto": gpd.GeoDataFrame(geometry=[Point(xy_snap)], crs=dem_crs).to_json(),
                "rios": gdf_rios.to_json()
            },
            "metrics": {
                "area_km2": cuenca_geom.area / 1_000_000,
                "lfp_metrics": {"longitud_m": longitud_total_m, "pendiente_media": pendiente_media}
            },
            "plots": {"mosaico": plot_mosaico_b64}
        })
        return results

    except Exception as e:
        results['message'] = f"Error en el análisis con PyFlwdir: {e}\n{traceback.format_exc()}"
        return results

# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES
# ==============================================================================
@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    try:
        cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
        buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs(TARGET_CRS_DOWNLOAD).buffer(BUFFER_METROS), crs=TARGET_CRS_DOWNLOAD)
        with rasterio.open(DEM_NACIONAL_PATH) as src:
            dem_recortado, _ = mask(dataset=src, shapes=buffer_gdf.to_crs(src.crs).geometry, crop=True, nodata=src.nodata or -32768)
            meta = src.meta.copy()
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": _, "compress": "NONE"})
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst:
                    dst.write(dem_recortado)
                buffer.seek(0)
                dem_bytes = buffer.read()
        return {"buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "dem_bytes": dem_bytes}
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
        acc_limpio = np.nan_to_num(acc, nan=0.0)
        scaled_acc = acc_limpio ** 0.2
        min_v, max_v = np.nanmin(scaled_acc), np.nanmax(scaled_acc)
        if max_v == min_v: return np.zeros_like(scaled_acc, dtype=np.uint8)
        img_acc = (255 * (np.nan_to_num(scaled_acc, nan=min_v) - min_v) / (max_v - min_v)).astype(np.uint8)
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

    st.divider()
    st.header("Análisis Hidrológico Interactivo")
    st.subheader("Paso 1: Seleccione un punto de salida (outlet)")
    
    cuenca_results = st.session_state.cuenca_results
    map_select = folium.Map(tiles="CartoDB positron")
    buffer_layer = folium.GeoJson(cuenca_results['buffer_gdf'], name="Área de Análisis", style_function=lambda x: {'color': 'tomato', 'fillOpacity': 0.1}).add_to(map_select)
    map_select.fit_bounds(buffer_layer.get_bounds())
    
    # RESTAURADO: Punto rojo de la Pestaña 1
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
        results = analisis_hidrologico_completo_pyflwdir(st.session_state.cuenca_results['dem_bytes'], st.session_state.outlet_coords, umbral_celdas)
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
            st.metric("Longitud LFP", f"{res['metrics']['lfp_metrics'].get('longitud_m', 0):.2f} m")
        with m_col2:
            st.download_button("📥 Cuenca (.zip)", export_gdf_to_zip(gdf_cuenca, "cuenca"), "cuenca.zip", use_container_width=True)
            st.download_button("📥 LFP (.zip)", export_gdf_to_zip(gdf_lfp, "lfp"), "lfp.zip", use_container_width=True)
            st.download_button("📥 Punto de Salida (.zip)", export_gdf_to_zip(gdf_punto, "punto"), "punto.zip", use_container_width=True)
            st.download_button("📥 Red Fluvial (.zip)", export_gdf_to_zip(gdf_rios, "rios"), "rios.zip", use_container_width=True)

        st.subheader("Gráficos de Análisis")
        st.image(io.BytesIO(base64.b64decode(res['plots']['mosaico'])), caption="Características de la Cuenca", use_container_width=True)