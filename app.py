# app.py
import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from bson.objectid import ObjectId
import json
from math import radians, cos, sin, asin, sqrt
from streamlit_autorefresh import st_autorefresh
from dateutil import parser as dateutil_parser

# -----------------------
# CONFIG
# -----------------------
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# Secrets (poner en secrets.toml / Streamlit secrets)
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key", "")

if not mongo_uri:
    st.error("No se encontró 'mongo_uri' en st.secrets. Añadela y recargá la app.")
    st.stop()

# Conexión a Mongo
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]
lecturas_col = db["lecturas"]

# Zona horaria
tz = pytz.timezone("America/Bogota")

# -----------------------
# Helpers
# -----------------------
def ensure_objectid(x):
    if x is None:
        return None
    if isinstance(x, ObjectId):
        return x
    try:
        return ObjectId(x)
    except Exception:
        return x

def to_datetime_local(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = dateutil_parser.parse(dt)
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz)

def utc_now():
    return datetime.now(tz)

def formatear_tiempo(segundos):
    return str(timedelta(seconds=int(segundos)))

def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# -----------------------
# SESSION STATE defaults
# -----------------------
defaults = {
    # Lectura
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": 1,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0.0,
    "lectura_id": None,
    # Desarrollo
    "dev_en_curso": False,
    "dev_inicio": None,
    "dev_id": None,
    # Flags (botones)
    "_flag_start_dev": False,
    "_flag_stop_dev": False,
    "_flag_start_lectura": False,
    "_flag_stop_lectura": False,
    # Inputs pendientes (populados por widgets antes de on_click)
    "_pending_dev_name": None,
    "_pending_lectura_title": None,
    "_pending_lectura_pages": None,
    "_pending_lectura_page_start": None
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto refresh cada 1s para mostrar cronómetros actualizados
st_autorefresh(interval=1000, key="cronometro_refresh")

# -----------------------
# Recepción de mensaje JS (ruta) - usar streamlit_js_eval si está disponible
# -----------------------
mensaje_js = None
try:
    from streamlit_js_eval import streamlit_js_eval
    mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => { return event.data; });", key="js_eval_listener")
except Exception:
    mensaje_js = None

if mensaje_js and isinstance(mensaje_js, dict) and mensaje_js.get("type") == "guardar_ruta":
    try:
        ruta = json.loads(mensaje_js.get("ruta", "[]"))
    except Exception:
        ruta = []
    st.session_state["ruta_actual"] = ruta
    # calcular distancia
    distancia_total = 0.0
    for i in range(len(ruta) - 1):
        p1 = ruta[i]; p2 = ruta[i+1]
        distancia_total += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
    st.session_state["ruta_distancia_km"] = distancia_total
    st.success(f"Ruta recibida ({distancia_total:.2f} km).")
    # Si hay una lectura activa, pedir que se finalice (marcamos la flag)
    if st.session_state.get("lectura_en_curso"):
        st.session_state["_flag_stop_lectura"] = True

# -----------------------
# DB operations: Lecturas
# -----------------------
def iniciar_lectura_db(titulo, paginas_totales, pagina_inicial=1):
    inicio = utc_now()
    doc = {
        "titulo": titulo,
        "inicio": inicio,
        "fin": None,
        "duracion_segundos": 0,
        "paginas_totales": paginas_totales,
        "pagina_inicial": pagina_inicial,
        "pagina_final": None,
        "ruta": [],
        "distancia_km": 0.0
    }
    res = lecturas_col.insert_one(doc)
    st.session_state.update({
        "lectura_id": res.inserted_id,
        "lectura_inicio": inicio,
        "lectura_en_curso": True,
        "lectura_titulo": titulo,
        "lectura_paginas": paginas_totales,
        "lectura_pagina_actual": pagina_inicial
    })

def actualizar_lectura_db_once():
    if st.session_state.get("lectura_en_curso") and st.session_state.get("lectura_id"):
        segundos = int((utc_now() - to_datetime_local(st.session_state["lectura_inicio"])).total_seconds()) if st.session_state.get("lectura_inicio") else 0
        lid = ensure_objectid(st.session_state["lectura_id"])
        if lid:
            lecturas_col.update_one({"_id": lid}, {"$set": {
                "pagina_final": st.session_state.get("lectura_pagina_actual"),
                "ruta": st.session_state.get("ruta_actual", []),
                "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
                "duracion_segundos": segundos
            }})

