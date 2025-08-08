# =========================
# app.py
# =========================

import streamlit as st
import time
import base64
import requests
import math
import pymongo
from datetime import datetime, timedelta
from pytz import timezone
from openai import OpenAI

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="📚 Tracker de Lectura con Movimiento", layout="wide")

# Leer keys desde secrets (todo en minúsculas)
GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]
OPENAI_API_KEY = st.secrets["openai_api_key"]
MONGODB_URI = st.secrets["mongodb_uri"]

# Conexión MongoDB
mongo_client = pymongo.MongoClient(MONGODB_URI)
db = mongo_client["tracker_lectura"]
col_libros = db["libros"]
col_sesiones = db["sesiones"]

# Cliente OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Estado inicial
if "coords" not in st.session_state:
    st.session_state.coords = []
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "reading" not in st.session_state:
    st.session_state.reading = False
if "titulo" not in st.session_state:
    st.session_state.titulo = None
if "autor" not in st.session_state:
    st.session_state.autor = None
if "total_paginas" not in st.session_state:
    st.session_state.total_paginas = None
if "pagina_inicio" not in st.session_state:
    st.session_state.pagina_inicio = None

# --- Funciones ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def draw_map(coords):
    if not coords:
        return ""
    markers = "&".join([f"markers=color:red%7C{lat},{lon}" for lat, lon in coords])
    path = "&path=color:blue|weight:3|" + "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://maps.googleapis.com/maps/api/staticmap?size=800x400&{markers}{path}&key={GOOGLE_MAPS_API_KEY}"
    return url

# --- JS para GPS en vivo ---
st.markdown("""
<script>
function updateLocation(){
    if (navigator.geolocation){
        navigator.geolocation.watchPosition(
            function(position){
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                const url = new URL(window.location.href);
                url.searchParams.set('lat', lat);
                url.searchParams.set('lon', lon);
                window.history.replaceState({}, '', url);
            },
            function(error){
                console.log("GPS error:", error);
            }
        );
    }
}
updateLocation();
</script>
""", unsafe_allow_html=True)

# --- Lectura de query params ---
params = st.query_params
lat = params.get("lat")
lon = params.get("lon")

if lat and lon:
    try:
        lat, lon = float(lat), float(lon)
        if not st.session_state.coords or (lat, lon) != st.session_state.coords[-1]:
            st.session_state.coords.append((lat, lon))
    except:
        pass

# Debug en pantalla
if not st.session_state.coords:
    st.warning("📍 Esperando ubicación GPS...")
else:
    st.success(f"Última ubicación: {st.session_state.coords[-1]}")

# Mostrar mapa
map_url = draw_map(st.session_state.coords)
if map_url:
    st.image(map_url, caption="Ruta en vivo", use_column_width=True)

# --- Identificación del libro ---
st.header("📖 Identificación del libro")
foto = st.file_uploader("Sube foto de portada o página", type=["jpg", "jpeg", "png"])
if foto and not st.session_state.titulo:
    try:
        img_bytes = foto.getvalue()
        base64_img = base64.b64encode(img_bytes).decode()
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Extrae el título y autor del libro en esta imagen."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}}
                ]
            }],
            max_tokens=50
        )
        texto_extraido = resp.choices[0].message.content.strip()
        if " - " in texto_extraido:
            partes = texto_extraido.split(" - ", 1)
            st.session_state.titulo, st.session_state.autor = partes[0], partes[1]
        else:
            st.session_state.titulo, st.session_state.autor = texto_extraido, "Autor desconocido"

        libro = col_libros.find_one({"titulo": st.session_state.titulo})
        if libro:
            st.session_state.total_paginas = libro["total_paginas"]
            st.info(f"Libro ya registrado con {st.session_state.total_paginas} páginas.")
        else:
            total_paginas = st.number_input("Total de páginas del libro", min_value=1)
            if total_paginas:
                st.session_state.total_paginas = total_paginas
                col_libros.insert_one({
                    "titulo": st.session_state.titulo,
                    "autor": st.session_state.autor,
                    "total_paginas": total_paginas
                })
                st.success("Libro guardado en la base de datos.")
    except Exception as e:
        st.error(f"Error identificando libro: {e}")

# --- Datos iniciales ---
if st.session_state.titulo:
    st.subheader(f"📚 {st.session_state.titulo} - {st.session_state.autor}")
    if st.session_state.pagina_inicio is None:
        st.session_state.pagina_inicio = st.number_input("Página de inicio", min_value=1)

# --- Cronómetro ---
if st.session_state.pagina_inicio:
    if not st.session_state.reading:
        if st.button("▶️ Iniciar lectura"):
            st.session_state.start_time = time.time()
            st.session_state.reading = True
    else:
        elapsed = int(time.time() - st.session_state.start_time)
        st.metric("⏱ Tiempo", f"{elapsed // 60:02d}:{elapsed % 60:02d}")
        if st.button("⏹ Detener lectura"):
            st.session_state.reading = False
            pagina_fin = st.number_input("Página final", min_value=st.session_state.pagina_inicio)
            if pagina_fin:
                paginas_leidas = pagina_fin - st.session_state.pagina_inicio
                duracion_min = elapsed / 60
                ppm = paginas_leidas / duracion_min if duracion_min > 0 else 0
                resumen = st.text_area("¿Qué se te quedó de la lectura?")
                
                # Predicción fin en hora Colombia
                bogota = timezone("America/Bogota")
                ahora = datetime.now(bogota)
                pags_restantes = st.session_state.total_paginas - pagina_fin
                mins_restantes = pags_restantes / ppm if ppm > 0 else 0
                fin_estimado = ahora + timedelta(minutes=mins_restantes)
                
                st.info(f"📅 Terminarías el {fin_estimado.strftime('%Y-%m-%d %H:%M')} (hora Colombia)")
                
                col_sesiones.insert_one({
                    "titulo": st.session_state.titulo,
                    "autor": st.session_state.autor,
                    "inicio": st.session_state.coords[0] if st.session_state.coords else None,
                    "fin": st.session_state.coords[-1] if st.session_state.coords else None,
                    "ruta": st.session_state.coords,
                    "duracion_min": duracion_min,
                    "paginas_leidas": paginas_leidas,
                    "resumen": resumen,
                    "ppm": ppm,
                    "fin_estimado": fin_estimado.isoformat()
                })
                st.success("✅ Sesión guardada en la base de datos.")

# =========================
# requirements.txt
# =========================
"""
streamlit
pymongo
openai
pytz
requests
"""