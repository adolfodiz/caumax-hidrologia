# perfil_terreno_tab.py (Versión Definitiva que respeta el flujo de Streamlit)

import streamlit as st
import os
import geopandas as gpd
import rasterio
from rasterio.mask import mask
from rasterio.io import MemoryFile
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import json
import folium
from streamlit_folium import st_folium
import plotly.graph_objects as go
from shapely.geometry import LineString, mapping
import zipfile
import tempfile

# --- 1. CONFIGURACIÓN Y RUTAS (Sin cambios) ---
# PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
# DATA_FOLDER = PROJECT_ROOT
MDT25_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/MDT25_peninsula_UTM30N_COG.tif"
CORINE_VISU_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/CORINE_visual_COG.tif"
CN_HIDRO_PATH = "https://pub-e3d06a464df847c6962ef2ff7362c24e.r2.dev/caumax-hidrologia-data/CN_hidrologico_COG.tif"
CORINE_COLOR_MAP = {111:'#E6004D',112:'#FF0000',121:'#CC4DF2',122:'#CC0000',123:'#E6CCCC',124:'#E6CCE6',131:'#A600CC',132:'#A64DCC',133:'#FF4DFF',141:'#FFA6FF',142:'#FFE6FF',211:'#FFFFA8',212:'#FFFF00',213:'#E6E600',221:'#E68000',222:'#F2A64D',223:'#E6A600',231:'#E6E64D',241:'#FFE6A6',242:'#FFE64D',243:'#E6CC4D',244:'#F2CCA6',311:'#80FF00',312:'#00A600',313:'#4DFF00',321:'#CCF24D',322:'#A6FF80',323:'#A6E64D',324:'#A6F200',331:'#E6E6E6',332:'#CCCCCC',333:'#CCFFCC',334:'#000000',335:'#A6E6CC',411:'#A6A6FF',412:'#4D4DFF',421:'#CCCCFF',422:'#E6E6FF',423:'#A6A6E6',511:'#00CCF2',512:'#80F2E6',521:'#00FFFF',522:'#A6FFFF',523:'#E6FFFF'}

# --- 2. FUNCIONES DE LÓGICA (Sin cambios) ---
@st.cache_resource(show_spinner=False)
def clip_raster_to_geometry(raster_path, _geometry_gdf):
    # Aseguramos que se lee directamente de la URL.
    if not raster_path.startswith('http'):
        st.error(f"Error interno: La ruta del ráster '{raster_path}' no es una URL.")
        return None, None
    print(f"LOG: Abriendo ráster (COG) directamente desde URL: {raster_path}...")
    with rasterio.open(raster_path) as src: # Rasterio puede abrir la URL directamente
        geometry_gdf_reprojected = _geometry_gdf.to_crs(src.crs)
        try:
            out_image, out_transform = mask(dataset=src, shapes=geometry_gdf_reprojected.geometry, crop=True, nodata=src.nodata)
            out_meta = src.meta.copy(); out_meta.update({"driver":"GTiff","height":out_image.shape[1],"width":out_image.shape[2],"transform":out_transform,"nodata":src.nodata})
            return out_image, out_meta
        except ValueError: return None, None

def raster_to_bytes(raster_image, raster_meta):
    with MemoryFile() as memfile:
        with memfile.open(**raster_meta) as dataset: dataset.write(raster_image)
        return memfile.read()

