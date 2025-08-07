# app_lector.py
import streamlit as st
import pytesseract
from PIL import Image
import io
import base64
import geopy
from geopy.geocoders import Nominatim
import time
import datetime
import pymongo
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")
client = pymongo.MongoClient(MONGO_URI)
db = client["lector"]
coleccion = db["registros"]

st.set_page_config(page_title="📚 Registro de Lectura", layout="centered")
st.title("📚 Registro de Lectura Automatizado")

# --- Carga de imagen ---
imagen_subida = st.file_uploader("Sube la imagen del libro (portada o página con datos)", type=["jpg", "png", "jpeg"])

# --- OCR ---
def extraer_texto(imagen_bytes):
    image = Image.open(io.BytesIO(imagen_bytes))
    texto = pytesseract.image_to_string(image, lang="spa")
    return texto

# --- Geolocalización ---
def obtener_ubicacion():
    try:
        geo = Nominatim(user_agent="app_lector")
        loc = geo.geocode("Colombia")  # Puedes mejorar esto con IP si deseas precisión
        return f"{loc.address} ({loc.latitude:.2f}, {loc.longitude:.2f})"
    except:
        return "Ubicación no detectada"

# --- Cronómetro ---
def iniciar_cronometro():
    if "inicio" not in st.session_state:
        st.session_state.inicio = time.time()

    tiempo_actual = time.time()
    duracion = tiempo_actual - st.session_state.inicio
    return str(datetime.timedelta(seconds=int(duracion)))

# --- Procesar imagen ---
datos_detectados = {"Título": "", "Autor": "", "Año": "", "Editorial": "", "ISBN": ""}
if imagen_subida:
    texto_extraido = extraer_texto(imagen_subida.read())
    st.text_area("Texto detectado:", value=texto_extraido, height=200)

    # Detección básica
    if "Fisher" in texto_extraido:
        datos_detectados["Autor"] = "Mark Fisher"
    if "Realismo capitalista" in texto_extraido:
        datos_detectados["Título"] = "Realismo capitalista: ¿No hay alternativa?"
    if "Caja Negra" in texto_extraido:
        datos_detectados["Editorial"] = "Caja Negra"
    if "2018" in texto_extraido:
        datos_detectados["Año"] = "2018"
    if "ISBN" in texto_extraido:
        isbn_line = [line for line in texto_extraido.split("\n") if "ISBN" in line]
        if isbn_line:
            datos_detectados["ISBN"] = isbn_line[0].split()[-1]

# --- Formulario editable ---
st.subheader("📝 Completa los datos del libro")
titulo = st.text_input("Título", value=datos_detectados["Título"])
autor = st.text_input("Autor", value=datos_detectados["Autor"])
editorial = st.text_input("Editorial", value=datos_detectados["Editorial"])
anio = st.text_input("Año", value=datos_detectados["Año"])
isbn = st.text_input("ISBN", value=datos_detectados["ISBN"])
pagina = st.number_input("Página leída", min_value=1, step=1)

# --- Cronómetro ---
st.subheader("⏱ Cronómetro de lectura")
tiempo_lectura = iniciar_cronometro()
st.info(f"Tiempo actual de lectura: {tiempo_lectura}")

# --- Geolocalización ---
st.subheader("🌍 Georreferenciación")
ubicacion = obtener_ubicacion()
st.success(f"Ubicación estimada: {ubicacion}")

# --- Guardar en MongoDB ---
if st.button("💾 Guardar registro"):
    registro = {
        "titulo": titulo,
        "autor": autor,
        "editorial": editorial,
        "anio": anio,
        "isbn": isbn,
        "pagina": pagina,
        "duracion": tiempo_lectura,
        "ubicacion": ubicacion,
        "timestamp": datetime.datetime.now()
    }
    coleccion.insert_one(registro)
    st.success("✅ Registro guardado exitosamente.")

# --- Mostrar historial ---
st.subheader("📚 Historial de lectura")
registros = list(coleccion.find().sort("timestamp", -1))
for r in registros[:5]:
    st.markdown(f"""
    **{r.get("titulo", "Sin título")}**  
    Autor: {r.get("autor", "")}  
    Página: {r.get("pagina", "")}  
    Tiempo: {r.get("duracion", "")}  
    Ubicación: {r.get("ubicacion", "")}  
    Fecha: {r.get("timestamp").strftime('%Y-%m-%d %H:%M:%S')}  
    ---  
    """)