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
import pandas as pd
import json
import zipfile
import tempfile
from folium.plugins import Draw
from shapely.geometry import shape, Point, LineString, Polygon
from pyproj import CRS, Transformer
import base64
from PIL import Image

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

# ==============================================================================
# SECCIÓN 2: CONSTANTES Y CONFIGURACIÓN
# ==============================================================================

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
HOJAS_MTN25_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MTN25_ACTUAL_ETRS89_Peninsula_Baleares_Canarias.zip"
# --- ¡CRÍTICO! Apunta al COG grande de 700MB ---
DEM_NACIONAL_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MDT25_peninsula_UTM30N_COG.tif"
BUFFER_METROS = 5000
LIMITE_AREA_KM2 = 15000
# --- ¡¡¡ESTA CONSTANTE FALTABA Y ES LA CAUSA DEL ERROR!!! ---
AREA_PROCESSING_LIMIT_KM2 = 50000 # Límite para evitar procesar cuencas gigantes en Pestaña 2
# --- ¡¡¡AHORA SÍ ESTÁ!!! ---

# ==============================================================================
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def realizar_analisis_hidrologico_directo(dem_url, outlet_coords_wgs84, umbral_rio_export):
    """
    Ejecuta el flujo de trabajo hidrológico completo directamente en la aplicación.
    Ahora lee el DEM directamente desde la URL.
    """
    results = {
        "success": False, "message": "", "plots": {}, "downloads": {},
        "lfp_metrics": {}, "hypsometric_data": {}, "lfp_profile_data": {}
    }
    
