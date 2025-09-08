# Usamos una imagen base que ya incluye mamba para mayor eficiencia
FROM mambaorg/micromamba:1.5.6

# --- ¡AQUÍ ESTÁ LA CORRECCIÓN CLAVE! ---
# 1. Creamos el directorio de la aplicación.
# 2. Le damos la propiedad al usuario 'micromamba' (que es el usuario 'mambauser').
# Hacemos esto ANTES de empezar a trabajar dentro de él.
RUN mkdir -p /app && chown -R micromamba:micromamba /app

# Ahora establecemos el directorio de trabajo. A partir de aquí, todos los
# comandos se ejecutarán dentro de /app, un directorio que nos pertenece.
WORKDIR /app

# Copiar el archivo de entorno primero para aprovechar el cacheo de Docker
COPY --chown=micromamba:micromamba environment.yml .

# Crear el entorno Conda usando mamba (mucho más rápido y eficiente en memoria)
# y luego limpiar la caché para mantener la imagen pequeña.
RUN micromamba create -y -f environment.yml -n caumax-env && \
    micromamba clean --all --yes

# Crear un script de activación para que los comandos posteriores usen el entorno
# Esto asegura que el entorno esté activo para el CMD
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# Copiar todo el código de la aplicación al contenedor
COPY --chown=micromamba:micromamba . .

# Configuración de Streamlit para el despliegue
# Este comando ahora funcionará porque estamos en un directorio que nos pertenece.
RUN mkdir -p .streamlit && \
    echo "[server]" > .streamlit/config.toml && \
    echo "headless = true" >> .streamlit/config.toml && \
    echo "port = 8501" >> .streamlit/config.toml && \
    echo "address = \"0.0.0.0\"" >> .streamlit/config.toml && \
    echo "enableCORS = false" >> .streamlit/config.toml && \
    echo "enableXsrfProtection = false" >> .streamlit/config.toml

# Exponer el puerto que Streamlit usará
EXPOSE 8501

# El comando de inicio ahora es más simple porque el entorno ya está activado
# Render usará la variable $PORT, así que la pasamos al comando
CMD streamlit run app.py --server.port=$PORT