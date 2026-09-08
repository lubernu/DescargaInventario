import os
import re
import io
import time
import hashlib
import pandas as pd
import numpy as np
import streamlit as st
import requests

# --- CONFIGURACIÓN STREAMLIT ---
st.set_page_config(
    page_title="Dashboard Inventario LEFCOM",
    page_icon="📱",
    layout="wide",
    initial_sidebar_state="expanded",
)

URL_BASE = "https://lefcom.solucionesig.com.co"
URL_LOGIN = f"{URL_BASE}/login.php"
URL_MENU = f"{URL_BASE}/menu_principal.php"
URL_REPORTE = f"{URL_BASE}/reportes/reporte_equipos_sin_ventas2.php"
URL_DESCARGAR = f"{URL_BASE}/common/Descargar.php?url=../common/Equipos_sin_ventas.csv&archivo=Equipos_sin_ventas.csv"


# ================================================================
# BACKEND (conexión HTTP directa a LEFCOM, sin Selenium)
# ================================================================

def crear_sesion():
    """Crea una sesión HTTP con headers compatibles con LEFCOM."""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'es-CO,es;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
    })
    return session


def login_lefcom(session, usuario, password):
    """Login al sistema LEFCOM vía HTTP POST (el password se envía en MD5)."""
    password_md5 = hashlib.md5(password.encode('utf-8')).hexdigest()

    login_data = {
        'login': usuario,
        'passw': password_md5,
        'boton-entrar': 'Entrar',
        'status': '',
    }

    resp = session.post(
        URL_LOGIN,
        data=login_data,
        headers={'Referer': f"{URL_BASE}/entrada.php", 'Origin': URL_BASE},
        allow_redirects=True,
        timeout=30,
    )

    if resp.status_code != 200 or 'menu_principal' not in resp.text.lower():
        raise Exception(
            "Login fallido: credenciales incorrectas o el sitio cambi\u00f3 su mecanismo. "
            "Verifica LEFCOM_USER y LEFCOM_PASS en los Secrets."
        )


def descargar_reporte(session):
    """Carga el reporte 'Equipos sin ventas' y descarga el CSV generado por LEFCOM."""
    # 1. Disparar generación del reporte (mismo POST que hace el navegador al pulsar BUSCAR)
    datos_reporte = {
        'bodega': '',
        'idbodega': '',
        'idgrupo': '',
        'cont_bot': '1',
        'link': '/reportes/reporte_equipos_sin_ventas.php',
    }
    resp = session.post(
        URL_REPORTE,
        data=datos_reporte,
        headers={'Referer': f"{URL_BASE}/reportes/reporte_equipos_sin_ventas.php", 'Origin': URL_BASE},
        timeout=60,
    )
    if resp.status_code != 200:
        raise Exception(f"No se pudo cargar el reporte (status {resp.status_code}).")

    # 2. Descargar el CSV del export
    resp_csv = session.get(
        URL_DESCARGAR,
        headers={'Referer': f"{URL_BASE}/reportes/reporte_equipos_sin_ventas2.php"},
        timeout=60,
    )
    if resp_csv.status_code != 200 or not resp_csv.content:
        raise Exception(f"No se pudo descargar el CSV (status {resp_csv.status_code}).")

    return resp_csv.content


# --- CACHÉ CONFIGURADO A 6 HORAS (21600 SEGUNDOS) ---
@st.cache_data(ttl=21600, show_spinner=False)
def obtener_y_procesar_inventario(usuario, password):
    """Conecta a LEFCOM por HTTP, descarga el reporte y lo procesa."""
    session = crear_sesion()

    try:
        login_lefcom(session, usuario, password)
        contenido_csv = descargar_reporte(session)
    except Exception as e:
        raise Exception(f"Error conectando con LEFCOM: {e}")

    contenido = contenido_csv.decode('utf-8', errors='replace')

    try:
        df = pd.read_csv(io.StringIO(contenido), sep='|', on_bad_lines='skip')
    except Exception:
        df = pd.read_csv(io.StringIO(contenido), sep=';', on_bad_lines='skip')

    if df.empty:
        raise Exception("El reporte descargado no contiene datos.")

    df.columns = df.columns.str.strip()
    df = df.dropna(how="all")

    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()

    # CLASIFICACIÓN DE MARCA SEGÚN REGLAS DE NEGOCIO
    if 'telefono' in df.columns and 'grupo' in df.columns:
        primera_palabra = df['telefono'].str.split().str[0]
        segunda_palabra = df['telefono'].str.split().str[1]

        condiciones = [
            df['grupo'].eq('EQUIPOS EN CONSIGNACION'),
            df['grupo'].eq('KIT PREPAGO INDIVIDUAL'),
            df['grupo'].str.startswith('SIM', na=False),
            df['grupo'].eq('ELECTRODOMESTICOS'),
        ]
        valores = [
            primera_palabra,
            segunda_palabra,
            'SIM',
            'ELECTRODOMESTICOS',
        ]

        df['marca'] = np.select(condiciones, valores, default=np.nan)

        df['marca'] = df['marca'].astype(str).str.upper().str.strip()

        correcciones_marcas = {
            'SAMSUN': 'SAMSUNG',
            'SAMSUMG': 'SAMSUNG',
            'SAMSUNGS': 'SAMSUNG',
            'APP': 'APPLE',
            'IPHONNE': 'APPLE',
            'IPHONE': 'APPLE',
            'MOTO': 'MOTOROLA',
            'XIAOM': 'XIAOMI',
        }

        df['marca'] = df['marca'].replace(correcciones_marcas)

        df['marca'] = df['marca'].replace({'NAN': np.nan, '': np.nan, 'NONE': np.nan})

    return df