def finalizar_lectura_db_and_state():
    lid = ensure_objectid(st.session_state.get("lectura_id"))
    if lid:
        segundos = int((utc_now() - to_datetime_local(st.session_state["lectura_inicio"])).total_seconds())
        lecturas_col.update_one({"_id": lid}, {"$set": {
            "fin": utc_now(),
            "pagina_final": st.session_state.get("lectura_pagina_actual", 1),
            "ruta": st.session_state.get("ruta_actual", []),
            "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
            "duracion_segundos": segundos
        }})
    # limpiar estado
    st.session_state.update({
        "lectura_titulo": None,
        "lectura_paginas": None,
        "lectura_pagina_actual": 1,
        "lectura_inicio": None,
        "lectura_en_curso": False,
        "ruta_actual": [],
        "ruta_distancia_km": 0.0,
        "lectura_id": None
    })

# -----------------------
# DB operations: Desarrollo
# -----------------------
def iniciar_desarrollo_db(nombre_proyecto):
    inicio = utc_now()
    doc = {"proyecto": nombre_proyecto, "inicio": inicio, "fin": None, "duracion_segundos": 0}
    res = dev_col.insert_one(doc)
    st.session_state.update({
        "dev_en_curso": True,
        "dev_inicio": inicio,
        "dev_id": res.inserted_id
    })

def actualizar_desarrollo_db_once():
    if st.session_state.get("dev_en_curso") and st.session_state.get("dev_id"):
        segundos = int((utc_now() - to_datetime_local(st.session_state["dev_inicio"])).total_seconds()) if st.session_state.get("dev_inicio") else 0
        did = ensure_objectid(st.session_state["dev_id"])
        if did:
            dev_col.update_one({"_id": did}, {"$set": {"duracion_segundos": segundos}})

def finalizar_desarrollo_db_and_state():
    did = ensure_objectid(st.session_state.get("dev_id"))
    if did:
        segundos = int((utc_now() - to_datetime_local(st.session_state["dev_inicio"])).total_seconds())
        dev_col.update_one({"_id": did}, {"$set": {"fin": utc_now(), "duracion_segundos": segundos}})
    st.session_state.update({
        "dev_en_curso": False,
        "dev_inicio": None,
        "dev_id": None
    })

# -----------------------
# Callbacks: solo marcan flags / guardan inputs
# -----------------------
def cb_mark_start_dev():
    st.session_state["_flag_start_dev"] = True
    st.session_state["_pending_dev_name"] = st.session_state.get("input_proyecto", "Trabajo")

def cb_mark_stop_dev():
    st.session_state["_flag_stop_dev"] = True

def cb_mark_start_lectura():
    st.session_state["_flag_start_lectura"] = True
    st.session_state["_pending_lectura_title"] = st.session_state.get("input_lectura_titulo", "Sin título")
    st.session_state["_pending_lectura_pages"] = st.session_state.get("input_lectura_paginas", 1)
    st.session_state["_pending_lectura_page_start"] = st.session_state.get("input_lectura_pagina_inicio", 1)

def cb_mark_stop_lectura():
    st.session_state["_flag_stop_lectura"] = True

# -----------------------
# Procesar flags (SECCION CRÍTICA: se ejecuta antes de mostrar la UI que depende de estado)
# -----------------------
# Iniciar desarrollo
if st.session_state.get("_flag_start_dev"):
    nombre = st.session_state.get("_pending_dev_name") or "Trabajo"
    iniciar_desarrollo_db(nombre)
    st.session_state["_flag_start_dev"] = False
    st.session_state["_pending_dev_name"] = None

# Finalizar desarrollo
if st.session_state.get("_flag_stop_dev"):
    finalizar_desarrollo_db_and_state()
    st.session_state["_flag_stop_dev"] = False

# Iniciar lectura
if st.session_state.get("_flag_start_lectura"):
    titulo = st.session_state.get("_pending_lectura_title") or "Sin título"
    paginas = int(st.session_state.get("_pending_lectura_pages") or 1)
    pagina_inicial = int(st.session_state.get("_pending_lectura_page_start") or 1)
    iniciar_lectura_db(titulo, paginas, pagina_inicial)
    st.session_state["_flag_start_lectura"] = False
    st.session_state["_pending_lectura_title"] = None
    st.session_state["_pending_lectura_pages"] = None
    st.session_state["_pending_lectura_page_start"] = None

