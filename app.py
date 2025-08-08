import streamlit as st
import time
from datetime import datetime, timedelta
import pytz
import pymongo
from streamlit.components.v1 import html

# --------- CONFIGURACIÓN -----------
st.set_page_config(page_title="Reader Tracker", layout="wide")

# MongoDB
mongo_uri = st.secrets.get("mongo_uri")
client = pymongo.MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]
historial_col = db["historial_lecturas"]

# Zona horaria
tz = pytz.timezone("America/Bogota")

def to_local(dt):
    return dt.astimezone(tz) if dt.tzinfo else tz.localize(dt)

# Restaurar evento en curso desarrollo
if "dev_running" not in st.session_state:
    st.session_state["dev_running"] = False
if "dev_start_time" not in st.session_state:
    st.session_state["dev_start_time"] = None
if "dev_event_id" not in st.session_state:
    st.session_state["dev_event_id"] = None

if not st.session_state["dev_running"]:
    event = dev_col.find_one({"tipo": "desarrollo", "en_curso": True})
    if event:
        st.session_state["dev_running"] = True
        st.session_state["dev_start_time"] = to_local(event["inicio"])
        st.session_state["dev_event_id"] = event["_id"]

# Función para el mapa
google_maps_api_key = st.secrets.get("google_maps_api_key")

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

# Dropdown con las 4 secciones
seccion = st.selectbox(
    "Selecciona una sección:",
    ["Tiempo de desarrollo", "GPT-4o y Cronómetro", "Mapa en vivo", "Historial de lecturas"]
)

if seccion == "Tiempo de desarrollo":
    st.header("⏱ Tiempo de desarrollo")
    start_button = st.button("🟢 Iniciar desarrollo", disabled=st.session_state["dev_running"])
    stop_button = st.button("⏹️ Finalizar desarrollo", disabled=not st.session_state["dev_running"])

    if start_button:
        start = datetime.now(tz)
        event = {"tipo": "desarrollo", "inicio": start, "en_curso": True}
        res = dev_col.insert_one(event)
        st.session_state["dev_running"] = True
        st.session_state["dev_start_time"] = start
        st.session_state["dev_event_id"] = res.inserted_id

    if stop_button and st.session_state["dev_running"]:
        finish = datetime.now(tz)
        dev_col.update_one(
            {"_id": st.session_state["dev_event_id"]},
            {"$set": {"fin": finish, "en_curso": False}}
        )
        st.session_state["dev_running"] = False
        st.session_state["dev_start_time"] = None
        st.session_state["dev_event_id"] = None
        st.success("✅ Registro finalizado.")

    placeholder = st.empty()
    if st.session_state["dev_running"]:
        while st.session_state["dev_running"]:
            elapsed = datetime.now(tz) - st.session_state["dev_start_time"]
            elapsed_str = str(timedelta(seconds=int(elapsed.total_seconds())))
            placeholder.markdown(f"### ⏱ Tiempo transcurrido: {elapsed_str}")
            time.sleep(1)
    else:
        st.info("Presiona 'Iniciar desarrollo' para comenzar el cronómetro.")

elif seccion == "GPT-4o y Cronómetro":
    st.header("Sección GPT-4o y Cronómetro")
    st.info("Aquí irá todo lo relacionado a GPT-4o, detección de título, autor y cronómetro (pendiente implementar).")

elif seccion == "Mapa en vivo":
    st.header("Sección Mapa en vivo")
    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas")
    st.info("Aquí irá el historial de lecturas (pendiente implementar).")
    registros = list(historial_col.find().sort("timestamp", -1))
    if registros:
        data = []
        total = len(registros)
        for i, reg in enumerate(registros):
            fecha = to_local(reg["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            data.append({
                "#": total - i,
                "Título": reg.get("titulo", "Desconocido"),
                "Autor": reg.get("autor", "Desconocido"),
                "Página": reg.get("pagina", "N/A"),
                "Fecha": fecha
            })
        st.dataframe(data, use_container_width=True)
    else:
        st.info("No hay registros de lectura.")
