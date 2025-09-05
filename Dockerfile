# Dockerfile multi-stage para deployment web
# Mantiene la arquitectura dual-environment: Python 3.13 principal + Python 3.9 para PySheds

# Etapa 1: Entorno PySheds con Python 3.9 usando Conda
FROM continuumio/miniconda3:latest as pysheds-env

# Configurar conda para usar conda-forge y evitar conflictos
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority strict && \
    conda update -n base -c defaults conda

# Crear entorno conda con Python 3.9 y dependencias geoespaciales
RUN conda create -n pysheds_env python=3.9 -y && \
    conda clean -a -y

# Activar entorno e instalar dependencias principales
RUN conda install -n pysheds_env -c conda-forge \
    python=3.9 \
    pysheds \
    numpy \
    scipy \
    matplotlib \
    geopandas \
    rasterio \
    shapely \
    pyproj \
    networkx \
    numba \
    scikit-image \
    pillow \
    pandas \
    folium \
    pytz \
    click \
    cartopy \
    contourpy \
    packaging \
    -y && \
    conda clean -a -y

# Instalar GDAL via conda (más confiable)
RUN conda install -n pysheds_env -c conda-forge gdal=3.8.4 -y && \
    conda clean -a -y

# Crear directorio para el entorno PySheds
WORKDIR /app/Py2Env

# Copiar script de delineación
COPY Py2Env/delinear_cuenca.py ./delinear_cuenca.py

# Etapa 2: Aplicación principal con Python 3.13
FROM python:3.13-slim

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-numpy-dev \
    libgdal-dev \
    python3-gdal \
    gdal-bin \
    libproj-dev \
    libgeos-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# Variables entorno (ANTES del pip install)
ENV GDAL_CONFIG=/usr/bin/gdal-config
ENV GDAL_DATA=/usr/share/gdal
ENV PROJ_LIB=/usr/share/proj

# GDAL para Python 3.13 específicamente
RUN python3.13 -m pip install --no-cache-dir GDAL[numpy]==3.8.4

# Crear directorio de la aplicación
WORKDIR /app

# Copiar entorno conda PySheds desde la etapa anterior
COPY --from=pysheds-env /opt/conda/envs/pysheds_env ./conda_env/pysheds_env
COPY --from=pysheds-env /app/Py2Env ./Py2Env

# Copiar requirements de la aplicación principal
COPY requirements.txt ./

# Instalar dependencias de la aplicación principal
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fuente de la aplicación
COPY app.py ./
COPY dem25_tab.py ./
COPY gis_tabs.py ./
COPY perfil_terreno_tab.py ./
COPY core_logic/ ./core_logic/
COPY logo.png ./
COPY data/ ./data/
COPY MDT25_peninsula_UTM30N.tif ./
# Crear directorio de configuración Streamlit
RUN mkdir -p .streamlit

# Configuración Streamlit para deployment
# Configuración Streamlit para deployment
RUN echo "[server]" > .streamlit/config.toml && \
    echo "headless = true" >> .streamlit/config.toml && \
    echo "address = \"0.0.0.0\"" >> .streamlit/config.toml && \
    echo "enableCORS = false" >> .streamlit/config.toml && \
    echo "enableXsrfProtection = false" >> .streamlit/config.toml && \
    echo "" >> .streamlit/config.toml && \
    echo "[theme]" >> .streamlit/config.toml && \
    echo "base = \"light\"" >> .streamlit/config.toml

# Exponer puerto
# EXPOSE 8501  # Render se encarga del routing automáticamente

# Verificar que el entorno conda PySheds funciona
RUN /app/conda_env/pysheds_env/bin/python --version

# Comando de inicio
CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0