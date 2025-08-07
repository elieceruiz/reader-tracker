import streamlit as st
import openai
import time
from datetime import datetime
from pymongo import MongoClient
from PIL import Image
import base64
import geocoder
import folium
from streamlit_folium import st_folium

# 🎯 Autenticación
openai.api_key = st.secrets["openai_api_key"]
openai.organization = st.secrets["openai_org_id"]
client = MongoClient(st.secrets["mongo_uri"])
db = client["reader_tracker"]

# 📚 Título principal
st.title("📚 Seguimiento lector – con cui")

# --- Paso 1: Cargar portada del libro ---
st.subheader("1. Sube portada del libro (opcional)")
uploaded_file = st.file_uploader("Foto de portada", type=["png", "jpg", "jpeg"])

book_title = ""

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Portada del libro", use_container_width=True)
    st.text("🧠 Leyendo texto en la portada...")

    try:
        image_bytes = uploaded_file.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Observa la imagen de portada del libro. ¿Puedes deducir cuál es el título del libro? Solo responde con el título más probable, sin explicaciones."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=30
        )

        book_title = response.choices[0].message.content.strip()

        if book_title:
            st.success(f"📖 Título detectado: *{book_title}*")
        else:
            st.warning("❌ No se pudo detectar el título. Puedes ingresarlo manualmente si lo deseas.")
    except Exception as e:
        st.warning("❌ No se pudo detectar el título. Puedes ingresarlo manualmente si lo deseas.")
        st.caption(f"Error técnico: {e}")

# Entrada manual si es necesario
if not book_title:
    book_title = st.text_input("Escribe el título del libro", placeholder="Por ejemplo: Cien años de soledad")

# --- Paso 2: Verificar colección ---
if book_title:
    collection_name = book_title.lower().replace(" ", "_")
else:
    collection_name = "libro_sin_titulo"

collection = db[collection_name]

# --- Paso 3: Página de inicio ---
st.subheader("2. ¿En qué página comienzas hoy?")
start_page = st.number_input("Página de inicio", min_value=1, step=1)

# --- Paso 4: Cronómetro de lectura ---
st.subheader("3. Cronómetro de lectura")
if "start_time" not in st.session_state:
    st.session_state.start_time = None

col1, col2 = st.columns(2)
with col1:
    start_btn = st.button("▶️ Iniciar lectura")
with col2:
    stop_btn = st.button("⏹️ Terminar lectura")

if start_btn:
    st.session_state.start_time = time.time()
    st.success("⏱️ Cronómetro iniciado.")

if stop_btn and st.session_state.start_time:
    elapsed = int(time.time() - st.session_state.start_time)
    minutes = elapsed // 60
    seconds = elapsed % 60
    st.success(f"⏹️ Tiempo registrado: {minutes} min {seconds} seg")

    # --- Paso 5: Página final y resumen ---
    end_page = st.number_input("¿En qué página terminaste?", min_value=start_page, step=1, key="end_page")
    resumen = st.text_area("¿Qué se te quedó de esta lectura?", placeholder="Escribe aquí...")

    # --- Paso 6: Georreferenciación ---
    st.subheader("📍 Ubicación de lectura (aproximada)")
    g = geocoder.ip("me")
    coords = g.latlng or [0.0, 0.0]

    # Mapa básico
    st.map(data={"lat": [coords[0]], "lon": [coords[1]]}, zoom=10)

    # Mapa interactivo
    m = folium.Map(location=coords, zoom_start=12)
    folium.Marker(coords, popup="Lectura").add_to(m)
    st_folium(m, width=700, height=400)

    # --- Paso 7: Guardar en MongoDB ---
    doc = {
        "titulo": book_title or "Sin título",
        "inicio": start_page,
        "final": end_page,
        "resumen": resumen,
        "duracion_min": minutes,
        "duracion_seg": seconds,
        "timestamp": datetime.utcnow(),
        "ubicacion": {"lat": coords[0], "lon": coords[1]}
    }
    collection.insert_one(doc)
    st.success("✅ Registro guardado con cui.")
    st.session_state.start_time = None