def sample_rasters_along_line(_line_geom, _rasters_data):
    # Aseguramos que se lee directamente de la URL.
    # Abrimos los datasets UNA VEZ fuera del bucle.
    dem_src = rasterio.open(_rasters_data['dem_bytes'])
    corine_src = rasterio.open(_rasters_data['corine_bytes'])
    cn_src = rasterio.open(_rasters_data['cn_bytes'])
    
    gdf_line = gpd.GeoDataFrame(geometry=[_line_geom], crs="EPSG:4326").to_crs(_rasters_data['dem_meta']['crs'])
    distances, dem_values, corine_values, cn_values = [], [], [], []
    num_samples = 150
    for i in range(num_samples + 1):
        point = gdf_line.geometry.iloc[0].interpolate(i / num_samples, normalized=True)
        distance = gdf_line.geometry.iloc[0].project(point)
        
        # Leemos los valores del ráster AHORA usando los objetos 'src' que abrimos al principio.
        # Esto es eficiente y correcto.
        dem_val = next(dem_src.sample([(point.x, point.y)]))[0]
        corine_val = next(corine_src.sample([(point.x, point.y)]))[0]
        cn_val = next(cn_src.sample([(point.x, point.y)]))[0]
        
        distances.append(distance / 1000)
        dem_values.append(dem_val if dem_val > -999 else np.nan)
        corine_values.append(corine_val)
        cn_values.append(cn_val if cn_val > 0 else np.nan)

    # Es importante cerrar los datasets al final, ya que los abrimos fuera del bucle.
    dem_src.close()
    corine_src.close()
    cn_src.close()
    
    return distances, dem_values, corine_values, cn_values

