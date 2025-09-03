import rasterio
import fiona
from shapely.geometry import shape, Point
import os
import json
from pyproj import CRS, Transformer

# Define the base data folder (relative to app.py)
DATA_FOLDER = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')

# This mapping should be consistent with app.py
LAYER_MAPPING = {
    "BASINS": "demarcaciones_hidrograficas.gpkg",
    "RIVERS": "red10km.gpkg",
    "ZONES": "regiones.gpkg",
    "MDT": "mdt.tif",
    "FLOWDIRS": "dir.tif",
    "I1ID": "i1id.tif",
    "P0": "p0.tif",
    "RAIN_2": "t2.tif",
    "RAIN_5": "t5.tif",
    "RAIN_10": "t10.tif",
    "RAIN_25": "t25.tif",
    "RAIN_100": "t100.tif",
    "RAIN_500": "t500.tif",
    "FLOW_2": "q2.tif",
    "FLOW_5": "q5.tif",
    "FLOW_10": "q10.tif",
    "FLOW_25": "q25.tif",
    "FLOW_100": "q100.tif",
    "FLOW_500": "q500.tif",
}

def get_layer_path(layer_name_key):
    """
    Returns the full path to a GIS layer file using the LAYER_MAPPING.
    """
    filename = LAYER_MAPPING.get(layer_name_key)
    if not filename:
        raise ValueError(f"Layer key '{layer_name_key}' not found in LAYER_MAPPING.")
    
    full_path = os.path.join(DATA_FOLDER, filename)
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"Layer file not found: {full_path}. Check DATA_FOLDER and LAYER_MAPPING.")
    return full_path

def get_raster_value_at_point(raster_path, point_utm):
    """
    Reads a raster value at a given UTM point (x, y).
    Returns None if the point is outside the raster or is NoData.
    """
    try:
        with rasterio.open(raster_path) as src:
            if not isinstance(point_utm, (list, tuple)) or len(point_utm) != 2:
                raise ValueError("point_utm must be a tuple or list of two floats (x, y).")

            row, col = src.index(point_utm[0], point_utm[1])
            
            if not (0 <= row < src.height and 0 <= col < src.width):
                return None

            value = src.read(1)[row, col]
            
            if src.nodata is not None and value == src.nodata:
                return None
            return value
    except Exception as e:
        print(f"Error reading raster {raster_path} at {point_utm}: {e}")
        return None

def get_vector_feature_at_point(vector_path, point_utm):
    """
    Finds the first vector feature at a given UTM point (x, y).
    Returns the feature as a dictionary or None if no feature found.
    """
    point_shapely = Point(point_utm)
    try:
        with fiona.open(vector_path, 'r') as source:
            for feature in source:
                # Use shapely.geometry.shape for robust geometry creation
                geom_shapely = shape(feature['geometry'])
                if geom_shapely.contains(point_shapely):
                    return feature
            return None
    except Exception as e:
        print(f"Error querying vector layer {vector_path} at {point_utm}: {e}")
        return None

def load_geojson_from_gpkg(gpkg_path):
    """
    Loads all features from a GPKG file and returns them as a GeoJSON FeatureCollection.
    Transforms coordinates to WGS84 (EPSG:4326) for Folium.
    Ensures all parts are JSON serializable.
    """
    features = []
    try:
        with fiona.open(gpkg_path, 'r') as source:
            source_crs = CRS(source.crs)
            target_crs = CRS("EPSG:4326")

            transformer = None
            if source_crs != target_crs:
                transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

            for feature in source:
                geom = shape(feature['geometry'])
                
                if transformer:
                    # Transform the geometry object itself
                    from shapely.ops import transform
                    geom = transform(transformer.transform, geom)

                # Create a JSON-serializable feature dictionary
                feature_dict = {
                    "type": "Feature",
                    "properties": dict(feature['properties']),
                    "geometry": geom.__geo_interface__ # Use the __geo_interface__ standard
                }
                features.append(feature_dict)

        return {
            "type": "FeatureCollection",
            "features": features
        }
    except Exception as e:
        print(f"Error loading GeoJSON from {gpkg_path}: {e}")
        return None