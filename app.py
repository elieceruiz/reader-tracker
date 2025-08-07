import streamlit as st
import openai
import base64
import requests
import time
import datetime

# API keys desde secrets
openai.api_key = st.secrets["openai_api_key"]
openai.organization = st.secrets["openai_org_id"]

# Función para capturar texto desde imagen (OpenAI)
def extraer_titulo_desde_imagen(image_bytes):
    base64_image = base64.b64encode(image_bytes).decode("utf-8")
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Eres un asistente que analiza textos a partir de una imagen y sugiere el título del documento."},
            {"role": "user", "content": f"Esta es la imagen en base64: {base64_image}. Detecta el texto principal y sugiere el título más probable del documento. Solo responde con el título propuesto."}
        ],
        temperature=0.2
    )
    return response.choices[0].message.content.strip()

# Página principal
st.title("📸 Seguimiento de Lectura")

# Cámara
img_file = st.camera_input("Captura la portada del texto")

if img_file:
    st.success("✅ Imagen capturada correctamente")
    
    # Extraer título desde OpenAI
    with st.spinner("Analizando la imagen para extraer el título..."):
        try:
            image_bytes = img_file.getvalue()
            titulo = extraer_titulo_desde_imagen(image_bytes)
            st.markdown(f"### 📘 Título detectado: **{titulo}**")
        except Exception as e:
            st.error(f"❌ Error al analizar la imagen: {e}")
            st.stop()

    # Página inicial
    pagina = st.number_input("📄 Página en la que comienzas", min_value=1, step=1)
    
    # Geolocalización
    st.markdown("### 📍 Ubicación aproximada")
    st.map()  # Simple geolocalización por IP

    # Cronómetro
    if st.button("⏱️ Iniciar cronómetro"):
        st.session_state["inicio"] = time.time()
        st.session_state["titulo"] = titulo
        st.session_state["pagina"] = pagina

# Cronómetro en curso
if "inicio" in st.session_state:
    st.markdown(f"### ⏱️ Leyendo **{st.session_state['titulo']}** desde página **{st.session_state['pagina']}**")
    
    elapsed = int(time.time() - st.session_state["inicio"])
    tiempo = str(datetime.timedelta(seconds=elapsed))
    st.metric("⏳ Tiempo transcurrido", tiempo)