import streamlit as st
from pymongo import MongoClient
import pytesseract
from PIL import Image
import openai
import os
import time
from datetime import datetime
from io import BytesIO

# Config
openai.api_key = os.getenv("OPENAI_API_KEY")
mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["reader_tracker"]

# UI
st.set_page_config(page_title="Reader Tracker", layout="centered")
st.title("📚 Seguimiento lector – con cui")

# --- 1. Subir imagen del libro y extraer nombre ---
st.subheader("1. Sube portada del libro (opcional)")
img = st.file_uploader("Foto de portada", type=["png", "jpg", "jpeg"])
book_title = ""

if img:
    image = Image.open(img)
    st.image(image, caption="Portada del libro", use_column_width=True)
    book_title = pytesseract.image_to_string(image).strip()
    book_title = book_title.split("\n")[0]
    st.success(f"Título extraído: {book_title}")

# --- 2. Pedir título manual si no hay OCR válido ---
book_title = st.text_input("Nombre del libro", value=book_title)
if not book_title:
    st.stop()

# --- 3. Crear colección o usar existente ---
collection = db[book_title.replace(" ", "_").lower()]

# --- 4. Revisar última sesión ---
last_session = collection.find_one(sort=[("timestamp", -1)])
last_page = last_session["end_page"] if last_session else None
last_time = last_session["timestamp"] if last_session else None
last_note = last_session["note"] if last_session else None

# --- 5. Página inicial ---
st.subheader("2. Página en la que comienzas hoy")
start_page = st.number_input("Página actual", min_value=1, value=last_page + 1 if last_page else 1)

# --- 6. Cronómetro ---
st.subheader("3. Cronómetro de lectura")
start = st.button("▶️ Empezar")
stop = st.button("⏹ Parar")

if "start_time" not in st.session_state:
    st.session_state.start_time = None

if start:
    st.session_state.start_time = time.time()
    st.success("¡Lectura iniciada!")

if stop and st.session_state.start_time:
    duration = time.time() - st.session_state.start_time
    minutes = int(duration // 60)
    seconds = int(duration % 60)
    st.success(f"Tiempo registrado: {minutes} min {seconds} s")
else:
    duration = None

# --- 7. Página final y nota ---
if stop and duration:
    end_page = st.number_input("¿En qué página terminaste?", min_value=start_page, value=start_page)
    note = st.text_area("¿Qué se te quedó de esta sesión?")
    
    if st.button("💾 Guardar sesión"):
        doc = {
            "start_page": int(start_page),
            "end_page": int(end_page),
            "duration_seconds": int(duration),
            "note": note,
            "timestamp": datetime.utcnow()
        }
        collection.insert_one(doc)
        st.success("Sesión registrada.")
        st.rerun()

# --- 8. Reflexión IA basada en historial ---
if last_session and st.checkbox("🧠 Mostrar observación de la IA (OpenAI)"):
    # Construir prompt
    now = datetime.utcnow()
    gap = (now - last_time).days
    short_note = last_note[:300] if last_note else ""

    prompt = f"""
Eres un lector consciente que lleva un diario lector. Hace {gap} días leíste el mismo libro. Esta fue tu última nota: "{short_note}".
Hoy retomas desde la página {start_page}. ¿Qué te dirías a ti mismo para notar si hay un hilo, un corte, o un cambio de tono en tu proceso?
Hazlo en tono reflexivo, no condescendiente. No adivines nada, solo formula preguntas o recordatorios.
"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        ai_message = response.choices[0].message.content
        st.markdown("### 🧠 IA dice:")
        st.info(ai_message)
    except Exception as e:
        st.warning("Error al consultar OpenAI. Revisa tu API Key.")
        st.text(str(e))
