import streamlit as st
import pymongo
from datetime import datetime
import time
import geopy.distance
import requests

# ====== LEER SECRETS EN MINÚSCULAS ======
MONGO_URI = st.secrets["mongo_uri"]
GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]

# ====== CONEXIÓN A MONGODB ======
client = pymongo.MongoClient(MONGO_URI)
db = client["reader_tracker"]
collection = db["lecturas"]

# ====== FUNCIONES ======
def get_current_location():
    """Obtiene ubicación aproximada usando la API de IP (solo para ejemplo rápido)"""
    try:
        res = requests.get("https://ipapi.co/json/")
        data = res.json()
        return (data["latitude"], data["longitude"])
    except:
        return None

def guardar_registro(titulo, autor, inicio, fin, coords_inicio, coords_fin):
    duracion = (fin - inicio).total_seconds()
    distancia = None
    if coords_inicio and coords_fin:
        distancia = geopy.distance.distance(coords_inicio, coords_fin).meters
    doc = {
        "titulo": titulo,
        "autor": autor,
        "inicio": inicio,
        "fin": fin,
        "duracion_seg": duracion,
        "coords_inicio": coords_inicio,
        "coords_fin": coords_fin,
        "distancia_m": distancia
    }
    collection.insert_one(doc)

def mostrar_mapa(coords_inicio, coords_fin):
    if not coords_inicio or not coords_fin:
        st.warning("No hay coordenadas para mostrar el mapa.")
        return
    url = (
        f"https://www.google.com/maps/embed/v1/directions"
        f"?key={GOOGLE_MAPS_API_KEY}"
        f"&origin={coords_inicio[0]},{coords_inicio[1]}"
        f"&destination={coords_fin[0]},{coords_fin[1]}"
        f"&mode=walking"
    )
    st.markdown(f'<iframe width="100%" height="400" src="{url}"></iframe>', unsafe_allow_html=True)

# ====== INTERFAZ STREAMLIT ======
st.title("📖 Tracker de Lectura con Ubicación")

if "inicio" not in st.session_state:
    st.session_state.inicio = None
    st.session_state.coords_inicio = None

# FORMULARIO DE DATOS DEL LIBRO
titulo = st.text_input("Título del libro")
autor = st.text_input("Autor")

# BOTÓN PARA INICIAR LECTURA
if st.button("Iniciar lectura"):
    st.session_state.inicio = datetime.now()
    st.session_state.coords_inicio = get_current_location()
    st.success("Lectura iniciada.")
    st.write(f"Ubicación inicial: {st.session_state.coords_inicio}")

# CRONÓMETRO
if st.session_state.inicio:
    elapsed = int((datetime.now() - st.session_state.inicio).total_seconds())
    minutos, segundos = divmod(elapsed, 60)
    st.metric("Tiempo leyendo", f"{minutos:02d}:{segundos:02d}")

# BOTÓN PARA FINALIZAR LECTURA
if st.session_state.inicio and st.button("Finalizar lectura"):
    fin = datetime.now()
    coords_fin = get_current_location()
    guardar_registro(titulo, autor, st.session_state.inicio, fin, st.session_state.coords_inicio, coords_fin)
    st.success("Lectura registrada.")
    mostrar_mapa(st.session_state.coords_inicio, coords_fin)
    st.session_state.inicio = None
    st.session_state.coords_inicio = None

# HISTORIAL
st.subheader("📜 Historial de lecturas")
registros = list(collection.find().sort("inicio", -1))
for r in registros:
    dur_min, dur_seg = divmod(int(r["duracion_seg"]), 60)
    st.write(f"**{r['titulo']}** – {r['autor']} – {dur_min:02d}:{dur_seg:02d} min")
    if r.get("distancia_m") and r["distancia_m"] > 0:
        st.write(f"Distancia recorrida: {r['distancia_m']:.1f} m")