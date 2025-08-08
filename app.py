import streamlit as st
import time
import base64
import json
import math
from datetime import datetime
import pytz
import pymongo
import openai
from streamlit_js_eval import streamlit_js_eval
from streamlit.components.v1 import html

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Reader Tracker (dinámico)", layout="wide")

# Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai_api_key = st.secrets.get("openai_api_key")
openai.organization = st.secrets.get("openai_org_id", None)

# Función del mapa (sin rutas ni dibujo, solo seguimiento y marcador)
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

# Dropdown para elegir sección
seccion = st.selectbox(
    "Selecciona una sección:",
    ["GPT-4o y Cronómetro", "Mapa en vivo", "Historial de lecturas"]
)

if seccion == "GPT-4o y Cronómetro":
    st.header("Sección: GPT-4o y Cronómetro")
    st.info("Aquí irá todo lo relacionado a GPT-4o, detección de título, autor y cronómetro (pendiente implementar).")

elif seccion == "Mapa en vivo":
    st.header("Sección: Mapa en vivo")

    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

elif seccion == "Historial de lecturas":
    st.header("Sección: Historial de lecturas")
    st.info("Aquí irá el historial de lecturas (pendiente implementar).")