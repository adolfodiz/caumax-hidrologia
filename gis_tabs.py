import streamlit as st
import os
import numpy as np
import io
import zipfile
import tempfile
import re
import rasterio
from rasterio.mask import mask
import fiona
import geopandas as gpd
import pydeck as pdk
import matplotlib.pyplot as plt
from rasterio.plot import show as show_raster
from pathlib import Path
import pandas as pd
from shapely.geometry import shape, Point
import folium
from streamlit_folium import st_folium
from branca.colormap import linear
import traceback

from pyproj import Transformer, CRS
from pysheds.grid import Grid
from pysheds.sview import Raster
from affine import Affine

# --- CONSTANTES GLOBALES PARA NODATA (Asegúrate de que estén así) ---
TARGET_NODATA_FLOAT = np.float32(-9999.0)
TARGET_NODATA_INT = np.int32(-9999) # Para fdir y acc
TARGET_NODATA_UINT8 = np.uint8(0)   # Para la máscara de ríos



# --- Configuración de CRS ---
crs_wgs84 = CRS("EPSG:4326")

# --- Constantes ---
HMS_COLORS = [
    [255, 128, 128, 130], [128, 128, 255, 130], [128, 255, 128, 130],
    [255, 255, 128, 130], [255, 128, 255, 130], [128, 255, 255, 130]
]



# --- Usamos st.cache_resource para objetos complejos ---
@st.cache_resource(show_spinner="Pre-procesando DEM e identificando red fluvial...")
def preprocess_dem_pysheds(_dem_bytes, threshold_cells):
    temp_dem_path = None
    try:
        # --- PASO 1: ESTANDARIZAR EL DEM DE ENTRADA ---
        # (Esta parte es correcta y se mantiene)
        with rasterio.io.MemoryFile(_dem_bytes) as memfile:
            with memfile.open() as src:
                transform, crs, nodata_val, dem_array = src.transform, src.crs, src.nodata, src.read(1)

        dem_array_float = dem_array.astype(np.float32)
        if nodata_val is not None:
            dem_array_float[dem_array_float == nodata_val] = TARGET_NODATA_FLOAT
        
        profile = {'driver': 'GTiff', 'dtype': 'float32', 'nodata': TARGET_NODATA_FLOAT,
                   'width': dem_array.shape[1], 'height': dem_array.shape[0],
                   'count': 1, 'crs': crs, 'transform': transform}

        with tempfile.NamedTemporaryFile(delete=False, suffix='.tif') as temp_dem:
            temp_dem_path = temp_dem.name
            with rasterio.open(temp_dem_path, 'w', **profile) as dst:
                dst.write(dem_array_float, 1)

        # --- PASO 2: CÁLCULOS HIDROLÓGICOS CON PySheds ---
        grid = Grid.from_raster(temp_dem_path)
        dem = grid.read_raster(temp_dem_path, nodata=TARGET_NODATA_FLOAT)
        dem_filled = grid.fill_depressions(dem=dem)

        # Usamos los tipos de dato INT32 para fdir y acc
        fdir = grid.flowdir(dem=dem_filled, nodata_out=TARGET_NODATA_INT, dtype_out=np.int32)
        acc = grid.accumulation(fdir=fdir, nodata_in=TARGET_NODATA_INT, nodata_out=TARGET_NODATA_INT, dtype_out=np.int32)
        
        # --- PASO 3: ASIGNAR DATOS PARA LOS MAPAS ESTÁTICOS ---
        # (Esto es lo que permite que los 4 mapas se dibujen correctamente)
        grid.dem_filled = dem_filled
        grid.fdir = fdir
        grid.acc = acc
        grid.transform = transform
        grid.crs = crs

        # --- PASO 4: VECTORIZAR LA RED FLUVIAL DE FORMA SEGURA ---
        # Aquí estaba el error. La solución es la siguiente:
        
        # a) Crear la máscara booleana
        stream_mask = grid.acc > threshold_cells
        
        # b) Convertir la máscara a uint8 y poligonizar, pasando
        #    un NoData que TAMBIÉN es de tipo uint8.
        stream_features = grid.polygonize(stream_mask.astype(np.uint8), nodata=TARGET_NODATA_UINT8)
        
        streams_geojson_list = [{'type': 'Feature', 'geometry': geom, 'properties': {'value': val}} for geom, val in stream_features if val == 1]

        return {
            "grid": grid,
            "streams_geojson": streams_geojson_list,
            "error": None
        }
    except Exception as e:
        st.error("Ha ocurrido un error durante el pre-procesamiento del DEM.")
        st.exception(e)
        tb_str = traceback.format_exc()
        return {"error": f"Error en el pre-procesamiento del DEM: {e}\n\nTraceback:\n{tb_str}"}
    finally:
        if temp_dem_path and os.path.exists(temp_dem_path):
            os.remove(temp_dem_path)

