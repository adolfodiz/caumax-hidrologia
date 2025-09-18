# dem25_tab.py (Versión adaptada para COGs grandes en Pestaña 2)

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
from folium.plugins import Draw
from shapely.geometry import shape, Point, LineString, Polygon
from pyproj import CRS, Transformer
import base64
from PIL import Image
import locale # Asegúrate de que esta línea está al principio del archivo
import platform # Y también esta
import sys # Asegúrate de que 'import sys' está al principio de tu script
# --- Imports específicos del análisis hidrológico (traídos de delinear_cuenca.py) ---
import traceback
import matplotlib.pyplot as plt
import matplotlib.colors as colors
from matplotlib.lines import Line2D
import numpy as np
from pysheds.grid import Grid
import pyflwdir
from rasterio.mask import mask
from rasterio import features
import rasterio
from core_logic.gis_utils import get_local_path_from_url # Necesitamos esta para los GPKG y ZIPs

import branca.colormap as cm
# ==============================================================================
# SECCIÓN 2: CONSTANTES Y CONFIGURACIÓN
# ==============================================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HOJAS_MTN25_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MTN25_ACTUAL_ETRS89_Peninsula_Baleares_Canarias.zip"
# --- ¡CRÍTICO! Apunta al COG grande de 700MB ---
DEM_NACIONAL_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MDT25_peninsula_UTM30N_COG.tif"
BUFFER_METROS = 5000
LIMITE_AREA_KM2 = 15000
AREA_PROCESSING_LIMIT_KM2 = 50000 # Límite para evitar procesar cuencas gigantes en Pestaña 2
CELL_AREA_M2 = 625 # Área de una celda de 25x25m
CELL_AREA_KM2 = CELL_AREA_M2 / 1_000_000 # 0.000625 km²

# dem25_tab.py

# ... (imports y constantes sin cambios) ...

# ==============================================================================
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO (MODIFICADA)
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

@st.cache_data(show_spinner="Paso 1: Delineando cuenca con PySheds...")
def delinear_cuenca_desde_punto(_dem_bytes, outlet_coords_wgs84, umbral_rio_export):
    results = {"success": False, "message": ""}
    dem_path_for_pysheds = None # Para asegurar la limpieza
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_crs = src.crs
                out_transform = src.transform
                no_data_value = src.nodata or -32768

                # Guardar el DEM en un archivo temporal para PySheds
                with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_dem_pysheds:
                    tmp_dem_pysheds.write(_dem_bytes)
                    dem_path_for_pysheds = tmp_dem_pysheds.name

        grid = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        dem = grid.read_raster(dem_path_for_pysheds, nodata=no_data_value)

        transformer_wgs84_to_dem_crs = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
        x_dem_crs, y_dem_crs = transformer_wgs84_to_dem_crs.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])

        # Asegurarse de que el punto de salida esté dentro de los límites del DEM
        if not (grid.extent[0] <= x_dem_crs <= grid.extent[1] and grid.extent[2] <= y_dem_crs <= grid.extent[3]):
            results['message'] = "El punto de desagüe seleccionado está fuera del DEM recortado. Por favor, seleccione un punto dentro del área de análisis."
            return results

        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)

        # Re-snap al DEM recortado
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_rio_export, (x_dem_crs, y_dem_crs))
        
        # Verificar si el punto de snap está fuera del DEM recortado
        if not (grid.extent[0] <= x_snap <= grid.extent[1] and grid.extent[2] <= y_snap <= grid.extent[3]):
            results['message'] = "El punto de desagüe se encuentra demasiado cerca del borde del DEM recortado para el análisis. Intente un punto más central."
            return results

        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")

        shapes_cuenca_clip = features.shapes(catch.view().astype(np.uint8), mask=catch.view(), transform=out_transform)
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom_clip]}, crs=dem_crs)

        results.update({
            "success": True, "message": "Cuenca delineada con éxito.",
            "pysheds_data": {
                # Solo guardamos el DEM original y la metadata esencial
                "dem_bytes": _dem_bytes,
                "x_snap": x_snap,
                "y_snap": y_snap,
                "out_transform": out_transform,
                "dem_crs": dem_crs,
                "no_data_value": no_data_value
            },
            "downloads": {
                "cuenca": gdf_cuenca.to_json(),
                "punto_salida": gpd.GeoDataFrame({'id': [1], 'geometry': [Point(x_snap, y_snap)]}, crs=dem_crs).to_json()
            }
        })
        return results
    except Exception as e:
        results['message'] = f"Error en la delineación: {e}\n{traceback.format_exc()}"
        return results
    finally:
        if dem_path_for_pysheds and os.path.exists(dem_path_for_pysheds):
            os.remove(dem_path_for_pysheds)

