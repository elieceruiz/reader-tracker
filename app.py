# app.py
import streamlit as st
import time
import pytz
from datetime import datetime, timedelta
import math
import base64
import json
from pymongo import MongoClient
from openai import OpenAI

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="📚 Tracker de Lectura con Movimiento", layout="wide")

# Leer keys desde secrets
GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]
OPENAI_API_KEY = st.secrets["openai_api_key"]
OPENAI_ORG_ID = st.secrets["openai_org_id"]
MONGODB_URI = st.secrets["mongo_uri"]

# Inicializar clientes
client = OpenAI(api_key=OPENAI_API_KEY, organization=OPENAI_ORG_ID)
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client["tracker"]
books_collection = db["books"]
sessions_collection = db["sessions"]

# --- FUNCIONES AUXILIARES ---
def haversine(coord1, coord2):
    R = 6371000
    lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
    lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def identify_book_from_image(image_bytes):
    response = client.responses.create(
        model="gpt-4o-mini",
        input=[
            {"role": "user", "content": [
                {"type": "input_text", "text": "Identifica título y autor del libro en esta imagen"},
                {"type": "input_image", "image": image_bytes}
            ]}
        ]
    )
    text = response.output_text
    parts = text.split("\n")
    titulo = parts[0] if parts else ""
    autor = parts[1] if len(parts) > 1 else ""
    return titulo.strip(), autor.strip()

def col_timezone_now():
    tz = pytz.timezone("America/Bogota")
    return datetime.now(tz)

# --- SESIONES ---
if "coords" not in st.session_state:
    st.session_state.coords = []
if "distance" not in st.session_state:
    st.session_state.distance = 0
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "pages_start" not in st.session_state:
    st.session_state.pages_start = None
if "pages_end" not in st.session_state:
    st.session_state.pages_end = None
if "book_info" not in st.session_state:
    st.session_state.book_info = {}
if "summary" not in st.session_state:
    st.session_state.summary = ""

tab1, tab2 = st.tabs(["📍 Tracker", "📜 Historial"])