# Esta es la función que sigue teniendo el problema subyacente, pero no la llamaremos
def delineate_catchment_from_coords(_processed_data, x, y):
    try:
        grid = _processed_data['grid']
        fdir = grid.fdir 

        try:
            x_snapped, y_snapped = grid.snap_to_mask(grid.acc > 100, (x, y))
        except Exception:
            x_snapped, y_snapped = x, y

        # --- INICIO DE LA SOLUCIÓN ALTERNATIVA ---

        # 1. Llamamos a catchment SIN especificar el tipo de salida.
        #    Aceptamos que creará un ráster de tipo int32 con NoData=-9999
        #    y un valor de 1 donde está la cuenca.
        catch_int32 = grid.catchment(
            x=x_snapped,
            y=y_snapped,
            fdir=fdir,
            xytype='coordinate'
        )

        # 2. Ahora tomamos el control. Convertimos manualmente el resultado a uint8.
        #    Donde el valor es 1, se queda en 1.
        #    Donde es -9999 (NoData), se convertirá en 0.
        catch_uint8 = (catch_int32 == 1).astype(np.uint8)

        # 3. Poligonizamos el nuevo array uint8, que ya es seguro,
        #    especificando que su NoData es 0.
        catch_geojson_generator = grid.polygonize(catch_uint8, nodata=TARGET_NODATA_UINT8)
        
        # --- FIN DE LA SOLUCIÓN ALTERNATIVA ---
        
        catch_geojson_list = [{'type': 'Feature', 'geometry': geom, 'properties': {'value': val}} for geom, val in catch_geojson_generator if val == 1]
        
        if not catch_geojson_list:
            return {"catchment_geojson": [], "error": "La delineación no produjo ninguna geometría."}

        return {"catchment_geojson": catch_geojson_list, "snapped_point": (x_snapped, y_snapped), "error": None}
    except Exception as e:
        st.error(f"Error durante la delineación de la cuenca: {e}")
        traceback.print_exc() 
        return {"error": f"Error durante la delineación de la cuenca: {e}"}

def create_download_zip(catchment_gdf, streams_gdf, dem_bytes, point_gdf):
    with io.BytesIO() as zip_buffer:
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            with tempfile.TemporaryDirectory() as tmpdir:
                catchment_path = os.path.join(tmpdir, "cuenca_delineada.shp")
                catchment_gdf.to_file(catchment_path, driver='ESRI Shapefile')
                for file in os.listdir(tmpdir):
                    if file.startswith("cuenca_delineada."): zf.write(os.path.join(tmpdir, file), arcname=file)
                
                point_path = os.path.join(tmpdir, "punto_desague.shp")
                point_gdf.to_file(point_path, driver='ESRI Shapefile')
                for file in os.listdir(tmpdir):
                    if file.startswith("punto_desague."): zf.write(os.path.join(tmpdir, file), arcname=file)

                if not streams_gdf.empty:
                    clipped_streams = gpd.clip(streams_gdf, catchment_gdf)
                    if not clipped_streams.empty:
                        streams_path = os.path.join(tmpdir, "rios_recortados.shp")
                        clipped_streams.to_file(streams_path, driver='ESRI Shapefile')
                        for file in os.listdir(tmpdir):
                            if file.startswith("rios_recortados."): zf.write(os.path.join(tmpdir, file), arcname=file)

                with rasterio.io.MemoryFile(dem_bytes) as memfile:
                    with memfile.open() as src:
                        out_image, out_transform = mask(src, catchment_gdf.geometry, crop=True, nodata=src.nodata)
                        out_meta = src.meta.copy()
                out_meta.update({"driver": "GTiff", "height": out_image.shape[1], "width": out_image.shape[2], "transform": out_transform})
                dem_path = os.path.join(tmpdir, "mdt_recortado.tif")
                with rasterio.open(dem_path, "w", **out_meta) as dest: dest.write(out_image)
                zf.write(dem_path, arcname="mdt_recortado.tif")

        zip_buffer.seek(0)
        return zip_buffer

