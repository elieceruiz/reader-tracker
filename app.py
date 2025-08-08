import streamlit as st
import streamlit.components.v1 as components
import json

st.set_page_config(page_title="Tracker en Vivo", layout="wide")

GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]

st.markdown("## 🚶 Tracker de ruta en vivo (cada 5 segundos)")

# HTML + JS
map_html = f"""
<div id="map" style="height:500px; width:100%;"></div>
<div id="status" style="margin-top:10px; font-weight:bold;"></div>
<button onclick="stopTracking()" style="margin-top:15px; padding:10px;">⏹ Parar y enviar datos</button>

<script>
let map;
let marker;
let pathCoords = [];
let polyline;
let watchId;
let totalDistance = 0;

function initMap() {{
    map = new google.maps.Map(document.getElementById('map'), {{
        zoom: 15,
        center: {{ lat: 0, lng: 0 }}
    }});

    polyline = new google.maps.Polyline({{
        map: map,
        path: [],
        geodesic: true,
        strokeColor: '#FF0000',
        strokeOpacity: 1.0,
        strokeWeight: 2
    }});

    if (!navigator.geolocation) {{
        document.getElementById('status').innerText = "⚠️ Geolocalización no soportada.";
        return;
    }}

    watchId = navigator.geolocation.watchPosition(
        updatePosition,
        (err) => {{
            document.getElementById('status').innerText = "❌ Error: " + err.message;
        }},
        {{
            enableHighAccuracy: true,
            maximumAge: 0,
            timeout: 10000
        }}
    );
}}

function updatePosition(position) {{
    let lat = position.coords.latitude;
    let lng = position.coords.longitude;
    let currentPos = new google.maps.LatLng(lat, lng);

    if (pathCoords.length > 0) {{
        totalDistance += google.maps.geometry.spherical.computeDistanceBetween(
            pathCoords[pathCoords.length - 1],
            currentPos
        );
    }}

    pathCoords.push(currentPos);
    polyline.setPath(pathCoords);

    if (!marker) {{
        marker = new google.maps.Marker({{
            position: currentPos,
            map: map,
            title: "Ubicación actual"
        }});
        map.setCenter(currentPos);
    }} else {{
        marker.setPosition(currentPos);
    }}

    document.getElementById('status').innerText = 
        "📍 Última posición: " + lat.toFixed(5) + ", " + lng.toFixed(5) +
        " | Distancia total: " + (totalDistance/1000).toFixed(2) + " km";
}}

function stopTracking() {{
    if (watchId) {{
        navigator.geolocation.clearWatch(watchId);
    }}

    // Convertir coordenadas a array simple para enviar a Python
    let coordsToSend = pathCoords.map(p => [p.lat(), p.lng()]);
    let payload = {{
        coords: coordsToSend,
        distance_km: (totalDistance/1000).toFixed(3)
    }};

    // Enviar datos a Streamlit
    window.parent.postMessage({{isStreamlitMessage: true, type: "TRACK_DATA", data: payload}}, "*");
}}

function gm_authFailure() {{
    document.getElementById('status').innerText = "❌ Error de autenticación con Google Maps API.";
}}
</script>

<script async defer
    src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&libraries=geometry&callback=initMap">
</script>
"""

# Render del mapa
components.html(map_html, height=600)

# Receptor del postMessage desde JS
from streamlit_javascript import st_javascript

tracking_data = st_javascript("""
    new Promise((resolve) => {
        window.addEventListener("message", (event) => {
            if (event.data && event.data.type === "TRACK_DATA") {
                resolve(event.data.data);
            }
        });
    })
""")

if tracking_data:
    st.success("✅ Datos recibidos desde el navegador")
    st.json(tracking_data)
    # Aquí puedes guardar en MongoDB:
    # mongo_collection.insert_one(tracking_data)