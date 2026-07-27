import os
import time
import glob
import pandas as pd
import streamlit as st

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from webdriver_manager.chrome import ChromeDriverManager

# --- CONFIGURACIÓN STREAMLIT ---
st.set_page_config(
    page_title="Dashboard Inventario LEFCOM",
    page_icon="📱",
    layout="wide"
)

DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

URL_LEFCOM = "https://lefcom.solucionesig.com.co/entrada.php"


def limpiar_carpeta_descargas(folder):
    """Elimina todos los archivos temporales para evitar acumular residuos en el servidor."""
    if os.path.exists(folder):
        for archivo in os.listdir(folder):
            ruta_completa = os.path.join(folder, archivo)
            try:
                if os.path.isfile(ruta_completa):
                    os.remove(ruta_completa)
            except Exception:
                pass


def iniciar_driver(folder_descargas):
    """Inicia Chromium en modo Headless apto para Streamlit Cloud (Linux)."""
    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    prefs = {
        "download.default_directory": folder_descargas,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True
    }
    chrome_options.add_experimental_option("prefs", prefs)

    rutas_driver = [
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver"
    ]
    
    for ruta in rutas_driver:
        if os.path.exists(ruta):
            return webdriver.Chrome(service=Service(ruta), options=chrome_options)
            
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)


def login_lefcom(driver, usuario, password):
    driver.get(URL_LEFCOM)
    wait = WebDriverWait(driver, 15)

    username_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
    username_field.clear()
    username_field.send_keys(usuario)

    password_field = driver.find_element(By.NAME, "passw")
    password_field.clear()
    password_field.send_keys(password)

    try:
        login_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
        login_btn.click()
    except NoSuchElementException:
        password_field.submit()

    try:
        WebDriverWait(driver, 3).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert.accept()
    except TimeoutException:
        pass

    time.sleep(2)


# --- CACHÉ CONFIGURADO A 1 HORA (3600 SEGUNDOS) ---
@st.cache_data(ttl=3600, show_spinner=False)
def obtener_y_procesar_inventario(usuario, password):
    limpiar_carpeta_descargas(DOWNLOAD_DIR)
    driver = iniciar_driver(DOWNLOAD_DIR)
    wait = WebDriverWait(driver, 25)
    
    try:
        login_lefcom(driver, usuario, password)
        
        try:
            driver.execute_script("irmenu_or('reportes/reporte_equipos_sin_ventas.php');")
        except Exception:
            btn_reportes = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'REPORTES')]")))
            btn_reportes.click()
            time.sleep(1)
            link_equipos = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@onclick, 'reporte_equipos_sin_ventas.php')]")))
            link_equipos.click()

        btn_buscar = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='send' and contains(text(), 'BUSCAR')]")))
        btn_buscar.click()

        btn_exportar = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='send' and contains(text(), 'EXPORTAR TODO')]")))
        btn_exportar.click()

        time.sleep(6)

        patron_busqueda = os.path.join(DOWNLOAD_DIR, "Equipos_sin_ventas*")
        archivos_encontrados = glob.glob(patron_busqueda)
        
        if not archivos_encontrados:
            raise FileNotFoundError("No se encontró el archivo exportado en la carpeta de descargas.")

        archivo_mas_reciente = max(archivos_encontrados, key=os.path.getctime)

        # Cargar con Pandas especificando el separador Pipe '|'
        try:
            df = pd.read_csv(archivo_mas_reciente, sep='|', encoding='utf-8', on_bad_lines='skip')
        except Exception:
            df = pd.read_excel(archivo_mas_reciente)

        # Normalizar y limpiar textos
        df.columns = df.columns.str.strip()
        df = df.dropna(how="all")

        for col in df.select_dtypes(include="object").columns:
            df[col] = df[col].astype(str).str.strip()

        limpiar_carpeta_descargas(DOWNLOAD_DIR)
        return df

    finally:
        driver.quit()


# --- INTERFAZ STREAMLIT ---

st.title("📱 Dashboard de Inventario LEFCOM")
st.caption("Control de Equipos Sin Ventas en Tiempo Real")

# Botón para forzar actualización
if st.button("🔄 Actualizar Inventario"):
    st.cache_data.clear()

