from streamlit.components.v1 import html
import streamlit as st

google_maps_api_key = st.secrets.get("google_maps_api_key", "")

def mostrar_mapa():
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style> html, body, #map {{ height: 100%; margin: 0; padding: 0; }} </style>
        <script src="https://maps.googleapis.com/maps/api/js?key={google_maps_api_key}&libraries=geometry"></script>
    </head>
    <body>
        <div id="map" style="height: 400px; width: 100%;"></div>
        <div id="distancia" style="margin-top:6px;font-weight:bold;"></div>

        <script>
            let map;
            let poly;

            function initMap() {{
                map = new google.maps.Map(document.getElementById('map'), {{
                    zoom: 17,
                    center: {{lat: 4.65, lng: -74.05}},
                    mapTypeId: 'roadmap'
                }});

                poly = new google.maps.Polyline({{
                    strokeColor: '#FF0000',
                    strokeOpacity: 1.0,
                    strokeWeight: 3,
                    map: map
                }});

                if (navigator.geolocation) {{
                    navigator.geolocation.watchPosition(pos => {{
                        let latlng = new google.maps.LatLng(pos.coords.latitude, pos.coords.longitude);
                        poly.getPath().push(latlng);
                        let distanciaMetros = google.maps.geometry.spherical.computeLength(poly.getPath());
                        document.getElementById('distancia').innerHTML = 
                            "Distancia: " + (distanciaMetros/1000).toFixed(2) + " km";
                    }}, err => {{
                        console.error(err);
                    }}, {{
                        enableHighAccuracy: true,
                        maximumAge: 1000,
                        timeout: 5000
                    }});
                }} else {{
                    alert("Geolocalización no soportada.");
                }}
            }}

            window.onload = initMap;
        </script>
    </body>
    </html>
    """
    html(html_code, height=450)
