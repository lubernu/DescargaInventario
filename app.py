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

# --- CONFIGURACIÓN DE PÁGINA STREAMLIT ---
st.set_page_config(
    page_title="Dashboard Inventario LEFCOM",
    page_icon="📦",
    layout="wide"
)

# Carpeta temporal para descargas en la nube
DOWNLOAD_DIR = os.path.abspath("./downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

URL_LEFCOM = "https://lefcom.solucionesig.com.co/entrada.php"


def iniciar_driver(folder_descargas):
    """Configura Google Chrome en modo Headless para entornos Linux de Streamlit Cloud."""
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

    # Rutas estándar donde Debian/Ubuntu instala chromium-driver
    rutas_driver = [
        "/usr/bin/chromedriver",
        "/usr/lib/chromium-browser/chromedriver",
        "/usr/lib/chromium/chromedriver"
    ]
    
    for ruta in rutas_driver:
        if os.path.exists(ruta):
            service = Service(ruta)
            return webdriver.Chrome(service=service, options=chrome_options)
            
    # Fallback automático con webdriver-manager si no encuentra las rutas del sistema
    return webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)


def login_lefcom(driver, usuario, password):
    """Inicia sesión en la plataforma LEFCOM."""
    driver.get(URL_LEFCOM)
    wait = WebDriverWait(driver, 15)

    # 1. Campo Usuario
    username_field = wait.until(EC.presence_of_element_located((By.NAME, "login")))
    username_field.clear()
    username_field.send_keys(usuario)

    # 2. Campo Contraseña
    password_field = driver.find_element(By.NAME, "passw")
    password_field.clear()
    password_field.send_keys(password)

    # 3. Clic en Entrar
    try:
        login_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
        login_btn.click()
    except NoSuchElementException:
        password_field.submit()

    # 4. Control opcional de alertas emergentes de JS
    try:
        WebDriverWait(driver, 3).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        alert.accept()
    except TimeoutException:
        pass

    time.sleep(2)


# --- CACHÉ CONFIGURADO A 1 HORA (3600 SEGUNDOS) ---
@st.cache_data(ttl=3600, show_spinner=False)
def obtener_datos_inventario(usuario, password):
    """Ejecuta Selenium, descarga el reporte y procesa el DataFrame."""
    driver = iniciar_driver(DOWNLOAD_DIR)
    wait = WebDriverWait(driver, 25)
    
    try:
        # Paso A: Login
        login_lefcom(driver, usuario, password)
        
        # Pasos B: Ir a Reporte Equipos Sin Ventas (Ejecuta la función JS directa)
        try:
            driver.execute_script("irmenu_or('reportes/reporte_equipos_sin_ventas.php');")
        except Exception:
            # Fallback en caso de requerir clic manual
            btn_reportes = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'REPORTES')]")))
            btn_reportes.click()
            time.sleep(1)
            link_equipos = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@onclick, 'reporte_equipos_sin_ventas.php')]")))
            link_equipos.click()

        # Paso C: Clic en BUSCAR
        btn_buscar = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='send' and contains(text(), 'BUSCAR')]")))
        btn_buscar.click()

        # Paso D: Clic en EXPORTAR TODO
        btn_exportar = wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@id='send' and contains(text(), 'EXPORTAR TODO')]")))
        btn_exportar.click()

        # Esperar la descarga completa en el servidor
        time.sleep(6)

        # Paso E: Buscar el archivo descargado más reciente con el prefijo "Equipos_sin_ventas"
        patron_busqueda = os.path.join(DOWNLOAD_DIR, "Equipos_sin_ventas*")
        archivos_encontrados = glob.glob(patron_busqueda)
        
        if not archivos_encontrados:
            raise FileNotFoundError("No se encontró el archivo 'Equipos_sin_ventas' descargado en la carpeta temporal.")

        # Obtener el archivo con la fecha/hora de creación más reciente
        archivo_mas_reciente = max(archivos_encontrados, key=os.path.getctime)

        # Paso F: Cargar el reporte con Pandas
        try:
            df = pd.read_excel(archivo_mas_reciente)
        except Exception:
            # Fallback si el archivo exportado es CSV en lugar de Excel
            df = pd.read_csv(archivo_mas_reciente, sep=None, engine='python')

        # Limpiar la carpeta temporal tras procesar los datos
        for archivo in archivos_encontrados:
            try:
                os.remove(archivo)
            except Exception:
                pass

        return df

    finally:
        driver.quit()


# --- INTERFAZ STREAMLIT ---

st.title("📦 Dashboard de Inventario - LEFCOM")
st.caption("Conexión automatizada a reporte de Equipos Sin Ventas")

# Botón para forzar actualización de la caché manualmente
col_btn, col_espacio = st.columns([1, 4])
with col_btn:
    if st.button("🔄 Forzar Actualización"):
        st.cache_data.clear()

# Obtener credenciales desde Streamlit Secrets o pedir por pantalla
try:
    user_cred = st.secrets["LEFCOM_USER"]
    pass_cred = st.secrets["LEFCOM_PASS"]
except Exception:
    st.info("💡 Tip: Configura LEFCOM_USER y LEFCOM_PASS en los Secrets de Streamlit para no escribirlos manualmente.")
    col_u, col_p = st.columns(2)
    with col_u:
        user_cred = st.text_input("Usuario LEFCOM:")
    with col_p:
        pass_cred = st.text_input("Contraseña:", type="password")

# Cargar y presentar los datos
if user_cred and pass_cred:
    with st.spinner("Obteniendo inventario desde LEFCOM (almacenado en caché por 1 hora)..."):
        try:
            df_inventario = obtener_datos_inventario(user_cred, pass_cred)
            
            st.success("¡Datos cargados exitosamente!")
            
            # Métricas resumen
            m1, m2 = st.columns(2)
            m1.metric("Total Registros", len(df_inventario))
            m2.metric("Estado de Caché", "Activo (1 hora)")
            
            st.markdown("---")
            
            # Visor del DataFrame
            st.dataframe(df_inventario, use_container_width=True)
            
            # Opción adicional para descargar la tabla limpia a tu celular/PC
            csv_data = df_inventario.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Descargar copia CSV a este dispositivo",
                data=csv_data,
                file_name="Inventario_Lefcom_Procesado.csv",
                mime="text/csv"
            )

        except Exception as e:
            st.error(f"Ocurrió un error al procesar la automatización: {e}")
else:
    st.warning("Por favor ingresa tus credenciales de LEFCOM para continuar.")
