# Etapa Única: Crear el entorno Conda completo
FROM continuumio/miniconda3:latest

# Crear directorio de la aplicación
WORKDIR /app

# Copiar el archivo de entorno
COPY environment.yml .

# Crear el entorno Conda a partir del archivo y limpiar caché
RUN conda env create -f environment.yml && \
    conda clean -a -y

# Copiar todo el código de la aplicación al contenedor
COPY . .

# Configuración de Streamlit para el despliegue
RUN mkdir -p .streamlit && \
    echo "[server]" > .streamlit/config.toml && \
    echo "headless = true" >> .streamlit/config.toml && \
    echo "port = 8501" >> .streamlit/config.toml && \
    echo "address = \"0.0.0.0\"" >> .streamlit/config.toml && \
    echo "enableCORS = false" >> .streamlit/config.toml && \
    echo "enableXsrfProtection = false" >> .streamlit/config.toml

# Exponer el puerto que Streamlit usará
EXPOSE 8501

# Activar el entorno Conda y ejecutar la aplicación
# Render usará la variable $PORT, así que la pasamos al comando
CMD conda run -n caumax-env streamlit run app.py --server.port=$PORT