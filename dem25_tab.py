# dem25_tab.py (Versión refactorizada con flujo secuencial)

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
LIMITE_AREA_KM2 = 15000
AREA_PROCESSING_LIMIT_KM2 = 50000

# ==============================================================================
# SECCIÓN 3: LÓGICA DE ANÁLISIS HIDROLÓGICO (REFACTORIZADA EN PASOS)
# ==============================================================================

def fig_to_base64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

# --- INICIO: NUEVA FUNCIÓN PASO 1 ---
@st.cache_data(show_spinner="Paso 1: Delineando cuenca con PySheds...")
def delinear_cuenca_desde_punto(_dem_bytes, outlet_coords_wgs84, umbral_rio_export):
    results = {"success": False, "message": ""}
    try:
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                dem_crs = src.crs
                out_transform = src.transform
                no_data_value = src.nodata or -32768
                dem_array = src.read(1)

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

        shapes_cuenca_clip = features.shapes(catch.astype(np.uint8), mask=catch, transform=out_transform)
        cuenca_geom_clip = [Polygon(s['coordinates'][0]) for s, v in shapes_cuenca_clip if v == 1][0]
        gdf_cuenca = gpd.GeoDataFrame({'id': [1], 'geometry': [cuenca_geom_clip]}, crs=dem_crs)

        results.update({
            "success": True,
            "message": "Cuenca delineada con éxito.",
            "pysheds_data": {
                "grid": grid,
                "conditioned_dem": conditioned_dem,
                "flowdir": flowdir,
                "acc": acc,
                "catch": catch,
                "x_snap": x_snap,
                "y_snap": y_snap,
                "out_transform": out_transform,
                "dem_crs": dem_crs,
                "dem_path_for_pysheds": dem_path_for_pysheds
            },
            "downloads": {
                "cuenca": gdf_cuenca.to_json(),
                "punto_salida": gpd.GeoDataFrame({'id': [1], 'geometry': [Point(x_snap, y_snap)]}, crs=dem_crs).to_json()
            }
        })
        return results

    except Exception as e:
        results['message'] = f"Error en la delineación de la cuenca: {e}\n{traceback.format_exc()}"
        return results
# --- FIN: NUEVA FUNCIÓN PASO 1 ---


# --- INICIO: NUEVA FUNCIÓN PASO 2 ---
@st.cache_data(show_spinner="Paso 2: Calculando LFP y red fluvial...")
def calcular_morfometria_cuenca(pysheds_data, umbral_rio_export):
    results = {"success": False, "message": ""}
    try:
        grid = pysheds_data["grid"]
        flowdir = pysheds_data["flowdir"]
        catch = pysheds_data["catch"]
        x_snap, y_snap = pysheds_data["x_snap"], pysheds_data["y_snap"]
        conditioned_dem = pysheds_data["conditioned_dem"]
        dem_path_for_pysheds = pysheds_data["dem_path_for_pysheds"]
        out_transform = pysheds_data["out_transform"]
        dem_crs = pysheds_data["dem_crs"]

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
        
        # PERFIL LONGITUDINAL Y MÉTRICAS LFP
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
        
        longitud_total_m = profile_distances[-1] if profile_distances else 0
        cota_ini, cota_fin = (profile_elevations[0], profile_elevations[-1]) if profile_elevations else (0,0)
        desnivel = abs(cota_fin - cota_ini)
        pendiente_media = desnivel / longitud_total_m if longitud_total_m > 0 else 0
        tc_h = (0.87 * (longitud_total_m**2 / (1000 * desnivel))**0.385) if desnivel > 0 else 0
        
        # CÁLCULO RED FLUVIAL CON PYFLWDIR
        flw = pyflwdir.from_dem(data=conditioned_dem, nodata=grid.nodata, transform=out_transform, latlon=False)
        upa = flw.upstream_area(unit='cell')
        stream_mask_strahler = upa > umbral_rio_export
        strahler_orders = flw.stream_order(mask=stream_mask_strahler, type='strahler')
        stream_features = flw.streams(mask=stream_mask_strahler, strord=strahler_orders)
        gdf_streams_full = gpd.GeoDataFrame.from_features(stream_features, crs=dem_crs)
        
        results.update({
            "success": True,
            "message": "Morfometría calculada con éxito.",
            "morphometry_data": {
                "lfp_profile_data": {"distancia_m": profile_distances, "elevacion_m": profile_elevations},
                "lfp_metrics": {"cota_ini_m": cota_ini, "cota_fin_m": cota_fin, "longitud_m": longitud_total_m, "pendiente_media": pendiente_media, "tc_h": tc_h, "tc_min": tc_h * 60}
            },
            "downloads": {
                "lfp": gpd.GeoDataFrame({'id': [1], 'geometry': [LineString(lfp_coords)]}, crs=dem_crs).to_json(),
                "rios_strahler": gdf_streams_full.to_json()
            }
        })
        return results

    except Exception as e:
        results['message'] = f"Error en el cálculo de la morfometría: {e}\n{traceback.format_exc()}"
        return results
