import streamlit as st
from PIL import Image
import base64
import openai
import datetime
import pymongo
import requests
import pandas as pd
import math

# ---------------- CONFIGURACIÓN INICIAL ----------------
st.set_page_config(page_title="📚 Seguimiento lector con cronómetro", layout="centered")

mongo_client = pymongo.MongoClient(st.secrets["mongo_uri"])
db = mongo_client["seguimiento_lector"]
collection = db["registros"]

openai.api_key = st.secrets["openai_api_key"]
openai.organization = st.secrets["openai_org_id"]

google_maps_key = st.secrets["google_maps_api_key"]

# ---------------- FUNCIONES ----------------
@st.cache_data(ttl=3600)
def obtener_geolocalizacion():
    try:
        res = requests.get("http://ip-api.com/json/")
        data = res.json()
        if data["status"] == "success":
            return {"lat": data["lat"], "lon": data["lon"], "city": data["city"], "country": data["country"]}
        return None
    except:
        return None

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1-a)))

def mostrar_mapa_google(lat, lon, zoom=15, height=300):
    map_html = f"""
        <iframe
            width="100%"
            height="{height}"
            style="border:0"
            loading="lazy"
            allowfullscreen
            referrerpolicy="no-referrer-when-downgrade"
            src="https://www.google.com/maps/embed/v1/view?key={google_maps_key}&center={lat},{lon}&zoom={zoom}&maptype=roadmap">
        </iframe>
    """
    st.components.v1.html(map_html, height=height)

def detectar_titulo(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    # Clasificación de tipo de imagen
    clasificacion = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": "Analiza esta imagen y responde SOLO con una de estas opciones: 'portada', 'pagina interior', 'referencia interna', 'otro'. No expliques nada más."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ],
        max_tokens=5
    ).choices[0].message.content.strip().lower()

    # Extracción de título según tipo
    if clasificacion in ["portada", "referencia interna"]:
        prompt = "Observa la imagen y responde con el título exacto del libro. No incluyas explicaciones ni otro texto."
    elif clasificacion == "pagina interior":
        prompt = "Extrae cualquier texto relevante de esta página y deduce si contiene el título del libro. Si lo encuentras, responde solo con el título; si no, responde 'No encontrado'."
    else:
        return ""

    titulo = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]}
        ],
        max_tokens=40
    ).choices[0].message.content.strip()

    return titulo if titulo.lower() != "no encontrado" else ""

# ---------------- ESTADO ----------------
if "inicio_lectura" not in st.session_state:
    st.session_state.inicio_lectura = None
if "geo_inicio" not in st.session_state:
    st.session_state.geo_inicio = None

# ---------------- PÁGINA DE INICIO ----------------
st.title("📚 Seguimiento lector con cronómetro y ubicación")

geo = obtener_geolocalizacion()
if geo:
    st.write(f"Ciudad: **{geo['city']}**, País: **{geo['country']}**")
    mostrar_mapa_google(geo["lat"], geo["lon"])
else:
    st.warning("No se pudo detectar la ubicación.")

# ---------------- CRONÓMETRO ----------------
if not st.session_state.inicio_lectura:
    if st.button("▶️ Iniciar lectura"):
        st.session_state.inicio_lectura = datetime.datetime.now()
        st.session_state.geo_inicio = geo
        st.success("Lectura iniciada.")
else:
    tiempo_transcurrido = datetime.datetime.now() - st.session_state.inicio_lectura
    st.info(f"⏱ Tiempo de lectura: {str(tiempo_transcurrido).split('.')[0]}")
    if st.button("⏹ Detener lectura"):
        geo_fin = obtener_geolocalizacion()
        tiempo_total = datetime.datetime.now() - st.session_state.inicio_lectura
        distancia = None
        if st.session_state.geo_inicio and geo_fin:
            distancia = haversine(
                st.session_state.geo_inicio["lat"], st.session_state.geo_inicio["lon"],
                geo_fin["lat"], geo_fin["lon"]
            )

        # Guardar datos base (sin título aún)
        st.session_state.registro_parcial = {
            "fecha_inicio": st.session_state.inicio_lectura,
            "fecha_fin": datetime.datetime.now(),
            "lat_inicio": st.session_state.geo_inicio["lat"] if st.session_state.geo_inicio else None,
            "lon_inicio": st.session_state.geo_inicio["lon"] if st.session_state.geo_inicio else None,
            "lat_fin": geo_fin["lat"] if geo_fin else None,
            "lon_fin": geo_fin["lon"] if geo_fin else None,
            "tiempo_total": str(tiempo_total).split('.')[0],
            "distancia_km": round(distancia, 2) if distancia else None
        }
        st.session_state.inicio_lectura = None
        st.success("Lectura detenida. Ahora registra el libro y comentario.")

# ---------------- REGISTRO DE LIBRO ----------------
if "registro_parcial" in st.session_state:
    st.subheader("📖 Detalles de la lectura")

    uploaded_file = st.file_uploader("Sube portada o página interior del libro", type=["jpg", "jpeg", "png"])
    book_title = ""
    if uploaded_file:
        image_bytes = uploaded_file.read()
        st.image(Image.open(uploaded_file), caption="Imagen subida", use_container_width=True)
        st.text("🧠 Detectando título...")
        book_title = detectar_titulo(image_bytes)
        if book_title:
            st.success(f"Título detectado: *{book_title}*")
        else:
            st.warning("No se pudo detectar el título.")

    titulo_final = st.text_input("Título del libro", value=book_title)
    comentario = st.text_area("Comentario o reflexión")

    if st.button("💾 Guardar registro completo"):
        datos = {**st.session_state.registro_parcial,
                 "titulo": titulo_final.strip(),
                 "comentario": comentario.strip()}
        collection.insert_one(datos)
        del st.session_state["registro_parcial"]
        st.success("✅ Registro guardado.")

# ---------------- HISTORIAL ----------------
st.subheader("🕓 Historial de lecturas")
registros = list(collection.find().sort("fecha_inicio", -1))

if registros:
    for r in registros:
        st.markdown(f"**📖 {r.get('titulo', 'Sin título')}**")
        st.caption(f"{r.get('fecha_inicio')} → {r.get('fecha_fin')}")
        if r.get("tiempo_total"):
            st.write(f"⏱ {r['tiempo_total']}")
        if r.get("distancia_km") is not None:
            st.write(f"🚶 Distancia: {r['distancia_km']} km")
        if r.get("comentario"):
            st.write(r["comentario"])

        if r.get("lat_inicio") and r.get("lon_inicio"):
            mostrar_mapa_google(r["lat_inicio"], r["lon_inicio"], zoom=14, height=200)
        st.markdown("---")
else:
    st.info("No hay lecturas registradas.")