def render_delineation_tab():
    st.header("Delineación Hidrológica a partir de un DEM")
    st.markdown("Esta herramienta replica el flujo de trabajo de HEC-HMS para delinear una cuenca hidrográfica.")
    st.info("**Instrucciones:**\n1. Suba un DEM y ajuste el umbral de celdas.\n2. Procese el DEM para ver los resultados intermedios.\n3. En la sección 5, **haga clic en un cauce brillante** del mapa interactivo para delinear la cuenca.")

    if 'delineation_dem_bytes' not in st.session_state: st.session_state.delineation_dem_bytes = None
    if 'dem_metadata' not in st.session_state: st.session_state.dem_metadata = None
    if 'uploaded_dem_name' not in st.session_state: st.session_state.uploaded_dem_name = None
    if 'processed_dem_data' not in st.session_state: st.session_state.processed_dem_data = None
    if 'delineation_click_wgs84' not in st.session_state: st.session_state.delineation_click_wgs84 = None
    if 'delineated_catchment_gdf' not in st.session_state: st.session_state.delineated_catchment_gdf = None
    if 'delineated_catchment_geojson_wgs84' not in st.session_state: st.session_state.delineated_catchment_geojson_wgs84 = None
    if 'last_delineation_click' not in st.session_state: st.session_state.last_delineation_click = None

    dem_file = st.file_uploader("1. Suba su archivo DEM", type=["tif", "tiff"], key="pysheds_dem_uploader")
    
    if dem_file and st.session_state.get('uploaded_dem_name') != dem_file.name:
        st.session_state.delineation_dem_bytes = dem_file.getvalue()
        st.session_state.uploaded_dem_name = dem_file.name
        st.session_state.dem_metadata = None
        st.session_state.processed_dem_data = None
        st.session_state.delineation_click_wgs84 = None
        st.session_state.delineated_catchment_gdf = None
        st.session_state.delineated_catchment_geojson_wgs84 = None
        st.session_state.last_delineation_click = None
        st.rerun()

    threshold_in_cells = 100

    if st.session_state.delineation_dem_bytes:
        if st.session_state.dem_metadata is None:
            try:
                with rasterio.io.MemoryFile(st.session_state.delineation_dem_bytes) as memfile:
                    with memfile.open() as src:
                        transform = src.transform
                        st.session_state.dem_metadata = {"cell_area_km2": abs(transform.a * transform.e) / 1_000_000}
            except Exception as e:
                st.error(f"Error al leer los metadatos del DEM: {e}")
                st.session_state.dem_metadata = {"cell_area_km2": 0}

        st.markdown("##### 2. Ajuste del Umbral de la Red Fluvial")
        st.info("**Defina la red:**\n1. Umbral (nº de celdas) = Área de Drenaje Deseada (m²) / Área de una Celda (m²)\n2. Área de una Celda (m²) = 25 m x 25 m = 625 m² (en un MDT25)\n3. Área de Drenaje (km²) = Umbral (nº de celdas) x Área de una Celda (0.000625 km²)\n4. Area < 0.01 km² (16 celdas) pueden generar mucho ruido, red excesivamente densa ::: Area > 1 km² (1600 celdas) puede eliminar cauces de interes, red demasiado preponderante\n5. Empiece por cauces que drenan 10 hectáreas (0.1 km² = 160 celdas)")
        cell_area_km2 = st.session_state.dem_metadata.get("cell_area_km2", 0)
        default_cells = int(1.0 / cell_area_km2) if cell_area_km2 > 0 else 100
        
        threshold_in_cells = st.slider("Umbral de acumulación (en número de celdas)", 10, 2000, default_cells, 10, help="Número mínimo de celdas que drenan a un punto para considerarlo un cauce.")
        threshold_km2 = threshold_in_cells * cell_area_km2
        st.info(f"ℹ️ Un umbral de **{threshold_in_cells}** celdas equivale a un área de drenaje de **{threshold_km2:.4f} km²** ::: celdas/acc")


    if st.button("3. Procesar DEM y Generar Red Fluvial", type="primary"):
        if st.session_state.delineation_dem_bytes:
            preprocess_dem_pysheds.clear()
            processed_data = preprocess_dem_pysheds(st.session_state.delineation_dem_bytes, threshold_in_cells)
            
            # --- INICIO DEL CAMBIO ---
            # Guardamos los datos procesados en el estado de la sesión
            st.session_state.processed_dem_data = processed_data

            # Comprobamos si hubo un error en el paso anterior
            if processed_data.get("error"):
                # No es necesario hacer nada aquí, el error ya se mostró dentro de la función
                # Pero nos aseguramos de que el mensaje de "éxito" no aparezca
                pass
            else:
                st.success("DEM procesado. Ahora, seleccione el punto de desagüe en el mapa de la sección 5.")
            # --- FIN DEL CAMBIO ---

            st.rerun()
        else:
            st.warning("Por favor, suba un archivo DEM primero.")

    # --- INICIO DEL NUEVO BLOQUE DE COMPROBACIÓN ---
    # Comprobamos si existen datos procesados y si contienen un error
    if 'processed_dem_data' in st.session_state and st.session_state.processed_dem_data:
        processed_data = st.session_state.processed_dem_data
        
        # Si el diccionario de datos contiene la clave 'error', lo mostramos y paramos
        if processed_data.get("error"):
            st.error("El procesamiento del DEM falló. Por favor, revise el error mostrado arriba y compruebe su archivo DEM.")
            st.code(processed_data["error"]) # Muestra el traceback como texto
            st.stop() # Detiene la ejecución del resto de la pestaña
    # --- FIN DEL NUEVO BLOQUE DE COMPROBACIÓN ---

    # El resto del código que dibuja los mapas y la delineación interactiva
    if 'processed_dem_data' in st.session_state and st.session_state.processed_dem_data and not st.session_state.processed_dem_data.get("error"):
        processed_data = st.session_state.processed_dem_data
        grid = processed_data['grid']
        
        st.subheader("4. Resultados del Pre-procesamiento Hidrológico")
        with st.expander("Ver mapas de resultados intermedios"):
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown("###### 1. DEM Rellenado"); fig, ax = plt.subplots(figsize=(5,5)); 
                # --- CAMBIO AQUÍ ---
                show_raster(grid.dem_filled, ax=ax, transform=grid.transform, cmap='magma') 
                st.pyplot(fig)

            with col2:
                st.markdown("###### 2. Direcciones de Flujo"); fig, ax = plt.subplots(figsize=(5,5)); 
                # Este lo dejamos con 'viridis' o 'jet' que es mejor para datos categóricos como las direcciones
                show_raster(grid.fdir, ax=ax, transform=grid.transform, cmap='viridis', vmin=1, vmax=128)
                st.pyplot(fig)

            with col3:
                st.markdown("###### 3. Acumulación (log)"); fig, ax = plt.subplots(figsize=(5,5)); 
                # --- CAMBIO AQUÍ ---
                show_raster(np.log1p(grid.acc), ax=ax, transform=grid.transform, cmap='magma') 
                st.pyplot(fig)

            with col4:
                st.markdown("###### 4. Red Fluvial Vectorizada"); fig, ax = plt.subplots(figsize=(5,5)); 
                # Aquí podemos usar una rampa de grises para el fondo para que el río azul resalte
                show_raster(grid.dem_filled, ax=ax, transform=grid.transform, cmap='gist_gray')
                stream_features = processed_data['streams_geojson']
                if stream_features:
                    geometries = [shape(feature['geometry']) for feature in stream_features]
                    streams_gdf = gpd.GeoDataFrame({'geometry': geometries}, crs=grid.crs.to_string())
                    streams_gdf.plot(ax=ax, edgecolor='cyan', linewidth=0.7)
                st.pyplot(fig)
        
        st.divider()
        
        st.subheader("5. Delineación Interactiva en el Mapa")
        
        try:
            source_crs_utm = CRS("EPSG:25830"); target_crs_wgs84 = CRS("EPSG:4326")
            transformer_utm_to_wgs = Transformer.from_crs(source_crs_utm, target_crs_wgs84, always_xy=True)
            lon_init, lat_init = transformer_utm_to_wgs.transform(st.session_state.x_utm, st.session_state.y_utm)
            map_center = [lat_init, lon_init]

            m = folium.Map(location=map_center, zoom_start=12, tiles='OpenStreetMap')
            folium.TileLayer('CartoDB positron', name='CartoDB Positron').add_to(m)
            folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Esri World Imagery').add_to(m)

            acc_data = np.asarray(grid.acc)
            acc_log = np.log1p(np.where(acc_data < 0, 0, acc_data))
            acc_norm = (acc_log - np.min(acc_log)) / (np.max(acc_log) - np.min(acc_log))
            colormap = plt.get_cmap('YlGnBu')
            acc_rgba = colormap(acc_norm)
            
            transformer_dem_to_wgs = Transformer.from_crs(grid.crs, target_crs_wgs84, always_xy=True)
            min_x, max_x, min_y, max_y = grid.extent
            bl_lon, bl_lat = transformer_dem_to_wgs.transform(min_x, min_y)
            tr_lon, tr_lat = transformer_dem_to_wgs.transform(max_x, max_y)
            bounds_wgs84 = [[bl_lat, bl_lon], [tr_lat, tr_lon]]
            
            folium.raster_layers.ImageOverlay(image=acc_rgba, bounds=bounds_wgs84, opacity=0.7, name='Acumulación de Flujo').add_to(m)

            # # --- INICIO DEL CÓDIGO AÑADIDO ---
            # # Extrae las geometrías de los ríos que se calcularon al procesar el DEM
            # stream_features = processed_data.get('streams_geojson')
            
            # # Si existen ríos, los dibuja en el mapa
            # if stream_features:
            #     folium.GeoJson(
            #         stream_features,
            #         name="Red Fluvial (según umbral)",
            #         style_function=lambda x: {'color': 'cyan', 'weight': 2, 'opacity': 0.8},
            #         tooltip="Red Fluvial (del umbral)"
            #     ).add_to(m)
            # # --- FIN DEL CÓDIGO AÑADIDO ---

            folium.Marker([lat_init, lon_init], popup="Punto Inicial (Global)", icon=folium.Icon(color="red", icon="info-sign")).add_to(m)

            if st.session_state.delineation_click_wgs84:
                click_coords = st.session_state.delineation_click_wgs84
                folium.Marker([click_coords['lat'], click_coords['lon']], popup=f"Punto de Delineación\nLat: {click_coords['lat']:.5f}, Lon: {click_coords['lon']:.5f}", icon=folium.Icon(color="orange", icon="tint")).add_to(m)

            if st.session_state.delineated_catchment_geojson_wgs84:
                folium.GeoJson(st.session_state.delineated_catchment_geojson_wgs84, name="Cuenca Delineada", style_function=lambda x: {'color': 'yellow', 'weight': 3, 'fillOpacity': 0.4}).add_to(m)
                m.fit_bounds(folium.GeoJson(st.session_state.delineated_catchment_geojson_wgs84).get_bounds())

            folium.LayerControl().add_to(m)

            map_data = st_folium(m, key="snap_map_interactive", returned_objects=["last_clicked"], width=None, height=600)

            if map_data and map_data.get("last_clicked"):
                current_click = map_data["last_clicked"]
                if current_click != st.session_state.last_delineation_click:
                    st.session_state.last_delineation_click = current_click
                    
                    with st.spinner("Delineando nueva cuenca..."):
                        st.session_state.delineation_click_wgs84 = {"lat": current_click["lat"], "lon": current_click["lng"]}
                        
                        transformer_wgs_to_dem = Transformer.from_crs(target_crs_wgs84, grid.crs, always_xy=True)
                        x_dem, y_dem = transformer_wgs_to_dem.transform(current_click["lng"], current_click["lat"])
                        
                        catchment_data = delineate_catchment_from_coords(processed_data, x_dem, y_dem)
                        
                        if catchment_data.get("error") or not catchment_data['catchment_geojson']:
                            st.warning(catchment_data.get("error", "No se pudo delinear la cuenca."))
                            st.session_state.delineated_catchment_gdf = None
                            st.session_state.delineated_catchment_geojson_wgs84 = None
                        else:
                            geometries = [shape(f['geometry']) for f in catchment_data['catchment_geojson']]
                            catch_gdf = gpd.GeoDataFrame({'geometry': geometries}, crs=grid.crs)
                            st.session_state.delineated_catchment_gdf = catch_gdf
                            
                            catch_gdf_wgs84 = catch_gdf.to_crs(target_crs_wgs84)
                            st.session_state.delineated_catchment_geojson_wgs84 = catch_gdf_wgs84.__geo_interface__
                            
                            snapped_x, snapped_y = catchment_data['snapped_point']
                            point_geom = Point(snapped_x, snapped_y)
                            st.session_state.delineated_point_gdf = gpd.GeoDataFrame([1], geometry=[point_geom], crs=grid.crs)

                    st.rerun()

        except Exception as e:
            st.error(f"Error al preparar o mostrar el mapa interactivo: {e}")
            traceback.print_exc()

        if st.session_state.delineated_catchment_gdf is not None:
            st.divider()
            st.subheader("6. Resultados de la Delineación")
            
            catchment_gdf = st.session_state.delineated_catchment_gdf
            area_km2 = catchment_gdf.area.sum() / 1_000_000
            st.metric("Área de la Cuenca Delineada", f"{area_km2:.3f} km²")

            if st.session_state.delineation_click_wgs84:
                coords = st.session_state.delineation_click_wgs84
                st.write(f"**Coordenadas del punto de desagüe (clic):** Lat: `{coords['lat']:.5f}`, Lon: `{coords['lon']:.5f}`")

            stream_features = processed_data['streams_geojson']
            stream_geometries = [shape(feature['geometry']) for feature in stream_features]
            streams_gdf = gpd.GeoDataFrame({'geometry': stream_geometries}, crs=grid.crs.to_string())
            
            zip_bytes = create_download_zip(catchment_gdf, streams_gdf, st.session_state.delineation_dem_bytes, st.session_state.delineated_point_gdf)
            
            st.download_button(label="📥 Descargar Resultados (.zip)", data=zip_bytes, file_name=f"delineacion_personalizada.zip", mime="application/zip")