# --- FIN: NUEVA FUNCIÓN PASO 2 ---


# --- INICIO: NUEVA FUNCIÓN PASO 3 ---
@st.cache_data(show_spinner="Paso 3: Generando gráficos y análisis finales...")
def generar_graficos_y_analisis(pysheds_data, morphometry_data, _cuenca_geojson, umbral_rio_export):
    results = {"success": False, "message": ""}
    try:
        grid = pysheds_data["grid"]
        catch = pysheds_data["catch"]
        conditioned_dem = pysheds_data["conditioned_dem"]
        flowdir = pysheds_data["flowdir"]
        acc = pysheds_data["acc"]
        dem_path_for_pysheds = pysheds_data["dem_path_for_pysheds"]
        out_transform = pysheds_data["out_transform"]
        lfp_profile_data = morphometry_data["lfp_profile_data"]
        
        plots = {}

        # GRÁFICO 1: MOSAICO
        grid_para_plot = Grid.from_raster(dem_path_for_pysheds, nodata=grid.nodata)
        grid_para_plot.clip_to(catch)
        plot_extent = grid_para_plot.extent
        fig1, axes = plt.subplots(2, 2, figsize=(12, 10))
        axes[0, 0].imshow(grid_para_plot.view(catch, nodata=np.nan), extent=plot_extent, cmap='Reds_r')
        axes[0, 0].set_title("Extensión de la Cuenca")
        im_dem = axes[0, 1].imshow(grid_para_plot.view(conditioned_dem, nodata=np.nan), extent=plot_extent, cmap='terrain')
        axes[0, 1].set_title("Elevación")
        fig1.colorbar(im_dem, ax=axes[0, 1], label='Elevación (m)', shrink=0.7)
        axes[1, 0].imshow(grid_para_plot.view(flowdir, nodata=np.nan), extent=plot_extent, cmap='twilight')
        axes[1, 0].set_title("Dirección de Flujo")
        im_acc = axes[1, 1].imshow(grid_para_plot.view(acc, nodata=np.nan), extent=plot_extent, cmap='cubehelix', norm=colors.LogNorm(vmin=1, vmax=acc.max()))
        axes[1, 1].set_title("Acumulación de Flujo")
        fig1.colorbar(im_acc, ax=axes[1, 1], label='Nº celdas', shrink=0.7)
        plt.tight_layout()
        plots['grafico_1_mosaico'] = fig_to_base64(fig1)

        # GRÁFICO 4: PERFIL LFP
        fig4, ax = plt.subplots(figsize=(12, 6))
        ax.plot(np.array(lfp_profile_data["distancia_m"]) / 1000, lfp_profile_data["elevacion_m"], color='darkblue')
        ax.fill_between(np.array(lfp_profile_data["distancia_m"]) / 1000, lfp_profile_data["elevacion_m"], alpha=0.2, color='lightblue')
        ax.set_title('Perfil Longitudinal del LFP'); ax.set_xlabel('Distancia (km)'); ax.set_ylabel('Elevación (m)'); ax.grid(True)
        plots['grafico_4_perfil_lfp'] = fig_to_base64(fig4)

        # GRÁFICOS 5 y 6: HISTOGRAMA Y CURVA HIPSOMÉTRICA
        elevaciones_cuenca = conditioned_dem[catch]
        fig56, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
        ax1.hist(elevaciones_cuenca, bins=50, color='skyblue', edgecolor='black')
        ax1.set_title('Distribución de Elevaciones'); ax1.set_xlabel('Elevación (m)'); ax1.set_ylabel('Frecuencia')
        elev_sorted = np.sort(elevaciones_cuenca)[::-1]
        cell_area = abs(out_transform.a * out_transform.e)
        area_acumulada = np.arange(1, len(elev_sorted) + 1) * cell_area
        area_normalizada = area_acumulada / area_acumulada.max()
        ax2.plot(area_normalizada, elev_sorted, color='red')
        ax2.set_title('Curva Hipsométrica'); ax2.set_xlabel('Fracción de área (a/A)'); ax2.set_ylabel('Elevación (m)')
        plots['grafico_5_6_histo_hipso'] = fig_to_base64(fig56)
        hypsometric_data = {"area_normalizada": area_normalizada.tolist(), "elevacion": elev_sorted.tolist()}

        # GRÁFICO 11: HAND Y LLANURAS DE INUNDACIÓN
        flw = pyflwdir.from_dem(data=conditioned_dem, nodata=grid.nodata, transform=out_transform, latlon=False)
        upa_km2 = flw.upstream_area(unit='km2')
        upa_min_threshold = (umbral_rio_export * cell_area) / 1_000_000 # umbral en km2
        hand = flw.hand(drain=upa_km2 > upa_min_threshold, elevtn=conditioned_dem)
        hand_masked = np.where(catch & (hand > 0), hand, np.nan)
        fig11, ax1 = plt.subplots(figsize=(9, 9))
        im_hand = ax1.imshow(hand_masked, extent=grid.extent, cmap='gist_earth_r', alpha=0.9, vmin=0, vmax=np.nanpercentile(hand_masked, 98))
        fig11.colorbar(im_hand, ax=ax1, label='Altura sobre drenaje (m)', shrink=0.6)
        ax1.set_title(f'Altura Sobre Drenaje (HAND)')
        plots['grafico_11_llanuras'] = fig_to_base64(fig11)

        results.update({
            "success": True,
            "message": "Análisis finalizado.",
            "visualization_data": {
                "plots": plots,
                "hypsometric_data": hypsometric_data
            }
        })
        return results

    except Exception as e:
        results['message'] = f"Error generando los gráficos: {e}\n{traceback.format_exc()}"
        return results
