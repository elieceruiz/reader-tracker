import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
import json
from math import radians, cos, sin, asin, sqrt
from streamlit_autorefresh import st_autorefresh

# Configuración
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# Variables de entorno / Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key")

# Conexión a Mongo
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]

# Zona horaria
tz = pytz.timezone("America/Bogota")

def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        from dateutil.parser import parse
        dt = parse(dt)
    return dt.astimezone(tz)

# Estado base sesión
for key, default in {
    "dev_start": None,
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": None,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0,
    "cronometro_segundos": 0,
    "cronometro_running": False,
    "lectura_id": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Auto refresh para cronómetro
st_autorefresh(interval=1000, key="cronometro_refresh")

def coleccion_por_titulo(titulo):
    nombre = titulo.lower().replace(" ", "_")
    return db[nombre]

def iniciar_lectura(titulo, paginas_totales, foto_b64=None):
    col = coleccion_por_titulo(titulo)
    doc = {
        "inicio": datetime.now(tz),
        "fin": None,
        "duracion_segundos": None,
        "paginas_totales": paginas_totales,
        "pagina_final": None,
        "ruta": [],
        "distancia_km": 0,
        "foto_base64": foto_b64,
    }
    res = col.insert_one(doc)
    st.session_state["lectura_id"] = res.inserted_id

def actualizar_lectura(pagina_actual, ruta, distancia_km):
    col = coleccion_por_titulo(st.session_state["lectura_titulo"])
    col.update_one(
        {"_id": st.session_state["lectura_id"]},
        {
            "$set": {
                "pagina_final": pagina_actual,
                "ruta": ruta,
                "distancia_km": distancia_km,
                "duracion_segundos": st.session_state["cronometro_segundos"],
            }
        },
    )

def finalizar_lectura():
    col = coleccion_por_titulo(st.session_state["lectura_titulo"])
    col.update_one(
        {"_id": st.session_state["lectura_id"]},
        {"$set": {"fin": datetime.now(tz)}},
    )
    for key in ["lectura_titulo", "lectura_paginas", "lectura_pagina_actual",
                "lectura_inicio", "lectura_en_curso", "ruta_actual",
                "ruta_distancia_km", "cronometro_segundos",
                "cronometro_running", "lectura_id"]:
        st.session_state[key] = None if key != "lectura_pagina_actual" else 0

# --- Función para calcular distancia entre puntos geográficos
def haversine(lat1, lon1, lat2, lon2):
    R = 6371  # km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

# --- Render del mapa para registrar ruta en vivo ---
def render_map_con_dibujo(api_key):
    from streamlit.components.v1 import html
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style> html, body, #map {{ height: 100%; margin: 0; padding: 0; }} </style>
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=geometry"></script>
    </head>
    <body>
        <div id="map" style="height: 100vh; width: 100%;"></div>
        <div style="position:absolute;top:10px;left:10px;background:white;padding:8px;z-index:5;">
            <button onclick="finalizarLectura()">Finalizar lectura</button>
            <div id="distancia"></div>
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
                alert("Lectura finalizada, ruta guardada.");
            }}

            window.onload = initMap;
        </script>
    </body>
    </html>
    """
    html(html_code, height=600)

# Escuchar mensaje JS (ruta dibujada)
try:
    from streamlit_js_eval import streamlit_js_eval
    mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => {return event.data});", key="js_eval_listener")
except ImportError:
    mensaje_js = None
    st.warning("Módulo 'streamlit_js_eval' no instalado: no se podrá recibir ruta desde mapa.")

if mensaje_js and isinstance(mensaje_js, dict) and "type" in mensaje_js and mensaje_js["type"] == "guardar_ruta":
    ruta = json.loads(mensaje_js["ruta"])
    st.session_state["ruta_actual"] = ruta

    distancia_total = 0
    for i in range(len(ruta)-1):
        p1 = ruta[i]
        p2 = ruta[i+1]
        distancia_total += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])

    st.session_state["ruta_distancia_km"] = distancia_total
    if st.session_state["lectura_en_curso"]:
        actualizar_lectura(
            st.session_state["lectura_pagina_actual"],
            st.session_state["ruta_actual"],
            st.session_state["ruta_distancia_km"]
        )
    st.success(f"Ruta guardada. Distancia total: {distancia_total:.2f} km")
    finalizar_lectura()
    st.rerun()

# --- Módulos de la App ---
seccion = st.selectbox(
    "Selecciona una sección:",
    [
        "Tiempo de desarrollo",
        "Lectura con Cronómetro",
        "Mapa en vivo",
        "Historial de lecturas"
    ]
)

# --- MÓDULO 1: Tiempo de desarrollo ---
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo")

    sesion_activa = dev_col.find_one({"fin": None})

    if sesion_activa:
        start_time = to_datetime_local(sesion_activa["inicio"])
        if sesion_activa.get("fin"):
            duracion = str(timedelta(seconds=sesion_activa["duracion_segundos"]))
        else:
            segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
            duracion = str(timedelta(seconds=segundos_transcurridos))

        st.success(f"🧠 Desarrollo en curso desde las {start_time.strftime('%H:%M:%S')}")
        st.markdown(f"### ⏱️ Duración: {duracion}")

        if st.button("⏹️ Finalizar desarrollo"):
            segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
            dev_col.update_one(
                {"_id": sesion_activa["_id"]},
                {"$set": {"fin": datetime.now(tz), "duracion_segundos": segundos_transcurridos}}
            )
            st.session_state["dev_finalizado_msg"] = f"✅ Desarrollo finalizado. Duración: {str(timedelta(seconds=segundos_transcurridos))}"
            st.rerun()

    else:
        if st.button("🟢 Iniciar desarrollo"):
            dev_col.insert_one({
                "inicio": datetime.now(tz),
                "fin": None,
                "duracion_segundos": None
            })
            st.rerun()

    if "dev_finalizado_msg" in st.session_state:
        st.success(st.session_state.pop("dev_finalizado_msg"))

# --- MÓDULO 2: Lectura con Cronómetro ---
elif seccion == "Lectura con Cronómetro":
    st.header("Lectura con Cronómetro")

    if st.session_state["lectura_en_curso"]:
        if st.session_state.get("lectura_id"):
            col = coleccion_por_titulo(st.session_state["lectura_titulo"])
            lectura_actual = col.find_one({"_id": st.session_state["lectura_id"]})
        else:
            lectura_actual = None

        if lectura_actual and lectura_actual.get("fin"):
            duracion = str(timedelta(seconds=lectura_actual["duracion_segundos"]))
        else:
            segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
            duracion = str(timedelta(seconds=segundos_transcurridos))

        st.success(f"📖 Lectura en curso: {st.session_state['lectura_titulo']}")
        st.markdown(f"### ⏱️ Duración: {duracion}")
        st.markdown(f"Página actual: {st.session_state['lectura_pagina_actual']} de {st.session_state['lectura_paginas']}")

        if st.button("⏹️ Finalizar lectura"):
            segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
            if st.session_state.get("lectura_id"):
                actualizar_lectura(
                    st.session_state["lectura_pagina_actual"],
                    st.session_state["ruta_actual"],
                    st.session_state["ruta_distancia_km"]
                )
                col = coleccion_por_titulo(st.session_state["lectura_titulo"])
                col.update_one(
                    {"_id": st.session_state["lectura_id"]},
                    {"$set": {
                        "fin": datetime.now(tz),
                        "duracion_segundos": segundos_transcurridos
                    }}
                )

            st.session_state["lectura_en_curso"] = False
            st.session_state["lectura_finalizada_msg"] = f"✅ Lectura finalizada. Duración: {str(timedelta(seconds=segundos_transcurridos))}"
            st.rerun()

    else:
        ya_guardado = st.checkbox("¿Ya tienes este libro guardado en el sistema?", key="checkbox_guardado")
        titulo = st.text_input(
            "Ingresa el título del texto:",
            value=st.session_state.get("lectura_titulo", ""),
            key="lectura_titulo"
        )

        if titulo:
            col = coleccion_por_titulo(titulo)
            pagina_seleccionada = None
            lectura_seleccionada_id = None

            if ya_guardado:
                lecturas_guardadas = list(col.find({"fin": {"$ne": None}}))
                if lecturas_guardadas:
                    lecturas_guardadas.sort(key=lambda x: (x.get("pagina_final", 0), x.get("inicio")), reverse=False)
                    opciones = [
                        f"Pág. {l.get('pagina_final', '?')} - Inició: {to_datetime_local(l['inicio']).strftime('%Y-%m-%d')}"
                        for l in lecturas_guardadas
                    ]
                    seleccion = st.selectbox("Selecciona la lectura donde la dejaste:", opciones, key="select_lecturas")
                    index = opciones.index(seleccion)
                    lectura_seleccionada = lecturas_guardadas[index]
                    pagina_seleccionada = lectura_seleccionada.get("pagina_final", 1)
                    lectura_seleccionada_id = lectura_seleccionada["_id"]
                else:
                    st.info("No se encontraron lecturas guardadas para este libro.")

            if not ya_guardado:
                ultima_lectura = col.find_one(sort=[("inicio", -1)])
                paginas_totales = ultima_lectura.get("paginas_totales") if ultima_lectura else None
            else:
                paginas_totales = None

            if paginas_totales is not None:
                st.session_state["lectura_paginas"] = paginas_totales
                st.write(f"Páginas totales: {paginas_totales}")
            else:
                paginas_manual = st.number_input(
                    "No se encontró historial. Ingresa número total de páginas:",
                    min_value=1,
                    step=1,
                    value=1,
                    key="paginas_manual"
                )
                st.session_state["lectura_paginas"] = paginas_manual
                st.write(f"Páginas totales: {paginas_manual}")

            pagina_inicial = pagina_seleccionada or st.number_input(
                "Página desde donde empiezas la lectura:",
                min_value=1,
                max_value=st.session_state["lectura_paginas"],
                value=st.session_state.get("lectura_pagina_actual", 1),
                step=1,
                key="pagina_inicio"
            )
            st.session_state["lectura_pagina_actual"] = pagina_inicial

            if st.button("▶️ Iniciar lectura"):
                st.session_state["lectura_inicio"] = datetime.now(tz)
                st.session_state["lectura_en_curso"] = True
                if lectura_seleccionada_id:
                    st.session_state["lectura_id"] = lectura_seleccionada_id
                else:
                    iniciar_lectura(st.session_state["lectura_titulo"], st.session_state["lectura_paginas"])
                st.rerun()

    if "lectura_finalizada_msg" in st.session_state:
        st.success(st.session_state.pop("lectura_finalizada_msg"))

# --- MÓDULO 3: Mapa en vivo ---
elif seccion == "Mapa en vivo":
    st.header("Mapa para registrar ruta en tiempo real")
    render_map_con_dibujo(google_maps_api_key)
    if st.session_state["ruta_actual"]:
        st.markdown(f"Ruta guardada con {len(st.session_state['ruta_actual'])} puntos.")
        st.markdown(f"Distancia total: {st.session_state['ruta_distancia_km']:.2f} km")

# --- MÓDULO 4: Historial de lecturas ---
elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas por título")
    titulo_hist = st.text_input("Ingresa el título para consultar historial:", key="historial_titulo")
    if titulo_hist:
        col = coleccion_por_titulo(titulo_hist)
        lecturas = list(col.find().sort("inicio", -1))
        if not lecturas:
            st.info("No hay registros de lecturas para este texto.")
        else:
            data = []
            for i, l in enumerate(lecturas):
                inicio = to_datetime_local(l["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
                fin = to_datetime_local(l["fin"]).strftime("%Y-%m-%d %H:%M:%S") if l.get("fin") else "-"
                duracion = str(timedelta(seconds=l.get("duracion_segundos", 0))) if l.get("duracion_segundos") else "-"
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