def realizar_analisis_hidrologico_directo(dem_url, outlet_coords_wgs84, umbral_rio_export):
    results = { ... }
    try:
        if dem_url is None: # Comprobación de seguridad
            results['message'] = "Error: El DEM de entrada para el análisis hidrológico es None."
            print("ERROR: realizar_analisis_hidrologico_directo - dem_url es None.")
            return results

        with rasterio.io.MemoryFile(dem_url) as memfile:
            with memfile.open() as src_global:
                print(f"DEBUG: realizar_analisis_hidrologico_directo - DEM global abierto desde MemoryFile. CRS: {src_global.crs}, Bounds: {src_global.bounds}") # <-- Añadir bounds
                
                transformer_wgs84_to_dem_crs = Transformer.from_crs("EPSG:4326", src_global.crs, always_xy=True)
                x_dem_crs, y_dem_crs = transformer_wgs84_to_dem_crs.transform(outlet_coords_wgs84['lng'], outlet_coords_wgs84['lat'])
                print(f"DEBUG: realizar_analisis_hidrologico_directo - Outlet UTM: ({x_dem_crs}, {y_dem_crs})") # <-- Nuevo print

                buffer_size_for_pysheds = 5000
                bbox_utm = (x_dem_crs - buffer_size_for_pysheds, y_dem_crs - buffer_size_for_pysheds,
                            x_dem_crs + buffer_size_for_pysheds, y_dem_crs + buffer_size_for_pysheds)
                print(f"DEBUG: realizar_analisis_hidrologico_directo - BBox para recorte PySheds: {bbox_utm}") # <-- Nuevo print

                # --- Verificar si el bbox está dentro de src_global.bounds ---
                # src_global.bounds es un BoundingBox, no un objeto Shapely.
                # Convertimos ambos a objetos Polygon para usar 'intersects'.
                # src_global_polygon = Polygon.from_bounds(*src_global.bounds) # <-- Comentado
                # bbox_utm_polygon = Polygon.from_bounds(*bbox_utm) # <-- Comentado

                # if not src_global_polygon.intersects(bbox_utm_polygon): # <-- Comentado
                #     results['message'] = "Error: El punto de desagüe y su buffer están fuera del DEM recortado de la cuenca. Intente un punto más central."
                #     print(f"ERROR: realizar_analisis_hidrologico_directo - BBox de PySheds fuera de los límites del DEM global. src_global.bounds: {src_global.bounds}")
                #     return results

                out_image, out_transform = mask(src_global, [Polygon.from_bounds(*bbox_utm)], crop=True, nodata=src_global.nodata)
                print(f"DEBUG: realizar_analisis_hidrologico_directo - out_image.shape después de mask: {out_image.shape}") # <-- Nuevo print
                print(f"DEBUG: realizar_analisis_hidrologico_directo - out_transform después de mask: {out_transform}") # <-- Nuevo print
                
                if out_image.size == 0 or out_image.shape[1] == 0 or out_image.shape[2] == 0: # <-- Nueva comprobación
                    results['message'] = "Error: El recorte del DEM para PySheds resultó en una imagen vacía o inválida."
                    print(f"ERROR: realizar_analisis_hidrologico_directo - out_image está vacío o inválido: {out_image.shape}") # <-- Nuevo print
                    return results

                out_meta = src_global.meta.copy()
                out_meta.update({"driver": "GTiff", "height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform, "compress": "NONE"})

                with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as tmp_dem_pysheds:
                    with rasterio.open(tmp_dem_pysheds.name, 'w', **out_meta) as dst:
                        dst.write(out_image)
                    dem_path_for_pysheds = tmp_dem_pysheds.name
                print(f"DEBUG: realizar_analisis_hidrologico_directo - DEM temporal para PySheds guardado en: {dem_path_for_pysheds}") # <-- Nuevo print

        # --- PASO 2: PROCESAMIENTO HIDROLÓGICO CON PYSHEDS (CÓDIGO ORIGINAL) ---
        no_data_value = out_meta.get('nodata', -32768)
        print(f"DEBUG: realizar_analisis_hidrologico_directo - Iniciando Grid.from_raster con {dem_path_for_pysheds}") # <-- Nuevo print
        grid = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        print(f"DEBUG: realizar_analisis_hidrologico_directo - Grid creado. Extent: {grid.extent}") # <-- Nuevo print
        dem = grid.read_raster(dem_path_for_pysheds, nodata=no_data_value)
        print(f"DEBUG: realizar_analisis_hidrologico_directo - DEM leído por Grid. Shape: {dem.shape}") # <-- Nuevo print

        # Ajustamos las coordenadas del punto de salida al nuevo DEM recortado
        x_snap, y_snap = grid.snap_to_mask(grid.accumulation(grid.flowdir(grid.fill_depressions(grid.fill_pits(dem)))) > umbral_rio_export, (x_dem_crs, y_dem_crs))
        
        # Si el punto de snap está fuera del DEM recortado, ajustamos.
        if not (grid.extent[0] <= x_snap <= grid.extent[1] and grid.extent[2] <= y_snap <= grid.extent[3]):
            results['message'] = "El punto de desagüe se encuentra demasiado cerca del borde del DEM recortado para el análisis. Intente un punto más central."
            return results

        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        
        # Re-snap al DEM recortado
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_rio_export, (x_dem_crs, y_dem_crs))
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")

        # --- PASO 3: INICIALIZACIÓN DE PYFLWDIR (CÓDIGO ORIGINAL) ---
        # PyFlwdir también puede abrir el DEM recortado
        flw = pyflwdir.from_dem(data=out_image[0], nodata=no_data_value, transform=out_transform, latlon=False)
        upa = flw.upstream_area(unit='cell')

        # --- PASO 4: GENERACIÓN DE GRÁFICOS Y MÉTRICAS (CÓDIGO ORIGINAL) ---
        # Asegúrate de que las llamadas a imshow y plot usen 'grid_para_plot.extent' o 'grid.extent'
        # y que los datos de elevación sean 'conditioned_dem' o 'dem_data' según corresponda.

        # GRÁFICO 1: MOSAICO DE CARACTERÍSTICAS
        grid_para_plot = Grid.from_raster(dem_path_for_pysheds, nodata=no_data_value)
        grid_para_plot.clip_to(catch)
        plot_extent = grid_para_plot.extent
        fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes[0, 0].imshow(grid_para_plot.view(catch, nodata=np.nan), extent=plot_extent, cmap='Reds_r')
        axes[0, 0].set_title("Extensión de la Cuenca")
        num_celdas_cuenca = np.sum(catch)
        area_pixel_m2 = abs(grid.affine.a * grid.affine.e)
        area_cuenca_km2 = (num_celdas_cuenca * area_pixel_m2) / 1_000_000
        area_texto = f'{area_cuenca_km2:.1f} km²'
        centro_x = (plot_extent[0] + plot_extent[1]) / 2
        centro_y = (plot_extent[2] + plot_extent[3]) / 2
        axes[0, 0].text(centro_x, centro_y, area_texto, ha='center', va='center', color='white', fontsize=12, fontweight='bold')
        im_dem = axes[0, 1].imshow(grid_para_plot.view(conditioned_dem, nodata=np.nan), extent=plot_extent, cmap='terrain')
        axes[0, 1].set_title("Elevación")
        fig1.colorbar(im_dem, ax=axes[0, 1], label='Elevación (m)', shrink=0.7)
        im_fdir = axes[1, 0].imshow(grid_para_plot.view(flowdir, nodata=np.nan), extent=plot_extent, cmap='twilight')
        axes[1, 0].set_title("Dirección de Flujo")
        im_acc = axes[1, 1].imshow(grid_para_plot.view(acc, nodata=np.nan), extent=plot_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.max()))
        axes[1, 1].set_title("Acumulación de Flujo")
        fig1.colorbar(im_acc, ax=axes[1, 1], label='Nº celdas', shrink=0.7)
        for ax in axes.flat: ax.tick_params(axis='both', labelsize=6)
        plt.suptitle("Características de la Cuenca Delineada", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        results['plots']['grafico_1_mosaico'] = fig_to_base64(fig1)

        # CÁLCULOS DEL LONGEST FLOW PATH (LFP)
        dist = grid._d8_flow_distance(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        dist_catch = np.where(catch, dist, -1)
        start_row, start_col = np.unravel_index(np.argmax(dist_catch), dist_catch.shape)
        dirmap = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1), 32:(-1,-1), 64:(-1,0), 128:(-1,1)}
        lfp_coords = []
        current_row, current_col = start_row, start_col
        with rasterio.open(dem_path_for_pysheds) as src_pysheds: raster_transform = src_pysheds.transform
        while catch[current_row, current_col]:
            x_coord, y_coord = raster_transform * (current_col, current_row); x_coord += raster_transform.a / 2.0; y_coord += raster_transform.e / 2.0
            lfp_coords.append((x_coord, y_coord))
            direction = flowdir[current_row, current_col]
            if direction == 0: break
            row_move, col_move = dirmap[direction]; current_row += row_move; current_col += col_move

        # GRÁFICO 3/7 UNIFICADO: LFP y Red Fluvial de Strahler
        stream_mask_strahler = upa > umbral_rio_export
        strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=src_global.crs) # Usamos el CRS original del DEM
        shapes_cuenca_clip = features.shapes(catch.astype(np.uint8), mask=catch, transform=out_transform) # Usamos out_transform
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca_clip = gpd.GeoDataFrame(geometry=[cuenca_geom_clip], crs=src_global.crs)
        gdf_streams_recortado = gpd.clip(gdf_streams_full, gdf_cuenca_clip)
        dem_cuenca_recortada = grid_para_plot.view(conditioned_dem, nodata=np.nan)
        fig37, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1 = axes[0]
        im1 = ax1.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='terrain', zorder=1)
        fig37.colorbar(im1, ax=ax1, label='Elevación (m)', shrink=0.6)
        x_coords, y_coords = zip(*lfp_coords)
        ax1.plot(x_coords, y_coords, color='red', linewidth=2, label='Longest Flow Path', zorder=2)
        ax1.set_title('Camino de Flujo Más Largo (LFP)'); ax1.legend(); ax1.grid(True, linestyle='--', alpha=0.6)
        ax2 = axes[1]
        ax2.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='Greys_r', alpha=0.8, zorder=1)
        gdf_streams_recortado_clean = gdf_streams_recortado[gdf_streams_recortado.geom_type.isin(["LineString", "MultiLineString"])]
        if not gdf_streams_recortado_clean.empty:
            gdf_streams_recortado_clean.plot(ax=ax2, column='strord', cmap='Blues', zorder=2, legend=True, categorical=True, legend_kwds={'title': "Orden de Strahler", 'loc': 'upper right'})
        else:
            ax2.text(0.5, 0.5, 'No se encontraron ríos\ncon el umbral actual', horizontalalignment='center', verticalalignment='center', transform=ax2.transAxes, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Red Fluvial por Orden de Strahler')
        plt.suptitle("Análisis Morfométrico de la Cuenca", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        results['plots']['grafico_3_7_lfp_strahler'] = fig_to_base64(fig37)

        # GRÁFICO 4: PERFIL LONGITUDINAL Y MÉTRICAS LFP
        with rasterio.open(dem_path_for_pysheds) as src_pysheds: inv_transform = ~src_pysheds.transform
        profile_elevations, valid_lfp_coords = [], []
        for x_c, y_c in lfp_coords:
            try:
                col, row = inv_transform * (x_c, y_c)
                elevation = conditioned_dem[int(row), int(col)]
                profile_elevations.append(elevation); valid_lfp_coords.append((x_c, y_c))
            except IndexError: continue
        profile_distances = [0]
        for i in range(1, len(valid_lfp_coords)):
            x1, y1 = valid_lfp_coords[i-1]; x2, y2 = valid_lfp_coords[i]
            profile_distances.append(profile_distances[-1] + np.sqrt((x2 - x1)**2 + (y2 - y1)**2))
        results['lfp_profile_data'] = {"distancia_m": profile_distances, "elevacion_m": profile_elevations}
        longitud_total_m = profile_distances[-1]
        cota_ini, cota_fin = profile_elevations[0], profile_elevations[-1]
        desnivel = abs(cota_fin - cota_ini)
        pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
        tc_h = (0.87 * (longitud_total_m**2 / (1000 * desnivel))**0.385) if desnivel > 0 else 0
        results['lfp_metrics'] = {"cota_ini_m": cota_ini, "cota_fin_m": cota_fin, "longitud_m": longitud_total_m, "pendiente_media": pendiente_media, "tc_h": tc_h, "tc_min": tc_h * 60}
        fig4, ax = plt.subplots(figsize=(12, 6))
        ax.plot(np.array(profile_distances) / 1000, profile_elevations, color='darkblue')
        ax.fill_between(np.array(profile_distances) / 1000, profile_elevations, alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del LFP'); ax.set_xlabel('Distancia (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True)
        results['plots']['grafico_4_perfil_lfp'] = fig_to_base64(fig4)

        # GRÁFICOS 5 y 6: HISTOGRAMA Y CURVA HIPSOMÉTRICA
        elevaciones_cuenca = conditioned_dem[catch]
        fig56, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        ax1.hist(elevaciones_cuenca, bins=50, color='skyblue', edgecolor='black')
        ax1.set_title('Distribución de Elevaciones'); ax1.set_xlabel('Elevación (m)'); ax1.set_ylabel('Frecuencia')
        elev_sorted = np.sort(elevaciones_cuenca)[::-1]
        cell_area = abs(out_transform.a * out_transform.e) # Usamos out_transform
        area_acumulada = np.arange(1, len(elev_sorted) + 1) * cell_area
        area_normalizada = area_acumulada / area_acumulada.max()
        elev_normalizada = (elev_sorted - elev_sorted.min()) / (elev_sorted.max() - elev_sorted.min())
        integral_hipsometrica = abs(np.trapz(area_normalizada, x=elev_normalizada))
        results['hypsometric_data'] = {"area_normalizada": area_normalizada.tolist(), "elevacion": elev_sorted.tolist()}
        elev_min, elev_max = elev_sorted.min(), elev_sorted.max()
        ax2.plot(area_normalizada, elev_sorted, color='red', linewidth=2, label='Curva Hipsométrica')
        ax2.fill_between(area_normalizada, elev_sorted, elev_min, color='red', alpha=0.2)
        ax2.plot([0, 1], [elev_max, elev_min], color='gray', linestyle='--', linewidth=2, label='Referencia lineal (HI=0.5)')
        ax2.text(0.05, 0.1, f'Integral Hipsométrica: {integral_hipsometrica:.3f}', transform=ax2.transAxes, fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Curva Hipsométrica'); ax2.set_xlabel('Fracción de área (a/A)'); ax2.set_ylabel('Elevación (m)'); ax2.legend(); ax2.set_xlim(0, 1)
        results['plots']['grafico_5_6_histo_hipso'] = fig_to_base64(fig56)

        # GRÁFICO 11: HAND Y LLANURAS DE INUNDACIÓN
        # Para pyflwdir, necesitamos el DEM recortado
        flw_recortado = pyflwdir.from_dem(data=out_image[0], nodata=no_data_value, transform=out_transform, latlon=False)
        upa_km2 = flw_recortado.upstream_area(unit='km2')
        upa_min_threshold = 1.0
        hand = flw_recortado.hand(drain=upa_km2 > upa_min_threshold, elevtn=out_image[0])
        floodplains = flw_recortado.floodplains(elevtn=out_image[0], uparea=upa_km2, upa_min=upa_min_threshold)
        
        dem_background = np.where(catch, conditioned_dem, np.nan)
        hand_masked = np.where(catch & (hand > 0), hand, np.nan)
        floodplains_masked = np.where(catch & (floodplains > 0), 1.0, np.nan)
        fig11, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1, ax2 = axes[0], axes[1]
        xmin, xmax, ymin, ymax = grid_para_plot.extent
        ax1.imshow(dem_background, extent=grid.extent, cmap='Greys_r', zorder=1)
        vmax_hand = np.nanpercentile(hand_masked, 98) if not np.all(np.isnan(hand_masked)) else 1
        im_hand = ax1.imshow(hand_masked, extent=grid.extent, cmap='gist_earth_r', alpha=0.7, zorder=2, vmin=0, vmax=vmax_hand)
        fig11.colorbar(im_hand, ax=ax1, label='Altura sobre drenaje (m)', shrink=0.6)
        ax1.set_title(f'Altura Sobre Drenaje (HAND)\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax1.set_xlabel('Coordenada X (UTM)'); ax1.set_ylabel('Coordenada Y (UTM)'); ax1.grid(True, linestyle='--', alpha=0.6)
        ax1.set_xlim(xmin, xmax); ax1.set_ylim(ymin, ymax)
        ax2.imshow(dem_background, extent=grid.extent, cmap='Greys', zorder=1)
        ax2.imshow(floodplains_masked, extent=grid.extent, cmap='Blues', alpha=0.7, zorder=2, vmin=0, vmax=1)
        ax2.set_title(f'Llanuras de Inundación\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax2.set_xlabel('Coordenada X (UTM)'); ax2.set_ylabel(''); ax2.grid(True, linestyle='--', alpha=0.6)
        ax2.set_xlim(xmin, xmax); ax2.set_ylim(ymin, ymax)
        fig11.suptitle("Índices de Elevación (HAND y Llanuras de Inundación)", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        results['plots']['grafico_11_llanuras'] = fig_to_base64(fig11)

        # --- PASO 5: EXPORTACIÓN A GEOMETRÍAS (CÓDIGO ORIGINAL) ---
        output_crs = "EPSG:25830"
        gdf_punto = gpd.GeoDataFrame({'id': [1], 'geometry': [Point(x_snap, y_snap)]}, crs=output_crs)
        results['downloads']['punto_salida'] = gdf_punto.to_json()
        gdf_lfp = gpd.GeoDataFrame({'id': [1], 'geometry': [LineString(lfp_coords)]}, crs=output_crs)
        results['downloads']['lfp'] = gdf_lfp.to_json()
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom_clip]}, crs=output_crs)
        results['downloads']['cuenca'] = gdf_cuenca.to_json()
        river_raster = acc > umbral_rio_export
        shapes_rios = features.shapes(river_raster.astype(np.uint8), mask=river_raster, transform=out_transform) # Usamos out_transform
        river_geoms = [LineString(s['coordinates'][0]) for s, v in shapes_rios if v == 1]
        gdf_rios_full = gpd.GeoDataFrame(geometry=river_geoms, crs=output_crs)
        gdf_rios_recortado = gpd.clip(gdf_rios_full, gdf_cuenca)
        gdf_rios_final = gdf_rios_recortado[gdf_rios_recortado.geom_type == 'LineString']
        results['downloads']['rios'] = gdf_rios_final.to_json()
        gdf_streams_recortado_clean.crs = output_crs # Aseguramos CRS para exportar
        results['downloads']['rios_strahler'] = gdf_streams_recortado_clean.to_json()

        # --- PASO 6: FINALIZAR Y DEVOLVER RESULTADOS ---
        results['success'] = True
        results['message'] = "Cálculo completado con éxito directamente desde la aplicación."

    # except Exception as e:
    #     results['message'] = f"Error en el análisis hidrológico directo: {traceback.format_exc()}"
    #     results['success'] = False
    # finally:
    #     # Aseguramos que el archivo temporal de PySheds se elimine
    #     if 'dem_path_for_pysheds' in locals() and os.path.exists(dem_path_for_pysheds):
    #         os.remove(dem_path_for_pysheds)
    # 
    # return results


    except Exception as e:
        # Aseguramos que 'results' sea un diccionario antes de intentar asignarle un mensaje
        if not isinstance(results, dict):
            results = {"success": False} # Re-inicializar si no es un dict
        
        results['message'] = f"Error en el análisis hidrológico directo: {e}\n{traceback.format_exc()}"
        results['success'] = False
        print(f"ERROR: realizar_analisis_hidrologico_directo - Error general capturado: {e}")
        print(traceback.format_exc())
    finally:
        # Aseguramos que el archivo temporal de PySheds se elimine
        # dem_path_for_pysheds solo se define si el bloque try se ejecuta hasta cierto punto.
        # Es más seguro verificar si existe en locals() antes de intentar eliminarlo.
        if 'dem_path_for_pysheds' in locals() and os.path.exists(dem_path_for_pysheds):
            try:
                os.remove(dem_path_for_pysheds)
                print(f"DEBUG: Archivo temporal eliminado: {dem_path_for_pysheds}")
            except Exception as cleanup_e:
                print(f"ERROR: Fallo al eliminar archivo temporal {dem_path_for_pysheds}: {cleanup_e}")
    return results


# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES DE LA PESTAÑA
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
            # El GeoTransform es una tupla (top_left_x, pixel_width, rotation_x, top_left_y, rotation_y, pixel_height)
            # pixel_width es trans_recortado[1] y pixel_height es trans_recortado[5]
            print(f"DEBUG: generar_dem - Operación de recorte del DEM finalizada. Resolución de píxel: {trans_recortado[1]}x{abs(trans_recortado[5])}. Shape: {dem_recortado.shape}") # <-- Print corregido
            
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
            meta.update({"driver": "GTiff", "height": dem_recortado.shape[1], "width": dem_recortado.shape[2], "transform": trans_recortado, "compress": "NONE"}) # <-- Añadir "compress": "NONE"
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
        if gdf.crs is None: gdf.set_crs("EPSG:4326", inplace=True)
        gdf.to_file(os.path.join(tmpdir, f"{filename_base}.shp"), driver='ESRI Shapefile', encoding='utf-8')
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
        # Pyflwdir necesita un archivo local o bytes en memoria.
        # Si _dem_bytes es una URL, lo descargamos a un MemoryFile.
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

        # Nuevo: Usar una transformación de potencia (corrección gamma) para aumentar el contraste
        # y hacer los píxeles de los cauces más evidentes para la selección.
        # Un exponente pequeño (ej. 0.2) realza los valores altos de acumulación,
        # haciendo que los píxeles individuales de la red fluvial sean más nítidos.
        power_factor = 0.2 # Valor recomendado para realce de contraste. Ajustar si es necesario (0.1 para más, 0.3 para menos).
        scaled_acc_for_viz = acc_limpio ** power_factor # <-- Nueva línea para la transformación de potencia
        
        min_val, max_val = np.nanmin(scaled_acc_for_viz), np.nanmax(scaled_acc_for_viz) # <-- Usar la nueva variable aquí
        
        if max_val == min_val:
            # Evitar división por cero si el ráster es plano
            img_acc = np.zeros_like(scaled_acc_for_viz, dtype=np.uint8) # <-- Usar la nueva variable aquí
        else:
            # Normalizar los valores a un rango de 0-255 para crear una imagen en escala de grises
            scaled_acc_nan_as_zero = np.nan_to_num(scaled_acc_for_viz, nan=min_val) # <-- Usar la nueva variable aquí
            img_acc = (255 * (scaled_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        # log_acc = np.log1p(acc_limpio)
        # min_val, max_val = np.nanmin(log_acc), np.nanmax(log_acc)
        # if max_val == min_val:
        #     img_acc = np.zeros_like(log_acc, dtype=np.uint8)
        # else:
        #     log_acc_nan_as_zero = np.nan_to_num(log_acc, nan=min_val)
        #     img_acc = (255 * (log_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        return img_acc
    except Exception as e:
        st.error(f"Error en el pre-cálculo con pyflwdir: {e}")
        st.code(traceback.format_exc())
        return None

# ==============================================================================
# SECCIÓN 5: FUNCIÓN PRINCIPAL DEL FRONTEND (RENDERIZADO DE LA PESTAÑA)
# ==============================================================================

def render_dem25_tab():
    st.header("Generador de Modelos Digitales del Terreno (MDT25)")
    st.subheader("(from NASA’s Earth Observing System Data and Information System -EOSDIS)")
    
    # --- INICIO: LLAMADA A LA FUNCIÓN DE PRE-CALENTAMIENTO ---
    # Esta función ya no es necesaria aquí, ya que los COGs se leen directamente.
    # La eliminamos para evitar confusiones y posibles descargas innecesarias.
    # precalentar_cache_archivos_grandes() 
    # --- FIN ---

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
            # precalcular_acumulacion ahora recibe los bytes del DEM recortado, no la URL del DEM nacional
            st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes']) 
            st.session_state.pop('poligono_results', None)
            st.session_state.pop('user_drawn_geojson', None)
            st.session_state.pop('polygon_error_message', None)
            st.session_state.pop('hidro_results_externo', None)
            st.session_state.show_dem25_content = True
            st.rerun()
        else:
            st.error("No se pudo procesar la cuenca. La operación falló o superó el tiempo de espera. Revisa los logs del servidor para más detalles.")
            st.session_state.show_dem25_content = False

    # if not st.session_state.get('show_dem25_content') or not st.session_state.get('cuenca_results'):
    #     st.stop()

    if not st.session_state.get('show_dem25_content') or not st.session_state.get('cuenca_results'):
        st.info("Seleccione un punto en el mapa y haga clic en 'Analizar Hojas y DEM para la Cuenca Actual' para empezar.") # <-- Nueva línea
        return # <-- Reemplaza st.stop()

    
    st.subheader("Mapa de Situación")
    m = folium.Map(tiles="CartoDB positron", zoom_start=10) # Añadido zoom_start para mejor visualización inicial
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
    # map_output = st_folium(m, use_container_width=True, height=800, returned_objects=['all_drawings'])
    map_output = st_folium(m, key="situacion_map", use_container_width=True, height=800, returned_objects=['all_drawings'])
    if st.session_state.get("drawing_mode_active") and map_output.get("all_drawings"):
        # Añadir un print para verificar el contenido
        print(f"DEBUG: Dibujo completado. GeoJSON: {json.dumps(map_output['all_drawings'][0]['geometry'])}") # <-- Añadir este print        
        st.session_state.user_drawn_geojson = json.dumps(map_output["all_drawings"][0]['geometry']); 
        st.session_state.drawing_mode_active = False; 
        st.rerun() # <-- Asegurarse de que este rerun esté presente

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
    map_select = folium.Map(tiles="CartoDB positron", zoom_start=10) # Añadido zoom_start para mejor visualización inicial
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
        acc_raster = st.session_state.precalculated_acc
        bounds = buffer_gdf.total_bounds
        img = Image.fromarray(acc_raster)
        buffered = io.BytesIO()
        img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        img_url = f"data:image/png;base64,{img_str}"
        folium.raster_layers.ImageOverlay(image=img_url, bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, pixelated=True, name='Referencia de Cauces (Acumulación)').add_to(map_select) # añadimos --> pixelated=True

    if 'outlet_coords' in st.session_state and st.session_state.outlet_coords is not None:
        coords = st.session_state.outlet_coords
        folium.Marker([coords['lat'], coords['lng']], popup="Punto de Salida Seleccionado", icon=folium.Icon(color='orange')).add_to(map_select)
    
    folium.LayerControl().add_to(map_select)
    map_output_select = st_folium(map_select, key="map_select", use_container_width=True, height=800, returned_objects=['last_clicked'])

    if map_output_select.get("last_clicked"):
        if st.session_state.get('outlet_coords') != map_output_select["last_clicked"]:
            st.session_state.outlet_coords = map_output_select["last_clicked"]
            st.rerun()

    # --- SECCIÓN DE CÁLCULO Y VISUALIZACIÓN (MODIFICADA PARA USAR LA FUNCIÓN DIRECTA) ---
    st.subheader("Paso 2: Cálculos GIS y Análisis de precisión")
    
    CELL_AREA_KM2 = 0.000625
    min_celdas, max_celdas, default_celdas, step_celdas = 10, 10000, 5000, 10
    slider_label = f"Umbral de celdas (Mín: {min_celdas*CELL_AREA_KM2:.4f} km² - Máx: {max_celdas*CELL_AREA_KM2:.2f} km²)"
    umbral_celdas = st.slider(label=slider_label, min_value=min_celdas, max_value=max_celdas, value=default_celdas, step=step_celdas)
    area_seleccionada_km2 = umbral_celdas * CELL_AREA_KM2
    st.info(f"**Valor seleccionado:** {umbral_celdas} celdas  ➡️  **Área de drenaje mínima:** {area_seleccionada_km2:.4f} km²")

    if st.button("Calcular Cuenca y Red Fluvial", use_container_width=True, disabled='outlet_coords' not in st.session_state):
        if 'hidro_results_externo' in st.session_state:
            del st.session_state['hidro_results_externo']

        # --- ¡AQUÍ ESTÁ EL CAMBIO CLAVE! ---
        # Se llama a la función directa en lugar del subproceso.
        with st.spinner("Ejecutando análisis hidrológico completo... Esto puede tardar unos segundos."):
            results = realizar_analisis_hidrologico_directo(
                st.session_state.cuenca_results['dem_bytes'], # dem_bytes es ahora el DEM recortado en memoria
                st.session_state.outlet_coords,
                umbral_celdas
            )
        
        if results and results.get("success"):
            st.session_state.hidro_results_externo = results
            st.success(results.get("message", "Cálculo completado."))
        elif results:
            st.error(f"El análisis reportó un error:")
            st.code(results.get("message", "Error desconocido."), language='bash')
        st.rerun()

    # --- La lógica para mostrar los resultados permanece igual, ya que la estructura del
    #     diccionario 'results' es idéntica a la que devolvía el script original.
    if 'hidro_results_externo' in st.session_state:
        results = st.session_state.hidro_results_externo
        
        st.divider()
        st.header("Resultados del Análisis sobre MDT25 en entorno GIS")

        try:
            gdf_cuenca = gpd.read_file(results["downloads"]["cuenca"]).to_crs("EPSG:4326")
            gdf_lfp = gpd.read_file(results["downloads"]["lfp"]).to_crs("EPSG:4326")
            gdf_punto = gpd.read_file(results["downloads"]["punto_salida"]).to_crs("EPSG:4326")
            m_results = folium.Map(tiles="CartoDB positron")
            folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Imágenes Satélite').add_to(m_results)
            folium.GeoJson(gdf_cuenca, name="Cuenca Delineada", style_function=lambda x: {'color': '#FF0000', 'weight': 2.5, 'fillColor': '#FF0000', 'fillOpacity': 0.2}).add_to(m_results)
            folium.GeoJson(gdf_lfp, name="Longest Flow Path (LFP)", style_function=lambda x: {'color': '#FFFF00', 'weight': 4, 'opacity': 0.9}).add_to(m_results)
            if "rios_strahler" in results["downloads"]:
                gdf_rios_strahler = gpd.read_file(results["downloads"]["rios_strahler"]).to_crs("EPSG:4326")
                if not gdf_rios_strahler.empty and 'strord' in gdf_rios_strahler.columns:
                    import branca.colormap as cm
                    min_order, max_order = gdf_rios_strahler['strord'].min(), gdf_rios_strahler['strord'].max()
                    colormap = cm.LinearColormap(colors=['lightblue', 'blue', 'darkblue'], vmin=min_order, vmax=max_order)
                    folium.GeoJson(gdf_rios_strahler, name="Red Fluvial (Strahler)", style_function=lambda f: {'color': colormap(f['properties']['strord']), 'weight': f['properties']['strord'] / 2 + 1, 'opacity': 0.8}, tooltip=lambda f: f"Orden: {f['properties']['strord']}").add_to(m_results)
                    m_results.add_child(colormap)
            lat, lon = gdf_punto.geometry.iloc[0].y, gdf_punto.geometry.iloc[0].x
            folium.Marker([lat, lon], popup="Punto de Desagüe", icon=folium.Icon(color='green', icon='tint', prefix='fa')).add_to(m_results)
            m_results.fit_bounds(gdf_cuenca.total_bounds[[1, 0, 3, 2]].tolist())
            folium.LayerControl().add_to(m_results)
            st_folium(m_results, use_container_width=True, height=800)

            st.subheader("Métricas de la Cuenca Delineada")
            gdf_rios_utm = gpd.read_file(results["downloads"]["rios"])
            cuenca_utm = gpd.read_file(results["downloads"]["cuenca"])
            area_cuenca_km2 = cuenca_utm.area.sum() / 1_000_000
            longitud_total_km = gdf_rios_utm.length.sum() / 1000 if not gdf_rios_utm.empty else 0
            densidad_drenaje = (longitud_total_km / area_cuenca_km2) if area_cuenca_km2 > 0 else 0
            col1, col2, col3, col4 = st.columns(4)
            with col1: st.metric("Umbral", f"{umbral_celdas} celdas"); st.caption(f"Área drenaje mín.: {area_seleccionada_km2:.4f} km²")
            with col2: st.metric("Área Cuenca", f"{area_cuenca_km2:.4f} km²")
            with col3: st.metric("Longitud Cauces", f"{longitud_total_km:.2f} km")
            with col4: st.metric("Densidad Drenaje", f"{densidad_drenaje:.2f} km/km²")
            st.info("""**¿Qué es la Densidad de Drenaje (Dd)?**\n\nLa Densidad de Drenaje es una medida de la eficiencia con la que una cuenca es drenada por su red de cauces...""", icon="ℹ️")

            if "lfp_metrics" in results:
                st.subheader("Métricas del Camino de Flujo Principal (LFP)")
                metrics = results["lfp_metrics"]
                col1, col2, col3 = st.columns(3)
                with col1: st.metric("Cota Inicio (Salida)", f"{metrics.get('cota_ini_m', 0):.2f} m"); st.metric("Cota Fin (Divisoria)", f"{metrics.get('cota_fin_m', 0):.2f} m")
                with col2: st.metric("Longitud LFP", f"{metrics.get('longitud_m', 0):.2f} m"); st.metric("Pendiente Media", f"{metrics.get('pendiente_media', 0):.4f} m/m")
                with col3: st.metric("Tiempo Concentración", f"{metrics.get('tc_h', 0):.3f} h"); st.caption(f"Equivalente a {metrics.get('tc_min', 0):.2f} minutos")

            st.subheader("Gráficos Generados")
            with st.expander("Ver todos los gráficos generados", expanded=True):
                plots = results.get("plots", {})
                plot_titles = {"grafico_1_mosaico": "Características de la Cuenca", "grafico_3_7_lfp_strahler": "LFP y Red Fluvial por Orden de Strahler", "grafico_4_perfil_lfp": "Perfil Longitudinal del LFP", "grafico_5_6_histo_hipso": "Histograma de Elevaciones y Curva Hipsométrica", "grafico_11_llanuras": "Índices de Elevación (HAND y Llanuras de Inundación)"}
                for key, title in plot_titles.items():
                    if key in plots and plots[key]: st.image(io.BytesIO(base64.b64decode(plots[key])), caption=title, use_container_width=True)

            st.subheader("Descargas GIS y Datos")
            downloads = results.get("downloads", {})
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                if "cuenca" in downloads: st.download_button("📥 Cuenca (.zip)", export_gdf_to_zip(gpd.read_file(downloads["cuenca"]), "cuenca_delineada"), "cuenca_delineada.zip", "application/zip", use_container_width=True)
            with col2:
                if "rios" in downloads: st.download_button("📥 Red Fluvial (.zip)", export_gdf_to_zip(gpd.read_file(downloads["rios"]), "red_fluvial"), "red_fluvial.zip", "application/zip", use_container_width=True)
            with col3:
                if "lfp" in downloads: st.download_button("📥 LFP (.zip)", export_gdf_to_zip(gpd.read_file(downloads["lfp"]), "lfp"), "lfp.zip", "application/zip", use_container_width=True)
            with col4:
                if "punto_salida" in downloads: st.download_button("📥 Punto Salida (.zip)", export_gdf_to_zip(gpd.read_file(downloads["punto_salida"]), "punto_salida"), "punto_salida.zip", "application/zip", use_container_width=True)
            
            col5, col6, col7 = st.columns(3)
            with col5:
                if "rios_strahler" in downloads: st.download_button("📥 Ríos Strahler (.zip)", export_gdf_to_zip(gpd.read_file(downloads["rios_strahler"]), "rios_strahler"), "rios_strahler.zip", "application/zip", use_container_width=True)
            with col6:
                if results.get("lfp_profile_data"): st.download_button("📥 Descargar Perfil LFP (.csv)", pd.DataFrame(results["lfp_profile_data"]).to_csv(index=False, sep=';').encode('utf-8'), "perfil_lfp.csv", "text/csv", use_container_width=True)
            with col7:
                if results.get("hypsometric_data"): st.download_button("📥 Descargar Curva Hipsométrica (.csv)", pd.DataFrame(results["hypsometric_data"]).to_csv(index=False, sep=';').encode('utf-8'), "curva_hipsometrica.csv", "text/csv", use_container_width=True)

        except Exception as e:
            st.warning(f"Se produjo un error al mostrar los resultados: {e}")
            st.code(traceback.format_exc())

    st.divider()
    st.markdown("##### Consejos para el Ajuste del Umbral de la Red Fluvial en HEC-HMS con un terreno MDT25 ")
    st.info("**Defina la red:**\n1. Umbral (nº de celdas) = Área de Drenaje Deseada (m²) / Área de una Celda (m²)\n2. Área de una Celda (m²) = 25 m x 25 m = 625 m² (en un MDT25)\n3. Área de Drenaje (km²) = Umbral (nº de celdas) x Área de una Celda (0.000625 km²)\n4. Areas < 0.03 km² (50 celdas) pueden generar cierto ruido, con una red excesivamente densa\n5. Areas > 3 km² (5000 celdas) puede eliminar cauces de interes, saliendo una red demasiado preponderante\n6. Empiece probando cauces que drenan 100 hectáreas (1 km² = 1600 celdas)")