# --- FIN: NUEVA FUNCIÓN PASO 3 ---


# ==============================================================================
# SECCIÓN 4: FUNCIONES AUXILIARES DE LA PESTAÑA (SIN CAMBIOS)
# ==============================================================================

@st.cache_data(show_spinner="Procesando la cuenca + buffer...")
def procesar_datos_cuenca(basin_geojson_str):
    try:
        local_zip_path = get_local_path_from_url(HOJAS_MTN25_PATH)
        if not local_zip_path:
            st.error("No se pudo obtener el archivo de hojas del MTN25.")
            return None
        hojas_gdf = gpd.read_file(local_zip_path)
        cuenca_gdf = gpd.read_file(basin_geojson_str).set_crs("EPSG:4326")
        buffer_gdf = gpd.GeoDataFrame(geometry=cuenca_gdf.to_crs("EPSG:25830").buffer(BUFFER_METROS), crs="EPSG:25830")
        geom_para_interseccion = buffer_gdf.to_crs(hojas_gdf.crs)
        hojas = gpd.sjoin(hojas_gdf, geom_para_interseccion, how="inner", predicate="intersects").drop_duplicates(subset=['numero'])
        
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
        return { "cuenca_gdf": cuenca_gdf, "buffer_gdf": buffer_gdf.to_crs("EPSG:4326"), "hojas": hojas, "dem_bytes": dem_bytes, "dem_array": dem_recortado, "shp_zip_bytes": shp_zip_bytes }
    except Exception as e:
        st.error(f"Error inesperado durante el procesamiento de la cuenca: {e}")
        st.exception(e)
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
        if max_val == min_val:
            img_acc = np.zeros_like(scaled_acc_for_viz, dtype=np.uint8)
        else:
            scaled_acc_nan_as_zero = np.nan_to_num(scaled_acc_for_viz, nan=min_val)
            img_acc = (255 * (scaled_acc_nan_as_zero - min_val) / (max_val - min_val)).astype(np.uint8)
        return img_acc
    except Exception as e:
        st.error(f"Error en el pre-cálculo con pyflwdir: {e}")
        return None

# ==============================================================================
# SECCIÓN 5: FUNCIÓN PRINCIPAL DEL FRONTEND (RENDERIZADO DE LA PESTAÑA)
# ==============================================================================