# ================================================================
# DISEÑO / TEMA
# ================================================================

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
[data-testid="stHeader"] {background: transparent; height: 0px;}

html, body, [class*="css"], [data-testid="stAppViewContainer"] {
    font-family: 'Plus Jakarta Sans', 'Segoe UI', sans-serif;
}

[data-testid="stAppViewContainer"] {
    background: #f4f6fb;
}

h1, h2, h3, h4 {color: #0f1b3d; letter-spacing: -0.02em;}

/* ---------- SIDEBAR ---------- */
[data-testid="stSidebar"] {
    background: #0f1b3d;
    border-right: 1px solid rgba(255,255,255,.06);
}
[data-testid="stSidebar"] * {color: #e8ecf5;}
[data-testid="stSidebar"] label p {color: #8fa3d8 !important; font-weight: 600;}
[data-testid="stSidebar"] [data-testid="stTextInput"] input {
    background: #16254f; border: 1px solid #24345f; color: #fff; border-radius: 10px;
}
[data-testid="stSidebar"] [data-testid="stTextInput"] input::placeholder {color: #8a97b8;}
[data-testid="stSidebar"] ::placeholder {color: #8a97b8;}
[data-testid="stSidebar"] [data-baseweb="select"] > div {
    background: #16254f; border-color: #24345f; border-radius: 10px;
}
[data-testid="stSidebar"] [data-baseweb="menu"] [role="option"] {color: #0f1b3d;}
[data-testid="stSidebar"] hr {border-color: rgba(255,255,255,.08);}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {color: #b9c7e8;}

.sidebar-brand {
    padding: 4px 2px 18px;
    border-bottom: 1px solid rgba(255,255,255,.09);
    margin-bottom: 14px;
}
.sidebar-brand .logo {
    font-size: 1.9rem;
}
.sidebar-brand h3 {
    color: #fff; font-size: 1.15rem; font-weight: 800; margin: 8px 0 2px;
}
.sidebar-brand p {
    color: #8fa3d8; font-size: .75rem; margin: 0; letter-spacing: .04em;
}
.sidebar-section-title {
    font-size: .7rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: .14em; color: #8fa3d8; margin: 8px 0 6px;
}

/* ---------- HERO ---------- */
.hero {
    position: relative;
    overflow: hidden;
    background: linear-gradient(135deg, #0b1230 0%, #12204a 45%, #2563eb 130%);
    border-radius: 22px;
    padding: 34px 42px;
    color: #fff;
    margin-bottom: 20px;
    box-shadow: 0 14px 44px rgba(15,27,61,.18);
}
.hero::after {
    content: "";
    position: absolute;
    top: -70%; right: -8%;
    width: 440px; height: 440px;
    background: radial-gradient(circle, rgba(37,99,235,.4), transparent 60%);
}
.hero-badge {
    display: inline-block;
    font-size: .72rem; font-weight: 700; letter-spacing: .16em;
    text-transform: uppercase;
    padding: 6px 14px; border-radius: 999px;
    background: rgba(255,255,255,.12); color: #c7d6ff;
    margin-bottom: 16px;
}
.hero h1 {
    color: #fff; font-size: 2.05rem; font-weight: 800;
    margin: 0 0 8px; letter-spacing: -.02em;
}
.hero p {
    color: #b9c7e8; font-size: 1rem; margin: 0 0 22px; max-width: 760px;
}
.hero-meta {display: flex; gap: 34px; flex-wrap: wrap;}
.hero-meta-item b {display: block; font-size: 1.25rem; color: #fff; font-weight: 800;}
.hero-meta-item span {font-size: .72rem; color: #8fa3d8; text-transform: uppercase; letter-spacing: .09em;}

/* ---------- KPI CARDS ---------- */
.kpi-card {
    background: #ffffff;
    border: 1px solid #e9edf5;
    border-radius: 18px;
    padding: 18px 20px;
    box-shadow: 0 6px 24px rgba(15,27,61,.05);
    border-top: 4px solid var(--accent);
    margin-bottom: 12px;
    transition: transform .15s ease, box-shadow .15s ease;
}
.kpi-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 30px rgba(15,27,61,.10);
}
.kpi-encabezado {display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;}
.kpi-icono {font-size: 1.6rem; line-height: 1;}
.kpi-sub {font-size: .7rem; color: #8a97b8; font-weight: 700; text-transform: uppercase; letter-spacing: .07em;}
.kpi-valor {font-size: 2.15rem; font-weight: 800; color: #0f1b3d; line-height: 1;}
.kpi-etiqueta {font-size: .83rem; color: #5b6b8c; font-weight: 600; margin-top: 8px;}

/* ---------- SECCIONES / PANELES ---------- */
.panel {
    background: #ffffff;
    border: 1px solid #e9edf5;
    border-radius: 18px;
    padding: 20px 24px;
    box-shadow: 0 6px 24px rgba(15,27,61,.04);
    margin-bottom: 16px;
}
.panel h3 {margin: 0 0 12px; font-size: 1.05rem; font-weight: 700;}

/* ---------- TABS ---------- */
.stTabs [data-baseweb="tab-list"] {gap: 8px; border-bottom: 1px solid #e4e9f2; padding-bottom: 2px;}
.stTabs [data-baseweb="tab"] {
    border-radius: 10px;
    padding: 8px 18px;
    background: #eef1f7;
    color: #5b6b8c;
    font-weight: 600;
    border: 1px solid transparent;
    transition: all .15s ease;
}
.stTabs [data-baseweb="tab"]:hover {color: #1d4ed8; background: #e6edff;}
.stTabs [aria-selected="true"] {
    background: #ffffff;
    border-color: #d4deef;
    color: #1d4ed8 !important;
    box-shadow: 0 2px 10px rgba(15,27,61,.08);
}

/* ---------- BOTONES ---------- */
.stButton > button {
    border-radius: 12px;
    font-weight: 600;
    border: none;
    padding: .55rem 1.2rem;
    background: linear-gradient(135deg, #2563eb, #1d4ed8);
    color: #ffffff;
    box-shadow: 0 4px 14px rgba(37,99,235,.25);
    transition: all .15s ease;
}
.stButton > button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 24px rgba(37,99,235,.38);
    color: #ffffff;
}
div[data-testid="stDownloadButton"] button {
    border-radius: 12px;
    font-weight: 600;
    border: 1.5px solid #2563eb;
    color: #1d4ed8;
    background: #eef4ff;
}
div[data-testid="stDownloadButton"] button:hover {background: #e0ebff; color: #1d4ed8;}

/* ---------- TABLAS ---------- */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid #e9edf5;
    box-shadow: 0 4px 18px rgba(15,27,61,.04);
}

/* ---------- SPINNER / TEXTO ---------- */
[data-testid="stSpinner"] > div {border-color: #2563eb !important;}

/* ---------- FOOTER ---------- */
.footer {
    margin-top: 30px;
    padding-top: 16px;
    border-top: 1px solid #e4e9f2;
    text-align: center;
    color: #8a97b8;
    font-size: .8rem;
}
"""


def inyectar_css():
    st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


def tarjeta_kpi(icono, etiqueta, valor, color, subtexto=""):
    st.markdown(
        f"""
        <div class="kpi-card" style="--accent:{color}">
            <div class="kpi-encabezado">
                <span class="kpi-icono">{icono}</span>
                <span class="kpi-sub">{subtexto}</span>
            </div>
            <div class="kpi-valor">{valor}</div>
            <div class="kpi-etiqueta">{etiqueta}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ================================================================
# INTERFAZ
# ================================================================

inyectar_css()

# ---------- SIDEBAR ----------
with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="logo">📱</div>
            <h3>LEFCOM Inventario</h3>
            <p>Control de equipos sin ventas</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="sidebar-section-title">Panel de control</div>', unsafe_allow_html=True)

    if st.button("🔄 Actualizar Inventario", use_container_width=True):
        st.cache_data.clear()

    query_telefono = st.text_input(
        "🔍 Buscar teléfono o modelo",
        placeholder="Ej: ZTE, 256GB, Motorola...",
    )

    st.caption("Los resultados se actualizan automáticamente cada 6 horas y con el botón de arriba.")

# ---------- CREDENCIALES ----------
try:
    user_cred = st.secrets["LEFCOM_USER"]
    pass_cred = st.secrets["LEFCOM_PASS"]
except Exception:
    st.error("Por favor configura tus credenciales LEFCOM_USER y LEFCOM_PASS en los Secrets de Streamlit.")
    st.stop()

# ---------- HERO ----------
st.markdown(
    f"""
    <div class="hero">
        <span class="hero-badge">Sistema LEFCOM · Tiempo Real</span>
        <h1>Inventario de Equipos Sin Ventas</h1>
        <p>Control centralizado de bodegas, marcas, grupos y préstamos. Busca por teléfono o modelo
        y descarga el filtro directamente en tu celular.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------- CARGA DE DATOS ----------
with st.spinner("Conectando con LEFCOM y procesando archivo..."):
    try:
        df_raw = obtener_y_procesar_inventario(user_cred, pass_cred)

        # ---------- FILTROS ADICIONALES (SIDEBAR) ----------
        with st.sidebar:
            st.markdown('<div class="sidebar-section-title">Filtros rápidos</div>', unsafe_allow_html=True)

            filtro_marca = []
            if 'marca' in df_raw.columns:
                marcas_opciones = sorted(df_raw['marca'].dropna().unique().tolist())
                if marcas_opciones:
                    filtro_marca = st.multiselect(
                        "🏷️ Marca",
                        options=marcas_opciones,
                        placeholder="Todas las marcas",
                    )

            filtro_estado = []
            if 'estado' in df_raw.columns:
                estados_opciones = sorted(df_raw['estado'].dropna().unique().tolist())
                if estados_opciones:
                    filtro_estado = st.multiselect(
                        "📌 Estado",
                        options=estados_opciones,
                        placeholder="Todos los estados",
                    )

        # ---------- APLICAR FILTROS ----------
        df_filtrado = df_raw.copy()

        if query_telefono.strip():
            df_filtrado = df_filtrado[
                df_filtrado['telefono'].str.contains(query_telefono.strip(), case=False, na=False)
            ]

        if filtro_marca:
            df_filtrado = df_filtrado[df_filtrado['marca'].isin(filtro_marca)]

        if filtro_estado:
            df_filtrado = df_filtrado[df_filtrado['estado'].isin(filtro_estado)]

        # ---------- KPIs ----------
        prestados_cant = (
            int((df_filtrado['estado'] == 'Prestado').sum())
            if 'estado' in df_filtrado.columns
            else 0
        )
        bodegas_cant = df_filtrado['bodega'].nunique() if 'bodega' in df_filtrado.columns else 0
        marcas_cant = df_filtrado['marca'].nunique(dropna=True) if 'marca' in df_filtrado.columns else 0

        k1, k2, k3, k4 = st.columns(4)
        with k1:
            tarjeta_kpi("🗂️", "Registros coincidentes", f"{len(df_filtrado):,}", "#2563eb", "Total equipos")
        with k2:
            tarjeta_kpi("🤝", "Equipos prestados", f"{prestados_cant:,}", "#f59e0b", "En préstamo")
        with k3:
            tarjeta_kpi("🏢", "Bodegas involucradas", f"{bodegas_cant:,}", "#8b5cf6", "Puntos de venta")
        with k4:
            tarjeta_kpi("🔖", "Marcas detectadas", f"{marcas_cant:,}", "#10b981", "Clasificación")

        st.markdown("---")

        # ---------- PESTAÑAS DETALLADAS ----------
        tab_tabla, tab_bodega, tab_grupo, tab_prestamos, tab_marca = st.tabs(
            ["📋 Tabla Completa", "🏢 Por Bodega", "📦 Por Grupo", "🤝 Préstamos", "🔖 Por Marca"]
        )

        # 1. TABLA COMPLETA
        with tab_tabla:
            st.markdown(
                """
                <div class="panel">
                    <h3>Inventario completo</h3>
                </div>
                """,
                unsafe_allow_html=True,
            )
            cols_orden = []
            for col in ['marca', 'telefono', 'bodega', 'estado', 'grupo']:
                if col in df_filtrado.columns and col not in cols_orden:
                    cols_orden.append(col)
            cols_orden += [c for c in df_filtrado.columns if c not in cols_orden]
            st.dataframe(df_filtrado[cols_orden], use_container_width=True, hide_index=True)

        # 2. POR BODEGA
        with tab_bodega:
            st.markdown(
                """
                <div class="panel">
                    <h3>Distribución por bodega y estado</h3>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if 'bodega' in df_filtrado.columns:
                colg1, colg2 = st.columns([3, 2])
                with colg1:
                    st.bar_chart(df_filtrado['bodega'].value_counts(), color="#10b981")
                with colg2:
                    resumen_bodega = df_filtrado.groupby(['bodega', 'estado']).size().unstack(fill_value=0)
                    st.dataframe(resumen_bodega, use_container_width=True)

        # 3. POR GRUPO
        with tab_grupo:
            st.markdown(
                """
                <div class="panel">
                    <h3>Resumen por grupo / categoría</h3>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if 'grupo' in df_filtrado.columns:
                colg1, colg2 = st.columns([2, 3])
                with colg1:
                    resumen_grupo = df_filtrado['grupo'].value_counts().reset_index()
                    resumen_grupo.columns = ['Grupo', 'Cantidad']
                    st.dataframe(resumen_grupo, use_container_width=True, hide_index=True)
                with colg2:
                    st.bar_chart(df_filtrado['grupo'].value_counts(), color="#f59e0b")

        # 4. PRÉSTAMOS
        with tab_prestamos:
            st.markdown(
                """
                <div class="panel">
                    <h3>Equipos en estado "Prestado"</h3>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if 'estado' in df_filtrado.columns:
                df_prestados = df_filtrado[df_filtrado['estado'] == 'Prestado']
                if not df_prestados.empty:
                    cols_prestamo = [
                        c for c in ['bodega', 'telefono', 'serial', 'nombres', 'apellidos', 'fec_vencimiento']
                        if c in df_prestados.columns
                    ]
                    st.dataframe(df_prestados[cols_prestamo], use_container_width=True, hide_index=True)
                else:
                    st.info("No hay equipos prestados en el filtro seleccionado.")

        # 5. POR MARCA
        with tab_marca:
            st.markdown(
                """
                <div class="panel">
                    <h3>Análisis por marca</h3>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if 'marca' in df_filtrado.columns:
                marcas_disponibles = sorted(df_filtrado['marca'].dropna().unique())
                if marcas_disponibles:
                    col_sel, col_sp = st.columns([1, 2])
                    with col_sel:
                        marca_seleccionada = st.selectbox("Selecciona una marca:", marcas_disponibles)
                    df_marca = df_filtrado[df_filtrado['marca'] == marca_seleccionada]
                    total_referencias = df_marca['telefono'].nunique()
                    total_registros = len(df_marca)

                    c1, c2 = st.columns(2)
                    with c1:
                        tarjeta_kpi("📱", "Cantidad de registros", f"{total_registros:,}", "#2563eb", "Unidades")
                    with c2:
                        tarjeta_kpi("🧩", "Referencias únicas (modelos)", f"{total_referencias:,}", "#8b5cf6", "Modelos")

                    m1, m2 = st.columns([3, 2])
                    with m1:
                        resumen_modelos = df_marca['telefono'].value_counts().reset_index()
                        resumen_modelos.columns = ['Teléfono', 'Cantidad']
                        st.dataframe(resumen_modelos, use_container_width=True, hide_index=True)
                    with m2:
                        st.subheader(f"Top modelos de {marca_seleccionada}")
                        st.bar_chart(df_marca['telefono'].value_counts().head(10), color="#10b981")
                else:
                    st.info("No hay marcas clasificadas en los datos actuales.")
            else:
                st.warning("La columna 'marca' no está disponible.")

        # ---------- DESCARGA ----------
        st.markdown("---")
        st.markdown(
            """
            <div class="panel">
                <h3>📥 Exportar resultado</h3>
            </div>
            """,
            unsafe_allow_html=True,
        )
        csv_descarga = df_filtrado.to_csv(index=False, sep='|').encode('utf-8')
        st.download_button(
            label="📲 Descargar este filtro a mi celular (CSV '|')",
            data=csv_descarga,
            file_name="Equipos_Sin_Ventas_Filtrado.csv",
            mime="text/csv",
            use_container_width=False,
        )

        # ---------- FOOTER ----------
        generado = time.strftime("%d/%m/%Y · %H:%M")
        st.markdown(
            f"""
            <div class="footer">
                Dashboard LEFCOM · Datos generados el {generado} · La información se recarga cada 6 horas
            </div>
            """,
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.error(f"Ocurrió un error con el archivo o la automatización: {e}")
