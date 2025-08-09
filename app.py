import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from math import radians, cos, sin, asin, sqrt
from streamlit_autorefresh import st_autorefresh

# -----------------------
# CONFIG
# -----------------------
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key", "")
if not mongo_uri:
    st.error("No se encontró 'mongo_uri' en st.secrets")
    st.stop()

# Conexión Mongo
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]
lecturas_col = db["lecturas"]

# Zona horaria
tz = pytz.timezone("America/Bogota")

# -----------------------
# Helpers
# -----------------------
def to_datetime_local(dt):
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        from dateutil.parser import parse
        dt = parse(dt)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz)

def formatear_tiempo(segundos):
    return str(timedelta(seconds=int(segundos)))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# -----------------------
# SESSION STATE defaults
# -----------------------
defaults = {
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": 1,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0,
    "lectura_id": None,
    "dev_en_curso": False,
    "dev_inicio": None,
    "dev_id": None
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto refresh
st_autorefresh(interval=1000, key="cronometro_refresh")

# -----------------------
# DB: Lecturas
# -----------------------
def iniciar_lectura(titulo, paginas_totales, pagina_inicial=1):
    inicio = datetime.now(tz)
    doc = {
        "titulo": titulo,
        "inicio": inicio,
        "fin": None,
        "duracion_segundos": 0,
        "paginas_totales": paginas_totales,
        "pagina_final": None,
        "pagina_inicial": pagina_inicial,
        "ruta": [],
        "distancia_km": 0
    }
    res = lecturas_col.insert_one(doc)
    st.session_state.update({
        "lectura_id": res.inserted_id,
        "lectura_inicio": inicio,
        "lectura_en_curso": True,
        "lectura_pagina_actual": pagina_inicial
    })

def actualizar_lectura():
    if st.session_state["lectura_en_curso"] and st.session_state["lectura_id"]:
        segundos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
        lecturas_col.update_one({"_id": ObjectId(st.session_state["lectura_id"])}, {
            "$set": {
                "pagina_final": st.session_state["lectura_pagina_actual"],
                "ruta": st.session_state["ruta_actual"],
                "distancia_km": st.session_state["ruta_distancia_km"],
                "duracion_segundos": segundos
            }
        })

def finalizar_lectura():
    if st.session_state["lectura_id"]:
        segundos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
        lecturas_col.update_one({"_id": ObjectId(st.session_state["lectura_id"])}, {
            "$set": {
                "fin": datetime.now(tz),
                "pagina_final": st.session_state["lectura_pagina_actual"],
                "ruta": st.session_state["ruta_actual"],
                "distancia_km": st.session_state["ruta_distancia_km"],
                "duracion_segundos": segundos
            }
        })
    st.session_state.update({
        "lectura_titulo": None,
        "lectura_paginas": None,
        "lectura_pagina_actual": 1,
        "lectura_inicio": None,
        "lectura_en_curso": False,
        "ruta_actual": [],
        "ruta_distancia_km": 0,
        "lectura_id": None
    })

# -----------------------
# DB: Desarrollo
# -----------------------
def iniciar_desarrollo_db(nombre_proyecto):
    inicio = datetime.now(tz)
    doc = {"proyecto": nombre_proyecto, "inicio": inicio, "fin": None, "duracion_segundos": 0}
    res = dev_col.insert_one(doc)
    st.session_state.update({
        "dev_en_curso": True,
        "dev_inicio": inicio,
        "dev_id": res.inserted_id
    })

def actualizar_desarrollo_db():
    if st.session_state["dev_en_curso"] and st.session_state["dev_id"]:
        segundos = int((datetime.now(tz) - st.session_state["dev_inicio"]).total_seconds())
        dev_col.update_one({"_id": ObjectId(st.session_state["dev_id"])}, {"$set": {"duracion_segundos": segundos}})

def finalizar_desarrollo_db():
    if st.session_state["dev_id"]:
        segundos = int((datetime.now(tz) - st.session_state["dev_inicio"]).total_seconds())
        dev_col.update_one({"_id": ObjectId(st.session_state["dev_id"])}, {
            "$set": {"fin": datetime.now(tz), "duracion_segundos": segundos}
        })
    st.session_state.update({
        "dev_en_curso": False,
        "dev_inicio": None,
        "dev_id": None
    })

# -----------------------
# AUTO UPDATE DURANTE SESIONES ACTIVAS
# -----------------------
if st.session_state["dev_en_curso"]:
    actualizar_desarrollo_db()
if st.session_state["lectura_en_curso"]:
    actualizar_lectura()

# -----------------------
# Mapa HTML/JS
# -----------------------
def render_map_con_dibujo(api_key):
    from streamlit.components.v1 import html
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8" />
        <style> html, body, #map {{ height: 100%; margin: 0; padding: 0; }} </style>
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=geometry"></script>
    </head>
    <body>
        <div id="map" style="height: 100vh; width: 100%;"></div>
        <script>
            let map, poly;
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
                    }}, err => console.error(err), {{enableHighAccuracy:true}});
                }}
            }}
            window.onload = initMap;
        </script>
    </body>
    </html>
    """
    html(html_code, height=600)

# -----------------------
# Layout
# -----------------------
seccion = st.selectbox("Sección:", ["Tiempo de desarrollo", "Lectura con Cronómetro", "Mapa en vivo", "Historial de lecturas"])

# --- Tiempo de desarrollo ---
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo de desarrollo")
    if st.session_state["dev_en_curso"]:
        segundos = int((datetime.now(tz) - st.session_state["dev_inicio"]).total_seconds())
        st.success(f"🧠 En curso desde {st.session_state['dev_inicio'].strftime('%H:%M:%S')}")
        st.markdown(f"### ⏱️ {formatear_tiempo(segundos)}")
        if st.button("⏹️ Finalizar desarrollo"):
            finalizar_desarrollo_db()
            st.success("Finalizado.")
    else:
        proyecto = st.text_input("Proyecto")
        if st.button("🟢 Iniciar desarrollo"):
            iniciar_desarrollo_db(proyecto or "Trabajo")
            st.success("Iniciado.")

# --- Lectura ---
elif seccion == "Lectura con Cronómetro":
    st.header("Lectura con Cronómetro")
    if st.session_state["lectura_en_curso"]:
        segundos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
        st.success(f"📖 {st.session_state['lectura_titulo']}")
        st.markdown(f"### ⏱️ {formatear_tiempo(segundos)}")
        if st.button("⏹️ Finalizar lectura"):
            finalizar_lectura()
            st.success("Lectura finalizada.")
        st.number_input("Página actual:", min_value=1,
                        max_value=st.session_state["lectura_paginas"],
                        value=st.session_state["lectura_pagina_actual"],
                        key="lectura_pagina_actual")
    else:
        titulo = st.text_input("Título")
        paginas = st.number_input("Páginas totales", min_value=1, value=1)
        if st.button("▶️ Iniciar lectura"):
            st.session_state["lectura_titulo"] = titulo
            st.session_state["lectura_paginas"] = paginas
            iniciar_lectura(titulo or "Sin título", paginas)
            st.success("Lectura iniciada.")

# --- Mapa ---
elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo")
    if google_maps_api_key:
        render_map_con_dibujo(google_maps_api_key)
    else:
        st.error("No API key para Google Maps")

# --- Historial ---
elif seccion == "Historial de lecturas":
    st.header("Historial")
    titulo_hist = st.text_input("Título")
    if titulo_hist:
        lecturas = list(lecturas_col.find({"titulo": titulo_hist}).sort("inicio", -1))
        if not lecturas:
            st.info("Sin registros")
        else:
            data = []
            for i, l in enumerate(lecturas):
                inicio = to_datetime_local(l["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
                fin = to_datetime_local(l["fin"]).strftime("%Y-%m-%d %H:%M:%S") if l.get("fin") else "-"
                duracion = formatear_tiempo(l.get("duracion_segundos", 0)) if l.get("duracion_segundos") else "-"
                paginas = f"{l.get('pagina_final', '-')}/{l.get('paginas_totales', '-')}"
                distancia = f"{l.get('distancia_km', 0):.2f} km"
                data.append({
                    "#": len(lecturas)-i,
                    "Inicio": inicio,
                    "Fin": fin,
                    "Duración": duracion,
                    "Páginas": paginas,
                    "Distancia": distancia
                })
            st.dataframe(data)