def render_dem25_tab():
    st.header("Generador de Modelos Digitales del Terreno (MDT25)")
    st.info("Esta herramienta permite delinear una cuenca hidrográfica y analizar su morfometría a partir de un punto de desagüe seleccionado sobre un MDT25.")

    if not st.session_state.get('basin_geojson'):
        st.warning("⬅️ Por favor, primero calcule una cuenca en la Pestaña 1 para definir un área de interés.")
        st.stop()

    if st.button("🗺️ Cargar Área de Análisis (Cuenca + Buffer)", use_container_width=True):
        with st.spinner("Procesando recorte del DEM..."):
            results = procesar_datos_cuenca(st.session_state.basin_geojson)
        if results:
            st.session_state.cuenca_results = results
            st.session_state.precalculated_acc = precalcular_acumulacion(results['dem_bytes'])
            # Limpiar estados de cálculos anteriores
            st.session_state.pop('pysheds_data', None)
            st.session_state.pop('morphometry_data', None)
            st.session_state.pop('visualization_data', None)
            st.session_state.pop('outlet_coords', None)
            st.session_state.show_dem25_content = True
            st.rerun()
        else:
            st.error("No se pudo procesar el área de la cuenca.")
            st.session_state.show_dem25_content = False

    if not st.session_state.get('show_dem25_content'):
        st.info("Haga clic en el botón de arriba para empezar.")
        return

    st.subheader("Paso 1: Seleccione un punto de salida (outlet) en el mapa")
    st.info("Haga clic en el mapa para definir el punto de desagüe. La capa semitransparente muestra las zonas de mayor acumulación de flujo para guiar su selección.")
    
    map_select = folium.Map(tiles="CartoDB positron")
    buffer_gdf = st.session_state.cuenca_results['buffer_gdf']
    buffer_layer_select = folium.GeoJson(buffer_gdf, name="Área de Análisis").add_to(map_select)
    map_select.fit_bounds(buffer_layer_select.get_bounds())
    
    if st.session_state.get('precalculated_acc') is not None:
        bounds = buffer_gdf.total_bounds
        img = Image.fromarray(st.session_state.precalculated_acc)
        buffered = io.BytesIO(); img.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode()
        folium.raster_layers.ImageOverlay(image=f"data:image/png;base64,{img_str}", bounds=[[bounds[1], bounds[0]], [bounds[3], bounds[2]]], opacity=0.6, name='Referencia de Cauces').add_to(map_select)

    if st.session_state.get('outlet_coords'):
        coords = st.session_state.outlet_coords
        folium.Marker([coords['lat'], coords['lng']], popup="Punto de Salida Seleccionado", icon=folium.Icon(color='orange')).add_to(map_select)
    
    folium.LayerControl().add_to(map_select)
    map_output_select = st_folium(map_select, key="map_select", use_container_width=True, height=500, returned_objects=['last_clicked'])

    if map_output_select.get("last_clicked"):
        if st.session_state.get('outlet_coords') != map_output_select["last_clicked"]:
            st.session_state.outlet_coords = map_output_select["last_clicked"]
            # Al seleccionar un nuevo punto, se resetean los cálculos posteriores
            st.session_state.pop('pysheds_data', None)
            st.session_state.pop('morphometry_data', None)
            st.session_state.pop('visualization_data', None)
            st.rerun()

    st.divider()
    st.subheader("Paso 2: Ejecute el análisis hidrológico secuencialmente")
    
    CELL_AREA_KM2 = 0.000625
    umbral_celdas = st.slider(label="Umbral de celdas para definir cauces", min_value=10, max_value=10000, value=1600, step=10, help=f"Un umbral de 1600 celdas equivale a un área de drenaje mínima de 1 km².")
    
    # --- MODIFICACIÓN: Lógica de cálculo secuencial ---
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("1. Delinear Cuenca", use_container_width=True, disabled=not st.session_state.get('outlet_coords')):
            results = delinear_cuenca_desde_punto(st.session_state.cuenca_results['dem_bytes'], st.session_state.outlet_coords, umbral_celdas)
            if results['success']:
                st.session_state.pysheds_data = results['pysheds_data']
                st.session_state.delineated_downloads = results['downloads']
                st.success("Paso 1 completado.")
            else:
                st.error("Falló el Paso 1.")
                st.code(results['message'])
            st.rerun()

    with col2:
        if st.button("2. Analizar LFP y Red Fluvial", use_container_width=True, disabled=not st.session_state.get('pysheds_data')):
            results = calcular_morfometria_cuenca(st.session_state.pysheds_data, umbral_celdas)
            if results['success']:
                st.session_state.morphometry_data = results['morphometry_data']
                st.session_state.morphometry_downloads = results['downloads']
                st.success("Paso 2 completado.")
            else:
                st.error("Falló el Paso 2.")
                st.code(results['message'])
            st.rerun()

    with col3:
        if st.button("3. Generar Gráficos Finales", use_container_width=True, disabled=not st.session_state.get('morphometry_data')):
            results = generar_graficos_y_analisis(st.session_state.pysheds_data, st.session_state.morphometry_data, st.session_state.delineated_downloads['cuenca'], umbral_celdas)
            if results['success']:
                st.session_state.visualization_data = results['visualization_data']
                st.success("Paso 3 completado.")
            else:
                st.error("Falló el Paso 3.")
                st.code(results['message'])
            st.rerun()

    # --- SECCIÓN DE VISUALIZACIÓN DE RESULTADOS ---
    if st.session_state.get('pysheds_data'):
        st.divider()
        st.header("Resultados del Análisis")

        # MAPA DE RESULTADOS
        m_results = folium.Map(tiles="CartoDB positron")
        gdf_cuenca = gpd.read_file(st.session_state.delineated_downloads["cuenca"]).to_crs("EPSG:4326")
        folium.GeoJson(gdf_cuenca, name="Cuenca Delineada", style_function=lambda x: {'color': '#FF0000', 'weight': 2.5, 'fillOpacity': 0.2}).add_to(m_results)
        
        if st.session_state.get('morphometry_data'):
            gdf_lfp = gpd.read_file(st.session_state.morphometry_downloads["lfp"]).to_crs("EPSG:4326")
            folium.GeoJson(gdf_lfp, name="Longest Flow Path (LFP)", style_function=lambda x: {'color': '#FFFF00', 'weight': 4}).add_to(m_results)
            
            gdf_rios = gpd.read_file(st.session_state.morphometry_downloads["rios_strahler"]).to_crs("EPSG:4326")
            gdf_rios_recortado = gpd.clip(gdf_rios, gdf_cuenca)
            if not gdf_rios_recortado.empty:
                folium.GeoJson(gdf_rios_recortado, name="Red Fluvial (Strahler)", style_function=lambda f: {'color': 'blue', 'weight': f['properties']['strord'] / 2 + 1}).add_to(m_results)

        m_results.fit_bounds(gdf_cuenca.total_bounds[[1, 0, 3, 2]].tolist())
        folium.LayerControl().add_to(m_results)
        st_folium(m_results, key="results_map", use_container_width=True, height=600)

        # MÉTRICAS
        area_cuenca_km2 = gpd.read_file(st.session_state.delineated_downloads["cuenca"]).area.sum() / 1_000_000
        st.metric("Área de la Cuenca Delineada", f"{area_cuenca_km2:.4f} km²")

        if st.session_state.get('morphometry_data'):
            st.subheader("Métricas del Camino de Flujo Principal (LFP)")
            metrics = st.session_state.morphometry_data["lfp_metrics"]
            m_col1, m_col2, m_col3 = st.columns(3)
            with m_col1: st.metric("Longitud LFP", f"{metrics.get('longitud_m', 0):.2f} m")
            with m_col2: st.metric("Pendiente Media", f"{metrics.get('pendiente_media', 0):.4f} m/m")
            with m_col3: st.metric("Tiempo Concentración", f"{metrics.get('tc_h', 0):.3f} h")

        # GRÁFICOS Y DESCARGAS FINALES
        if st.session_state.get('visualization_data'):
            st.subheader("Gráficos Generados")
            plots = st.session_state.visualization_data["plots"]
            plot_titles = {"grafico_1_mosaico": "Características de la Cuenca", "grafico_4_perfil_lfp": "Perfil Longitudinal del LFP", "grafico_5_6_histo_hipso": "Histograma y Curva Hipsométrica", "grafico_11_llanuras": "Altura Sobre Drenaje (HAND)"}
            for key, title in plot_titles.items():
                if key in plots: st.image(io.BytesIO(base64.b64decode(plots[key])), caption=title, use_container_width=True)

            st.subheader("Descargas GIS y Datos")
            d_col1, d_col2, d_col3, d_col4 = st.columns(4)
            with d_col1:
                st.download_button("📥 Cuenca (.zip)", export_gdf_to_zip(gdf_cuenca, "cuenca_delineada"), "cuenca_delineada.zip", use_container_width=True)
            with d_col2:
                st.download_button("📥 LFP (.zip)", export_gdf_to_zip(gpd.read_file(st.session_state.morphometry_downloads['lfp']), "lfp"), "lfp.zip", use_container_width=True)
            with d_col3:
                st.download_button("📥 Red Fluvial (.zip)", export_gdf_to_zip(gpd.read_file(st.session_state.morphometry_downloads['rios_strahler']), "red_fluvial"), "red_fluvial.zip", use_container_width=True)
            with d_col4:
                df_perfil = pd.DataFrame(st.session_state.morphometry_data['lfp_profile_data'])
                st.download_button("📥 Perfil LFP (.csv)", df_perfil.to_csv(index=False, sep=';').encode('utf-8'), "perfil_lfp.csv", use_container_width=True)