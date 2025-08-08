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

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai_api_key = st.secrets.get("openai_api_key")
openai.organization = st.secrets.get("openai_org_id", None)

# Zona horaria
tz = pytz.timezone("America/Bogota")

# Conexión MongoDB
client = None
dev_col = None
if mongo_uri:
    try:
        client = pymongo.MongoClient(mongo_uri)
        db = client["reader_tracker"]
        dev_col = db["dev_tracker"]  # Colección para tiempo de desarrollo
        # Aquí podrían ir otras colecciones para historial, órdenes, etc.
    except Exception as e:
        st.warning(f"No se pudo conectar a MongoDB: {e}")

# Utilidad robusta para convertir a datetime local
from dateutil.parser import parse
def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        dt = parse(dt)
    return dt.astimezone(tz)

# --------- FUNCIONES DEL MÓDULO MAPA ----------
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
          let path = [];

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


# --------- DROPDOWN DE SECCIONES ----------
seccion = st.selectbox(
    "Selecciona una sección:",
    ["Tiempo de desarrollo", "GPT-4o y Cronómetro", "Mapa en vivo", "Historial de lecturas"]
)


# ------------- MÓDULO 1: TIEMPO DE DESARROLLO -------------
if seccion == "Tiempo de desarrollo":
    st.subheader("⏱️ Tiempo dedicado al desarrollo")

    if dev_col is None:
        st.error("No hay conexión a MongoDB para registrar el tiempo de desarrollo.")
    else:
        evento = dev_col.find_one({"tipo": "ordenador_dev", "en_curso": True})

        if not evento:
            # No hay desarrollo activo: mostramos solo botón inicio
            if st.button("🟢 Iniciar desarrollo"):
                dev_col.insert_one({"tipo": "ordenador_dev", "inicio": datetime.now(tz), "en_curso": True})
                st.experimental_rerun()
        else:
            # Hay desarrollo activo: mostrar cronómetro y botón detener
            hora_inicio = to_datetime_local(evento["inicio"])
            st.success(f"🧠 Desarrollo en curso desde las {hora_inicio.strftime('%H:%M:%S')}")
            segundos_transcurridos = int((datetime.now(tz) - hora_inicio).total_seconds())
            cronometro = st.empty()
            stop_button = st.button("⏹️ Finalizar desarrollo")

            if stop_button:
                dev_col.update_one({"_id": evento["_id"]}, {"$set": {"fin": datetime.now(tz), "en_curso": False}})
                st.success("✅ Registro finalizado.")
                st.experimental_rerun()

            duracion = str(timedelta(seconds=segundos_transcurridos))
            cronometro.markdown(f"### ⏱️ Duración: {duracion}")



# ------------- MÓDULO 2: GPT-4o y Cronómetro (pendiente) -------------
elif seccion == "GPT-4o y Cronómetro":
    st.header("Sección: GPT-4o y Cronómetro")
    st.info("Aquí irá todo lo relacionado a GPT-4o, detección de título, autor y cronómetro (pendiente implementar).")


# ------------- MÓDULO 3: MAPA EN VIVO -------------
elif seccion == "Mapa en vivo":
    st.header("Sección: Mapa en vivo")

    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")


# ------------- MÓDULO 4: HISTORIAL DE LECTURAS (pendiente) -------------
elif seccion == "Historial de lecturas":
    st.header("Sección: Historial de lecturas")
    st.info("Aquí irá el historial de lecturas (pendiente implementar).")