# --- 3. FUNCIÓN PRINCIPAL DE LA PESTAÑA ---
def render_perfil_terreno_tab():
    st.title("🔬 Perfil Interactivo de Terreno y Usos del Suelo")
    st.info("Seleccione o dibuje un perfil. Cualquier nueva selección reemplazará automáticamente a la anterior.")

    if 'profile_map_key' not in st.session_state:
        st.session_state.profile_map_key = 0

    active_geometry_gdf = None
    source_name = "Ninguna"
    if 'poligono_results' in st.session_state and "error" not in st.session_state.get('poligono_results', {}):
        active_geometry_gdf = st.session_state.poligono_results.get('poligono_gdf')
        source_name = "Polígono Manual"
    elif 'cuenca_results' in st.session_state:
        active_geometry_gdf = st.session_state.cuenca_results.get('buffer_gdf')
        source_name = "Cuenca + Buffer (5km)"

    if active_geometry_gdf is None:
        st.warning("Primero debe analizar una cuenca en la pestaña 'Generador DEM CNIG'.")
        st.stop()

    st.success(f"**Área activa para el análisis y recorte:** {source_name}")
    
    if 'perfil_data' in st.session_state and st.session_state.perfil_data.get('source_name') != source_name:
        del st.session_state['perfil_data']
        if 'active_profile_line' in st.session_state: del st.session_state['active_profile_line']
        st.info("La fuente de datos ha cambiado. Por favor, cargue los nuevos datos para el área activa.")
        st.rerun()

    if 'perfil_data' not in st.session_state:
        if st.button("🚀 Cargar Datos y Activar Mapa de Perfilado", use_container_width=True):
            with st.spinner(f"Recortando rásters nacionales para: {source_name}..."):
                geometry_for_clipping = active_geometry_gdf.to_crs("EPSG:4326")
                dem_image, dem_meta = clip_raster_to_geometry(MDT25_PATH, geometry_for_clipping)
                corine_image, corine_meta = clip_raster_to_geometry(CORINE_VISU_PATH, geometry_for_clipping)
                cn_image, cn_meta = clip_raster_to_geometry(CN_HIDRO_PATH, geometry_for_clipping)
                
                if dem_image is not None and corine_image is not None and cn_image is not None:
                    st.session_state.perfil_data = {
                        "source_name": source_name,
                        "dem_bytes": raster_to_bytes(dem_image, dem_meta), "corine_bytes": raster_to_bytes(corine_image, corine_meta),
                        "cn_bytes": raster_to_bytes(cn_image, cn_meta), "bounds": list(geometry_for_clipping.total_bounds),
                        "dem_meta": dem_meta, "area_geojson": geometry_for_clipping.to_json(), "dem_image": dem_image, "corine_image": corine_image,
                        "cn_image": cn_image, "corine_meta": corine_meta, "cn_meta": cn_meta
                    }
                    st.session_state.profile_map_key += 1
                    st.rerun()
                else: st.error("No se pudieron generar los recortes. El área seleccionada podría estar fuera de la cobertura de datos.")
        st.stop()
    
    with st.expander("Verificación y Descarga de Datos Recortados", expanded=False):
        data = st.session_state.perfil_data
        col1, col2, col3 = st.columns(3)
        with col1:
            st.subheader("MDT25 (ETRS89 UTM Zone30N)"); fig, ax = plt.subplots(); plot_array = data['dem_image'][0].astype('float32'); nodata = data['dem_meta'].get('nodata')
            if nodata is not None: plot_array[plot_array == nodata] = np.nan
            im = ax.imshow(plot_array, cmap='terrain'); fig.colorbar(im, ax=ax, label='Elevación (m)'); ax.set_axis_off(); st.pyplot(fig)
            st.download_button("📥 Descargar MDT25", data['dem_bytes'], "mdt25_recortado.tif", "image/tiff", use_container_width=True)
        with col2:
            st.subheader("CORINE Land Cover"); fig, ax = plt.subplots(); corine_array = data['corine_image'][0]; plot_data = corine_array.astype(float); nodata = data['corine_meta'].get('nodata')
            if nodata is not None: plot_data[plot_data == nodata] = np.nan
            unique_codes = [code for code in np.unique(plot_data) if not np.isnan(code)]; colors = [CORINE_COLOR_MAP.get(code, '#FFFFFF') for code in unique_codes]
            if colors:
                cmap = mcolors.ListedColormap(colors); bounds_norm = [code - 0.5 for code in unique_codes]; bounds_norm.append(unique_codes[-1] + 0.5); norm = mcolors.BoundaryNorm(bounds_norm, cmap.N)
                im = ax.imshow(plot_data, cmap=cmap, norm=norm)
            else: im = ax.imshow(plot_data)
            ax.set_axis_off(); st.pyplot(fig)
            st.download_button("📥 Descargar CORINE", data['corine_bytes'], "corine_recortado.tif", "image/tiff", use_container_width=True)
        with col3:
            st.subheader("Curve Number (CN)"); fig, ax = plt.subplots(); cn_array = data['cn_image'][0].astype('float32'); nodata = data['cn_meta'].get('nodata')
            if nodata is not None: cn_array[cn_array == nodata] = np.nan
            im = ax.imshow(cn_array, cmap='viridis', vmin=40, vmax=100); fig.colorbar(im, ax=ax, label='Valor CN'); ax.set_axis_off(); st.pyplot(fig)
            st.download_button("📥 Descargar CN", data['cn_bytes'], "cn_recortado.tif", "image/tiff", use_container_width=True)

    # st.header("1. Origen del Perfil")
    # 
    # # --- LA CORRECCIÓN CLAVE ---
    # def handle_profile_upload():
    #     uploaded_file = st.session_state.get('profile_uploader')
    #     if not uploaded_file: return
    #     # El callback ahora SÓLO modifica el session_state.
    #     # Streamlit se encargará del rerun de forma natural y ordenada.
    #     tmp_path = None
    #     try:
    #         with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp: tmp.write(uploaded_file.getvalue()); tmp_path = tmp.name
    #         gdf_uploaded = gpd.read_file(f"zip://{tmp_path}")
    #         if len(gdf_uploaded) != 1 or not ("LineString" in gdf_uploaded.geometry.iloc[0].geom_type):
    #             st.error("Error: El Shapefile debe contener una única Polilínea (LineString).")
    #             return
    #         st.session_state.active_profile_line = gdf_uploaded.to_crs("EPSG:4326").geometry.iloc[0]
    #         st.session_state.profile_source = 'Shapefile Cargado'
    #         st.session_state.profile_map_key += 1
    #         # NO hay st.rerun() aquí.
    #     except Exception as e: st.error(f"Error al procesar el shapefile: {e}")
    #     finally:
    #         if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
    # 
    # col1, col2 = st.columns(2)
    # with col1:
    #     if st.button("Usar Cauce Calculado", use_container_width=True, disabled=not st.session_state.get('main_channel_geojson')):
    #         st.session_state.active_profile_line = LineString(json.loads(st.session_state.main_channel_geojson)['coordinates'])
    #         st.session_state.profile_source = 'Cauce Calculado'
    #         st.session_state.profile_map_key += 1
    #         st.rerun()
    # with col2:
    #     st.file_uploader("Cargar Shapefile (.zip)", type=['zip'], key='profile_uploader', on_change=handle_profile_upload)

    st.header("1. Origen del Perfil")

    # --- Función de callback para la carga de Shapefile (sin cambios) ---
    def handle_profile_upload():
        uploaded_file = st.session_state.get('profile_uploader')
        if not uploaded_file: return
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp: tmp.write(uploaded_file.getvalue()); tmp_path = tmp.name
            gdf_uploaded = gpd.read_file(f"zip://{tmp_path}")
            if len(gdf_uploaded) != 1 or not ("LineString" in gdf_uploaded.geometry.iloc[0].geom_type):
                st.error("Error: El Shapefile debe contener una única Polilínea (LineString).")
                return
            st.session_state.active_profile_line = gdf_uploaded.to_crs("EPSG:4326").geometry.iloc[0]
            st.session_state.profile_source = 'Shapefile Cargado'
            st.session_state.profile_map_key += 1
        except Exception as e: st.error(f"Error al procesar el shapefile: {e}")
        finally:
            if tmp_path and os.path.exists(tmp_path): os.remove(tmp_path)
    
    col1, col2 = st.columns(2)
    with col1:
        # --- INICIO: SECCIÓN MODIFICADA ---
        
        # Comprobar de forma segura si los datos del LFP existen en el estado de la sesión
        lfp_data_exists = st.session_state.get('hidro_results_externo', {}).get('downloads', {}).get('lfp')

        # El botón ahora se llama "Cargar LFP" y se activa/desactiva según si los datos existen
        if st.button("Cargar LFP (Longuest Flow Path)", use_container_width=True, disabled=not lfp_data_exists):
            try:
                # Obtener el GeoJSON del LFP desde los resultados de la pestaña anterior
                lfp_geojson_str = st.session_state.hidro_results_externo['downloads']['lfp']
                
                # Cargar el GeoJSON en un GeoDataFrame
                gdf_lfp = gpd.read_file(lfp_geojson_str)
                
                # Reproyectar a WGS84 (EPSG:4326), que es el CRS que usa esta pestaña para dibujar
                gdf_lfp_wgs84 = gdf_lfp.to_crs("EPSG:4326")

                # Extraer la geometría LineString y guardarla como el perfil activo
                st.session_state.active_profile_line = gdf_lfp_wgs84.geometry.iloc[0]
                
                # Actualizar el nombre de la fuente para que el usuario sepa de dónde viene
                st.session_state.profile_source = 'LFP Calculado'
                
                # Forzar la actualización del mapa y la interfaz
                st.session_state.profile_map_key += 1
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo cargar el LFP: {e}")
        # --- FIN: SECCIÓN MODIFICADA ---

    with col2:
        st.file_uploader("Cargar Shapefile (.zip)", type=['zip'], key='profile_uploader', on_change=handle_profile_upload)






    st.subheader("Dibujar Perfil Manualmente")
    data = st.session_state.perfil_data
    bounds = data['bounds']
    center = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    
    m = folium.Map(location=center, zoom_start=11)
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    
    folium.GeoJson(data['area_geojson'], name=f"Área Activa ({source_name})", style_function=lambda x: {'color': 'gray', 'weight': 2, 'opacity': 0.8, 'fillOpacity': 0.1, 'dashArray': '5, 5'}).add_to(m)
    if source_name == "Polígono Manual" and 'cuenca_results' in st.session_state:
        folium.GeoJson(st.session_state.cuenca_results['buffer_gdf'], name="Contexto: Cuenca + Buffer", style_function=lambda x: {'color': 'tomato', 'weight': 2, 'fillOpacity': 0.05}).add_to(m)
    if source_name != "Polígono Manual" and 'poligono_results' in st.session_state and 'poligono_gdf' in st.session_state.poligono_results:
        folium.GeoJson(st.session_state.poligono_results['poligono_gdf'], name="Contexto: Polígono Manual", style_function=lambda x: {'color': 'magenta', 'weight': 2, 'fillOpacity': 0.1}).add_to(m)

    if 'active_profile_line' in st.session_state and st.session_state.active_profile_line:
        line_to_draw = gpd.GeoDataFrame(geometry=[st.session_state.active_profile_line], crs="EPSG:4326").to_json()
        folium.GeoJson(line_to_draw, name="Perfil Activo", style_function=lambda x: {'color': 'red', 'weight': 3}).add_to(m)

    draw = folium.plugins.Draw(export=True, filename='dibujo.geojson', draw_options={'polyline': {'shapeOptions': {'color': 'red'}}, 'polygon': False, 'marker': False, 'circle': False, 'rectangle': False, 'circlemarker': False})
    draw.add_to(m)
    
    map_output = st_folium(m, use_container_width=True, height=800, returned_objects=['all_drawings'], key=f"profile_map_{st.session_state.profile_map_key}")

    if map_output and map_output.get("all_drawings"):
        if map_output["all_drawings"]:
            last_drawing = map_output["all_drawings"][-1]
            if last_drawing['geometry']['type'] == 'LineString':
                new_line = LineString(last_drawing['geometry']['coordinates'])
                current_line = st.session_state.get('active_profile_line')
                if current_line is None or not new_line.equals(current_line):
                    st.session_state.active_profile_line = new_line
                    st.session_state.profile_source = 'Dibujo Manual'
                    st.session_state.profile_map_key += 1
                    st.rerun()
    
    st.divider()

    if 'active_profile_line' in st.session_state and st.session_state.active_profile_line:
        st.header(f"2. Resultados del Perfil (Origen: {st.session_state.profile_source})")
        with st.spinner("Calculando perfiles..."):
            distances, dem_values, corine_values, cn_values = sample_rasters_along_line(st.session_state.active_profile_line, data)
            
            col_res_1, col_res_2, col_res_3 = st.columns(3)
            with col_res_1:
                fig_elev = go.Figure(); fig_elev.add_trace(go.Scatter(x=distances, y=dem_values, mode='lines', fill='tozeroy', name='Elevación'))
                fig_elev.update_layout(title='Perfil de Elevación', xaxis_title='Distancia (km)', yaxis_title='Elevación (m)'); st.plotly_chart(fig_elev, use_container_width=True)
            with col_res_2:
                corine_colors = [CORINE_COLOR_MAP.get(code, '#FFFFFF') for code in corine_values]
                corine_text = [f"Código: {int(code)}" if not np.isnan(code) else "N/D" for code in corine_values]
                fig_corine = go.Figure(); fig_corine.add_trace(go.Bar(x=distances, y=[1] * len(distances), marker_color=corine_colors, text=corine_text, hoverinfo='text'))
                fig_corine.update_layout(title='Perfil de Cobertura (CORINE)', xaxis_title='Distancia (km)', yaxis={'showticklabels': False, 'showgrid': False, 'zeroline': False}, bargap=0); st.plotly_chart(fig_corine, use_container_width=True)
            with col_res_3:
                fig_cn = go.Figure(); fig_cn.add_trace(go.Scatter(x=distances, y=cn_values, mode='lines', name='CN', line={'color': 'blue'}))
                fig_cn.update_layout(title='Perfil de Número de Curva (CN)', xaxis_title='Distancia (km)', yaxis_title='Valor CN', yaxis_range=[40,100]); st.plotly_chart(fig_cn, use_container_width=True)
