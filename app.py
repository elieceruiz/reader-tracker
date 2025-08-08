import streamlit as st
import time
import base64
import json
import math
from datetime import datetime
import pymongo
import openai

# CONFIGURACIÓN DE PÁGINA
st.set_page_config(page_title="📚 Reader Tracker", layout="wide")

# SECRETS (todo en minúsculas)
MONGO_URI = st.secrets.get("mongo_uri")
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps_api_key")
OPENAI_API_KEY = st.secrets.get("openai_api_key")

# CSS para estilo personalizado
st.markdown(
    """
    <style>
    .title {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        color: #1F4E79;
        font-size: 3rem;
        font-weight: 700;
        margin-bottom: 0.25rem;
    }
    .subtitle {
        color: #3E92CC;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .stButton>button {
        background-color: #3E92CC !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
        padding: 0.5rem 1rem !important;
        transition: background-color 0.3s ease !important;
    }
    .stButton>button:hover {
        background-color: #2B6CA3 !important;
        cursor: pointer !important;
    }
    .metric-container {
        background: #F0F8FF;
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
        box-shadow: 2px 2px 10px rgba(0,0,0,0.1);
    }
    .section-divider {
        border-top: 2px solid #3E92CC;
        margin: 1rem 0 1rem 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Título y subtítulo
st.markdown('<div class="title">📚 Reader Tracker</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Sigue tu lectura con ubicación y análisis automático.</div>', unsafe_allow_html=True)

# Conexión MongoDB
mongo_collection = None
if MONGO_URI:
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client["reader_tracker"]
        mongo_collection = db["lecturas"]
    except Exception as e:
        st.warning(f"No se pudo conectar a MongoDB: {e}")

# Funciones
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def openai_extract_title_author(image_bytes):
    openai.api_key = OPENAI_API_KEY
    data_uri = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("utf-8")
    system_prompt = (
        "Eres un extractor que devuelves SOLO JSON con claves 'titulo' y 'autor'. "
        "Si no encuentras autor, devuelve cadena vacía. Ejemplo: {\"titulo\":\"Cien años de soledad\",\"autor\":\"Gabriel García Márquez\"}"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extrae únicamente título y autor de esta imagen."},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]}
            ],
            max_tokens=200,
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        try:
            parsed = json.loads(text)
            titulo = parsed.get("titulo", "") if isinstance(parsed.get("titulo", ""), str) else ""
            autor = parsed.get("autor", "") if isinstance(parsed.get("autor", ""), str) else ""
            return titulo.strip(), autor.strip()
        except Exception:
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                parsed = json.loads(text[start:end])
                return parsed.get("titulo","").strip(), parsed.get("autor","").strip()
            except Exception:
                return text.replace("\n"," ").strip(), ""
    except Exception as e:
        st.warning(f"Error al llamar a OpenAI: {e}")
        return "", ""

# UI

with st.expander("📍 Capturar ubicación de inicio"):
    if st.button("📍 Capturar ubicación inicio"):
        js_getpos = """
        new Promise((resolve) => {
          if (!navigator.geolocation) { resolve(null); return; }
          navigator.geolocation.getCurrentPosition(
            (pos) => resolve({latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
            (err) => resolve(null),
            {enableHighAccuracy: true, timeout:10000}
          );
        })
        """
        from streamlit_js_eval import streamlit_js_eval
        coords = streamlit_js_eval(js_expressions=js_getpos, key="getpos_start")
        if coords:
            st.session_state["start_coords"] = (float(coords["latitude"]), float(coords["longitude"]))
            st.success(f"Ubicación inicio capturada: {st.session_state['start_coords']}")
        else:
            st.error("No se pudo obtener la ubicación desde el navegador. Asegurate de dar permiso.")

st.markdown('<hr class="section-divider"/>')

with st.expander("📷 Detectar título y autor (sube foto de portada)"):
    uploaded = st.file_uploader("Foto (portada o página clara)", type=["jpg","jpeg","png"])
    titulo_sugerido = ""
    autor_sugerido = ""

    if uploaded:
        st.image(uploaded, caption="Imagen subida", use_column_width=True)
        if st.button("🔎 Detectar título y autor (GPT-4o)"):
            image_bytes = uploaded.read()
            with st.spinner("Analizando imagen con GPT-4o..."):
                t, a = openai_extract_title_author(image_bytes)
            if t or a:
                titulo_sugerido = t
                autor_sugerido = a
                st.session_state["titulo_sugerido"] = titulo_sugerido
                st.session_state["autor_sugerido"] = autor_sugerido
                st.success("Detección completada.")
            else:
                st.warning("No se detectó título/autor con confianza.")

    titulo_val = st.text_input("Título (confirmá o edita)", value=st.session_state.get("titulo_sugerido", ""))
    autor_val = st.text_input("Autor (confirmá o edita)", value=st.session_state.get("autor_sugerido", ""))

st.markdown('<hr class="section-divider"/>')

with st.expander("⏱️ Control de lectura"):
    if "reading_started" not in st.session_state:
        st.session_state["reading_started"] = False

    if not st.session_state["reading_started"]:
        if st.button("▶️ Iniciar lectura"):
            if "start_coords" not in st.session_state:
                st.error("Primero capturá la ubicación de inicio con 'Capturar ubicación inicio'.")
            elif not titulo_val:
                st.error("Confirmá el título antes de iniciar la lectura.")
            else:
                st.session_state["reading_started"] = True
                st.session_state["start_time"] = time.time()
                st.session_state["titulo"] = titulo_val
                st.session_state["autor"] = autor_val
                st.success("Cronómetro iniciado.")
    else:
        elapsed = int(time.time() - st.session_state["start_time"])
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        st.markdown(f'<div class="metric-container">⏳ Tiempo transcurrido: <b>{hh:02d}:{mm:02d}:{ss:02d}</b></div>', unsafe_allow_html=True)

        if st.button("⏹ Detener lectura"):
            js_getpos_end = """
            new Promise((resolve) => {
              if (!navigator.geolocation) { resolve(null); return; }
              navigator.geolocation.getCurrentPosition(
                (pos) => resolve({latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
                (err) => resolve(null),
                {enableHighAccuracy: true, timeout:10000}
              );
            })
            """
            coords_end = streamlit_js_eval(js_expressions=js_getpos_end, key="getpos_end")
            if not coords_end:
                st.error("No se pudo obtener ubicación final desde el navegador.")
            else:
                end_coords = (float(coords_end["latitude"]), float(coords_end["longitude"]))
                start_coords = st.session_state["start_coords"]
                duration_sec = int(time.time() - st.session_state["start_time"])
                duration_str = f"{duration_sec//3600:02d}:{(duration_sec%3600)//60:02d}:{duration_sec%60:02d}"
                distancia_km = haversine_km(start_coords[0], start_coords[1], end_coords[0], end_coords[1])
                modo = "En movimiento" if (distancia_km * 1000) > 10 else "En reposo"

                registro = {
                    "titulo": st.session_state.get("titulo",""),
                    "autor": st.session_state.get("autor",""),
                    "inicio_ts": datetime.utcnow(),
                    "inicio_coords": {"lat": start_coords[0], "lon": start_coords[1]},
                    "fin_ts": datetime.utcnow(),
                    "fin_coords": {"lat": end_coords[0], "lon": end_coords[1]},
                    "duracion_sec": duration_sec,
                    "duracion_str": duration_str,
                    "distancia_km": round(distancia_km, 4),
                    "modo": modo
                }

                if mongo_collection:
                    try:
                        mongo_collection.insert_one(registro)
                        st.success("Registro guardado en MongoDB ✅")
                    except Exception as e:
                        st.warning(f"No se pudo guardar en MongoDB: {e}")
                        st.session_state.setdefault("historia_local", []).insert(0, registro)
                else:
                    st.session_state.setdefault("historia_local", []).insert(0, registro)
                    st.success("Registro guardado localmente en sesión.")

                st.write(f"**Resumen:** {registro['titulo']} — {registro['autor']}")
                st.write(f"Duración: {registro['duracion_str']} — Distancia: {registro['distancia_km']*1000:.1f} m — {registro['modo']}")

                # Mostrar mapa con ruta si tienes key
                if GOOGLE_MAPS_API_KEY:
                    origin = f"{start_coords[0]},{start_coords[1]}"
                    dest = f"{end_coords[0]},{end_coords[1]}"
                    directions_url = (
                        f"https://www.google.com/maps/embed/v1/directions?key={GOOGLE_MAPS_API_KEY}"
                        f"&origin={origin}&destination={dest}&mode=walking"
                    )
                    st.components.v1.html(f'<iframe width="100%" height="320" src="{directions_url}" style="border:0"></iframe>', height=320)
                else:
                    st.warning("No hay google_maps_api_key para mostrar ruta.")

                # Limpiar estado para nueva sesión
                st.session_state["reading_started"] = False
                st.session_state.pop("start_coords", None)

st.markdown('<hr class="section-divider"/>')

st.subheader("📜 Historial de lecturas")

historia = st.session_state.get("historia_local", [])
if mongo_collection:
    try:
        docs = list(mongo_collection.find().sort("inicio_ts", -1).limit(20))
        for d in docs:
            historia.append({
                "titulo": d.get("titulo",""),
                "autor": d.get("autor",""),
                "duracion_str": f"{int(d.get('duracion_sec',0)//3600):02d}:{int(d.get('duracion_sec',0)%3600//60):02d}:{int(d.get('duracion_sec',0)%60):02d}",
                "distancia_km": d.get("distancia_km", 0),
                "inicio_coords": d.get("inicio_coords"),
                "fin_coords": d.get("fin_coords"),
                "modo": d.get("modo","")
            })
    except Exception:
        pass

if historia:
    for h in historia:
        st.markdown(f"### 📖 {h.get('titulo','Sin título')} — {h.get('autor','')}")
        st.write(f"⏰ Duración: {h.get('duracion_str','?')} — 🚶‍♂️ Distancia: {round(h.get('distancia_km',0)*1000,1)} m — 📍 {h.get('modo','')}")
        if h.get("inicio_coords") and h.get("fin_coords") and GOOGLE_MAPS_API_KEY:
            origin = f"{h['inicio_coords']['lat']},{h['inicio_coords']['lon']}"
            dest = f"{h['fin_coords']['lat']},{h['fin_coords']['lon']}"
            directions_url = (
                f"https://www.google.com/maps/embed/v1/directions?key={GOOGLE_MAPS_API_KEY}"
                f"&origin={origin}&destination={dest}&mode=walking"
            )
            st.components.v1.html(f'<iframe width="100%" height="220" src="{directions_url}" style="border:0"></iframe>', height=220)
        st.markdown("---")
else:
    st.info("Aún no hay registros de lectura.")