# --- Funciones para Pestaña de HEC-HMS ---
def parse_subbasin_names(file_content):
    subbasin_names = []
    for line in file_content.splitlines():
        if line.strip().startswith("Subbasin:"):
            name = line.split(":", 1)[1].strip()
            subbasin_names.append(name)
    return subbasin_names

def get_name_column(gdf, prefix="Elemento"):
    POSSIBLE_NAME_COLS = ['Name', 'NAME', 'nombre', 'ID', 'id', 'HYD_ID']
    for col in POSSIBLE_NAME_COLS:
        if col in gdf.columns: return gdf[col].copy().fillna('Sin Nombre')
    return [f"{prefix} {i+1}" for i in range(len(gdf))]

def create_gis_plot_hms(terrain_path, subbasins_gdf=None, streams_gdf=None):
    if not terrain_path or not terrain_path.exists():
        st.warning(f"No se encontró el ráster de terreno en `{terrain_path}`."); return None
    try:
        fig, ax = plt.subplots(figsize=(10, 10))
        with rasterio.open(terrain_path) as src:
            show_raster(src, ax=ax, cmap='terrain')
            raster_crs = src.crs
            if subbasins_gdf is not None: subbasins_gdf.to_crs(raster_crs).plot(ax=ax, facecolor='none', edgecolor='black', linewidth=1.5)
            if streams_gdf is not None: streams_gdf.to_crs(raster_crs).plot(ax=ax, edgecolor='blue', linewidth=1.5)
        ax.set_facecolor('lightgray'); ax.set_title("Vista GIS del Terreno y la Cuenca")
        ax.set_xlabel("Easting (m)"); ax.set_ylabel("Northing (m)")
        ax.tick_params(axis='x', rotation=45); ax.grid(True, linestyle='--', alpha=0.6)
        return fig
    except Exception as e:
        st.error(f"Ocurrió un error al generar la vista GIS: {e}"); return None

