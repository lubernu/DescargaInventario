FROM python:3.11-slim

WORKDIR /app

# 1. Instalación de Chromium, driver y librerías gráficas necesarias
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    chromium-driver \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# 2. VERIFICACIÓN DE DEBUG (Esto aparecerá en los logs de Streamlit)
RUN echo "=== VERIFICANDO INSTALACIÓN ===" && \
    chromium --version && \
    chromedriver --version && \
    ls -l /usr/bin/chromedriver

# 3. Instalación de dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copiar código
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
