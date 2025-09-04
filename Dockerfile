# Dockerfile multi-stage para deployment web
# Mantiene la arquitectura dual-environment: Python 3.13 principal + Python 3.9 para PySheds

# Etapa 1: Entorno PySheds con Python 3.9 usando Conda
FROM continuumio/miniconda3:4.12.0 as pysheds-env

# Configurar conda para usar conda-forge y evitar conflictos
RUN conda config --add channels conda-forge && \
    conda config --set channel_priority strict && \
    conda update -n base -c defaults conda

# Crear entorno conda con Python 3.9 y dependencias geoespaciales
RUN conda create -n pysheds_env python=3.9 -y && \
    conda clean -a -y

# Activar entorno e instalar dependencias principales
RUN conda install -n pysheds_env -c conda-forge \
    pysheds=0.5 \
    numpy=1.26.4 \
    scipy=1.11.4 \
    matplotlib=3.9.4 \
    geopandas=1.0.1 \
    rasterio=1.4.3 \
    shapely=2.1.1 \
    pyproj=3.7.2 \
    networkx=3.3 \
    numba=0.60.0 \
    scikit-image=0.22.0 \
    pillow=11.3.0 \
    pandas=2.3.1 \
    folium=0.19.2 \
    pytz=2024.2 \
    click=8.1.7 \
    cartopy=0.23.0 \
    contourpy=1.3.0 \
    packaging=25.0 \
    -y && \
    conda clean -a -y

# Crear directorio para el entorno PySheds
WORKDIR /app/Py2Env

# Copiar script de delineación
COPY delinear_cuenca.py ./delinear_cuenca.py

# Etapa 2: Aplicación principal con Python 3.13
FROM python:3.13-slim

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    libgdal-dev \
    gdal-bin \
    libproj-dev \
    libgeos-dev \
    libspatialindex-dev \
    && rm -rf /var/lib/apt/lists/*

# Configurar variables de entorno GDAL
ENV GDAL_DATA=/usr/share/gdal
ENV PROJ_LIB=/usr/share/proj

# Crear directorio de la aplicación
WORKDIR /app

# Copiar entorno conda PySheds desde la etapa anterior
COPY --from=pysheds-env /opt/conda/envs/pysheds_env ./conda_env/pysheds_env
COPY --from=pysheds-env /app/Py2Env ./Py2Env

# Copiar requirements de la aplicación principal
COPY requirements.txt ./

# Crear requirements optimizado para web (sin versiones problemáticas)
RUN echo "streamlit==1.40.2" > requirements-web.txt && \
    echo "folium==0.19.2" >> requirements-web.txt && \
    echo "streamlit-folium==0.26.0" >> requirements-web.txt && \
    echo "geopandas==1.1.1" >> requirements-web.txt && \
    echo "rasterio==1.4.3" >> requirements-web.txt && \
    echo "pyproj==3.7.2" >> requirements-web.txt && \
    echo "shapely==2.1.1" >> requirements-web.txt && \
    echo "matplotlib==3.10.5" >> requirements-web.txt && \
    echo "plotly==5.24.1" >> requirements-web.txt && \
    echo "pandas==2.3.1" >> requirements-web.txt && \
    echo "scipy==1.16.1" >> requirements-web.txt && \
    echo "numpy==1.26.4" >> requirements-web.txt && \
    echo "Pillow==11.3.0" >> requirements-web.txt && \
    echo "branca==0.9.0" >> requirements-web.txt

# Instalar dependencias de la aplicación principal
RUN pip install --no-cache-dir --upgrade pip
RUN pip install --no-cache-dir -r requirements-web.txt

# Copiar código fuente de la aplicación
COPY app.py ./
COPY dem25_tab.py ./
COPY gis_tabs.py ./
COPY perfil_terreno_tab.py ./
COPY core_logic/ ./core_logic/
COPY logo.png ./

# Crear directorio de configuración Streamlit
RUN mkdir -p .streamlit

# Configuración Streamlit para deployment
RUN echo "[server]" > .streamlit/config.toml && \
    echo "headless = true" >> .streamlit/config.toml && \
    echo "address = \"0.0.0.0\"" >> .streamlit/config.toml && \
    echo "port = 8501" >> .streamlit/config.toml && \
    echo "enableCORS = false" >> .streamlit/config.toml && \
    echo "enableXsrfProtection = false" >> .streamlit/config.toml && \
    echo "" >> .streamlit/config.toml && \
    echo "[theme]" >> .streamlit/config.toml && \
    echo "base = \"light\"" >> .streamlit/config.toml

# Exponer puerto
EXPOSE 8501

# Verificar que el entorno conda PySheds funciona
RUN /app/conda_env/pysheds_env/bin/python --version

# Comando de inicio
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]