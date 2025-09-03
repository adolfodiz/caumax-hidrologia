import argparse
import geopandas as gpd
import numpy as np
import rasterio
from pysheds.grid import Grid
from shapely.geometry import shape
import sys

def delineate_from_precomputed(fdir_path, acc_path, x_coord, y_coord, snap_threshold, output_path):
    try:
        print(f"[WORKER] Iniciado. Args: fdir={fdir_path}, acc={acc_path}, x={x_coord}, y={y_coord}, th={snap_threshold}", file=sys.stderr)
        
        grid = Grid.from_raster(fdir_path)
        fdir = grid.read_raster(fdir_path)
        acc = grid.read_raster(acc_path)
        print("[WORKER] Rasters fdir y acc cargados.", file=sys.stderr)

        try:
            x_snapped, y_snapped = grid.snap_to_mask(acc > snap_threshold, (x_coord, y_coord))
            print(f"[WORKER] Punto original: ({x_coord}, {y_coord}). Punto ajustado (snap): ({x_snapped}, {y_snapped})", file=sys.stderr)
        except Exception as e:
            print(f"[WORKER] ERROR en snap_to_mask: {e}", file=sys.stderr)
            x_snapped, y_snapped = x_coord, y_coord

        print("[WORKER] Delineando catchment...", file=sys.stderr)
        catch = grid.catchment(x=x_snapped, y=y_snapped, fdir=fdir, xytype='coordinate')
        print("[WORKER] Catchment generado. Polygonizando...", file=sys.stderr)
        
        catch_geojson_generator = grid.polygonize(catch)
        
        geometries = [
            {'type': 'Feature', 'geometry': geom, 'properties': {'value': val}}
            for geom, val in catch_geojson_generator if val == 1
        ]
        print(f"[WORKER] Geometrías encontradas: {len(geometries)}", file=sys.stderr)

        if not geometries:
            raise ValueError("La delineación no produjo ninguna geometría.")

        with rasterio.open(fdir_path) as src:
            output_crs = src.crs

        gdf_geometries = [shape(f['geometry']) for f in geometries]
        catch_gdf = gpd.GeoDataFrame({'value': 1}, geometry=gdf_geometries, crs=output_crs)
        print(f"[WORKER] GeoDataFrame creado. ¿Está vacío? {catch_gdf.empty}", file=sys.stderr)
        
        catch_gdf.to_file(output_path, driver='GeoJSON')
        print(f"[WORKER] Archivo de salida guardado en {output_path}", file=sys.stderr)

        print(f"SUCCESS:{output_path}", file=sys.stdout)

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Delineate a watershed catchment using precomputed raster data.")
    parser.add_argument("--fdir_path", required=True, help="Path to the flow direction raster (fdir.tif).")
    parser.add_argument("--acc_path", required=True, help="Path to the flow accumulation raster (acc.tif).")
    parser.add_argument("--x_coord", type=float, required=True, help="X coordinate for delineation point.")
    parser.add_argument("--y_coord", type=float, required=True, help="Y coordinate for delineation point.")
    parser.add_argument("--snap_threshold", type=float, required=True, help="Threshold for snapping to the stream network.")
    parser.add_argument("--output_path", required=True, help="Path to save the output GeoJSON file.")
    
    args = parser.parse_args()
    
    delineate_from_precomputed(
        fdir_path=args.fdir_path,
        acc_path=args.acc_path,
        x_coord=args.x_coord,
        y_coord=args.y_coord,
        snap_threshold=args.snap_threshold,
        output_path=args.output_path
    )