# Credenciales
try:
    user_cred = st.secrets["LEFCOM_USER"]
    pass_cred = st.secrets["LEFCOM_PASS"]
except Exception:
    st.error("Por favor configura tus credenciales LEFCOM_USER y LEFCOM_PASS en los Secrets de Streamlit.")
    st.stop()

# Carga de Datos
with st.spinner("Conectando con LEFCOM y procesando archivo..."):
    try:
        df_raw = obtener_y_procesar_inventario(user_cred, pass_cred)
        
        # --- BUSCADOR POR TELÉFONO / MODELO ---
        st.subheader("🔍 Buscador de Equipos")
        query_telefono = st.text_input("Escribe el nombre o palabra clave del Teléfono/Modelo (ej: ZTE, Motorola, 256GB):", "")
        
        df_filtrado = df_raw.copy()
        
        if query_telefono.strip():
            # Filtra por la columna 'telefono' a medida que escribes
            df_filtrado = df_filtrado[df_filtrado['telefono'].str.contains(query_telefono, case=False, na=False)]

        # --- SECCIÓN DE RESUMEN Y MÉTRICAS CLAVE ---
        col_m1, col_m2, col_m3 = st.columns(3)
        col_m1.metric("Total Registros Coincidentes", len(df_filtrado))
        
        # Conteo de prestados
        prestados_cant = len(df_filtrado[df_filtrado['estado'] == 'Prestado']) if 'estado' in df_filtrado.columns else 0
        col_m2.metric("Equipos Prestados", prestados_cant)
        
        # Total Bodegas activas
        bodegas_cant = df_filtrado['bodega'].nunique() if 'bodega' in df_filtrado.columns else 0
        col_m3.metric("Bodegas Involucradas", bodegas_cant)

        st.markdown("---")

        # --- SECCIÓN DE PESTAÑAS DETALLADAS ---
        tab_tabla, tab_bodega, tab_grupo, tab_prestamos = st.tabs([
            "📋 Tabla Completa", 
            "🏢 Por Bodega", 
            "📦 Por Grupo", 
            "🤝 Préstamos"
        ])

        # 1. Pestaña Tabla Completa
        with tab_tabla:
            st.dataframe(df_filtrado, use_container_width=True, hide_index=True)

        # 2. Pestaña Por Bodega
        with tab_bodega:
            st.markdown("### Resumen por Bodega")
            if 'bodega' in df_filtrado.columns:
                resumen_bodega = df_filtrado.groupby(['bodega', 'estado']).size().unstack(fill_value=0)
                st.dataframe(resumen_bodega, use_container_width=True)
                st.bar_chart(df_filtrado['bodega'].value_counts())

        # 3. Pestaña Por Grupo
        with tab_grupo:
            st.markdown("### Resumen por Grupo / Categoría")
            if 'grupo' in df_filtrado.columns:
                resumen_grupo = df_filtrado['grupo'].value_counts().reset_index()
                resumen_grupo.columns = ['Grupo', 'Cantidad']
                st.dataframe(resumen_grupo, use_container_width=True, hide_index=True)

        # 4. Pestaña Préstamos
        with tab_prestamos:
            st.markdown("### Equipos en Estado 'Prestado'")
            if 'estado' in df_filtrado.columns:
                df_prestados = df_filtrado[df_filtrado['estado'] == 'Prestado']
                if not df_prestados.empty:
                    # Columnas clave para controlar préstamos
                    cols_prestamo = [c for c in ['bodega', 'telefono', 'serial', 'nombres', 'apellidos', 'fec_vencimiento'] if c in df_prestados.columns]
                    st.dataframe(df_prestados[cols_prestamo], use_container_width=True, hide_index=True)
                else:
                    st.info("No hay equipos prestados en el filtro seleccionado.")

        # --- BOTÓN DESCARGAR A CELULAR ---
        st.markdown("---")
        csv_descarga = df_filtrado.to_csv(index=False, sep='|').encode('utf-8')
        st.download_button(
            label="📥 Descargar este filtro a mi celular (CSV '|')",
            data=csv_descarga,
            file_name="Equipos_Sin_Ventas_Filtrado.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"Ocurrió un error con el archivo o la automatización: {e}")
