import streamlit as st
import time
import base64
import json
import math
from datetime import datetime, timedelta
import pytz
import pymongo
import openai
from streamlit_js_eval import streamlit_js_eval
from streamlit.components.v1 import html
from dateutil.parser import parse

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Reader Tracker", layout="wide")

# Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai_api_key = st.secrets.get("openai_api_key")
openai.organization = st.secrets.get("openai_org_id", None)

tz = pytz.timezone("America/Bogota")

# Conexión MongoDB
mongo_collection = None
if mongo_uri:
    try:
        client = pymongo.MongoClient(mongo_uri)
        db = client["reader_tracker"]
        mongo_collection = db["lecturas"]
    except Exception as e:
        st.warning(f"No se pudo conectar a MongoDB: {e}")

# ---------------- FUNCIONES UTILITARIAS ----------------

def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        dt = parse(dt)
    return dt.astimezone(tz)

def render_live_map(api_key, height=420, center_coords=None):
    center_lat = center_coords[0] if center_coords else 0
    center_lon = center_coords[1] if center_coords else 0
    html_code = f"""
    <!doctype html>
    <html>
      <head>
        <meta name="viewport" content="initial-scale=1.0, width=device-width" />
        <style> html, body, #map {{ height: 100%; margin:0; padding:0 }} </style>
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=geometry"></script>
      </head>
      <body>
        <div id="map"></div>
        <script>
          let map;
          let marker;

          function initMap() {{
            map = new google.maps.Map(document.getElementById('map'), {{
              zoom: 17,
              center: {{lat:{center_lat}, lng:{center_lon}}},
              mapTypeId: 'roadmap'
            }});
            marker = new google.maps.Marker({{ map: map, position: {{lat:{center_lat}, lng:{center_lon}}}, title: "Tú" }});
          }}

          function updatePosition(pos) {{
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            const latlng = new google.maps.LatLng(lat, lng);
            marker.setPosition(latlng);
            map.setCenter(latlng);
          }}

          function handleError(err) {{
            console.error('Geolocation error', err);
          }}

          if (navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition(
              function(p) {{
                initMap();
                updatePosition(p);
                navigator.geolocation.watchPosition(updatePosition, handleError, {{ enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 }});
              }},
              function(e) {{
                initMap();
                console.error('Error getCurrentPosition', e);
              }},
              {{ enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 }}
            );
          }} else {{
            initMap();
            console.error('Navegador no soporta geolocalización');
          }}
        </script>
      </body>
    </html>
    """
    html(html_code, height=height)

# ---------------- MÓDULOS ----------------

# --- Módulo 1: Tiempo dedicado al desarrollo ---
def modulo_tiempo_desarrollo():
    st.header("Tiempo dedicado al desarrollo")
    if "dev_start" not in st.session_state:
        st.session_state["dev_start"] = None

    if st.session_state["dev_start"] is None:
        if st.button("🟢 Iniciar desarrollo"):
            st.session_state["dev_start"] = datetime.now(tz)
            st.success("🧠 Desarrollo iniciado")
            st.rerun()
    else:
        start_time = st.session_state["dev_start"]
        elapsed = datetime.now(tz) - start_time
        st.markdown(f"🧠 Desarrollo en curso desde las {start_time.strftime('%H:%M:%S')}")
        st.markdown(f"⏱️ Tiempo transcurrido: {str(elapsed).split('.')[0]}")

        if st.button("⏹️ Finalizar desarrollo"):
            # Aquí podrías guardar el registro en MongoDB si quieres
            st.session_state["dev_start"] = None
            st.success("✅ Desarrollo finalizado")
            st.rerun()

# --- Módulo 2: GPT-4o, detección título/autor y cronómetro lectura ---
def modulo_gpt_cronometro():
    st.header("GPT-4o, detección título/autor y cronómetro lectura")
    st.info("Pendiente integrar aquí toda la lógica que ya tenés para detectar título, autor, registrar páginas, cronómetro y resumen.")

# --- Módulo 3: Mapa en vivo ---
def modulo_mapa_en_vivo():
    st.header("Mapa en vivo")
    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

# --- Módulo 4: Historial de lecturas ---
def modulo_historial():
    st.header("Historial de lecturas")
    st.info("Pendiente implementar historial de lecturas con datos locales y MongoDB.")

# ---------------- INTERFAZ PRINCIPAL ----------------

st.title("Reader Tracker")

seccion = st.selectbox(
    "Selecciona una sección:",
    ["Tiempo de desarrollo", "GPT-4o y cronómetro", "Mapa en vivo", "Historial de lecturas"]
)

if seccion == "Tiempo de desarrollo":
    modulo_tiempo_desarrollo()
elif seccion == "GPT-4o y cronómetro":
    modulo_gpt_cronometro()
elif seccion == "Mapa en vivo":
    modulo_mapa_en_vivo()
elif seccion == "Historial de lecturas":
    modulo_historial()
