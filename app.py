import streamlit as st
import pymongo
import time
import pytz
from datetime import datetime
from openai import OpenAI
from math import radians, sin, cos, sqrt, atan2
from streamlit_autorefresh import st_autorefresh
import requests
from io import BytesIO

# ------------------ CONFIG ------------------
google_maps_api_key = st.secrets["google_maps_api_key"]
mongo_uri = st.secrets["mongo_uri"]
openai_api_key = st.secrets["openai_api_key"]

client_ai = OpenAI(api_key=openai_api_key)
mongo_client = pymongo.MongoClient(mongo_uri)
db = mongo_client["reading_tracker"]

tz_colombia = pytz.timezone("America/Bogota")

st.set_page_config(page_title="Tracker de Lectura con Movimiento", layout="wide")

# ------------------ FUNCIONES ------------------
def haversine(coord1, coord2):
    R = 6371000
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1) * cos(phi2) * sin(dlambda/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def get_static_map(coords):
    path = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&path=color:0xff0000ff|weight:3|{path}&key={google_maps_api_key}"
    return url

def extract_book_info(image_bytes):
    resp = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Extrae el título y el autor del libro de esta imagen, devuelve solo en formato: Título - Autor."},
            {"role": "user", "content": [{"type": "input_image", "image_data": image_bytes}]}
        ]
    )
    return resp.choices[0].message["content"]

def predict_finish(pag_total, pag_leidas, duracion_s):
    if duracion_s == 0 or pag_leidas == 0:
        return None
    vel_ppm = pag_leidas / (duracion_s / 60)
    faltan = pag_total - pag_leidas
    mins_rest = faltan / vel_ppm
    fin_estimado = datetime.now(tz_colombia) + timedelta(minutes=mins_rest)
    return fin_estimado, vel_ppm

# ------------------ ESTADOS ------------------
if "coords" not in st.session_state:
    st.session_state.coords = []
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "modo_lectura" not in st.session_state:
    st.session_state.modo_lectura = "reposo"
if "libro" not in st.session_state:
    st.session_state.libro = None
if "pag_total" not in st.session_state:
    st.session_state.pag_total = None
if "pag_inicio" not in st.session_state:
    st.session_state.pag_inicio = None

# ------------------ JS GEOLOC ------------------
st.markdown("""
<script>
navigator.geolocation.watchPosition(
    (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const newUrl = window.location.protocol + "//" + window.location.host + window.location.pathname + `?lat=${lat}&lon=${lon}`;
        window.history.replaceState({ path: newUrl }, '', newUrl);
    },
    (err) => { console.error(err); },
    { enableHighAccuracy: true }
);
</script>
""", unsafe_allow_html=True)

# ------------------ AUTOREFRESH ------------------
st_autorefresh(interval=5000, key="map_refresh")

# ------------------ LEER COORDENADAS ------------------
params = st.query_params
if "lat" in params and "lon" in params:
    lat, lon = float(params["lat"]), float(params["lon"])
    new_coord = (lat, lon)
    if not st.session_state.coords or st.session_state.coords[-1] != new_coord:
        st.session_state.coords.append(new_coord)

# ------------------ DETECCIÓN MOVIMIENTO ------------------
umbral = st.number_input("Umbral de movimiento (m)", value=20)
if len(st.session_state.coords) > 1:
    dist_total = sum(haversine(st.session_state.coords[i], st.session_state.coords[i+1])
                     for i in range(len(st.session_state.coords)-1))
    st.session_state.modo_lectura = "movimiento" if dist_total > umbral else "reposo"

# ------------------ UI MAPA ------------------
if st.session_state.coords:
    st.image(get_static_map(st.session_state.coords), caption=f"Modo: {st.session_state.modo_lectura}")
else:
    st.info("Esperando ubicación...")

# ------------------ IDENTIFICACIÓN LIBRO ------------------
st.subheader("Identificación del libro")
img_file = st.file_uploader("Sube foto de portada/página", type=["jpg", "jpeg", "png"])
if img_file and not st.session_state.libro:
    image_bytes = img_file.read()
    st.session_state.libro = extract_book_info(image_bytes)
    st.success(f"Libro detectado: {st.session_state.libro}")

    # Buscar si existe en Mongo
    libro_doc = db.libros.find_one({"nombre": st.session_state.libro})
    if libro_doc:
        st.session_state.pag_total = libro_doc["pag_total"]
        st.info(f"Total de páginas: {st.session_state.pag_total}")
    else:
        st.session_state.pag_total = st.number_input("Número total de páginas", min_value=1, step=1)
        if st.button("Guardar libro"):
            db.libros.insert_one({"nombre": st.session_state.libro, "pag_total": st.session_state.pag_total})
            st.success("Libro guardado en MongoDB")

# ------------------ DATOS INICIALES SESIÓN ------------------
if st.session_state.pag_total:
    st.session_state.pag_inicio = st.number_input("Página de inicio", min_value=1, max_value=st.session_state.pag_total)

# ------------------ CRONÓMETRO ------------------
col1, col2 = st.columns(2)

with col1:
    if st.button("Iniciar lectura"):
        st.session_state.start_time = time.time()

    if st.session_state.start_time:
        elapsed_placeholder = st.empty()
        elapsed = int(time.time() - st.session_state.start_time)
        mins, secs = divmod(elapsed, 60)
        elapsed_placeholder.metric("Tiempo de lectura", f"{mins:02d}:{secs:02d}")

with col2:
    if st.button("Detener lectura"):
        if st.session_state.start_time:
            duracion = int(time.time() - st.session_state.start_time)
            pagina_final = st.number_input("Página final", min_value=1, max_value=st.session_state.pag_total)
            pag_leidas = pagina_final - st.session_state.pag_inicio
            reflexion = st.text_area("¿Qué se te quedó de la lectura?")

            prediccion = predict_finish(st.session_state.pag_total, pagina_final, duracion)

            doc = {
                "fecha": datetime.now(tz_colombia),
                "coords": st.session_state.coords,
                "modo": st.session_state.modo_lectura,
                "duracion": duracion,
                "libro": st.session_state.libro,
                "pag_inicio": st.session_state.pag_inicio,
                "pag_final": pagina_final,
                "pag_leidas": pag_leidas,
                "reflexion": reflexion,
                "prediccion_fin": prediccion[0].isoformat() if prediccion else None,
                "vel_ppm": prediccion[1] if prediccion else None
            }
            db.sesiones.insert_one(doc)
            st.success("Sesión guardada en MongoDB")

            # Reset estados
            st.session_state.start_time = None
            st.session_state.coords = []
            st.session_state.pag_inicio = None