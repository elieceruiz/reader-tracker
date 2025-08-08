import streamlit as st
import time
import requests
import pymongo
from datetime import datetime
import pytz
from openai import OpenAI
from math import radians, sin, cos, sqrt, atan2

# ==============================
# CONFIGURACIONES DESDE SECRETS
# ==============================
google_maps_api_key = st.secrets["google_maps_api_key"]
mongo_uri = st.secrets["mongo_uri"]
openai_api_key = st.secrets["openai_api_key"]

# ==============================
# CLIENTES
# ==============================
client_ai = OpenAI(api_key=openai_api_key)
mongo_client = pymongo.MongoClient(mongo_uri)
db = mongo_client["reading_tracker"]

# ==============================
# FUNCIONES AUXILIARES
# ==============================
def haversine(coord1, coord2):
    # Calcula distancia en metros
    R = 6371000
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))

def get_static_map(coords):
    markers = "|".join([f"{lat},{lon}" for lat, lon in coords])
    path = "|".join([f"{lat},{lon}" for lat, lon in coords])
    return f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&markers=color:red|{markers}&path=color:blue|{path}&key={google_maps_api_key}"

def identify_book(image_file):
    # Usa GPT-4o para extraer título y autor
    img_bytes = image_file.getvalue()
    response = client_ai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": "Extrae título y autor del libro de esta imagen. Responde en formato JSON con keys 'titulo' y 'autor'."},
                {"type": "image", "image_data": img_bytes}
            ]}
        ]
    )
    import json
    try:
        data = json.loads(response.choices[0].message.content)
        return data.get("titulo"), data.get("autor")
    except:
        return None, None

# ==============================
# ESTADO INICIAL
# ==============================
if "coords" not in st.session_state:
    st.session_state.coords = []
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "modo_lectura" not in st.session_state:
    st.session_state.modo_lectura = "reposo"

# ==============================
# CONFIG USUARIO
# ==============================
st.title("📚 Tracker de Lectura con Movimiento")
umbral = st.number_input("Umbral de movimiento (m)", value=20)

# ==============================
# SCRIPT JS PARA GEOLOCALIZACIÓN
# ==============================
st.markdown("""
<script>
navigator.geolocation.watchPosition(
    (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const params = new URLSearchParams(window.location.search);
        params.set("lat", lat);
        params.set("lon", lon);
        window.history.replaceState({}, "", `${window.location.pathname}?${params}`);
    },
    (err) => { console.error(err); },
    { enableHighAccuracy: true }
);
</script>
""", unsafe_allow_html=True)

# ==============================
# LECTURA DE POSICIÓN Y MODO
# ==============================
location_data = st.query_params
if "lat" in location_data and "lon" in location_data:
    new_coord = (float(location_data["lat"]), float(location_data["lon"]))
    if not st.session_state.coords or st.session_state.coords[-1] != new_coord:
        st.session_state.coords.append(new_coord)
        if len(st.session_state.coords) > 1:
            dist = sum(
                haversine(st.session_state.coords[i], st.session_state.coords[i+1])
                for i in range(len(st.session_state.coords)-1)
            )
            st.session_state.modo_lectura = "movimiento" if dist > umbral else "reposo"

# Mostrar mapa
if st.session_state.coords:
    st.image(get_static_map(st.session_state.coords), caption="Ruta en vivo")

# ==============================
# CRONÓMETRO
# ==============================
if st.button("Iniciar lectura"):
    st.session_state.start_time = time.time()

if st.session_state.start_time:
    timer_placeholder = st.empty()
    elapsed = 0
    # Mostrar cronómetro en vivo
    elapsed = int(time.time() - st.session_state.start_time)
    mins, secs = divmod(elapsed, 60)
    timer_placeholder.metric("Tiempo de lectura", f"{mins:02d}:{secs:02d}")

# ==============================
# IDENTIFICAR LIBRO
# ==============================
uploaded_image = st.file_uploader("📷 Foto de portada o página", type=["jpg", "jpeg", "png"])
if uploaded_image:
    titulo, autor = identify_book(uploaded_image)
    if titulo and autor:
        st.success(f"📖 {titulo} — {autor}")
        libro = db.libros.find_one({"titulo": titulo, "autor": autor})
        if not libro:
            total_pags = st.number_input("Número total de páginas", min_value=1)
            if st.button("Guardar libro"):
                db.libros.insert_one({"titulo": titulo, "autor": autor, "total_pags": total_pags})
                st.success("Libro guardado.")
    else:
        st.error("No se pudo identificar el libro.")

# ==============================
# FINALIZAR SESIÓN
# ==============================
if st.button("Finalizar sesión"):
    pagina_inicio = st.number_input("Página inicial", min_value=1)
    pagina_final = st.number_input("Página final", min_value=pagina_inicio)
    resumen = st.text_area("¿Qué se te quedó de la lectura?")

    elapsed = int(time.time() - st.session_state.start_time)
    pags_leidas = pagina_final - pagina_inicio
    ritmo_ppm = pags_leidas / (elapsed / 60)
    libro_data = db.libros.find_one({"titulo": titulo, "autor": autor})
    prediccion = None
    if libro_data and "total_pags" in libro_data:
        pags_restantes = libro_data["total_pags"] - pagina_final
        mins_restantes = pags_restantes / ritmo_ppm
        prediccion = datetime.now(pytz.timezone("America/Bogota")) + timedelta(minutes=mins_restantes)

    sesion = {
        "titulo": titulo,
        "autor": autor,
        "inicio": datetime.now(pytz.timezone("America/Bogota")),
        "duracion_seg": elapsed,
        "coords": st.session_state.coords,
        "modo": st.session_state.modo_lectura,
        "pags_leidas": pags_leidas,
        "resumen": resumen,
        "prediccion_fin": prediccion
    }
    db.sesiones.insert_one(sesion)
    st.success("Sesión guardada.")

# ==============================
# HISTORIAL
# ==============================
st.header("Historial")
for ses in db.sesiones.find().sort("inicio", -1):
    st.subheader(f"{ses['titulo']} — {ses['autor']}")
    st.write(f"Modo: {ses['modo']}")
    st.write(f"Duración: {ses['duracion_seg']//60} min {ses['duracion_seg']%60} seg")
    st.image(get_static_map(ses["coords"]))
    st.write(f"Resumen: {ses['resumen']}")
    if ses.get("prediccion_fin"):
        st.write(f"📅 Estimación de fin: {ses['prediccion_fin']}")