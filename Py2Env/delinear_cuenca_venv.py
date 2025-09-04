# -*- coding: utf-8 -*-
# Este script está diseñado para ser llamado como un proceso externo.
# Recibe argumentos desde la línea de comandos y devuelve los resultados
# como un string JSON a la salida estándar (stdout).

import sys
import os
import json
import base64
import io
import matplotlib.pyplot as plt
import numpy as np
from pysheds.grid import Grid
import matplotlib.colors as colors
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString
from rasterio import features
import rasterio
import pandas as pd

def run_analysis(dem_file, outlet_coords_utm, umbral_acumulacion):
    """
    Función principal que ejecuta todo el análisis hidrológico.
    """
    results = {
        "plots": {},
        "downloads": {},
        "lfp_profile_data": None,
        "success": False,
        "message": ""
    }

    try:
        x, y = outlet_coords_utm['x'], outlet_coords_utm['y']
        
        # PASO 1: PROCESAMIENTO HIDROLÓGICO
        no_data_value = -32768
        grid = Grid.from_raster(dem_file, nodata=no_data_value)
        dem = grid.read_raster(dem_file, nodata=no_data_value)

        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_acumulacion, (x, y))
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")

        # PASO 2: GENERACIÓN DE GRÁFICOS (GUARDADOS EN MEMORIA)
        
        # --- GRÁFICO 1: Mosaico de características ---
        grid_para_plot = Grid.from_raster(dem_file, nodata=no_data_value)
        grid_para_plot.clip_to(catch)
        catch_view = grid_para_plot.view(catch, nodata=np.nan)
        dem_view = grid_para_plot.view(conditioned_dem, nodata=np.nan)
        acc_view = grid_para_plot.view(acc, nodata=np.nan)
        plot_extent = grid_para_plot.extent
        
        fig, axes = plt.subplots(1, 3, figsize=(18, 5))
        axes[0].imshow(catch_view, extent=plot_extent, cmap='Greys_r')
        axes[0].set_title("Extensión de la Cuenca")
        im_dem = axes[1].imshow(dem_view, extent=plot_extent, cmap='viridis')
        axes[1].set_title("Elevación")
        fig.colorbar(im_dem, ax=axes[1], label='Elevación (m)', shrink=0.7)
        im_acc = axes[2].imshow(acc_view, extent=plot_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.max()))
        axes[2].set_title("Acumulación de Flujo")
        fig.colorbar(im_acc, ax=axes[2], label='Nº Celdas', shrink=0.7)
        plt.suptitle("Características de la Cuenca Delineada", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        results['plots']['grafico_1_mosaico'] = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)

        # --- CÁLCULO DEL LFP (Longest Flow Path) ---
        dist = grid._d8_flow_distance(x=x_snap, y=y_snap, fdir=flowdir, xytype='coordinate')
        dist_catch = np.where(catch, dist, -1)
        start_row, start_col = np.unravel_index(np.argmax(dist_catch), dist_catch.shape)
        dirmap = {1:(0,1), 2:(1,1), 4:(1,0), 8:(1,-1), 16:(0,-1), 32:(-1,-1), 64:(-1,0), 128:(-1,1)}
        lfp_coords = []
        current_row, current_col = start_row, start_col
        with rasterio.open(dem_file) as src: raster_transform = src.transform
        while catch[current_row, current_col]:
            x_coord, y_coord = raster_transform * (current_col, current_row); x_coord += raster_transform.a / 2.0; y_coord += raster_transform.e / 2.0
            lfp_coords.append((x_coord, y_coord))
            direction = flowdir[current_row, current_col];
            if direction == 0: break
            row_move, col_move = dirmap[direction]; current_row += row_move; current_col += col_move
        
        # --- GRÁFICO 4: Perfil Longitudinal ---
        with rasterio.open(dem_file) as src: fwd_transform = src.transform; inv_transform = ~fwd_transform
        profile_elevations = []; valid_lfp_coords = []
        for x_coord, y_coord in lfp_coords:
            try:
                col, row = inv_transform * (x_coord, y_coord); row_idx, col_idx = int(row), int(col)
                elevation = conditioned_dem[row_idx, col_idx]; profile_elevations.append(elevation); valid_lfp_coords.append((x_coord, y_coord))
            except IndexError: continue
        profile_distances = [0]
        for i in range(1, len(valid_lfp_coords)):
            x1, y1 = valid_lfp_coords[i-1]; x2, y2 = valid_lfp_coords[i]
            segment_dist = np.sqrt((x2 - x1)**2 + (y2 - y1)**2); profile_distances.append(profile_distances[-1] + segment_dist)
        profile_distances_km = np.array(profile_distances) / 1000
        
        fig, ax = plt.subplots(figsize=(12, 6))
        ax.plot(profile_distances_km, profile_elevations, color='darkblue')
        ax.fill_between(profile_distances_km, profile_elevations, alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del Camino de Flujo Más Largo (LFP)')
        ax.set_xlabel('Distancia desde el origen (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True, linestyle='--', alpha=0.7)
        
        buf = io.BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight')
        results['plots']['grafico_4_perfil_lfp'] = base64.b64encode(buf.getvalue()).decode('utf-8')
        plt.close(fig)

        # Guardar datos del perfil para CSV
        results['lfp_profile_data'] = {
            'distancia_km': profile_distances_km.tolist(),
            'elevacion_m': np.array(profile_elevations).tolist()
        }

        # PASO 3: PREPARACIÓN DE DATOS PARA DESCARGA
        output_crs = "EPSG:25830"
        
        # --- Cuenca ---
        shapes = features.shapes(catch.astype(np.uint8), mask=catch, transform=raster_transform)
        cuenca_geom = [Polygon(s['coordinates'][0]) for s, v in shapes if v == 1][0]
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom]}, crs=output_crs)
        results['downloads']['cuenca'] = gdf_cuenca.to_json()

        # --- Red Fluvial ---
        river_raster = acc > umbral_acumulacion
        shapes_rios = features.shapes(river_raster.astype(np.uint8), mask=river_raster & catch, transform=raster_transform)
        river_geoms = [LineString(s['coordinates'][0]) for s, v in shapes_rios if v == 1]
        gdf_rios = gpd.GeoDataFrame(geometry=river_geoms, crs=output_crs)
        results['downloads']['rios'] = gdf_rios.to_json()

        # --- LFP ---
        lfp_geom = LineString(lfp_coords)
        gdf_lfp = gpd.GeoDataFrame({'id': [1], 'geometry': [lfp_geom]}, crs=output_crs)
        results['downloads']['lfp'] = gdf_lfp.to_json()

        # --- Punto de Salida ---
        punto_geom = Point(x_snap, y_snap)
        gdf_punto = gpd.GeoDataFrame({'id': [1], 'geometry': [punto_geom]}, crs=output_crs)
        results['downloads']['punto_salida'] = gdf_punto.to_json()

        results['success'] = True
        results['message'] = "Análisis completado con éxito."

    except Exception as e:
        import traceback
        results['success'] = False
        results['message'] = f"Error en el script externo: {str(e)}\n{traceback.format_exc()}"

    return results

if __name__ == "__main__":
    # Este bloque se ejecuta cuando se llama al script desde la línea de comandos
    try:
        dem_input_path = sys.argv[1]
        outlet_coords_json_str = sys.argv[2]
        
        # Parámetros fijos por ahora
        UMBRAL_FIJO = 5000 
        
        outlet_coords = json.loads(outlet_coords_json_str)
        
        # Ejecutar el análisis
        final_results = run_analysis(dem_input_path, outlet_coords, UMBRAL_FIJO)
        
        # Imprimir el resultado final como un string JSON a la consola.
        # El proceso padre (Streamlit) leerá esta salida.
        print(json.dumps(final_results))

    except Exception as e:
        # Si algo falla al leer los argumentos, devolver un JSON de error
        import traceback
        error_result = {
            "success": False,
            "message": f"Error al inicializar el script: {str(e)}\n{traceback.format_exc()}",
            "plots": {},
            "downloads": {}
        }
        print(json.dumps(error_result))