# Finalizar lectura
if st.session_state.get("_flag_stop_lectura"):
    finalizar_lectura_db_and_state()
    st.session_state["_flag_stop_lectura"] = False

# -----------------------
# Auto-update DB mientras hay sesiones activas (se ejecuta cada run, gracias a st_autorefresh)
# -----------------------
if st.session_state.get("dev_en_curso"):
    try:
        actualizar_desarrollo_db_once()
    except Exception as e:
        st.error(f"Error actualizando desarrollo: {e}")

if st.session_state.get("lectura_en_curso"):
    try:
        actualizar_lectura_db_once()
    except Exception as e:
        st.error(f"Error actualizando lectura: {e}")

# -----------------------
# Mapa HTML/JS (render)
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
        <div style="position:absolute;top:10px;left:10px;background:white;padding:8px;z-index:5;border-radius:6px;box-shadow:0 2px 6px rgba(0,0,0,0.2);">
            <button onclick="finalizarLectura()">Finalizar lectura</button>
            <div id="distancia" style="margin-top:6px;"></div>
        </div>

        <script>
            let map;
            let poly;
            let path = [];
            let watchId;

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
                    navigator.geolocation.getCurrentPosition(pos => {{
                        let latlng = new google.maps.LatLng(pos.coords.latitude, pos.coords.longitude);
                        map.setCenter(latlng);
                        poly.getPath().push(latlng);
                        path.push({{lat: pos.coords.latitude, lng: pos.coords.longitude}});
                        actualizarDistancia();
                    }}, err => {{
                        console.error(err);
                    }}, {{
                        enableHighAccuracy: true,
                        maximumAge: 1000,
                        timeout: 5000
                    }});

                    watchId = navigator.geolocation.watchPosition(pos => {{
                        let latlng = new google.maps.LatLng(pos.coords.latitude, pos.coords.longitude);
                        poly.getPath().push(latlng);
                        path.push({{lat: pos.coords.latitude, lng: pos.coords.longitude}});
                        actualizarDistancia();
                    }}, err => {{
                        console.error(err);
                    }}, {{
                        enableHighAccuracy: true,
                        maximumAge: 1000,
                        timeout: 5000
                    }});
                }} else {{
                    alert("Geolocalización no soportada por tu navegador.");
                }}
            }}

            function actualizarDistancia() {{
                let distanciaMetros = google.maps.geometry.spherical.computeLength(poly.getPath());
                let km = (distanciaMetros / 1000).toFixed(2);
                document.getElementById('distancia').innerHTML = "Distancia recorrida: " + km + " km";
            }}

            function finalizarLectura() {{
                if(watchId) {{
                    navigator.geolocation.clearWatch(watchId);
                }}
                const rutaJson = JSON.stringify(path);
                window.parent.postMessage({{type: "guardar_ruta", ruta: rutaJson}}, "*");
                alert("Ruta enviada al servidor.");
            }}

            window.onload = initMap;
        </script>
    </body>
    </html>
    """
    html(html_code, height=600)

# -----------------------
# APP LAYOUT: selector de sección
# -----------------------
seccion = st.selectbox("Selecciona una sección:",
                       ["Tiempo de desarrollo", "Lectura con Cronómetro", "Mapa en vivo", "Historial de lecturas"])

# -----------------------
# MÓDULO 1: Tiempo de desarrollo
# -----------------------
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo")

    # Restaurar sesión en curso desde DB solo si no tenemos ya dev_en_curso
    if not st.session_state.get("dev_en_curso"):
        doc = dev_col.find_one({"fin": None}, sort=[("inicio", -1)])
        if doc:
            st.session_state["dev_en_curso"] = True
            st.session_state["dev_inicio"] = doc["inicio"]
            st.session_state["dev_id"] = doc["_id"]

    if st.session_state.get("dev_en_curso"):
        inicio_local = to_datetime_local(st.session_state["dev_inicio"])
        segundos = int((utc_now() - inicio_local).total_seconds())
        st.success(f"🧠 Desarrollo en curso (desde {inicio_local.strftime('%Y-%m-%d %H:%M:%S')})")
        st.markdown(f"### ⏱️ Duración: {formatear_tiempo(segundos)}")
        st.button("⏹️ Finalizar desarrollo", on_click=cb_mark_stop_dev)
    else:
        st.text_input("Nombre del proyecto / tarea", key="input_proyecto")
        st.button("🟢 Iniciar desarrollo", on_click=cb_mark_start_dev)

    st.markdown("---")
    st.subheader("Historial (Desarrollos)")
    rows = list(dev_col.find().sort("inicio", -1).limit(200))
    if rows:
        for r in rows:
            inicio = to_datetime_local(r["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
            if r.get("fin"):
                dur = formatear_tiempo(r.get("duracion_segundos", 0))
                st.write(f"**{r.get('proyecto','-')}** | {inicio} | ⏱ {dur}")
            else:
                st.write(f"**{r.get('proyecto','-')}** | {inicio} | ⏳ En curso")
    else:
        st.info("No hay registros de desarrollo.")

# -----------------------
# MÓDULO 2: Lectura con Cronómetro
# -----------------------
elif seccion == "Lectura con Cronómetro":
    st.header("Lectura con Cronómetro")

    # Restaurar lectura en curso si no está en session_state
    if not st.session_state.get("lectura_en_curso"):
        doc = lecturas_col.find_one({"fin": None}, sort=[("inicio", -1)])
        if doc:
            st.session_state["lectura_en_curso"] = True
            st.session_state["lectura_inicio"] = doc["inicio"]
            st.session_state["lectura_id"] = doc["_id"]
            st.session_state["lectura_titulo"] = doc.get("titulo")
            st.session_state["lectura_paginas"] = doc.get("paginas_totales")
            st.session_state["lectura_pagina_actual"] = doc.get("pagina_final") or doc.get("pagina_inicial", 1)
            st.session_state["ruta_actual"] = doc.get("ruta", [])
            st.session_state["ruta_distancia_km"] = doc.get("distancia_km", 0.0)

    if st.session_state.get("lectura_en_curso"):
        inicio_local = to_datetime_local(st.session_state["lectura_inicio"])
        segundos = int((utc_now() - inicio_local).total_seconds())
        st.success(f"📖 {st.session_state.get('lectura_titulo','—')}")
        st.markdown(f"### ⏱️ Duración: {formatear_tiempo(segundos)}")

        st.number_input("Página actual:", min_value=1,
                        max_value=st.session_state.get("lectura_paginas", 99999),
                        value=st.session_state.get("lectura_pagina_actual", 1),
                        key="lectura_pagina_actual")
        st.markdown(f"Distancia registrada: {st.session_state.get('ruta_distancia_km',0.0):.2f} km")
        st.button("⏹️ Finalizar lectura", on_click=cb_mark_stop_lectura)
    else:
        st.text_input("Ingresa el título del texto:", key="input_lectura_titulo")
        st.number_input("Páginas totales:", min_value=1, value=1, key="input_lectura_paginas")
        st.number_input("Página desde donde empiezas la lectura:", min_value=1, value=1, key="input_lectura_pagina_inicio")
        st.button("▶️ Iniciar lectura", on_click=cb_mark_start_lectura)

# -----------------------
# MÓDULO 3: Mapa en vivo
# -----------------------
elif seccion == "Mapa en vivo":
    st.header("Mapa para registrar ruta en tiempo real")
    if not google_maps_api_key:
        st.error("No se encontró 'google_maps_api_key' en st.secrets. El mapa no se mostrará.")
    else:
        render_map_con_dibujo(google_maps_api_key)

    if st.session_state.get("ruta_actual"):
        st.markdown(f"Ruta guardada con {len(st.session_state['ruta_actual'])} puntos — distancia: {st.session_state['ruta_distancia_km']:.2f} km")

# -----------------------
# MÓDULO 4: Historial de lecturas
# -----------------------
elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas por título")
    titulo_hist = st.text_input("Ingresa el título para consultar historial:", key="historial_titulo")
    if titulo_hist:
        lecturas = list(lecturas_col.find({"titulo": titulo_hist}).sort("inicio", -1))
        if not lecturas:
            st.info("No hay registros de lecturas para este texto.")
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
