import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from bson.objectid import ObjectId
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
lecturas_col = db["lecturas"]  # UNA sola colección para todos los libros

# Zona horaria
tz = pytz.timezone("America/Bogota")

def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        from dateutil.parser import parse
        dt = parse(dt)
    # Aseguramos tz-aware
    if dt.tzinfo is None:
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz)

# Estado base sesión
for key, default in {
    "dev_start": None,
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": 1,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0,
    "lectura_id": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Auto refresh para cronómetro (1s)
st_autorefresh(interval=1000, key="cronometro_refresh")

# ---------- Funciones DB ----------
def iniciar_lectura(titulo, paginas_totales, foto_b64=None, pagina_inicial=1):
    doc = {
        "titulo": titulo,
        "inicio": datetime.now(tz),
        "fin": None,
        "duracion_segundos": None,
        "paginas_totales": paginas_totales,
        "pagina_final": None,
        "ruta": [],
        "distancia_km": 0,
        "foto_base64": foto_b64,
        "pagina_inicial": pagina_inicial,
    }
    res = lecturas_col.insert_one(doc)
    st.session_state["lectura_id"] = res.inserted_id
    st.session_state["lectura_inicio"] = doc["inicio"]
    return res.inserted_id

def actualizar_lectura(pagina_actual, ruta, distancia_km, duracion_segundos=None):
    if st.session_state.get("lectura_id") is None:
        return
    update = {
        "pagina_final": pagina_actual,
        "ruta": ruta,
        "distancia_km": distancia_km,
    }
    if duracion_segundos is not None:
        update["duracion_segundos"] = duracion_segundos
    lecturas_col.update_one(
        {"_id": ObjectId(st.session_state["lectura_id"])},
        {"$set": update}
    )

def finalizar_lectura(duracion_segundos):
    if st.session_state.get("lectura_id") is None:
        return
    lecturas_col.update_one(
        {"_id": ObjectId(st.session_state["lectura_id"])},
        {"$set": {
            "fin": datetime.now(tz),
            "duracion_segundos": duracion_segundos,
            "pagina_final": st.session_state.get("lectura_pagina_actual", 1),
            "ruta": st.session_state.get("ruta_actual", []),
            "distancia_km": st.session_state.get("ruta_distancia_km", 0),
        }}
    )
    # limpiar estado
    for key in ["lectura_titulo", "lectura_paginas", "lectura_pagina_actual",
                "lectura_inicio", "lectura_en_curso", "ruta_actual",
                "ruta_distancia_km", "lectura_id"]:
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
    # escuchamos mensajes enviados desde el iframe/html
    mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => {return event.data});", key="js_eval_listener")
except ImportError:
    mensaje_js = None
    st.warning("Módulo 'streamlit_js_eval' no instalado: no se podrá recibir ruta desde mapa.")

if mensaje_js and isinstance(mensaje_js, dict) and mensaje_js.get("type") == "guardar_ruta":
    # mensaje_js["ruta"] es el JSON con la ruta (string)
    ruta = json.loads(mensaje_js["ruta"])
    st.session_state["ruta_actual"] = ruta

    distancia_total = 0
    for i in range(len(ruta)-1):
        p1 = ruta[i]
        p2 = ruta[i+1]
        distancia_total += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])

    st.session_state["ruta_distancia_km"] = distancia_total

    if st.session_state["lectura_en_curso"]:
        segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
        actualizar_lectura(
            st.session_state["lectura_pagina_actual"],
            st.session_state["ruta_actual"],
            st.session_state["ruta_distancia_km"],
        )
        finalizar_lectura(segundos_transcurridos)

    st.success(f"Ruta guardada. Distancia total: {distancia_total:.2f} km")
    st.experimental_rerun()

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

