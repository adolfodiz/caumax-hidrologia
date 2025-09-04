# Dockerfile multi-stage para deployment web
# Mantiene la arquitectura dual-environment: Python 3.13 principal + Python 3.9 para PySheds

# Etapa 1: Entorno PySheds con Python 3.9
FROM python:3.9-slim as pysheds-env

# Instalar dependencias del sistema para compilación
RUN apt-get update && apt-get install -y \
    build-essential \
    libgdal-dev \
    gdal-bin \
    && rm -rf /var/lib/apt/lists/*

# Crear directorio para el entorno PySheds
WORKDIR /app/Py2Env

# Crear entorno virtual para PySheds
RUN python -m venv venv_pysheds

# Copiar requirements específico de PySheds y script
COPY Py2Env/requirements.txt ./
COPY Py2Env/delinear_cuenca.py ./

# Instalar dependencias PySheds en el entorno virtual
RUN ./venv_pysheds/bin/pip install --no-cache-dir --upgrade pip
RUN ./venv_pysheds/bin/pip install --no-cache-dir -r requirements.txt

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

# Copiar entorno PySheds desde la etapa anterior
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
    echo "port = 10000" >> .streamlit/config.toml && \
    echo "enableCORS = false" >> .streamlit/config.toml && \
    echo "enableXsrfProtection = false" >> .streamlit/config.toml && \
    echo "" >> .streamlit/config.toml && \
    echo "[theme]" >> .streamlit/config.toml && \
    echo "base = \"light\"" >> .streamlit/config.toml

# Exponer puerto
EXPOSE 10000

# Verificar que el entorno PySheds funciona
RUN /app/Py2Env/venv_pysheds/bin/python --version

# Comando de inicio
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=10000", "--server.address=0.0.0.0"]
