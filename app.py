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

# --- Autenticación ---
openai.api_key = st.secrets["openai_api_key"]
openai.organization = st.secrets["openai_org_id"]
client = MongoClient(st.secrets["mongo_uri"])
db = client["reader_tracker"]

# --- Título ---
st.title("📚 Seguimiento lector – con cui")

# --- Paso 1: Subir portada ---
st.subheader("1. Sube portada del libro (opcional)")
uploaded_file = st.file_uploader("Foto de portada", type=["png", "jpg", "jpeg"])
book_title = ""

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Portada del libro", use_container_width=True)

    # Intentar detectar título con OpenAI Vision
    st.text("🧠 Leyendo texto en la portada...")
    try:
        image_bytes = uploaded_file.read()
        base64_image = base64.b64encode(image_bytes).decode("utf-8")
        response = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "¿Cuál es el título del libro en esta imagen?"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            max_tokens=30
        )
        book_title = response.choices[0].message.content.strip()
        st.success(f"📖 Título detectado: *{book_title}*")
    except Exception as e:
        st.error("❌ No se pudo detectar el título. Puedes ingresarlo manualmente si lo deseas.")
        book_title = ""

# --- Paso 2: Crear colección Mongo ---
if book_title:
    collection_name = book_title.lower().replace(" ", "_")
else:
    collection_name = "libro_sin_titulo"

collection = db[collection_name]

# --- Paso 3: Ingreso manual si no hay título detectado ---
if not book_title:
    book_title = st.text_input("¿Cuál es el título del libro?", placeholder="Ingresa el título manualmente")

# --- Paso 4: Página de inicio ---
st.subheader("2. ¿En qué página comienzas hoy?")
start_page = st.number_input("Página de inicio", min_value=1, step=1)

# --- Paso 5: Cronómetro ---
st.subheader("3. Cronómetro de lectura")

if "start_time" not in st.session_state:
    st.session_state.start_time = None

col1, col2 = st.columns(2)
with col1:
    if st.button("▶️ Iniciar lectura"):
        st.session_state.start_time = time.time()
        st.success("⏱️ Cronómetro iniciado.")
with col2:
    stop_clicked = st.button("⏹️ Terminar lectura")

# --- Paso 6: Finalizar lectura ---
if stop_clicked and st.session_state.start_time:
    elapsed = int(time.time() - st.session_state.start_time)
    minutes = elapsed // 60
    seconds = elapsed % 60
    st.success(f"⏹️ Tiempo registrado: {minutes} min {seconds} seg")

    st.subheader("4. ¿En qué página terminaste?")
    end_page = st.number_input("Página final", min_value=start_page, step=1, key="end_page")

    st.subheader("5. ¿Qué se te quedó de esta lectura?")
    resumen = st.text_area("Resumen", placeholder="Escribe aquí tus ideas principales...")

    # --- Paso 6: Ubicación ---
    st.subheader("6. Ubicación de lectura (aproximada)")
    g = geocoder.ip("me")
    coords = g.latlng or [0.0, 0.0]
    st.map(data={"lat": [coords[0]], "lon": [coords[1]]}, zoom=10)

    m = folium.Map(location=coords, zoom_start=12)
    folium.Marker(coords, popup="Lectura aquí").add_to(m)
    st_folium(m, width=700, height=400)

    # --- Guardar en MongoDB ---
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
    st.success("✅ Registro guardado correctamente.")
    st.session_state.start_time = None