# ---------- MÓDULO 1: Tiempo de desarrollo ----------
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo")

    sesion_activa = dev_col.find_one({"fin": None})

    if sesion_activa:
        start_time = to_datetime_local(sesion_activa["inicio"])
        segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
        duracion = str(timedelta(seconds=segundos_transcurridos))

        st.success(f"🧠 Desarrollo en curso desde las {start_time.strftime('%H:%M:%S')}")
        st.markdown(f"### ⏱️ Duración: {duracion}")

        if st.button("⏹️ Finalizar desarrollo"):
            dev_col.update_one(
                {"_id": sesion_activa["_id"]},
                {"$set": {"fin": datetime.now(tz), "duracion_segundos": segundos_transcurridos}}
            )
            st.session_state["dev_finalizado_msg"] = f"✅ Desarrollo finalizado. Duración: {str(timedelta(seconds=segundos_transcurridos))}"
            st.experimental_rerun()

    else:
        if st.button("🟢 Iniciar desarrollo"):
            dev_col.insert_one({
                "inicio": datetime.now(tz),
                "fin": None,
                "duracion_segundos": None
            })
            st.experimental_rerun()

    if "dev_finalizado_msg" in st.session_state:
        st.success(st.session_state.pop("dev_finalizado_msg"))

# ---------- MÓDULO 2: Lectura con Cronómetro ----------
elif seccion == "Lectura con Cronómetro":
    st.header("Lectura con Cronómetro")

    # Restaurar lectura en curso desde Mongo si la sesión está vacía
    if not st.session_state["lectura_en_curso"]:
        lectura_db = lecturas_col.find_one({"fin": None})
        if lectura_db:
            st.session_state["lectura_en_curso"] = True
            st.session_state["lectura_titulo"] = lectura_db.get("titulo")
            st.session_state["lectura_inicio"] = lectura_db.get("inicio")
            st.session_state["lectura_paginas"] = lectura_db.get("paginas_totales")
            st.session_state["lectura_pagina_actual"] = lectura_db.get("pagina_final") or lectura_db.get("pagina_inicial", 1)
            st.session_state["ruta_actual"] = lectura_db.get("ruta", [])
            st.session_state["ruta_distancia_km"] = lectura_db.get("distancia_km", 0)
            st.session_state["lectura_id"] = lectura_db.get("_id")

    if st.session_state["lectura_en_curso"]:
        # calcular duración desde lectura_inicio guardada en DB
        start_time = to_datetime_local(st.session_state["lectura_inicio"])
        segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
        duracion = str(timedelta(seconds=segundos_transcurridos))

        st.success(f"📖 Lectura en curso: {st.session_state.get('lectura_titulo', '—')}")
        st.markdown(f"### ⏱️ Duración: {duracion}")
        st.markdown(f"Página actual: {st.session_state.get('lectura_pagina_actual', 1)} de {st.session_state.get('lectura_paginas', '?')}")

        # botones de control
        col1, col2 = st.columns(2)
        with col1:
            if st.button("⏹️ Finalizar lectura"):
                # actualizar guardado y finalizar
                segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
                actualizar_lectura(
                    st.session_state.get("lectura_pagina_actual", 1),
                    st.session_state.get("ruta_actual", []),
                    st.session_state.get("ruta_distancia_km", 0),
                )
                finalizar_lectura(segundos_transcurridos)
                st.session_state["lectura_finalizada_msg"] = f"✅ Lectura finalizada. Duración: {str(timedelta(seconds=segundos_transcurridos))}"
                st.experimental_rerun()
        with col2:
            # posibilidad de actualizar página actual manualmente
            nueva_pag = st.number_input("Actualizar página actual:", min_value=1,
                                       max_value=st.session_state.get("lectura_paginas", 10000),
                                       value=st.session_state.get("lectura_pagina_actual", 1),
                                       step=1, key="input_pagina_actual")
            if st.button("Guardar página"):
                st.session_state["lectura_pagina_actual"] = int(nueva_pag)
                # actualizar en DB (sin finalizar)
                segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
                actualizar_lectura(
                    st.session_state["lectura_pagina_actual"],
                    st.session_state.get("ruta_actual", []),
                    st.session_state.get("ruta_distancia_km", 0),
                    duracion_segundos=segundos_transcurridos
                )
                st.success("Página actual guardada.")

    else:
        # Iniciar nueva lectura (o continuar desde historial)
        ya_guardado = st.checkbox("¿Ya tienes este libro guardado en el sistema?", key="checkbox_guardado")
        titulo = st.text_input(
            "Ingresa el título del texto:",
            value=st.session_state.get("lectura_titulo", ""),
            key="lectura_titulo_input"
        )

        if titulo:
            st.session_state["lectura_titulo"] = titulo
            pagina_seleccionada = None

            if ya_guardado:
                # listamos lecturas finalizadas para ese título
                lecturas_guardadas = list(lecturas_col.find({"titulo": titulo, "fin": {"$ne": None}}).sort("inicio", -1))
                if lecturas_guardadas:
                    opciones = [
                        f"Pág. {l.get('pagina_final', '?')} - Inició: {to_datetime_local(l['inicio']).strftime('%Y-%m-%d')}"
                        for l in lecturas_guardadas
                    ]
                    seleccion = st.selectbox("Selecciona la lectura donde la dejaste:", opciones, key="select_lecturas")
                    idx = opciones.index(seleccion)
                    lectura_seleccionada = lecturas_guardadas[idx]
                    pagina_seleccionada = lectura_seleccionada.get("pagina_final", 1)
                    st.markdown(f"Continuar desde página {pagina_seleccionada}.")
                else:
                    st.info("No se encontraron lecturas guardadas para este libro.")

            # si hay historial, proponemos páginas totales
            ultima_lectura = lecturas_col.find_one({"titulo": titulo}, sort=[("inicio", -1)])
            paginas_totales = ultima_lectura.get("paginas_totales") if ultima_lectura else None

            if paginas_totales:
                st.session_state["lectura_paginas"] = paginas_totales
                st.write(f"Páginas totales: {paginas_totales}")
            else:
                paginas_manual = st.number_input(
                    "No se encontró historial. Ingresa número total de páginas:",
                    min_value=1,
                    step=1,
                    value=1,
                    key="paginas_manual_input"
                )
                st.session_state["lectura_paginas"] = paginas_manual
                st.write(f"Páginas totales: {paginas_manual}")

            pagina_inicial = pagina_seleccionada or st.number_input(
                "Página desde donde empiezas la lectura:",
                min_value=1,
                max_value=st.session_state["lectura_paginas"],
                value=st.session_state.get("lectura_pagina_actual", 1),
                step=1,
                key="pagina_inicio_input"
            )
            st.session_state["lectura_pagina_actual"] = int(pagina_inicial)

            if st.button("▶️ Iniciar lectura"):
                # iniciar nueva lectura y persistir inicio en DB
                st.session_state["lectura_titulo"] = titulo
                st.session_state["lectura_inicio"] = datetime.now(tz)
                st.session_state["lectura_en_curso"] = True
                # Creamos un nuevo documento (iniciar_lectura) — no reutilizamos antiguos docs
                iniciar_lectura(titulo, st.session_state["lectura_paginas"], pagina_inicial=st.session_state["lectura_pagina_actual"])
                st.experimental_rerun()

    if "lectura_finalizada_msg" in st.session_state:
        st.success(st.session_state.pop("lectura_finalizada_msg"))

# ---------- MÓDULO 3: Mapa en vivo ----------
elif seccion == "Mapa en vivo":
    st.header("Mapa para registrar ruta en tiempo real")
    render_map_con_dibujo(google_maps_api_key)
    if st.session_state.get("ruta_actual"):
        st.markdown(f"Ruta guardada con {len(st.session_state['ruta_actual'])} puntos.")
        st.markdown(f"Distancia total: {st.session_state['ruta_distancia_km']:.2f} km")

# ---------- MÓDULO 4: Historial de lecturas ----------
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