with tab1:
    st.title("📚 Tracker de Lectura con Movimiento")

    # --- MAPA EN VIVO ---
    st.markdown("""
    <div id="map" style="height:400px;width:100%;"></div>
    <div id="debug" style="color:red;font-weight:bold;"></div>
    <script>
    let coords = [];
    let map, marker, polyline;
    function initMap(lat, lon) {
        map = new google.maps.Map(document.getElementById('map'), {
            center: { lat: lat, lng: lon },
            zoom: 16
        });
        marker = new google.maps.Marker({ position: { lat: lat, lng: lon }, map: map });
        polyline = new google.maps.Polyline({ path: [{lat: lat, lng: lon}], map: map, strokeColor: "#FF0000" });
    }
    function updateMap(lat, lon) {
        marker.setPosition({ lat: lat, lng: lon });
        const path = polyline.getPath();
        path.push(new google.maps.LatLng(lat, lon));
        map.panTo({ lat: lat, lng: lon });
    }
    if (navigator.geolocation) {
        navigator.geolocation.watchPosition(
            function(position) {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                document.getElementById("debug").innerHTML = "Lat: " + lat + " | Lon: " + lon;
                coords.push({lat: lat, lon: lon, ts: Date.now()});
                window.parent.postMessage({type: 'coords_update', data: coords}, "*");
                if (!map) { initMap(lat, lon); } else { updateMap(lat, lon); }
            },
            function(error) {
                document.getElementById("debug").innerHTML = "Error obteniendo ubicación: " + error.message;
            },
            { enableHighAccuracy: true, maximumAge: 0, timeout: 5000 }
        );
    } else {
        document.getElementById("debug").innerHTML = "Geolocalización no soportada.";
    }
    </script>
    <script src="https://maps.googleapis.com/maps/api/js?key=""" + GOOGLE_MAPS_API_KEY + """"></script>
    """, unsafe_allow_html=True)

    coords_data = st.query_params.get("coords")
    if coords_data:
        try:
            coords_list = json.loads(coords_data)
            if coords_list:
                if not st.session_state.coords:
                    st.session_state.coords.append((coords_list[0]['lat'], coords_list[0]['lon']))
                else:
                    last_coord = st.session_state.coords[-1]
                    new_coord = (coords_list[-1]['lat'], coords_list[-1]['lon'])
                    st.session_state.distance += haversine(last_coord, new_coord)
                    st.session_state.coords.append(new_coord)
        except:
            pass

    # --- FLUJO ---
    st.subheader("1. Identificación del libro")
    image = st.file_uploader("Sube una foto de la portada", type=["jpg", "jpeg", "png"])
    if image:
        titulo, autor = identify_book_from_image(image.read())
        st.session_state.book_info = {"titulo": titulo, "autor": autor}
        st.write(f"**Título:** {titulo}")
        st.write(f"**Autor:** {autor}")
        existing = books_collection.find_one({"titulo": titulo, "autor": autor})
        if not existing:
            total_pages = st.number_input("Número total de páginas", min_value=1)
            if total_pages:
                books_collection.insert_one({"titulo": titulo, "autor": autor, "total_pages": total_pages})
                st.success("Libro registrado en base de datos.")
        else:
            st.success("Libro ya registrado.")

    st.subheader("2. Datos iniciales de la sesión")
    pages_start = st.number_input("Página de inicio", min_value=1)
    if pages_start:
        st.session_state.pages_start = pages_start

    if st.button("📖 Iniciar lectura"):
        st.session_state.start_time = time.time()

    if st.session_state.start_time:
        elapsed = int(time.time() - st.session_state.start_time)
        st.metric("Tiempo de lectura", f"{elapsed} s")

    if st.button("⏹ Finalizar lectura") and st.session_state.start_time:
        st.session_state.pages_end = st.number_input("Página final", min_value=st.session_state.pages_start or 1)
        if st.session_state.pages_end:
            pages_read = st.session_state.pages_end - st.session_state.pages_start
            duration_min = (time.time() - st.session_state.start_time) / 60
            ppm = pages_read / duration_min if duration_min > 0 else 0
            tz_now = col_timezone_now()
            total_pages = books_collection.find_one(st.session_state.book_info).get("total_pages", 0)
            remaining_pages = total_pages - st.session_state.pages_end
            est_finish = tz_now + timedelta(minutes=remaining_pages / ppm) if ppm > 0 else None
            mode = "movimiento" if st.session_state.distance > 20 else "reposo"
            summary = st.text_area("¿Qué se te quedó de la lectura?")
            st.session_state.summary = summary
            # Guardar en Mongo
            sessions_collection.insert_one({
                "titulo": st.session_state.book_info.get("titulo"),
                "autor": st.session_state.book_info.get("autor"),
                "coords": st.session_state.coords,
                "distancia_m": st.session_state.distance,
                "duracion_s": int(time.time() - st.session_state.start_time),
                "paginas_leidas": pages_read,
                "modo": mode,
                "reflexion": summary,
                "prediccion_fin": est_finish.isoformat() if est_finish else None
            })
            st.success(f"Sesión guardada. Predicción fin: {est_finish.strftime('%Y-%m-%d %H:%M')} (hora Colombia)")

with tab2:
    st.title("📜 Historial de sesiones")
    libros = books_collection.find()
    libros_list = [f"{l['titulo']} - {l['autor']}" for l in libros]
    libro_sel = st.selectbox("Selecciona un libro", libros_list)
    if libro_sel:
        titulo_sel, autor_sel = libro_sel.split(" - ")
        sesiones = list(sessions_collection.find({"titulo": titulo_sel, "autor": autor_sel}))
        sesiones = sorted(sesiones, key=lambda x: x.get("prediccion_fin", ""), reverse=True)
        ses_sel = st.selectbox("Selecciona una sesión", [s["_id"] for s in sesiones])
        ses_data = next((s for s in sesiones if s["_id"] == ses_sel), None)
        if ses_data:
            st.write(f"**Duración:** {ses_data['duracion_s']} s")
            st.write(f"**Distancia:** {ses_data['distancia_m']:.1f} m")
            st.write(f"**Modo:** {ses_data['modo']}")
            st.write(f"**Reflexión:** {ses_data['reflexion']}")
            coords_js = json.dumps(ses_data.get("coords", []))
            st.markdown(f"""
            <div id="map_hist" style="height:400px;width:100%;"></div>
            <script>
            let coords_hist = {coords_js};
            function initMapHist() {{
                if (coords_hist.length === 0) return;
                let map = new google.maps.Map(document.getElementById('map_hist'), {{
                    center: {{ lat: coords_hist[0][0], lng: coords_hist[0][1] }},
                    zoom: 15
                }});
                let path = coords_hist.map(c => {{ return {{ lat: c[0], lng: c[1] }}; }});
                new google.maps.Polyline({{ path: path, map: map, strokeColor: "#0000FF" }});
            }}
            initMapHist();
            </script>
            <script src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}"></script>
            """, unsafe_allow_html=True)