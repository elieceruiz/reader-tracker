import streamlit as st
from PIL import Image
import base64
import io
import openai
from pymongo import MongoClient
from datetime import datetime

# --- Configuración inicial ---
st.set_page_config(page_title="📚 Seguimiento lector – con cui", layout="centered")
st.title("📚 Seguimiento lector – con cui")

# --- Claves (usa st.secrets o variables locales) ---
openai.api_key = st.secrets["OPENAI_API_KEY"]
mongo_uri = st.secrets["MONGO_URI"]
client = MongoClient(mongo_uri)
db = client["reader_tracker"]

# --- Función para extraer texto desde imagen usando GPT-4o ---
def extract_title_with_openai(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    img_bytes = buffer.getvalue()
    base64_image = base64.b64encode(img_bytes).decode()

    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Extrae el título del libro a partir de esta portada. Responde solo con el título."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "¿Cuál es el título del libro en esta imagen?"},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]
            }
        ],
        max_tokens=50,
        temperature=0.2,
    )
    return response.choices[0].message.content.strip()

# --- Sube portada del libro ---
uploaded_file = st.file_uploader("### 1. Sube portada del libro (opcional)", type=["png", "jpg", "jpeg"])
book_title = ""

if uploaded_file:
    image = Image.open(uploaded_file)
    st.image(image, caption="Portada del libro", use_container_width=True)

    with st.spinner("Leyendo título con OpenAI..."):
        book_title = extract_title_with_openai(image)
        st.success(f"📖 Título detectado: **{book_title}**")

# --- Entrada manual si no hay portada ---
if not book_title:
    book_title = st.text_input("📘 Escribe el título del libro")

if book_title:
    col = db[book_title.replace(" ", "_").lower()]
    st.markdown("---")

    # --- Registro inicial ---
    st.subheader("2. ¿En qué página comienzas hoy?")
    start_page = st.number_input("Página de inicio", min_value=1, step=1)
    start_btn = st.button("▶️ Comenzar lectura")

    if start_btn:
        start_time = datetime.utcnow()
        col.insert_one({
            "inicio": start_time,
            "pagina_inicio": start_page,
            "activo": True
        })
        st.success("🕒 Seguimiento iniciado.")

    # --- Parar lectura ---
    st.subheader("3. ¿Dónde terminaste y qué se te quedó?")
    stop_page = st.number_input("Página de término", min_value=1, step=1)
    notes = st.text_area("📝 ¿Qué se te quedó de esta lectura?")
    stop_btn = st.button("⏹️ Terminar sesión")

    if stop_btn:
        doc = col.find_one({"activo": True}, sort=[("inicio", -1)])
        if doc:
            end_time = datetime.utcnow()
            col.update_one(
                {"_id": doc["_id"]},
                {
                    "$set": {
                        "fin": end_time,
                        "pagina_fin": stop_page,
                        "notas": notes,
                        "activo": False
                    }
                }
            )
            duration = end_time - doc["inicio"]
            mins = duration.total_seconds() // 60
            st.success(f"✅ Sesión registrada. Duración: {int(mins)} min.")

    # --- Historial (opcional) ---
    with st.expander("📖 Ver historial"):
        rows = list(col.find().sort("inicio", -1))
        for r in rows:
            st.write(f"{r['inicio'].strftime('%Y-%m-%d %H:%M')} - {r.get('pagina_inicio')} ➡️ {r.get('pagina_fin', '?')}")
            if "notas" in r:
                st.caption(r["notas"])