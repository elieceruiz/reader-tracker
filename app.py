import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Mapa en Vivo", layout="wide")

# Leer clave de Google Maps desde secrets
GOOGLE_MAPS_API_KEY = st.secrets["google_maps_api_key"]

st.markdown("## 📍 Mapa en vivo con debug de errores")

# HTML + JS para Google Maps
map_html = f"""
<div id="map" style="height:500px; width:100%;"></div>
<div id="status" style="margin-top:10px; font-weight:bold; color:red;"></div>

<script>
function initMap() {{
    if (!navigator.geolocation) {{
        document.getElementById('status').innerText = "⚠️ Geolocalización no soportada por tu navegador";
        return;
    }}
    
    navigator.geolocation.getCurrentPosition(
        function(position) {{
            var myLatLng = {{
                lat: position.coords.latitude,
                lng: position.coords.longitude
            }};

            var map = new google.maps.Map(document.getElementById('map'), {{
                zoom: 15,
                center: myLatLng
            }});

            var marker = new google.maps.Marker({{
                position: myLatLng,
                map: map,
                title: "Ubicación inicial"
            }});

            document.getElementById('status').innerText = "✅ Mapa cargado correctamente.";
        }},
        function(error) {{
            document.getElementById('status').innerText = "❌ Error obteniendo ubicación: " + error.message;
        }}
    );
}}

function gm_authFailure() {{
    document.getElementById('status').innerText = "❌ Error de autenticación con Google Maps API. Verifica la clave y restricciones.";
}}
</script>

<script async defer
    src="https://maps.googleapis.com/maps/api/js?key={GOOGLE_MAPS_API_KEY}&callback=initMap"
    onerror="document.getElementById('status').innerText = '❌ No se pudo cargar el script de Google Maps. Revisa la clave y la conexión.'">
</script>
"""

components.html(map_html, height=600)