def get_profile_data_hms(geom, reach_crs, terrain_raster_path, terrain_crs):
    if geom is None or geom.is_empty: return None
    if geom.geom_type == 'MultiLineString': geom = max(geom.geoms, key=lambda line: line.length)
    if geom.geom_type != 'LineString': return None
    try:
        with rasterio.open(terrain_raster_path) as src:
            reach_reproj = gpd.GeoSeries([geom], crs=reach_crs).to_crs(terrain_crs).iloc[0]
            length_m = reach_reproj.length
            if length_m < 1.0: return None
            num_points = int(length_m / 20) if length_m > 40 else 50
            distances = np.linspace(0, length_m, num_points)
            points = [reach_reproj.interpolate(dist) for dist in distances]
            coords = [(p.x, p.y) for p in points]
            sampled_elev = list(src.sample(coords))
            valid_points = [(dist, elev[0]) for dist, elev in zip(distances, sampled_elev) if elev is not None and elev[0] > -9999]
            if len(valid_points) < 2: return None
            return list(zip(*valid_points))
    except Exception: return None

def calculate_kirpich_tc_hms(length_m, slope_m_m):
    if slope_m_m <= 0 or length_m <= 0: return 0
    length_ft = length_m * 3.28084
    tc_hours = 0.0078 * (length_ft ** 0.77) * (slope_m_m ** -0.385)
    return tc_hours * 60

