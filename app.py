import streamlit as st
import time
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
import openai
from dateutil.parser import parse
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html

# === CONFIGURACIÓN ===
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# === SECRETS ===
mongo_uri = st.secrets.get("mongo_uri")
openai_api_key = st.secrets.get("openai_api_key")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai.organization = st.secrets.get("openai_org_id", None)

# === CONEXIONES ===
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]
# Otras colecciones que necesites, por ejemplo historial_col, etc.

# === ZONA HORARIA ===
tz = pytz.timezone("America/Bogota")

def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        dt = parse(dt)
    return dt.astimezone(tz)

# === SESIÓN ESTADO BASE ===
if "dev_start" not in st.session_state:
    st.session_state["dev_start"] = None

# === FUNCIONES ===

def iniciar_desarrollo():
    ahora = datetime.now(tz)
    st.session_state["dev_start"] = ahora
    dev_col.insert_one({
        "tipo": "desarrollo",
        "inicio": ahora,
        "en_curso": True
    })

def finalizar_desarrollo():
    ahora = datetime.now(tz)
    registro = dev_col.find_one({"en_curso": True, "tipo": "desarrollo"})
    if registro:
        dev_col.update_one(
            {"_id": registro["_id"]},
            {"$set": {"fin": ahora, "en_curso": False}}
        )
    st.session_state["dev_start"] = None

# === MÓDULOS ===

# Dropdown para elegir sección
seccion = st.selectbox(
    "Selecciona una sección:",
    [
        "Tiempo de desarrollo",
        "GPT-4o y Cronómetro",
        "Mapa en vivo",
        "Historial de lecturas"
    ]
)

# ------------------ MÓDULO 1: Tiempo de desarrollo ------------------

if seccion == "1. Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo")

    # Buscar en BD si hay sesión activa
    sesion_activa = db.dev_sessions.find_one({"fin": None})

    if sesion_activa:
        # Hay sesión activa, tomar inicio y mostrar cronómetro
        start_time = sesion_activa["inicio"].astimezone(tz) if hasattr(sesion_activa["inicio"], "astimezone") else to_datetime_local(sesion_activa["inicio"])
        segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
        st.success(f"🧠 Desarrollo en curso desde las {start_time.strftime('%H:%M:%S')}")

        cronometro = st.empty()
        stop_button = st.button("⏹️ Finalizar desarrollo")

        if stop_button:
            duracion = str(timedelta(seconds=segundos_transcurridos))
            db.dev_sessions.update_one({"_id": sesion_activa["_id"]}, {"$set": {"fin": datetime.now(tz), "duracion_segundos": segundos_transcurridos}})
            st.success(f"✅ Desarrollo finalizado. Duración: {duracion}")
            st.experimental_rerun()
        else:
            for i in range(segundos_transcurridos, segundos_transcurridos + 100000):
                duracion = str(timedelta(seconds=i))
                cronometro.markdown(f"### ⏱️ Duración: {duracion}")
                time.sleep(1)
    else:
        # No hay sesión activa
        if st.button("🟢 Iniciar desarrollo"):
            # Insertar nueva sesión con fin=None para marcar como activa
            db.dev_sessions.insert_one({
                "inicio": datetime.now(tz),
                "fin": None,
                "duracion_segundos": None
            })
            st.rerun()

# ------------------ MÓDULO 2: GPT-4o y Cronómetro ------------------

elif seccion == "GPT-4o y Cronómetro":
    st.header("GPT-4o y Cronómetro")
    st.info("Aquí va toda la lógica de detección con OpenAI, título, autor, cronómetro específico de lectura, registro de página, etc. (pendiente implementar)")

# ------------------ MÓDULO 3: Mapa en vivo ------------------

elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo")

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

    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

# ------------------ MÓDULO 4: Historial de lecturas ------------------

elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas")
    st.info("Aquí irá el historial completo de lecturas (pendiente implementar).")
