# -*- coding: utf-8 -*-

# 1. Imports
import os
import sys
import json
import io
import base64
import traceback
import matplotlib.pyplot as plt
import numpy as np
from pysheds.grid import Grid
import matplotlib.colors as colors
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString
from rasterio import features
import rasterio
import pyflwdir
from matplotlib.lines import Line2D

# Función para convertir figuras de Matplotlib a Base64
def fig_to_base64(fig):
    """Convierte una figura de Matplotlib a una cadena Base64 para incrustarla en JSON."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def main():
    # Diccionario para almacenar todos los resultados que se devolverán como JSON
    results = {
        "success": False,
        "message": "",
        "plots": {},
        "downloads": {},
        "lfp_metrics": {},
        "hypsometric_data": {},
        "lfp_profile_data": {}
    }

    try:
        # ==================================================================
        # PASO 2: LECTURA DE DATOS DE ENTRADA DESDE ARGUMENTOS
        # ==================================================================
        dem_file = sys.argv[1]
        outlet_coords_utm_json = sys.argv[2]
        umbral_acumulacion_str = sys.argv[3]

        outlet_coords = json.loads(outlet_coords_utm_json)
        x, y = outlet_coords['x'], outlet_coords['y']
        umbral_rio_export = int(umbral_acumulacion_str)

        no_data_value = -32768
        grid = Grid.from_raster(dem_file, nodata=no_data_value)
        dem = grid.read_raster(dem_file, nodata=no_data_value)

        # ==================================================================
        # PASO 3: PROCESAMIENTO HIDROLÓGICO COMPLETO
        # ==================================================================
        pit_filled_dem = grid.fill_pits(dem)
        flooded_dem = grid.fill_depressions(pit_filled_dem)
        conditioned_dem = grid.resolve_flats(flooded_dem)
        flowdir = grid.flowdir(conditioned_dem)
        acc = grid.accumulation(flowdir)
        x_snap, y_snap = grid.snap_to_mask(acc > umbral_rio_export, (x, y))
        catch = grid.catchment(x=x_snap, y=y_snap, fdir=flowdir, xytype="coordinate")

        # ==================================================================
        # INICIALIZACIÓN DE PYFLWDIR PARA ANÁLISIS ADICIONALES
        # ==================================================================
        with rasterio.open(dem_file) as src:
            dem_data = src.read(1)
            transform = src.transform
            crs = src.crs
        flw = pyflwdir.from_dem(data=dem_data, nodata=no_data_value, transform=transform, latlon=False)
        upa = flw.upstream_area(unit='cell')

        # ==================================================================
        # GRÁFICO 1: MOSAICO DE CARACTERÍSTICAS
        # ==================================================================
        grid_para_plot = Grid.from_raster(dem_file, nodata=no_data_value)
        grid_para_plot.clip_to(catch)
        plot_extent = grid_para_plot.extent
        fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes[0, 0].imshow(grid_para_plot.view(catch, nodata=np.nan), extent=plot_extent, cmap='Reds_r')
        axes[0, 0].set_title("Extensión de la Cuenca")
        # --- CÁLCULO Y VISUALIZACIÓN DEL ÁREA ---
        num_celdas_cuenca = np.sum(catch)
        area_pixel_m2 = abs(grid.affine.a * grid.affine.e)
        area_cuenca_km2 = (num_celdas_cuenca * area_pixel_m2) / 1_000_000
        area_texto = f'{area_cuenca_km2:.1f} km²'
        centro_x = (plot_extent[0] + plot_extent[1]) / 2
        centro_y = (plot_extent[2] + plot_extent[3]) / 2
        axes[0, 0].text(centro_x, centro_y, area_texto,
             ha='center', va='center', color='white',
             fontsize=12, fontweight='bold')
        im_dem = axes[0, 1].imshow(grid_para_plot.view(conditioned_dem, nodata=np.nan), extent=plot_extent, cmap='terrain')
        axes[0, 1].set_title("Elevación")
        fig1.colorbar(im_dem, ax=axes[0, 1], label='Elevación (m)', shrink=0.7)
        im_fdir = axes[1, 0].imshow(grid_para_plot.view(flowdir, nodata=np.nan), extent=plot_extent, cmap='twilight')
        axes[1, 0].set_title("Dirección de Flujo")
        im_acc = axes[1, 1].imshow(grid_para_plot.view(acc, nodata=np.nan), extent=plot_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.max()))
        axes[1, 1].set_title("Acumulación de Flujo")
        fig1.colorbar(im_acc, ax=axes[1, 1], label='Nº celdas', shrink=0.7)
        # --- AJUSTE TAMAÑO LETRA EN TODOS LOS EJES ---
        axes[0, 0].tick_params(axis='both', labelsize=6)
        axes[0, 1].tick_params(axis='both', labelsize=6)
        axes[1, 0].tick_params(axis='both', labelsize=6)
        axes[1, 1].tick_params(axis='both', labelsize=6)
        plt.suptitle("Características de la Cuenca Delineada", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        results['plots']['grafico_1_mosaico'] = fig_to_base64(fig1)

        # ==================================================================
        # CÁLCULOS DEL LONGEST FLOW PATH (LFP)
        # ==================================================================
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
            direction = flowdir[current_row, current_col]
            if direction == 0: break
            row_move, col_move = dirmap[direction]; current_row += row_move; current_col += col_move

        # # ==================================================================
        # # GRÁFICO 3/7 UNIFICADO: LFP y Red Fluvial de Strahler
        # # ==================================================================
        # stream_mask_strahler = upa > umbral_rio_export
        # strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        # stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        # gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=crs)
        # shapes_cuenca_clip = features.shapes(catch.astype(np.uint8), mask=catch, transform=transform)
        # cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        # gdf_cuenca_clip = gpd.GeoDataFrame(geometry=[cuenca_geom_clip], crs=crs)
        # gdf_streams_recortado = gpd.clip(gdf_streams_full, gdf_cuenca_clip)
        # dem_cuenca_recortada = grid_para_plot.view(conditioned_dem, nodata=np.nan)
        # fig37, axes = plt.subplots(1, 2, figsize=(18, 9))
        # ax1 = axes[0]
        # im1 = ax1.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='terrain', zorder=1)
        # fig37.colorbar(im1, ax=ax1, label='Elevación (m)', shrink=0.6)
        # x_coords, y_coords = zip(*lfp_coords)
        # ax1.plot(x_coords, y_coords, color='red', linewidth=2, label='Longest Flow Path', zorder=2)
        # ax1.set_title('Camino de Flujo Más Largo (LFP)')
        # ax1.legend(); ax1.grid(True, linestyle='--', alpha=0.6)
        # ax2 = axes[1]
        # ax2.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='Greys_r', alpha=0.8, zorder=1)
        # gdf_streams_recortado_clean = gdf_streams_recortado[gdf_streams_recortado.geom_type.isin(["LineString", "MultiLineString"])]
        # if not gdf_streams_recortado_clean.empty:
        #     gdf_streams_recortado_clean.plot(ax=ax2, column='strord', cmap='Blues', zorder=2, legend=True, categorical=True, legend_kwds={'title': "Orden de Strahler", 'loc': 'upper right'})
        # ax2.set_title('Red Fluvial por Orden de Strahler')
        # plt.suptitle("Análisis Morfométrico de la Cuenca", fontsize=16)
        # plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        # results['plots']['grafico_3_7_lfp_strahler'] = fig_to_base64(fig37)
        
        
        # ==================================================================
        # GRÁFICO 3/7 UNIFICADO: LFP y Red Fluvial de Strahler (VERSIÓN ESTABLE ORIGINAL)
        # ==================================================================
        stream_mask_strahler = upa > umbral_rio_export
        strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=crs)
        
        shapes_cuenca_clip = features.shapes(catch.astype(np.uint8), mask=catch, transform=transform)
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca_clip = gpd.GeoDataFrame(geometry=[cuenca_geom_clip], crs=crs)
        gdf_streams_recortado = gpd.clip(gdf_streams_full, gdf_cuenca_clip)
        
        dem_cuenca_recortada = grid_para_plot.view(conditioned_dem, nodata=np.nan)
        
        fig37, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1 = axes[0]
        im1 = ax1.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='terrain', zorder=1)
        fig37.colorbar(im1, ax=ax1, label='Elevación (m)', shrink=0.6)
        x_coords, y_coords = zip(*lfp_coords)
        ax1.plot(x_coords, y_coords, color='red', linewidth=2, label='Longest Flow Path', zorder=2)
        ax1.set_title('Camino de Flujo Más Largo (LFP)')
        ax1.legend(); ax1.grid(True, linestyle='--', alpha=0.6)
        
        ax2 = axes[1]
        ax2.imshow(dem_cuenca_recortada, extent=grid_para_plot.extent, cmap='Greys_r', alpha=0.8, zorder=1)
        
        gdf_streams_recortado_clean = gdf_streams_recortado[gdf_streams_recortado.geom_type.isin(["LineString", "MultiLineString"])]
        if not gdf_streams_recortado_clean.empty:
            gdf_streams_recortado_clean.plot(ax=ax2, column='strord', cmap='Blues', zorder=2, legend=True, categorical=True, legend_kwds={'title': "Orden de Strahler", 'loc': 'upper right'})
        else:
            # Texto para cuando no se encuentran ríos
            ax2.text(0.5, 0.5, 'No se encontraron ríos\ncon el umbral actual', 
                     horizontalalignment='center', verticalalignment='center', 
                     transform=ax2.transAxes, bbox=dict(facecolor='white', alpha=0.8))

        ax2.set_title('Red Fluvial por Orden de Strahler')
        plt.suptitle("Análisis Morfométrico de la Cuenca", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        results['plots']['grafico_3_7_lfp_strahler'] = fig_to_base64(fig37)
        
        
        
        
        # ==================================================================
        # GRÁFICO 4: PERFIL LONGITUDINAL Y MÉTRICAS LFP
        # ==================================================================
        with rasterio.open(dem_file) as src: inv_transform = ~src.transform
        profile_elevations = []
        valid_lfp_coords = []
        for x_c, y_c in lfp_coords:
            try:
                col, row = inv_transform * (x_c, y_c)
                elevation = conditioned_dem[int(row), int(col)]
                profile_elevations.append(elevation)
                valid_lfp_coords.append((x_c, y_c))
            except IndexError: continue
        profile_distances = [0]
        for i in range(1, len(valid_lfp_coords)):
            x1, y1 = valid_lfp_coords[i-1]; x2, y2 = valid_lfp_coords[i]
            segment_dist = np.sqrt((x2 - x1)**2 + (y2 - y1)**2)
            profile_distances.append(profile_distances[-1] + segment_dist)
        results['lfp_profile_data'] = {"distancia_m": profile_distances, "elevacion_m": profile_elevations}
        
        # Métricas LFP
        longitud_total_m = profile_distances[-1]
        cota_ini = profile_elevations[0]
        cota_fin = profile_elevations[-1]
        desnivel = abs(cota_fin - cota_ini)
        pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
        tc_h = (0.87 * (longitud_total_m**2 / (1000 * desnivel))**0.385) if desnivel > 0 else 0
        results['lfp_metrics'] = {
            "cota_ini_m": cota_ini, "cota_fin_m": cota_fin, "longitud_m": longitud_total_m,
            "pendiente_media": pendiente_media, "tc_h": tc_h, "tc_min": tc_h * 60
        }

        fig4, ax = plt.subplots(figsize=(12, 6))
        ax.plot(np.array(profile_distances) / 1000, profile_elevations, color='darkblue')
        ax.fill_between(np.array(profile_distances) / 1000, profile_elevations, alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del LFP')
        ax.set_xlabel('Distancia (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True)
        results['plots']['grafico_4_perfil_lfp'] = fig_to_base64(fig4)

        # ==================================================================
        # GRÁFICOS 5 y 6: HISTOGRAMA Y CURVA HIPSOMÉTRICA
        # ==================================================================
        elevaciones_cuenca = conditioned_dem[catch]
        fig56, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        ax1.hist(elevaciones_cuenca, bins=50, color='skyblue', edgecolor='black')
        ax1.set_title('Distribución de Elevaciones'); ax1.set_xlabel('Elevación (m)'); ax1.set_ylabel('Frecuencia')
        
        # elev_sorted = np.sort(elevaciones_cuenca)[::-1]
        # cell_area = abs(transform.a * transform.e)
        # area_acumulada = np.arange(1, len(elev_sorted) + 1) * cell_area
        # area_normalizada = area_acumulada / area_acumulada.max()
        # results['hypsometric_data'] = {"area_normalizada": area_normalizada.tolist(), "elevacion": elev_sorted.tolist()}
        # elev_min, elev_max = elev_sorted.min(), elev_sorted.max()
        # ax2.plot(area_normalizada, elev_sorted, color='red')
        # ax2.fill_between(area_normalizada, elev_sorted, elev_min, color='red', alpha=0.2)
        # ax2.set_title('Curva Hipsométrica'); ax2.set_xlabel('Fracción de área (a/A)'); ax2.set_ylabel('Elevación (m)')
        
        # ▼▼▼ ESTE ES EL NUEVO BLOQUE COMPLETO Y CORRECTO ▼▼▼
        # --- Cálculos para la Curva Hipsométrica ---
        elev_sorted = np.sort(elevaciones_cuenca)[::-1]
        cell_area = abs(transform.a * transform.e)
        area_acumulada = np.arange(1, len(elev_sorted) + 1) * cell_area
        area_normalizada = area_acumulada / area_acumulada.max()
        elev_normalizada = (elev_sorted - elev_sorted.min()) / (elev_sorted.max() - elev_sorted.min())
        integral_hipsometrica = abs(np.trapz(area_normalizada, x=elev_normalizada))
        results['hypsometric_data'] = {"area_normalizada": area_normalizada.tolist(), "elevacion": elev_sorted.tolist()}
        
        # --- Dibujo del gráfico en ax2 ---
        elev_min, elev_max = elev_sorted.min(), elev_sorted.max()
        ax2.plot(area_normalizada, elev_sorted, color='red', linewidth=2, label='Curva Hipsométrica')
        ax2.fill_between(area_normalizada, elev_sorted, elev_min, color='red', alpha=0.2)
        # Añadir la línea de referencia
        ax2.plot([0, 1], [elev_max, elev_min], color='gray', linestyle='--', linewidth=2, label='Referencia lineal (HI=0.5)')
        # Añadir el texto de la integral
        ax2.text(0.05, 0.1, f'Integral Hipsométrica: {integral_hipsometrica:.3f}', 
                 transform=ax2.transAxes, fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
        ax2.set_title('Curva Hipsométrica')
        ax2.set_xlabel('Fracción de área (a/A)')
        ax2.set_ylabel('Elevación (m)')
        ax2.legend()
        ax2.set_xlim(0, 1)
        # ▲▲▲ FIN DEL BLOQUE ▲▲▲        
        
        results['plots']['grafico_5_6_histo_hipso'] = fig_to_base64(fig56)

        # ==================================================================
        # GRÁFICO 11: HAND Y LLANURAS DE INUNDACIÓN
        # ==================================================================
        upa_km2 = flw.upstream_area(unit='km2')
        upa_min_threshold = 1.0 # ▼▼▼ Umbral de área de flujo (km2)  ▼▼▼
        hand = flw.hand(drain=upa_km2 > upa_min_threshold, elevtn=dem_data)
        floodplains = flw.floodplains(elevtn=dem_data, uparea=upa_km2, upa_min=upa_min_threshold)
        # --- PREPARACIÓN DE DATOS (SIN RECORTARLOS, PARA MÁXIMA ESTABILIDAD) ---
        # Simplemente enmascaramos los arrays completos, igual que en tu código original que funcionaba.
        dem_background = np.where(catch, conditioned_dem, np.nan)
        hand_masked = np.where(catch & (hand > 0), hand, np.nan)
        floodplains_masked = np.where(catch & (floodplains > 0), 1.0, np.nan)

        # --- VISUALIZACIÓN ---
        fig11, axes = plt.subplots(1, 2, figsize=(18, 9))
        ax1, ax2 = axes[0], axes[1]

        # Extraemos los límites exactos de la cuenca del grid que SÍ está bien recortado
        xmin, xmax, ymin, ymax = grid_para_plot.extent

        # --- Gráfico de la izquierda: HAND ---
        # Dibujamos los arrays completos y LUEGO forzamos el zoom
        ax1.imshow(dem_background, extent=grid.extent, cmap='Greys_r', zorder=1)
        vmax_hand = np.nanpercentile(hand_masked, 98) if not np.all(np.isnan(hand_masked)) else 1
        im_hand = ax1.imshow(hand_masked, extent=grid.extent, cmap='gist_earth_r', alpha=0.7, zorder=2, vmin=0, vmax=vmax_hand)
        fig11.colorbar(im_hand, ax=ax1, label='Altura sobre drenaje (m)', shrink=0.6)
        ax1.set_title(f'Altura Sobre Drenaje (HAND)\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax1.set_xlabel('Coordenada X (UTM)')
        ax1.set_ylabel('Coordenada Y (UTM)')
        ax1.grid(True, linestyle='--', alpha=0.6)
        # Forzamos el encuadre a los límites de la cuenca
        ax1.set_xlim(xmin, xmax)
        ax1.set_ylim(ymin, ymax)

        # --- Gráfico de la derecha: Llanuras ---
        # Dibujamos los arrays completos y LUEGO forzamos el zoom
        ax2.imshow(dem_background, extent=grid.extent, cmap='Greys', zorder=1)
        ax2.imshow(floodplains_masked, extent=grid.extent, cmap='Blues', alpha=0.7, zorder=2, vmin=0, vmax=1)
        ax2.set_title(f'Llanuras de Inundación\n(upa_min > {upa_min_threshold:.1f} km²)')
        ax2.set_xlabel('Coordenada X (UTM)')
        ax2.set_ylabel('')
        ax2.grid(True, linestyle='--', alpha=0.6)
        # Forzamos el encuadre a los límites de la cuenca
        ax2.set_xlim(xmin, xmax)
        ax2.set_ylim(ymin, ymax)

        # --- Título y ajuste final ---
        fig11.suptitle("Índices de Elevación (HAND y Llanuras de Inundación)", fontsize=16)
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        
        results['plots']['grafico_11_llanuras'] = fig_to_base64(fig11)

        # ==================================================================
        # EXPORTACIÓN A GEOMETRÍAS (PARA DEVOLVER EN JSON)
        # ==================================================================
        output_crs = "EPSG:25830"
        
        # Punto de salida
        punto_geom = Point(x_snap, y_snap)
        gdf_punto = gpd.GeoDataFrame({'id': [1], 'geometry': [punto_geom]}, crs=output_crs)
        results['downloads']['punto_salida'] = gdf_punto.to_json()

        # LFP
        lfp_geom = LineString(lfp_coords)
        gdf_lfp = gpd.GeoDataFrame({'id': [1], 'geometry': [lfp_geom]}, crs=output_crs)
        results['downloads']['lfp'] = gdf_lfp.to_json()

        # Cuenca
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom_clip]}, crs=output_crs)
        results['downloads']['cuenca'] = gdf_cuenca.to_json()

        # Ríos (umbral de cálculo)
        river_raster = acc > umbral_rio_export
        shapes_rios = features.shapes(river_raster.astype(np.uint8), mask=river_raster, transform=transform)
        river_geoms = [LineString(s['coordinates'][0]) for s, v in shapes_rios if v == 1]
        gdf_rios_full = gpd.GeoDataFrame(geometry=river_geoms, crs=output_crs)
        gdf_rios_recortado = gpd.clip(gdf_rios_full, gdf_cuenca)
        gdf_rios_final = gdf_rios_recortado[gdf_rios_recortado.geom_type == 'LineString']
        results['downloads']['rios'] = gdf_rios_final.to_json()

        # Ríos de Strahler (ya calculados)
        results['downloads']['rios_strahler'] = gdf_streams_recortado_clean.to_json()

        results['success'] = True
        results['message'] = "Cálculo completado con éxito."

    except Exception as e:
        results['message'] = f"Error en el script delinear_cuenca.py: {traceback.format_exc()}"
        results['success'] = False

    # Imprimir el JSON final a la salida estándar para que el script principal lo capture
    print(json.dumps(results))

if __name__ == "__main__":
    main()
