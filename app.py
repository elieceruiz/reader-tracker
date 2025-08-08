import streamlit as st
import pymongo
import time
import math
import json
from datetime import datetime
from streamlit.components.v1 import html

# =============== CONFIGURACIÓN ===============
st.set_page_config(page_title="Reader Tracker", layout="wide")

# Cargar secretos
MONGO_URI = st.secrets["MONGO_URI"]
GOOGLE_MAPS_API_KEY = st.secrets["GOOGLE_MAPS_API_KEY"]

# Conexión MongoDB
client = pymongo.MongoClient(MONGO_URI)
db = client["reader_tracker"]
lecturas_col = db["lecturas"]

# =============== FUNCIONES AUXILIARES ===============
def haversine(lat1, lon1, lat2, lon2):
    """Calcula la distancia en metros entre dos coordenadas."""
    R = 6371 * 1000  # Radio de la tierra en metros
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1-a))

# Guardar coordenadas del navegador
def get_location():
    code = """
    <script>
    navigator.geolocation.getCurrentPosition(
        function(position) {
            const coords = {
                lat: position.coords.latitude,
                lon: position.coords.longitude
            };
            window.parent.postMessage(JSON.stringify(coords), "*");
        },
        function(error) {
            console.error(error);
        }
    );
    </script>
    """
    html(code)

# =============== INTERFAZ ===============
st.title("📖 Reader Tracker – Registro de Lectura")

# Estado en sesión
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "start_coords" not in st.session_state:
    st.session_state.start_coords = None

# Obtener ubicación inicial
if st.button("📍 Obtener ubicación inicial"):
    get_location()
    st.info("Ubicación inicial solicitada, acepta en tu navegador.")

# Subir portada opcional
portada = st.file_uploader("Sube la portada o página interior del libro (opcional)", type=["jpg", "png"])

titulo = st.text_input("Título del libro")
autor = st.text_input("Autor")

# Iniciar cronómetro
if st.button("▶ Iniciar lectura"):
    st.session_state.start_time = time.time()
    st.session_state.start_coords = None
    st.success("Lectura iniciada. Cuando termines, presiona 'Detener'.")
    get_location()

# Detener cronómetro
if st.button("⏹ Detener lectura"):
    if st.session_state.start_time:
        end_time = time.time()
        duracion = end_time - st.session_state.start_time

        # Obtener ubicación final
        get_location()

        # Dummy coords si no se capturan en tiempo real
        lat_inicio, lon_inicio = (4.6097, -74.0817)  # Bogotá
        lat_fin, lon_fin = (4.6097, -74.0817)

        distancia = haversine(lat_inicio, lon_inicio, lat_fin, lon_fin)
        en_movimiento = distancia > 10

        doc = {
            "titulo": titulo,
            "autor": autor,
            "duracion_seg": duracion,
            "fecha_inicio": datetime.fromtimestamp(st.session_state.start_time),
            "fecha_fin": datetime.now(),
            "lat_inicio": lat_inicio,
            "lon_inicio": lon_inicio,
            "lat_fin": lat_fin,
            "lon_fin": lon_fin,
            "distancia_m": distancia,
            "modo": "En movimiento" if en_movimiento else "En reposo"
        }
        lecturas_col.insert_one(doc)

        st.success(f"Lectura registrada: {round(duracion/60, 1)} min – {doc['modo']} ({round(distancia,1)} m)")
        st.session_state.start_time = None
    else:
        st.warning("No hay lectura activa.")

# Mostrar historial
st.subheader("📜 Historial de lecturas")
historial = list(lecturas_col.find().sort("fecha_inicio", -1))

if historial:
    for h in historial:
        st.write(f"**{h['titulo']}** – {h['autor']} – {round(h['duracion_seg']/60,1)} min – {h['modo']} ({round(h['distancia_m'],1)} m)")
else:
    st.info("No hay registros aún.")