@st.cache_data(show_spinner="Paso 2: Calculando morfometría y generando gráficos...")
def calcular_morfometria_cuenca(_pysheds_data, umbral_rio_export):
    results = {"success": False, "message": ""}
    dem_path_for_pysheds = None # Para asegurar la limpieza
    try:
        # Recuperar datos esenciales
        dem_bytes = _pysheds_data["dem_bytes"]
        x_snap, y_snap = _pysheds_data["x_snap"], _pysheds_data["y_snap"]
        out_transform = _pysheds_data["out_transform"]
        dem_crs = _pysheds_data["dem_crs"]
        no_data_value = _pysheds_data["no_data_value"]

        # Reconstruir el Grid de PySheds a partir del DEM original
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_dem_pysheds:
            tmp_dem_pysheds.write(dem_bytes)
            dem_path_for_pysheds = tmp_dem_pysheds.name

        grid = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        dem = grid.read_raster(dem_path_for_pysheds, nodata=no_data_value) # Obtener el objeto Raster del DEM

        # Volver a ejecutar los pasos de preprocesamiento para obtener objetos Raster válidos
        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")

        # CÁLCULOS DEL LONGEST FLOW PATH (LFP)
        dist = grid._d8_flow_distance(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        dist_catch = np.where(catch.view(), dist.view(), -1) # Usar .view() para los arrays NumPy
        
        if np.all(dist_catch == -1):
            results['message'] = "No se pudo calcular el LFP. El punto de desagüe podría estar en un área sin flujo acumulado o fuera de la cuenca."
            return results

        start_row, start_col = np.unravel_index(np.argmax(dist_catch), dist_catch.shape)
        dirmap = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1), 32:(-1,-1), 64:(-1,0), 128:(-1,1)}
        lfp_coords = []
        current_row, current_col = start_row, start_col
        
        while True:
            x_coord, y_coord = out_transform * (current_col + 0.5, current_row + 0.5)
            lfp_coords.append((x_coord, y_coord))
            
            if not (0 <= current_row < flowdir.shape[0] and 0 <= current_col < flowdir.shape[1]):
                break
            
            if not catch.view()[current_row, current_col]:
                break
            
            direction = flowdir.view()[current_row, current_col]
            if direction == 0:
                break
            
            row_move, col_move = dirmap[direction]
            current_row += row_move
            current_col += col_move

        # PERFIL LONGITUDINAL Y MÉTRICAS LFP
        inv_transform = ~out_transform
        profile_elevations, valid_lfp_coords = [], []
        for x_c, y_c in lfp_coords:
            try:
                col, row = inv_transform * (x_c, y_c)
                if 0 <= int(row) < conditioned_dem.shape[0] and 0 <= int(col) < conditioned_dem.shape[1]:
                    elevation = conditioned_dem.view()[int(row), int(col)]
                    profile_elevations.append(elevation)
                    valid_lfp_coords.append((x_c, y_c))
            except IndexError:
                continue

        profile_distances = [0]
        for i in range(1, len(valid_lfp_coords)):
            x1, y1 = valid_lfp_coords[i-1]; x2, y2 = valid_lfp_coords[i]
            profile_distances.append(profile_distances[-1] + np.sqrt((x2 - x1)**2 + (y2 - y1)**2))
        
        longitud_total_m = profile_distances[-1] if profile_distances else 0
        cota_ini = profile_elevations[-1] if profile_elevations else 0
        cota_fin = profile_elevations[0] if profile_elevations else 0
        desnivel = abs(cota_fin - cota_ini)
        pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
        tc_h = (0.87 * (longitud_total_m**2 / (1000 * desnivel))**0.385) if desnivel > 0 else 0

        # INICIALIZACIÓN DE PYFLWDIR Y CÁLCULO DE ORDEN DE STRAHLER
        flw = pyflwdir.from_dem(data=conditioned_dem.view(), nodata=no_data_value, transform=out_transform, latlon=False)
        upa = flw.upstream_area(unit='cell')
        stream_mask_strahler = upa > umbral_rio_export
        strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=dem_crs)
        
        # HISTOGRAMA Y CURVA HIPSOMÉTRICA
        elevaciones_cuenca = conditioned_dem.view()[catch.view()]
        if elevaciones_cuenca.size == 0:
            results['message'] = "No hay datos de elevación válidos en la cuenca para el análisis hipsométrico."
            return results
        
        elev_sorted = np.sort(elevaciones_cuenca)[::-1]
        cell_area = abs(out_transform.a * out_transform.e)
        area_acumulada = np.arange(1, len(elev_sorted) + 1) * cell_area
        area_normalizada = area_acumulada / area_acumulada.max()
        elev_normalizada = (elev_sorted - elev_sorted.min()) / (elev_sorted.max() - elev_sorted.min())
        integral_hipsometrica = abs(np.trapz(area_normalizada, x=elev_normalizada))

        # --- INICIO: GENERACIÓN DE GRÁFICOS (SOLO LOS REQUERIDOS) ---
        plots = {}
        
        # GRÁFICO 4: PERFIL LONGITUDINAL DEL LFP
        fig4, ax = plt.subplots(figsize=(12, 6))
        ax.plot(np.array(profile_distances) / 1000, profile_elevations, color='darkblue')
        ax.fill_between(np.array(profile_distances) / 1000, profile_elevations, alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del LFP'); ax.set_xlabel('Distancia (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True)
        plots['grafico_4_perfil_lfp'] = fig_to_base64(fig4)

        # GRÁFICOS 5 y 6: HISTOGRAMA Y CURVA HIPSOMÉTRICA
        fig56, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        ax1.hist(elevaciones_cuenca, bins=50, color='skyblue', edgecolor='black')
        ax1.set_title('Distribución de Elevaciones'); ax1.set_xlabel('Elevación (m)'); ax1.set_ylabel('Frecuencia')
        
        ax2.plot(area_normalizada, elev_sorted, color='red', linewidth=2, label='Curva Hipsométrica')
        ax2.fill_between(area_normalizada, elev_sorted, elev_sorted.min(), color='red', alpha=0.2)
        ax2.plot([0, 1], [elev_sorted.max(), elev_sorted.min()], color='gray', linestyle='--', linewidth=2, label='Referencia lineal (HI=0.5)')
        ax2.text(0.05, 0.1, f'Integral Hipsométrica: {integral_hipsometrica:.3f}', transform=ax2.transAxes, fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Curva Hipsométrica'); ax2.set_xlabel('Fracción de área (a/A)'); ax2.set_ylabel('Elevación (m)'); ax2.legend(); ax2.set_xlim(0, 1)
        plots['grafico_5_6_histo_hipso'] = fig_to_base64(fig56)
        # --- FIN: GENERACIÓN DE GRÁFICOS ---

        results.update({
            "success": True, "message": "Morfometría calculada y gráficos generados con éxito.",
            "morphometry_data": {
                "lfp_profile_data": {"distancia_m": profile_distances, "elevacion_m": profile_elevations},
                "lfp_metrics": {"cota_ini_m": cota_ini, "cota_fin_m": cota_fin, "longitud_m": longitud_total_m, "pendiente_media": pendiente_media, "tc_h": tc_h, "tc_min": tc_h * 60},
                "hypsometric_data": {"area_normalizada": area_normalizada.tolist(), "elevacion": elev_sorted.tolist(), "integral_hipsometrica": integral_hipsometrica},
                "lfp_coords": lfp_coords,
                "gdf_streams_full": gdf_streams_full,
                "upa_pyflwdir_array": upa.view()
            },
            "downloads": {
                "lfp": gpd.GeoDataFrame({'id': [1], 'geometry': [LineString(lfp_coords)]}, crs=dem_crs).to_json(),
                "rios_strahler": gdf_streams_full.to_json()
            },
            "plots": plots # Los gráficos ahora se devuelven aquí
        })
        return results
    except Exception as e:
        results['message'] = f"Error en morfometría: {e}\n{traceback.format_exc()}"
        return results
    finally:
        if dem_path_for_pysheds and os.path.exists(dem_path_for_pysheds):
            os.remove(dem_path_for_pysheds)
            
            
@st.cache_data(show_spinner="Paso 3: Generando gráficos y análisis finales...")
def generar_graficos_y_analisis(_pysheds_data, _morphometry_data, umbral_rio_export):
    results = {"success": False, "message": ""}
    dem_path_for_pysheds = None # Para asegurar la limpieza
    try:
        # Recuperar datos esenciales
        dem_bytes = _pysheds_data["dem_bytes"]
        x_snap, y_snap = _pysheds_data["x_snap"], _pysheds_data["y_snap"] # Necesario para catchment
        out_transform = _pysheds_data["out_transform"]
        dem_crs = _pysheds_data["dem_crs"]
        no_data_value = _pysheds_data["no_data_value"]

        # Reconstruir el Grid de PySheds a partir del DEM original
        with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_dem_pysheds:
            tmp_dem_pysheds.write(dem_bytes)
            dem_path_for_pysheds = tmp_dem_pysheds.name

        grid = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        dem = grid.read_raster(dem_path_for_pysheds, nodata=no_data_value) # Obtener el objeto Raster del DEM

        # Volver a ejecutar los pasos de preprocesamiento para obtener objetos Raster válidos
        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate") # Re-delinear la cuenca

        lfp_profile_data = _morphometry_data["lfp_profile_data"]
        hypsometric_data = _morphometry_data["hypsometric_data"]
        lfp_coords = _morphometry_data["lfp_coords"]
        gdf_streams_full = _morphometry_data["gdf_streams_full"]
        upa_pyflwdir_array = _morphometry_data["upa_pyflwdir_array"] # UPA de pyflwdir (array NumPy)

        plots = {}
        
        # GRÁFICO 1: MOSAICO DE CARACTERÍSTICAS
        plot_extent = grid.extent
        fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
        
        # Extensión de la Cuenca
        axes[0, 0].imshow(catch.view(), extent=plot_extent, cmap='Reds_r')
        axes[0, 0].set_title("Extensión de la Cuenca")
        num_celdas_cuenca = np.sum(catch.view())
        area_pixel_m2 = abs(grid.affine.a * grid.affine.e)
        area_cuenca_km2 = (num_celdas_cuenca * area_pixel_m2) / 1_000_000
        area_texto = f'{area_cuenca_km2:.1f} km²'
        centro_x = (plot_extent[0] + plot_extent[1]) / 2
        centro_y = (plot_extent[2] + plot_extent[3]) / 2
        axes[0, 0].text(centro_x, centro_y, area_texto, ha='center', va='center', color='white', fontsize=12, fontweight='bold')
        
        # Elevación
        im_dem = axes[0, 1].imshow(conditioned_dem.view(), extent=plot_extent, cmap='terrain')
        axes[0, 1].set_title("Elevación")
        fig1.colorbar(im_dem, ax=axes[0, 1], label='Elevación (m)', shrink=0.7)
        
        # Dirección de Flujo
        im_fdir = axes[1, 0].imshow(flowdir.view(), extent=plot_extent, cmap='twilight')
        axes[1, 0].set_title("Dirección de Flujo")
        
        # Acumulación de Flujo
        im_acc = axes[1, 1].imshow(acc.view(), extent=plot_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.view().max()))
        axes[1, 1].set_title("Acumulación de Flujo")
        fig1.colorbar(im_acc, ax=axes[1, 1], label='Nº celdas', shrink=0.7)
        
        for ax in axes.flat: ax.tick_params(axis='both', labelsize=6)
        plt.suptitle("Características de la Cuenca Delineada", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plots['grafico_1_mosaico'] = fig_to_base64(fig1)

        # GRÁFICO 3/7 UNIFICADO: LFP y Red Fluvial de Strahler
        # Recortar la red fluvial a la cuenca delineada
        shapes_cuenca_clip = features.shapes(catch.view().astype(np.uint8), mask=catch.view(), transform=out_transform)
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca_clip = gpd.GeoDataFrame(geometry=[cuenca_geom_clip], crs=dem_crs)
        gdf_streams_recortado = gpd.clip(gdf_streams_full, gdf_cuenca_clip)
        
        dem_cuenca_recortada = conditioned_dem.view()
        dem_cuenca_recortada = np.where(catch.view(), dem_cuenca_recortada, np.nan) # Enmascarar fuera de la cuenca
        
        fig37, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1 = axes[0]
        im1 = ax1.imshow(dem_cuenca_recortada, extent=plot_extent, cmap='terrain', zorder=1)
        fig37.colorbar(im1, ax=ax1, label='Elevación (m)', shrink=0.6)
        x_coords, y_coords = zip(*lfp_coords)
        ax1.plot(x_coords, y_coords, color='red', linewidth=2, label='Longest Flow Path', zorder=2)
        ax1.set_title('Camino de Flujo Más Largo (LFP)'); ax1.legend(); ax1.grid(True, linestyle='--', alpha=0.6)
        ax2 = axes[1]
        ax2.imshow(dem_cuenca_recortada, extent=plot_extent, cmap='Greys_r', alpha=0.8, zorder=1)
        gdf_streams_recortado_clean = gdf_streams_recortado[gdf_streams_recortado.geom_type.isin(["LineString", "MultiLineString"])]
        if not gdf_streams_recortado_clean.empty:
            gdf_streams_recortado_clean['strord'] = pd.to_numeric(gdf_streams_recortado_clean['strord'], errors='coerce')
            gdf_streams_recortado_clean = gdf_streams_recortado_clean.dropna(subset=['strord'])
            if not gdf_streams_recortado_clean.empty:
                gdf_streams_recortado_clean.plot(ax=ax2, column='strord', cmap='Blues', zorder=2, legend=True, categorical=True, legend_kwds={'title': "Orden de Strahler", 'loc': 'upper right'})
            else:
                ax2.text(0.5, 0.5, 'No se encontraron ríos\ncon el umbral actual', horizontalalignment='center', verticalalignment='center', transform=ax2.transAxes, bbox=dict(facecolor='white', alpha=0.8))
        else:
            ax2.text(0.5, 0.5, 'No se encontraron ríos\ncon el umbral actual', horizontalalignment='center', verticalalignment='center', transform=ax2.transAxes, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Red Fluvial por Orden de Strahler')
        plt.suptitle("Análisis Morfométrico de la Cuenca", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plots['grafico_3_7_lfp_strahler'] = fig_to_base64(fig37)

        # GRÁFICO 4: PERFIL LONGITUDINAL Y MÉTRICAS LFP
        fig4, ax = plt.subplots(figsize=(12, 6))
        ax.plot(np.array(lfp_profile_data["distancia_m"]) / 1000, lfp_profile_data["elevacion_m"], color='darkblue')
        ax.fill_between(np.array(lfp_profile_data["distancia_m"]) / 1000, lfp_profile_data["elevacion_m"], alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del LFP'); ax.set_xlabel('Distancia (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True)
        plots['grafico_4_perfil_lfp'] = fig_to_base64(fig4)

        # GRÁFICOS 5 y 6: HISTOGRAMA Y CURVA HIPSOMÉTRICA
        elevaciones_cuenca = conditioned_dem.view()[catch.view()]
        fig56, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        ax1.hist(elevaciones_cuenca, bins=50, color='skyblue', edgecolor='black')
        ax1.set_title('Distribución de Elevaciones'); ax1.set_xlabel('Elevación (m)'); ax1.set_ylabel('Frecuencia')
        
        area_normalizada = hypsometric_data["area_normalizada"]
        elev_sorted = hypsometric_data["elevacion"]
        integral_hipsometrica = hypsometric_data["integral_hipsometrica"]
        elev_min, elev_max = np.min(elev_sorted), np.max(elev_sorted)

        ax2.plot(area_normalizada, elev_sorted, color='red', linewidth=2, label='Curva Hipsométrica')
        ax2.fill_between(area_normalizada, elev_sorted, elev_min, color='red', alpha=0.2)
        ax2.plot([0, 1], [elev_max, elev_min], color='gray', linestyle='--', linewidth=2, label='Referencia lineal (HI=0.5)')
        ax2.text(0.05, 0.1, f'Integral Hipsométrica: {integral_hipsometrica:.3f}', transform=ax2.transAxes, fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Curva Hipsométrica'); ax2.set_xlabel('Fracción de área (a/A)'); ax2.set_ylabel('Elevación (m)'); ax2.legend(); ax2.set_xlim(0, 1)
        plots['grafico_5_6_histo_hipso'] = fig_to_base64(fig56)

        # GRÁFICO 11: HAND Y LLANURAS DE INUNDACIÓN
        flw_recortado = pyflwdir.from_dem(data=conditioned_dem.view(), nodata=no_data_value, transform=out_transform, latlon=False)
        # Reconstruir el objeto UPA de pyflwdir a partir del array NumPy guardado
        upa_pyflwdir_obj = pyflwdir.Raster(upa_pyflwdir_array, flw_recortado.affine, flw_recortado.crs, flw_recortado.nodata)
        upa_km2 = upa_pyflwdir_obj.to_crs(unit='km2')
        
        upa_min_threshold = 1.0 # Umbral para drenajes en km2
        hand = flw_recortado.hand(drain=upa_km2.view() > upa_min_threshold, elevtn=conditioned_dem.view())
        floodplains = flw_recortado.floodplains(elevtn=conditioned_dem.view(), uparea=upa_km2.view(), upa_min=upa_min_threshold)
        
        dem_background = np.where(catch.view(), conditioned_dem.view(), np.nan)
        hand_masked = np.where(catch.view() & (hand > 0), hand, np.nan)
        floodplains_masked = np.where(catch.view() & (floodplains > 0), 1.0, np.nan)
        
        fig11, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1, ax2 = axes[0], axes[1]
        xmin, xmax, ymin, ymax = plot_extent
        
        ax1.imshow(dem_background, extent=plot_extent, cmap='Greys_r', zorder=1)
        vmax_hand = np.nanpercentile(hand_masked, 98) if not np.all(np.isnan(hand_masked)) else 1
        im_hand = ax1.imshow(hand_masked, extent=plot_extent, cmap='gist_earth_r', alpha=0.7, zorder=2, vmin=0, vmax=vmax_hand)
        fig11.colorbar(im_hand, ax=ax1, label='Altura sobre drenaje (m)', shrink=0.6)
        ax1.set_title(f'Altura Sobre Drenaje (HAND)\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax1.set_xlabel('Coordenada X (UTM)'); ax1.set_ylabel('Coordenada Y (UTM)'); ax1.grid(True, linestyle='--', alpha=0.6)
        ax1.set_xlim(xmin, xmax); ax1.set_ylim(ymin, ymax)
        
        ax2.imshow(dem_background, extent=plot_extent, cmap='Greys', zorder=1)
        ax2.imshow(floodplains_masked, extent=plot_extent, cmap='Blues', alpha=0.7, zorder=2, vmin=0, vmax=1)
        ax2.set_title(f'Llanuras de Inundación\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax2.set_xlabel('Coordenada X (UTM)'); ax2.set_ylabel(''); ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.set_xlim(xmin, xmax); ax2.set_ylim(ymin, ymax)
        
        fig11.suptitle("Índices de Elevación (HAND y Llanuras de Inundación)", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        plots['grafico_11_llanuras'] = fig_to_base64(fig11)

        results.update({
            "success": True, "message": "Gráficos generados con éxito.",
            "visualization_data": {"plots": plots}
        })
        return results
    except Exception as e:
        results['message'] = f"Error en gráficos: {e}\n{traceback.format_exc()}"
        return results
    finally:
        if dem_path_for_pysheds and os.path.exists(dem_path_for_pysheds):
            os.remove(dem_path_for_pysheds)

# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES DE LA PESTAÑA (SIN CAMBIOS)
# ==============================================================================

@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    try:
        print("LOG: Iniciando procesar_datos_cuenca...")
        
        print("LOG: Descargando/obteniendo ruta de Hojas MTN25...")
        local_zip_path = get_local_path_from_url(HOJAS_MTN25_PATH)
        if not local_zip_path:
            st.error("No se pudo obtener el archivo de hojas del MTN25 desde el caché.")
            return None
        print("LOG: Leyendo GDF de Hojas...")
        hojas_gdf = gpd.read_file(local_zip_path)
        
        cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
        buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs("EPSG:25830").buffer(BUFFER_METROS), crs="EPSG:25830")
        
        print("LOG: Realizando intersección espacial (sjoin)...")
        geom_para_interseccion = buffer_gdf.to_crs(hojas_gdf.crs)
        hojas = gpd.sjoin(hojas_gdf, geom_para_interseccion, how="inner", predicate="intersects").drop_duplicates(subset=['numero'])
        
        # --- ¡CRÍTICO! Abrimos el DEM Nacional (COG) directamente desde la URL con rasterio ---
        print(f"LOG: Abriendo DEM Nacional (COG) directamente desde URL: {DEM_NACIONAL_PATH}...")
        with rasterio.open(DEM_NACIONAL_PATH) as src:
            geom_recorte_gdf = buffer_gdf.to_crs(src.crs)
            print("LOG: Iniciando operación de recorte del DEM (rasterio.mask)...")
      
            dem_recortado, trans_recortado = mask(dataset=src, shapes=geom_recorte_gdf.geometry, crop=True, nodata=src.nodata or -32768)
            print(f"DEBUG: generar_dem - Operación de recorte del DEM finalizada. Resolución de píxel: {trans_recortado[1]}x{abs(trans_recortado[5])}. Shape: {dem_recortado.shape}")
            
            meta = src.meta.copy(); 
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado, "compress": "NONE"})            
            
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst:
                    dst.write(dem_recortado)
                buffer.seek(0)
                dem_bytes = buffer.read()
        
        if dem_bytes is None:
            st.error("La generación del DEM recortado falló (dem_bytes is None).")
            return None
        
        print("LOG: Exportando GDF a ZIP...")
        shp_zip_bytes = export_gdf_to_zip(buffer_gdf, "contorno_cuenca_buffer")
        print("LOG: procesar_datos_cuenca finalizado con éxito.")
        return { "cuenca_gdf": cuenca_gdf, "buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "hojas": hojas, "dem_bytes": dem_bytes, "dem_array": dem_recortado, "shp_zip_bytes": shp_zip_bytes }

    except Exception as e:
        st.error("Ha ocurrido un error inesperado durante el procesamiento de la cuenca.")
        st.exception(e)
        print(f"ERROR TRACEBACK en procesar_datos_cuenca: {traceback.format_exc()}")
        return None

@st.cache_data(show_spinner="Procesando el polígono dibujado...")
def procesar_datos_poligono(polygon_geojson_str):
    try:
        poly_gdf = gpd.read_file(polygon_geojson_str).set_crs("EPSG:4326")
        area_km2 = poly_gdf.to_crs("EPSG:25830").area.iloc[0] / 1_000_000
        if area_km2 > LIMITE_AREA_KM2:
            return {"error": f"El área ({area_km2:,.0f} km²) supera los límites de {LIMITE_AREA_KM2:,.0f} km²."}
        
        local_zip_path = get_local_path_from_url(HOJAS_MTN25_PATH)
        if not local_zip_path:
            st.error("No se pudo descargar el archivo de hojas del MTN25 desde la nube.")
            return None
        hojas_gdf = gpd.read_file(local_zip_path)
        
        geom_para_interseccion = poly_gdf.to_crs(hojas_gdf.crs)
        hojas = gpd.sjoin(hojas_gdf, geom_para_interseccion, how="inner", predicate="intersects").drop_duplicates(subset=['numero'])
        
        # --- ¡CRÍTICO! Abrimos el DEM Nacional (COG) directamente desde la URL con rasterio ---
        print(f"LOG: Abriendo DEM Nacional (COG) directamente desde URL: {DEM_NACIONAL_PATH} para polígono...")
        with rasterio.open(DEM_NACIONAL_PATH) as src:
            geom_recorte_gdf = poly_gdf.to_crs(src.crs)
            dem_recortado, trans_recortado = mask(dataset=src, shapes=geom_recorte_gdf.geometry, crop=True, nodata=src.nodata or -32768)
            meta = src.meta.copy()
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado, "compress": "NONE"})
            with io.BytesIO() as buffer:
                with rasterio.open(buffer, 'w', **meta) as dst:
                    dst.write(dem_recortado)
                buffer.seek(0)
                dem_bytes = buffer.read()

        if dem_bytes is None:
            st.error("La generación del DEM recortado para el polígono falló.")
            return None
            
        shp_zip_bytes = export_gdf_to_zip(poly_gdf, "contorno_poligono_manual")
        return { "poligono_gdf": poly_gdf, "hojas": hojas, "dem_bytes": dem_bytes, "dem_array": dem_recortado, "shp_zip_bytes": shp_zip_bytes, "area_km2": area_km2 }

    except Exception as e:
        st.error("Ha ocurrido un error inesperado durante el procesamiento del polígono.")
        st.exception(e)
        print(traceback.format_exc())
        return None

def export_gdf_to_zip(gdf, filename_base):
    with tempfile.TemporaryDirectory() as tmpdir:
        if gdf.crs is None: gdf.set_crs("EPSG:4326", inplace=True) # Asegurar CRS si no está definido
        # Si el CRS es geográfico, lo proyectamos a UTM30N para la exportación de Shapefile.
        # Si ya es proyectado (ej. UTM30N), lo mantenemos.
        if gdf.crs.is_geographic:
            gdf_proj = gdf.to_crs("EPSG:25830") # Proyectar a UTM30N
        else:
            gdf_proj = gdf
            
        gdf_proj.to_file(os.path.join(tmpdir, f"{filename_base}.shp"), driver='ESRI Shapefile', encoding='utf-8')
        zip_io = io.BytesIO()
        with zipfile.ZipFile(zip_io, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmpdir):
                for file in files:
                    if file.startswith(filename_base): zf.write(os.path.join(root, file), arcname=file)
        zip_io.seek(0)
        return zip_io

@st.cache_data(show_spinner="Pre-calculando referencia de cauces (pyflwdir)...")
def precalcular_acumulacion(_dem_bytes):
    try:
        if isinstance(_dem_bytes, str) and _dem_bytes.startswith('http'):
            with requests.get(_dem_bytes, stream=True) as r:
                r.raise_for_status()
                dem_bytes_content = r.content
            memfile = rasterio.io.MemoryFile(dem_bytes_content)
        else:
            memfile = rasterio.io.MemoryFile(_dem_bytes)

        with memfile.open() as src:
            dem_array = src.read(1).astype(np.float32)
            nodata = src.meta.get('nodata')
            if nodata is not None: dem_array[dem_array == nodata] = np.nan
            transform = src.transform
        
        flwdir = pyflwdir.from_dem(data=dem_array, transform=transform, nodata=np.nan)
        acc = flwdir.upstream_area(unit='cell')
        acc_limpio = np.nan_to_num(acc, nan=0.0)
        acc_limpio = np.where(acc_limpio < 0, 0, acc_limpio)

        power_factor = 0.2
        scaled_acc_for_viz = acc_limpio ** power_factor
        
        min_val, max_val = np.nanmin(scaled_acc_for_viz), np.nanmax(scaled_acc_for_viz)
        
        if max_val == min_val:
            img_acc = np.zeros_like(scaled_acc_for_viz, dtype=np.uint8)
        else:
            scaled_acc_nan_as_zero = np.nan_to_num(scaled_acc_for_viz, nan=min_val)
            img_acc = (255 * (scaled_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        return img_acc
    except Exception as e:
        st.error(f"Error en el pre-cálculo con pyflwdir: {e}")
        st.code(traceback.format_exc())
        return None

# ==============================================================================
# SECCIÓN 5: FUNCIÓN PRINCIPAL DEL FRONTEND (RENDERIZADO DE LA PESTAÑA - MODIFICADA)
# ==============================================================================

def render_dem25_tab():
    st.header("Generador de Modelos Digitales del Terreno (MDT25)")
    st.subheader("(from NASA’s Earth Observing System Data and Information System -EOSDIS)")
    
    st.info("Esta herramienta identifica las hojas del MTN25 y genera un DEM recortado para la cuenca (con buffer de 5km) o para un área dibujada manualmente.")

    if not st.session_state.get('basin_geojson'):
        st.warning("⬅️ Por favor, primero calcule una cuenca en la Pestaña 1.")
        st.stop()

    if st.button("🗺️ Analizar Hojas y DEM para la Cuenca Actual", use_container_width=True):
        try:
            temp_cuenca_gdf = gpd.read_file(st.session_state.basin_geojson).set_crs("EPSG:4326")
            area_km2 = temp_cuenca_gdf.to_crs("EPSG:25830").area.sum() / 1_000_000
            if area_km2 > AREA_PROCESSING_LIMIT_KM2:
                st.error(f"El área de la cuenca calculada ({area_km2:,.0f} km²) es demasiado grande. Límite: {AREA_PROCESSING_LIMIT_KM2:,.0f} km².")
                st.stop() 
        except Exception as e:
            st.error(f"No se pudo verificar el área de la cuenca: {e}")
            st.stop()

        with st.spinner("Procesando recorte del DEM... Esta operación puede tardar varios segundos. Por favor, espere."):
            results = procesar_datos_cuenca(st.session_state.basin_geojson)
        
        if results:
            st.session_state.cuenca_results = results
            st.session_state.processed_basin_id = st.session_state.basin_geojson
            st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes']) 
            
            # Limpiar estados de análisis hidrológico anterior
            st.session_state.pop('poligono_results', None)
            st.session_state.pop('user_drawn_geojson', None)
            st.session_state.pop('polygon_error_message', None)
            st.session_state.pop('outlet_coords', None)
            st.session_state.pop('pysheds_data', None)
            st.session_state.pop('delineated_downloads', None)
            st.session_state.pop('morphometry_data', None)
            st.session_state.pop('morphometry_downloads', None)
            st.session_state.pop('visualization_data', None)

            st.session_state.show_dem25_content = True
            st.rerun()
        else:
            st.error("No se pudo procesar la cuenca. La operación falló o superó el tiempo de espera. Revisa los logs del servidor para más detalles.")
            st.session_state.show_dem25_content = False

    if not st.session_state.get('show_dem25_content') or not st.session_state.get('cuenca_results'):
        st.info("Seleccione un punto en el mapa y haga clic en 'Analizar Hojas y DEM para la Cuenca Actual' para empezar.")
        return

    
    st.subheader("Mapa de Situación")
    m = folium.Map(tiles="CartoDB positron", zoom_start=10)
    folium.TileLayer('OpenStreetMap').add_to(m)
    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m)
    cuenca_results = st.session_state.cuenca_results
    folium.GeoJson(cuenca_results['cuenca_gdf'], name="Cuenca", style_function=lambda x: {'color': 'white', 'weight': 2.5}).add_to(m)
    buffer_layer = folium.GeoJson(cuenca_results['buffer_gdf'], name="Buffer Cuenca (5km)", style_function=lambda x: {'color': 'tomato', 'fillOpacity': 0.1}).add_to(m)
    folium.GeoJson(cuenca_results['hojas'], name="Hojas (Cuenca)", style_function=lambda x: {'color': '#ffc107', 'weight': 2, 'fillOpacity': 0.4}).add_to(m)
    m.fit_bounds(buffer_layer.get_bounds())
    
    if st.session_state.get('user_drawn_geojson'): folium.GeoJson(json.loads(st.session_state.user_drawn_geojson), name="Polígono Dibujado", style_function=lambda x: {'color': 'magenta', 'weight': 3, 'fillOpacity': 0.2, 'dashArray': '5, 5'}).add_to(m)
    if 'poligono_results' in st.session_state and "error" not in st.session_state.poligono_results: folium.GeoJson(st.session_state.poligono_results['hojas'], name="Hojas (Polígono)", style_function=lambda x: {'color': 'magenta', 'weight': 2.5, 'fillOpacity': 0.5}).add_to(m)
    if st.session_state.get("drawing_mode_active"): Draw(export=True, filename='data.geojson', position='topleft', draw_options={'polyline': False, 'rectangle': False, 'circle': False, 'marker': False, 'circlemarker': False, 'polygon': {'shapeOptions': {'color': 'magenta', 'weight': 3, 'fillOpacity': 0.2}}}, edit_options={'edit': False}).add_to(m)
    folium.LayerControl().add_to(m)
    map_output = st_folium(m, key="situacion_map", use_container_width=True, height=800, returned_objects=['all_drawings'])
    if st.session_state.get("drawing_mode_active") and map_output.get("all_drawings"):
        print(f"DEBUG: Dibujo completado. GeoJSON: {json.dumps(map_output['all_drawings'][0]['geometry'])}")
        st.session_state.user_drawn_geojson = json.dumps(map_output["all_drawings"][0]['geometry']); 
        st.session_state.drawing_mode_active = False; 
        st.rerun()

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
    st.info("Haga clic en el mapa para definir el punto de desagüe. Puede usar la capa de referencia (semitransparente) para localizar los cauces principales.")
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

    if 'precalculated_acc' in st.session_state and st.session_state.precalculated_acc is not None:
        bounds = buffer_gdf.total_bounds
        img = Image.fromarray(st.session_state.precalculated_acc)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        img_url = f"data:image/png;base64,{img_str}"
        folium.raster_layers.ImageOverlay(image=img_url, bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, pixelated=True, name='Referencia de Cauces (Acumulación)').add_to(map_select)

    # --- NUEVO: Cargar la cuenca delineada si ya existe ---
    if st.session_state.get('delineated_downloads') and st.session_state.delineated_downloads.get("cuenca"):
        try:
            gdf_delineated_cuenca = gpd.read_file(st.session_state.delineated_downloads["cuenca"]).to_crs("EPSG:4326")
            folium.GeoJson(gdf_delineated_cuenca, name="Cuenca Delineada (Paso 1)", style_function=lambda x: {'color': 'blue', 'weight': 3, 'fillOpacity': 0.2}).add_to(map_select)
        except Exception as e:
            st.warning(f"No se pudo cargar la cuenca delineada en el mapa de selección: {e}")
    # --- FIN NUEVO ---

    if 'outlet_coords' in st.session_state and st.session_state.outlet_coords is not None:
        coords = st.session_state.outlet_coords
        folium.Marker([coords['lat'], coords['lng']], popup="Punto de Salida Seleccionado", icon=folium.Icon(color='orange')).add_to(map_select)
    
    folium.LayerControl().add_to(map_select)
    map_output_select = st_folium(map_select, key="map_select", use_container_width=True, height=800, returned_objects=['last_clicked'])

    

    if map_output_select.get("last_clicked"):
        if st.session_state.get('outlet_coords') != map_output_select["last_clicked"]:
            st.session_state.outlet_coords = map_output_select["last_clicked"]
            # Resetear los resultados de los pasos siguientes si se cambia el punto de salida
            st.session_state.pop('pysheds_data', None)
            st.session_state.pop('delineated_downloads', None)
            st.session_state.pop('morphometry_data', None)
            st.session_state.pop('downloads', None) # Limpiar descargas anteriores
            st.session_state.pop('plots', None) # Limpiar plots anteriores
            st.rerun()

    # --- SECCIÓN DE CÁLCULO Y VISUALIZACIÓN (MODIFICADA) ---
    st.subheader("Paso 2: Ejecute el análisis hidrológico")
    
    min_celdas, max_celdas, default_celdas, step_celdas = 10, 10000, 1600, 10
    slider_label = f"Umbral de celdas para definir cauces (Mín: {min_celdas*CELL_AREA_KM2:.4f} km² - Máx: {max_celdas*CELL_AREA_KM2:.2f} km²)"
    umbral_celdas = st.slider(label=slider_label, min_value=min_celdas, max_value=max_celdas, value=default_celdas, step=step_celdas, help=f"Un umbral de {default_celdas} celdas (25x25m) equivale a un área de drenaje mínima de {default_celdas*CELL_AREA_KM2:.2f} km².")
    area_seleccionada_km2 = umbral_celdas * CELL_AREA_KM2
    st.info(f"**Valor seleccionado:** {umbral_celdas} celdas  ➡️  **Área de drenaje mínima:** {area_seleccionada_km2:.4f} km²")

    b_col1, b_col2 = st.columns(2) # Solo dos columnas para dos botones
    
    # Botón 1: Delinear Cuenca
    with b_col1:
        if st.button("1. Delinear Cuenca", use_container_width=True, disabled=not st.session_state.get('outlet_coords')):
            with st.spinner("Delineando cuenca con PySheds..."):
                results = delinear_cuenca_desde_punto(
                    st.session_state.cuenca_results['dem_bytes'],
                    st.session_state.outlet_coords,
                    umbral_celdas
                )
            if results['success']:
                st.session_state.pysheds_data = results['pysheds_data']
                st.session_state.delineated_downloads = results['downloads']
                # Limpiar resultados del Paso 2 si el Paso 1 se recalcula
                st.session_state.pop('morphometry_data', None)
                st.session_state.pop('downloads', None)
                st.session_state.pop('plots', None)
                st.success(results['message'])
                st.rerun()
            else:
                st.error(f"Falló el Paso 1: {results['message']}")
    
    # Botón 2: Analizar Morfometría (ahora incluye gráficos)
    with b_col2:
        if st.button("2. Analizar Morfometría y Generar Gráficos", use_container_width=True, disabled=not st.session_state.get('pysheds_data')):
            with st.spinner("Calculando morfometría y generando gráficos..."):
                results = calcular_morfometria_cuenca(
                    st.session_state.pysheds_data,
                    umbral_celdas
                )
            if results['success']:
                st.session_state.morphometry_data = results['morphometry_data']
                st.session_state.downloads = results['downloads'] # Guardar descargas aquí
                st.session_state.plots = results['plots'] # Guardar plots aquí
                st.success(results['message'])
                st.rerun()
            else:
                st.error(f"Falló el Paso 2: {results['message']}")

    # --- Lógica para mostrar los resultados por pasos ---
    if st.session_state.get('pysheds_data'):
        st.divider()
        st.header("Resultados del Análisis Hidrológico")
        
        # --- Resultados del Paso 1: Delineación de Cuenca ---
        st.subheader("Resultados del Paso 1: Delineación de Cuenca")
        try:
            gdf_cuenca = gpd.read_file(st.session_state.delineated_downloads["cuenca"])
            area_cuenca_km2 = gdf_cuenca.area.sum() / 1_000_000
            
            res1_col1, res1_col2 = st.columns([2,1])
            with res1_col1:
                m_results_1 = folium.Map(tiles="CartoDB positron")
                folium.TileLayer('OpenStreetMap').add_to(m_results_1)
                folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m_results_1)

                folium.GeoJson(gdf_cuenca.to_crs("EPSG:4326"), name="Cuenca Delineada", style_function=lambda x: {'color': '#FF0000', 'weight': 2.5, 'fillOpacity': 0.2}).add_to(m_results_1)
                
                # Añadir el punto de salida
                gdf_punto_salida = gpd.read_file(st.session_state.delineated_downloads["punto_salida"])
                lat, lon = gdf_punto_salida.to_crs("EPSG:4326").geometry.iloc[0].y, gdf_punto_salida.to_crs("EPSG:4326").geometry.iloc[0].x
                folium.Marker([lat, lon], popup="Punto de Desagüe", icon=folium.Icon(color='green', icon='tint', prefix='fa')).add_to(m_results_1)

                m_results_1.fit_bounds(gdf_cuenca.to_crs("EPSG:4326").total_bounds[[1, 0, 3, 2]].tolist())
                folium.LayerControl().add_to(m_results_1)
                st_folium(m_results_1, key="results_map_1_delineated", use_container_width=True, height=400) # Cambiado key para evitar conflicto
            with res1_col2:
                st.metric("Área de la Cuenca Delineada", f"{area_cuenca_km2:.4f} km²")
                st.download_button("📥 Descargar Cuenca (.zip)", export_gdf_to_zip(gdf_cuenca, "cuenca_delineada"), "cuenca_delineada.zip", "application/zip", use_container_width=True)
                st.download_button("📥 Descargar Punto Salida (.zip)", export_gdf_to_zip(gdf_punto_salida, "punto_salida"), "punto_salida.zip", "application/zip", use_container_width=True)
        except Exception as e:
            st.warning(f"Error al mostrar resultados del Paso 1: {e}")
            st.code(traceback.format_exc())

        # --- Resultados del Paso 2: Morfometría y Gráficos ---
        if st.session_state.get('morphometry_data'):
            st.subheader("Resultados del Paso 2: Morfometría y Gráficos")
            
            # 1. Longitud de LFP y Pendiente Media y T. Concentración
            if "lfp_metrics" in st.session_state.morphometry_data:
                st.markdown("#### Métricas del Camino de Flujo Principal (LFP)")
                metrics = st.session_state.morphometry_data["lfp_metrics"]
                
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
            
            # Descargas de GeoJSON (LFP y Ríos Strahler)
            st.markdown("#### Descargas de Geometrías GIS")
            col_dl_lfp, col_dl_rios = st.columns(2)
            with col_dl_lfp:
                if st.session_state.get('downloads') and st.session_state.downloads.get("lfp"):
                    gdf_lfp_download = gpd.read_file(st.session_state.downloads["lfp"])
                    zip_lfp = export_gdf_to_zip(gdf_lfp_download, "lfp")
                    st.download_button("📥 Descargar LFP (.zip)", zip_lfp, "lfp.zip", "application/zip", use_container_width=True)
            with col_dl_rios:
                if st.session_state.get('downloads') and st.session_state.downloads.get("rios_strahler"):
                    gdf_rios_strahler_download = gpd.read_file(st.session_state.downloads["rios_strahler"])
                    zip_rios_strahler = export_gdf_to_zip(gdf_rios_strahler_download, "rios_strahler")
                    st.download_button("📥 Descargar Ríos Strahler (.zip)", zip_rios_strahler, "rios_strahler.zip", "application/zip", use_container_width=True)

            # Gráfico del perfil longitudinal del LFP + tabla + descarga CSV
            if st.session_state.get('plots') and st.session_state.plots.get('grafico_4_perfil_lfp'):
                st.markdown("#### Perfil Longitudinal del LFP")
                st.image(io.BytesIO(base64.b64decode(st.session_state.plots['grafico_4_perfil_lfp'])), caption="Perfil Longitudinal del LFP", use_container_width=True)
                
                if st.session_state.morphometry_data.get("lfp_profile_data"):
                    df_lfp_profile = pd.DataFrame(st.session_state.morphometry_data["lfp_profile_data"])
                    st.dataframe(df_lfp_profile, use_container_width=True)
                    csv_lfp_profile = df_lfp_profile.to_csv(index=False, sep=';').encode('utf-8')
                    st.download_button("📥 Descargar Perfil LFP (.csv)", csv_lfp_profile, "perfil_lfp.csv", "text/csv", use_container_width=True)
            
            # Gráficos de curva hipsométrica + tabla + descarga CSV
            if st.session_state.get('plots') and st.session_state.plots.get('grafico_5_6_histo_hipso'):
                st.markdown("#### Histograma de Elevaciones y Curva Hipsométrica")
                st.image(io.BytesIO(base64.b64decode(st.session_state.plots['grafico_5_6_histo_hipso'])), caption="Histograma de Elevaciones y Curva Hipsométrica", use_container_width=True)
                
                if st.session_state.morphometry_data.get("hypsometric_data"):
                    df_hypsometric = pd.DataFrame(st.session_state.morphometry_data["hypsometric_data"])
                    st.dataframe(df_hypsometric, use_container_width=True)
                    csv_hypsometric = df_hypsometric.to_csv(index=False, sep=';').encode('utf-8')
                    st.download_button("📥 Descargar Curva Hipsométrica (.csv)", csv_hypsometric, "curva_hipsometrica.csv", "text/csv", use_container_width=True)
            
            st.divider()
            st.markdown("##### Consejos para el Ajuste del Umbral de la Red Fluvial en HEC-HMS con un terreno MDT25 ")
            st.info(f"""**Defina la red:**
1. Umbral (nº de celdas) = Área de Drenaje Deseada (m²) / Área de una Celda (m²)
2. Área de una Celda (m²) = 25 m x 25 m = {CELL_AREA_M2} m² (en un MDT25)
3. Área de Drenaje (km²) = Umbral (nº de celdas) x Área de una Celda ({CELL_AREA_KM2} km²)
4. Areas < 0.03 km² (50 celdas) pueden generar cierto ruido, con una red excesivamente densa
5. Areas > 3 km² (5000 celdas) puede eliminar cauces de interes, saliendo una red demasiado preponderante
6. Empiece probando cauces que drenan 100 hectáreas (1 km² = {int(1/CELL_AREA_KM2)} celdas)""")
