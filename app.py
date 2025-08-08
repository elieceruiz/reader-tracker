import streamlit as st
import time
import pymongo
import pytz
from openai import OpenAI
from datetime import datetime, timedelta
from math import radians, sin, cos, sqrt, atan2

# --- CONFIG DESDE SECRETS ---
google_maps_api_key = st.secrets["google_maps_api_key"]
mongo_uri = st.secrets["mongo_uri"]
openai_api_key = st.secrets["openai_api_key"]

# --- CLIENTES ---
client_ai = OpenAI(api_key=openai_api_key)
mongo_client = pymongo.MongoClient(mongo_uri)
db = mongo_client["reading_tracker"]

# --- ZONA HORARIA COLOMBIA ---
tz_colombia = pytz.timezone("America/Bogota")

# --- FUNCIONES ---
def haversine(coord1, coord2):
    R = 6371.0
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    dlon = radians(lon2 - lon1)
    dlat = radians(lat2 - lat1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c * 1000  # metros

def draw_map(coords):
    markers = "|".join([f"{lat},{lon}" for lat, lon in coords])
    path = "|".join([f"{lat},{lon}" for lat, lon in coords])
    url = f"https://maps.googleapis.com/maps/api/staticmap?size=600x400&markers=color:red|{markers}&path=color:blue|{path}&key={google_maps_api_key}"
    st.image(url)

def get_book_info_from_image(image_file):
    resp = client_ai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Extrae título y autor del libro que aparece en la imagen."},
            {"role": "user", "content": [{"type": "image", "image_data": image_file.getvalue()}]}
        ]
    )
    return resp.choices[0].message.content.strip()

def save_session(data):
    db.sessions.insert_one(data)

def get_total_pages_if_exists(title):
    book = db.books.find_one({"title": title})
    return book["total_pages"] if book else None

def save_book(title, author, total_pages):
    db.books.update_one({"title": title}, {"$set": {"author": author, "total_pages": total_pages}}, upsert=True)

# --- ESTADO ---
if "coords" not in st.session_state:
    st.session_state.coords = []
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "modo_lectura" not in st.session_state:
    st.session_state.modo_lectura = "reposo"

# --- UI ---
st.title("📖 Tracker de Lectura con Movimiento")
umbral = st.number_input("Umbral movimiento (m)", value=20)

# JS para capturar ubicación en vivo
st.markdown("""
<script>
navigator.geolocation.watchPosition(
    (pos) => {
        const lat = pos.coords.latitude;
        const lon = pos.coords.longitude;
        const queryParams = new URLSearchParams(window.location.search);
        queryParams.set("lat", lat);
        queryParams.set("lon", lon);
        window.location.search = queryParams.toString();
    },
    (err) => {console.error(err);},
    {enableHighAccuracy: true, maximumAge: 0, timeout: 5000}
);
</script>
""", unsafe_allow_html=True)

# Guardar coordenadas
location_data = st.experimental_get_query_params()
if "lat" in location_data and "lon" in location_data:
    new_coord = (float(location_data["lat"][0]), float(location_data["lon"][0]))
    if not st.session_state.coords or st.session_state.coords[-1] != new_coord:
        st.session_state.coords.append(new_coord)
        if len(st.session_state.coords) > 1:
            dist = sum(haversine(st.session_state.coords[i], st.session_state.coords[i+1]) for i in range(len(st.session_state.coords)-1))
            st.session_state.modo_lectura = "movimiento" if dist > umbral else "reposo"

if st.session_state.coords:
    draw_map(st.session_state.coords)

# Foto del libro
image_file = st.file_uploader("Sube foto de la portada")
if image_file:
    info = get_book_info_from_image(image_file)
    st.write(f"📚 Detectado: {info}")
    title, author = info.split("\n") if "\n" in info else (info, "")
    total_pages = get_total_pages_if_exists(title)
    if not total_pages:
        total_pages = st.number_input("Número total de páginas", min_value=1)
        if st.button("Guardar libro"):
            save_book(title, author, total_pages)
            st.success("Libro guardado")

    start_page = st.number_input("Página de inicio", min_value=1, max_value=total_pages)
    if st.button("Iniciar lectura"):
        st.session_state.start_time = datetime.now(tz_colombia)  # hora de Colombia
        st.session_state.start_page = start_page
        st.success(f"📍 Cronómetro iniciado a las {st.session_state.start_time.strftime('%H:%M:%S')} (hora Colombia)")

# Finalizar lectura
if st.session_state.start_time:
    if st.button("Detener lectura"):
        end_time = datetime.now(tz_colombia)  # hora de Colombia
        duration = (end_time - st.session_state.start_time).total_seconds() / 60
        end_page = st.number_input("Página final", min_value=st.session_state.start_page, max_value=total_pages)
        pages_read = end_page - st.session_state.start_page
        resumen = st.text_area("¿Qué se te quedó de la lectura?")
        ritmo = pages_read / duration if duration > 0 else 0
        est_fin = None
        if ritmo > 0:
            remaining_pages = total_pages - end_page
            est_fin = datetime.now(tz_colombia) + timedelta(minutes=(remaining_pages / ritmo))
        session_data = {
            "title": title,
            "author": author,
            "start_time": st.session_state.start_time,
            "end_time": end_time,
            "start_page": st.session_state.start_page,
            "end_page": end_page,
            "pages_read": pages_read,
            "duration_min": duration,
            "coords": st.session_state.coords,
            "modo_lectura": st.session_state.modo_lectura,
            "resumen": resumen,
            "prediccion_fin": est_fin
        }
        save_session(session_data)
        st.success("✅ Sesión guardada")

# Historial
if st.checkbox("📜 Ver historial"):
    for s in db.sessions.find().sort("_id", -1):
        st.subheader(f"{s['title']} - {s['author']}")
        st.write(f"Páginas leídas: {s['pages_read']}, Duración: {round(s['duration_min'],1)} min, Modo: {s['modo_lectura']}")
        if s.get("prediccion_fin"):
            st.write(f"Estimación fin: {s['prediccion_fin'].strftime('%Y-%m-%d %H:%M:%S')} (hora Colombia)")
        if s.get("coords"):
            draw_map(s["coords"])
        if s.get("resumen"):
            st.write(f"💭 {s['resumen']}")