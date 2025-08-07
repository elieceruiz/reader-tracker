import streamlit as st
from PIL import Image
import base64
import openai
import datetime
import pymongo
import requests
import pandas as pd
from bson.objectid import ObjectId

# Configuración inicial
st.set_page_config(page_title="📚 Seguimiento lector – con cui", layout="centered")

# Conexión a MongoDB
mongo_client = pymongo.MongoClient(st.secrets["mongo_uri"])
db = mongo_client["seguimiento_lector"]
collection = db["registros"]

# Configurar API de OpenAI
openai.api_key = st.secrets["openai_api_key"]
openai.organization = st.secrets["openai_org_id"]

# Función para geolocalización por IP
@st.cache_data(ttl=3600)
def obtener_geolocalizacion():
    try:
        res = requests.get("https://ipinfo.io/json")
        data = res.json()
        lat, lon = map(float, data["loc"].split(","))
        return {"lat": lat, "lon": lon}
    except:
        return None

# Título principal
st.title("📚 Seguimiento lector – con cui")

# 1. Subida de portada (opcional)
st.subheader("1. Sube portada del libro (opcional)")
uploaded_file = st.file_uploader("Foto de portada", type=["jpg", "jpeg", "png"])

book_title = ""
image_bytes = None

if uploaded_file:
    image_bytes = uploaded_file.read()
    image = Image.open(uploaded_file)
    st.image(image, caption="Portada del libro", use_container_width=True)
    st.text("🧠 Leyendo texto en la portada...")

    try:
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

# 2. Ingreso de título manual
st.subheader("2. Título del libro")
book_title_manual = st.text_input("Título", value=book_title)

# 3. Comentario o reflexión
st.subheader("3. Comentario o reflexión")
comment = st.text_area("¿Qué leíste? ¿Qué te dejó esta lectura?", height=150)

# 4. Guardar registro
if st.button("💾 Guardar registro"):
    if not book_title_manual.strip():
        st.error("Por favor ingresa un título.")
    elif not comment.strip():
        st.error("Por favor escribe un comentario.")
    else:
        geo = obtener_geolocalizacion()
        registro = {
            "titulo": book_title_manual.strip(),
            "comentario": comment.strip(),
            "fecha": datetime.datetime.now(),
            "lat": geo["lat"] if geo else None,
            "lon": geo["lon"] if geo else None,
        }
        collection.insert_one(registro)
        st.success("✅ Registro guardado con éxito")

# 5. Mostrar historial
st.subheader("🕓 Historial de lecturas")
registros = list(collection.find().sort("fecha", -1))

if registros:
    for r in registros:
        st.markdown(f"**📖 {r['titulo']}**")
        st.caption(r["fecha"].strftime("%Y-%m-%d %H:%M"))
        st.write(r["comentario"])
        if r.get("lat") and r.get("lon"):
            st.map(pd.DataFrame([{"lat": r["lat"], "lon": r["lon"]}]))
        st.markdown("---")
else:
    st.info("Aún no hay registros.")
