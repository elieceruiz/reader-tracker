import streamlit as st
import time
import pymongo
import openai
from datetime import datetime
import geopy.distance
import requests

# ===== CONFIGURACIÓN =====
st.set_page_config(page_title="Lectura con Tracking", layout="centered")

# Llaves desde Secrets (minúsculas)
MONGO_URI = st.secrets["mongo_uri"]
GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]
OPENAI_API_KEY = st.secrets["openai_api_key"]

openai.api_key = OPENAI_API_KEY

# Conexión MongoDB
client = pymongo.MongoClient(MONGO_URI)
db = client["lecturas_db"]
coleccion = db["lecturas"]

# ===== FUNCIONES =====
def get_location():
    """Obtiene ubicación aproximada por IP."""
    try:
        res = requests.get("https://ipinfo.io/json").json()
        lat, lon = map(float, res["loc"].split(","))
        return lat, lon
    except:
        return None, None

def mostrar_mapa(lat, lon):
    """Muestra un mapa centrado en lat/lon con Google Maps."""
    if lat and lon:
        maps_url = f"https://www.google.com/maps/embed/v1/view?key={GOOGLE_MAPS_API_KEY}&center={lat},{lon}&zoom=16"
        st.markdown(f'<iframe width="100%" height="300" frameborder="0" style="border:0" src="{maps_url}" allowfullscreen></iframe>', unsafe_allow_html=True)

def extraer_titulo_autor(imagen_bytes):
    """Envía la imagen a OpenAI para extraer título y autor."""
    prompt = """
    Eres un asistente que analiza portadas o páginas interiores de libros.
    Devuelve únicamente en formato JSON el título y el autor.
    Ejemplo: {"titulo": "Cien años de soledad", "autor": "Gabriel García Márquez"}
    """
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": prompt},
            ],
            files=[{"name": "portada.jpg", "content": imagen_bytes}]
        )
        contenido = response.choices[0].message["content"]
        datos = eval(contenido)  # Como el modelo devuelve JSON puro
        return datos.get("titulo", ""), datos.get("autor", "")
    except Exception as e:
        st.error(f"Error al extraer datos: {e}")
        return "", ""

def calcular_distancia(lat1, lon1, lat2, lon2):
    """Calcula distancia en km."""
    if None in (lat1, lon1, lat2, lon2):
        return 0
    return geopy.distance.distance((lat1, lon1), (lat2, lon2)).km

# ===== APP =====
st.title("📚 Registro de Lectura con Tracking")

# 1️⃣ Ubicación inicial
st.subheader("Ubicación inicial")
lat_ini, lon_ini = get_location()
mostrar_mapa(lat_ini, lon_ini)

# 2️⃣ Subir foto del libro
st.subheader("Foto del libro")
imagen = st.file_uploader("Sube una foto de la portada o página interior", type=["jpg", "jpeg", "png"])

if imagen:
    imagen_bytes = imagen.read()
    st.image(imagen_bytes, caption="Imagen subida", use_container_width=True)

    if st.button("📖 Detectar título y autor"):
        titulo_detectado, autor_detectado = extraer_titulo_autor(imagen_bytes)
        titulo = st.text_input("Título", titulo_detectado)
        autor = st.text_input("Autor", autor_detectado)

        if st.button("✅ Iniciar lectura"):
            inicio = datetime.now()
            st.session_state["lectura"] = {
                "titulo": titulo,
                "autor": autor,
                "inicio": inicio,
                "lat_ini": lat_ini,
                "lon_ini": lon_ini
            }
            st.success(f"Lectura iniciada: {titulo} - {autor}")

# 3️⃣ Cronómetro y finalización
if "lectura" in st.session_state:
    lectura = st.session_state["lectura"]
    st.subheader("⏱ Cronómetro")
    tiempo_transcurrido = (datetime.now() - lectura["inicio"]).seconds
    st.write(f"Tiempo: {tiempo_transcurrido // 60} min {tiempo_transcurrido % 60} s")

    if st.button("🛑 Finalizar lectura"):
        lat_fin, lon_fin = get_location()
        fin = datetime.now()
        distancia = calcular_distancia(
            lectura["lat_ini"], lectura["lon_ini"],
            lat_fin, lon_fin
        )
        registro = {
            "titulo": lectura["titulo"],
            "autor": lectura["autor"],
            "inicio": lectura["inicio"],
            "fin": fin,
            "lat_ini": lectura["lat_ini"],
            "lon_ini": lectura["lon_ini"],
            "lat_fin": lat_fin,
            "lon_fin": lon_fin,
            "distancia_km": distancia
        }
        coleccion.insert_one(registro)
        st.success("Lectura registrada en la base de datos ✅")

        if distancia > 0:
            st.subheader("Recorrido")
            mostrar_mapa(lat_fin, lon_fin)

        del st.session_state["lectura"]

# 4️⃣ Historial
st.subheader("📜 Historial")
for doc in coleccion.find().sort("inicio", -1).limit(5):
    st.write(f"**{doc['titulo']}** - {doc['autor']}")
    st.write(f"Inició: {doc['inicio']} | Distancia: {doc['distancia_km']:.2f} km")