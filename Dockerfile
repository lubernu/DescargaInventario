# Usamos una imagen oficial de Python basada en Debian 12 (Bookworm), que tiene repositorios vigentes
FROM python:3.11-slim

WORKDIR /app

# Actualizamos e instalamos Chromium y su driver
# --no-install-recommends mantiene la imagen ligera
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Instalamos las dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos el resto del código de tu aplicación
COPY . .

# Expone el puerto que usa Streamlit
EXPOSE 8501

# Comando para iniciar la app (obligatorio en contenedores)
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