def render_hms_tab():
    st.header("Analizador Interactivo HEC-HMS")
    st.info("Sube un archivo `.zip` que contenga todos los archivos de tu proyecto HEC-HMS (incluyendo `.basin`, `.sqlite` o `.gpkg`, y la carpeta de terreno).")
    uploaded_zip_hms = st.file_uploader("Carga tu proyecto HEC-HMS en formato ZIP", type=["zip"], key="hms_zip_uploader")

    if uploaded_zip_hms is not None:
        with st.spinner("Procesando proyecto HEC-HMS..."):
            try:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    with zipfile.ZipFile(uploaded_zip_hms, 'r') as zip_ref:
                        zip_ref.extractall(temp_path)
                    
                    basin_files = list(temp_path.rglob("*.basin"))
                    if not basin_files:
                        st.error("No se encontró ningún archivo `.basin` en el ZIP subido."); st.stop()
                    
                    basin_file_path = basin_files[0]
                    basin_dir = basin_file_path.parent
                    with open(basin_file_path, 'r', errors='ignore') as f: content = f.read()

                    sqlite_files = list(temp_path.rglob("*.sqlite")) + list(temp_path.rglob("*.gpkg"))
                    if not sqlite_files:
                        st.error("No se encontró ningún archivo .sqlite o .gpkg en el ZIP subido."); st.stop()
                    full_sqlite_path = sqlite_files[0].resolve()
                    
                    spatial_props_match = re.search(r"Basin Spatial Properties:(.*?)\nEnd:", content, re.DOTALL)
                    if not spatial_props_match:
                        st.error("No se pudo encontrar el bloque 'Basin Spatial Properties' en el archivo .basin."); st.stop()
                    spatial_content = spatial_props_match.group(1)

                    crs_match = re.search(r"Coordinate System:\s*(PROJCS.+)", spatial_content)
                    if not crs_match:
                        st.error("No se pudo extraer el 'Coordinate System' de dentro del bloque 'Basin Spatial Properties'."); st.stop()

                    terrain_name_match = re.search(r"Terrain:\s*(.*)", spatial_content)
                    if not terrain_name_match:
                        st.error("No se pudo encontrar el nombre del dataset 'Terrain:' en el bloque 'Basin Spatial Properties'."); st.stop()
                    
                    terrain_name = terrain_name_match.group(1).strip()
                    
                    # --- CORRECCIÓN APLICADA AQUÍ ---
                    terrain_folder_name = terrain_name.replace(" ", "_")
                    hms_terrain_raster_path = (basin_dir / "terrain" / terrain_folder_name / "00" / "elevation.tif").resolve()

                    if not full_sqlite_path.exists():
                        st.error(f"El archivo '{full_sqlite_path.name}' no se encontró en la ruta esperada dentro del ZIP."); st.stop()
                    if not hms_terrain_raster_path.exists():
                        st.warning(f"No se encontró '{hms_terrain_raster_path.name}' en la estructura de carpetas esperada. La vista GIS no estará disponible.")

                    source_crs = CRS.from_wkt(crs_match.group(1).strip())
                    terrain_crs = None
                    if hms_terrain_raster_path.exists():
                        with rasterio.open(hms_terrain_raster_path) as src: terrain_crs = src.crs or source_crs

                    # --- El resto de la lógica de la función permanece igual ---
                    loaded_gdfs = {}
                    for layer_name in fiona.listlayers(str(full_sqlite_path)):
                        gdf = gpd.read_file(str(full_sqlite_path), layer=layer_name).set_crs(source_crs, allow_override=True)
                        if gdf is not None and not gdf.empty: loaded_gdfs[layer_name] = gdf
                    
                    if loaded_gdfs:
                        subbasin_gdf = next((gdf for name, gdf in loaded_gdfs.items() if 'subbasin' in name.lower()), None)
                        streams_gdf = next((gdf for name, gdf in loaded_gdfs.items() if 'reach' in name.lower() or 'stream' in name.lower()), None)
                        
                        if subbasin_gdf is not None:
                            parsed_names = parse_subbasin_names(content)
                            subbasin_gdf['name_for_analysis'] = parsed_names if parsed_names and len(parsed_names) == len(subbasin_gdf) else get_name_column(subbasin_gdf, prefix="Subcuenca")
                            
                            reach_lengths, reach_geoms = [], []
                            for _, subbasin in subbasin_gdf.iterrows():
                                length, geom = 0.0, None
                                if streams_gdf is not None:
                                    try:
                                        clipped_streams = gpd.clip(streams_gdf, subbasin.geometry)
                                        if not clipped_streams.empty:
                                            main_reach_geom = clipped_streams.loc[clipped_streams.geometry.length.idxmax()].geometry
                                            length, geom = main_reach_geom.length, main_reach_geom
                                    except Exception: pass
                                reach_lengths.append(length); reach_geoms.append(geom)
                            subbasin_gdf['main_reach_length'] = reach_lengths
                            subbasin_gdf['main_reach_geom'] = reach_geoms
                        
                        col_map, col_gis = st.columns(2)
                        with col_map:
                            st.header("Mapa Interactivo")
                            pydeck_layers = []
                            if subbasin_gdf is not None:
                                subbasin_gdf_wgs84 = subbasin_gdf.to_crs("EPSG:4326")
                                subbasin_gdf_wgs84['color'] = [HMS_COLORS[i % len(subbasin_gdf_wgs84)] for i in range(len(subbasin_gdf_wgs84))]
                                subbasin_viz_gdf = subbasin_gdf_wgs84[['geometry', 'name_for_analysis', 'color']].rename(columns={'name_for_analysis': 'name'})
                                pydeck_layers.append(pdk.Layer("GeoJsonLayer", data=subbasin_viz_gdf, opacity=0.5, stroked=True, filled=True, get_fill_color='color', get_line_color=[30, 30, 30, 200], get_line_width=2, pickable=True, tooltip={"html": "<b>{name}</b>"}))
                                subbasin_gdf_wgs84['centroid'] = subbasin_gdf_wgs84.geometry.centroid
                                label_data = pd.DataFrame({'text': subbasin_gdf_wgs84['name_for_analysis'], 'position': subbasin_gdf_wgs84['centroid'].apply(lambda p: [p.x, p.y])})
                                pydeck_layers.append(pdk.Layer("TextLayer", data=label_data, get_position='position', get_text='text', get_color=[0, 0, 0, 200], get_size=16, alignment_baseline='bottom'))
                            if streams_gdf is not None:
                                streams_gdf_wgs84 = streams_gdf.to_crs("EPSG:4326")
                                streams_gdf_wgs84['name'] = get_name_column(streams_gdf, prefix="Cauce")
                                pydeck_layers.append(pdk.Layer("GeoJsonLayer", data=streams_gdf_wgs84[['geometry', 'name']], get_line_color=[100, 149, 237, 255], get_line_width=3, pickable=True, tooltip={"html": "<b>{name}</b>"}))
                            
                            view_state = pdk.ViewState(latitude=40.2, longitude=-0.25, zoom=10, pitch=0)
                            if loaded_gdfs:
                                combined_gdf = gpd.GeoDataFrame(pd.concat([gdf.to_crs("EPSG:4326") for gdf in loaded_gdfs.values() if not gdf.empty], ignore_index=True), crs="EPSG:4326")
                                if not combined_gdf.empty:
                                    bounds = combined_gdf.total_bounds
                                    view_state.longitude, view_state.latitude = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
                            st.pydeck_chart(pdk.Deck(map_style="mapbox://styles/mapbox/light-v10", initial_view_state=view_state, layers=pydeck_layers))

                        with col_gis:
                            st.header("Vista GIS del Terreno")
                            gis_plot_fig = create_gis_plot_hms(hms_terrain_raster_path, subbasin_gdf, streams_gdf)
                            if gis_plot_fig: st.pyplot(fig=gis_plot_fig); plt.close(gis_plot_fig)

                        st.divider()
                        st.header("Análisis de Parámetros por Subcuenca")
                        if subbasin_gdf is not None and terrain_crs is not None:
                            for index, subbasin in subbasin_gdf.iterrows():
                                with st.expander(f"**{subbasin['name_for_analysis']}**", expanded=index == 0):
                                    st.metric("Área (km²)", f"{(subbasin.get('Area') or (subbasin.geometry.area / 1_000_000)):.3f}")
                                    st.metric("Longitud del Cauce Principal (m)", f"{subbasin['main_reach_length']:.2f}")
                                    profile_data = get_profile_data_hms(subbasin['main_reach_geom'], source_crs, hms_terrain_raster_path, terrain_crs)
                                    if profile_data:
                                        distances, elevations = profile_data
                                        fig, ax = plt.subplots(figsize=(10,3)); ax.plot(distances, elevations, color='blue')
                                        ax.set_title("Perfil Longitudinal"); ax.set_xlabel("Distancia (m)"); ax.set_ylabel("Elevación (m)")
                                        ax.grid(True); plt.tight_layout(); st.pyplot(fig=fig); plt.close(fig)
                                        e_min, e_max = min(elevations), max(elevations)
                                        slope = abs(e_max - e_min) / distances[-1] if distances[-1] > 0 else 0
                                        tc = calculate_kirpich_tc_hms(subbasin['main_reach_length'], slope)
                                        st.metric("Elevación Cauce (Máx/Mín)", f"{e_max:.2f} m / {e_min:.2f} m")
                                        st.metric("Pendiente Media (m/m)", f"{slope:.4f}")
                                        st.metric("Tc (Kirpich, min)", f"{tc:.2f}")
                                    else:
                                        st.warning("Perfil no disponible.")
            except Exception as e:
                st.error(f"Ocurrió un error inesperado al procesar el archivo ZIP: {e}")
