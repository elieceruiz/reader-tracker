# app.py
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

# Secrets (debe existir en Streamlit secrets)
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key", "")

if not mongo_uri:
    st.error("No se encontró la variable 'mongo_uri' en st.secrets. Añadila y reiniciá la app.")
    st.stop()

# Conexión a Mongo
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]
lecturas_col = db["lecturas"]  # colección unificada para libros

# Zona horaria
tz = pytz.timezone("America/Bogota")

# -----------------------
# Helpers
# -----------------------
def to_datetime_local(dt):
    """Asegura que dt es datetime tz-aware y lo convierte a zona local."""
    if dt is None:
        return None
    if not isinstance(dt, datetime):
        from dateutil.parser import parse
        dt = parse(dt)
    if dt.tzinfo is None:
        # asumimos UTC si vino naive
        dt = pytz.utc.localize(dt)
    return dt.astimezone(tz)

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
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": 1,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0,
    "lectura_id": None,
    # dev module
    "dev_en_curso": False,
    "dev_inicio": None,
    "dev_id": None,
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto refresh para cronómetro (1s)
st_autorefresh(interval=1000, key="cronometro_refresh")

# -----------------------
# DB operations: Lecturas (libros)
# -----------------------
def iniciar_lectura(titulo, paginas_totales, pagina_inicial=1, foto_b64=None):
    doc = {
        "titulo": titulo,
        "inicio": datetime.now(tz),
        "fin": None,
        "duracion_segundos": None,
        "paginas_totales": paginas_totales,
        "pagina_final": None,
        "pagina_inicial": pagina_inicial,
        "ruta": [],
        "distancia_km": 0,
        "foto_base64": foto_b64,
    }
    res = lecturas_col.insert_one(doc)
    st.session_state["lectura_id"] = res.inserted_id
    st.session_state["lectura_inicio"] = doc["inicio"]
    st.session_state["lectura_en_curso"] = True
    st.session_state["lectura_pagina_actual"] = pagina_inicial

def actualizar_lectura(pagina_actual=None, ruta=None, distancia_km=None, duracion_segundos=None):
    if not st.session_state.get("lectura_id"):
        return
    update = {}
    if pagina_actual is not None:
        update["pagina_final"] = pagina_actual
    if ruta is not None:
        update["ruta"] = ruta
    if distancia_km is not None:
        update["distancia_km"] = distancia_km
    if duracion_segundos is not None:
        update["duracion_segundos"] = duracion_segundos
    if update:
        lecturas_col.update_one({"_id": ObjectId(st.session_state["lectura_id"])}, {"$set": update})

def finalizar_lectura(duracion_segundos=None):
    if not st.session_state.get("lectura_id"):
        return
    update = {"fin": datetime.now(tz)}
    if duracion_segundos is not None:
        update["duracion_segundos"] = duracion_segundos
    # aseguramos página final/ruta guardadas
    update.setdefault("pagina_final", st.session_state.get("lectura_pagina_actual", 1))
    update.setdefault("ruta", st.session_state.get("ruta_actual", []))
    update.setdefault("distancia_km", st.session_state.get("ruta_distancia_km", 0))
    lecturas_col.update_one({"_id": ObjectId(st.session_state["lectura_id"])}, {"$set": update})
    # limpiar estado
    st.session_state["lectura_titulo"] = None
    st.session_state["lectura_paginas"] = None
    st.session_state["lectura_pagina_actual"] = 1
    st.session_state["lectura_inicio"] = None
    st.session_state["lectura_en_curso"] = False
    st.session_state["ruta_actual"] = []
    st.session_state["ruta_distancia_km"] = 0
    st.session_state["lectura_id"] = None

# -----------------------
# DB operations: Desarrollo (módulo Tiempo de desarrollo)
# -----------------------
def iniciar_desarrollo_db(nombre_proyecto):
    inicio = datetime.now(tz)
    doc = {"proyecto": nombre_proyecto, "inicio": inicio, "fin": None, "duracion_segundos": None}
    res = dev_col.insert_one(doc)
    st.session_state["dev_iniciado_por"] = nombre_proyecto
    st.session_state["dev_en_curso"] = True
    st.session_state["dev_inicio"] = inicio
    st.session_state["dev_id"] = res.inserted_id

def finalizar_desarrollo_db():
    if not st.session_state.get("dev_id"):
        return
    fin = datetime.now(tz)
    segundos = int((fin - st.session_state["dev_inicio"]).total_seconds())
    dev_col.update_one({"_id": ObjectId(st.session_state["dev_id"])}, {"$set": {"fin": fin, "duracion_segundos": segundos}})
    # limpiar
    st.session_state["dev_en_curso"] = False
    st.session_state["dev_inicio"] = None
    st.session_state["dev_id"] = None
    if "dev_iniciado_por" in st.session_state:
        del st.session_state["dev_iniciado_por"]

def restaurar_desarrollo_si_hay():
    if st.session_state.get("dev_en_curso"):
        return
    doc = dev_col.find_one({"fin": None}, sort=[("inicio", -1)])
    if doc:
        st.session_state["dev_en_curso"] = True
        st.session_state["dev_inicio"] = doc["inicio"]
        st.session_state["dev_id"] = doc["_id"]
        st.session_state["dev_iniciado_por"] = doc.get("proyecto", "—")

# -----------------------
# Mapa HTML/JS (Google Maps) - renderizado
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
                // enviamos al parent (Streamlit)
                window.parent.postMessage({{type: "guardar_ruta", ruta: rutaJson}}, "*");
                alert("Lectura finalizada, ruta enviada.");
            }}

            window.onload = initMap;
        </script>
    </body>
    </html>
    """
    # altura razonable dentro del layout
    html(html_code, height=600)

# -----------------------
# Recibir mensaje desde JS (ruta)
# -----------------------
try:
    # streamlit_js_eval devuelve last message data si hay
    from streamlit_js_eval import streamlit_js_eval
    mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => {return event.data});", key="js_eval_listener")
except Exception:
    mensaje_js = None

if mensaje_js and isinstance(mensaje_js, dict) and mensaje_js.get("type") == "guardar_ruta":
    try:
        ruta = json.loads(mensaje_js.get("ruta", "[]"))
    except Exception:
        ruta = []
    st.session_state["ruta_actual"] = ruta
    distancia_total = 0
    for i in range(len(ruta) - 1):
        p1 = ruta[i]
        p2 = ruta[i + 1]
        distancia_total += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
    st.session_state["ruta_distancia_km"] = distancia_total

    # si hay lectura activa, actualizamos y finalizamos
    if st.session_state.get("lectura_en_curso"):
        segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
        actualizar_lectura(
            pagina_actual=st.session_state.get("lectura_pagina_actual", 1),
            ruta=st.session_state.get("ruta_actual", []),
            distancia_km=st.session_state.get("ruta_distancia_km", 0),
            duracion_segundos=segundos_transcurridos
        )
        finalizar_lectura(duracion_segundos=segundos_transcurridos)

    st.success(f"Ruta recibida y guardada ({distancia_total:.2f} km).")
    st.experimental_rerun()

# -----------------------
# APP Layout: selector de secciones
# -----------------------
seccion = st.selectbox("Selecciona una sección:",
                       ["Tiempo de desarrollo", "Lectura con Cronómetro", "Mapa en vivo", "Historial de lecturas"])

# -----------------------
# MÓDULO 1: Tiempo de desarrollo
# -----------------------
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo")
    # restaurar posible sesión en curso
    restaurar_desarrollo_si_hay()

    if st.session_state.get("dev_en_curso"):
        inicio = to_datetime_local(st.session_state["dev_inicio"])
        segundos = int((datetime.now(tz) - inicio).total_seconds())
        st.success(f"🧠 Desarrollo en curso (desde {inicio.strftime('%Y-%m-%d %H:%M:%S')})")
        st.markdown(f"### ⏱️ Duración: {formatear_tiempo(segundos)}")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("⏹️ Finalizar desarrollo"):
                finalizar_desarrollo_db()
                st.success("Desarrollo finalizado.")
                st.experimental_rerun()
        with col2:
            st.write("")  # placeholder
    else:
        with st.form("form_inicio_desarrollo"):
            proyecto = st.text_input("Nombre del proyecto / tarea", value="")
            iniciado = st.form_submit_button("🟢 Iniciar desarrollo")
            if iniciado:
                proyecto = proyecto.strip() or "Trabajo"
                iniciar_desarrollo_db(proyecto)
                st.success(f"Desarrollo iniciado para: {proyecto}")
                st.experimental_rerun()

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

    # Restaurar lectura en curso (última sin fin)
    if not st.session_state.get("lectura_en_curso"):
        lectura_db = lecturas_col.find_one({"fin": None}, sort=[("inicio", -1)])
        if lectura_db:
            st.session_state["lectura_en_curso"] = True
            st.session_state["lectura_titulo"] = lectura_db.get("titulo")
            st.session_state["lectura_inicio"] = lectura_db.get("inicio")
            st.session_state["lectura_paginas"] = lectura_db.get("paginas_totales")
            st.session_state["lectura_pagina_actual"] = lectura_db.get("pagina_final") or lectura_db.get("pagina_inicial", 1)
            st.session_state["ruta_actual"] = lectura_db.get("ruta", [])
            st.session_state["ruta_distancia_km"] = lectura_db.get("distancia_km", 0)
            st.session_state["lectura_id"] = lectura_db.get("_id")

    if st.session_state.get("lectura_en_curso"):
        start_time = to_datetime_local(st.session_state["lectura_inicio"])
        segundos_transcurridos = int((datetime.now(tz) - start_time).total_seconds())
        st.success(f"📖 Lectura en curso: {st.session_state.get('lectura_titulo','—')}")
        st.markdown(f"### ⏱️ Duración: {formatear_tiempo(segundos_transcurridos)}")
        st.markdown(f"Página actual: {st.session_state.get('lectura_pagina_actual',1)} de {st.session_state.get('lectura_paginas','?')}")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("⏹️ Finalizar lectura"):
                segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
                actualizar_lectura(
                    pagina_actual=st.session_state.get("lectura_pagina_actual",1),
                    ruta=st.session_state.get("ruta_actual",[]),
                    distancia_km=st.session_state.get("ruta_distancia_km",0),
                    duracion_segundos=segundos_transcurridos
                )
                finalizar_lectura(duracion_segundos=segundos_transcurridos)
                st.success("Lectura finalizada y guardada.")
                st.experimental_rerun()
        with col2:
            nueva_pag = st.number_input("Actualizar página actual:", min_value=1,
                                       max_value=st.session_state.get("lectura_paginas", 10000),
                                       value=st.session_state.get("lectura_pagina_actual",1),
                                       step=1, key="input_pagina_actual")
            if st.button("Guardar página"):
                st.session_state["lectura_pagina_actual"] = int(nueva_pag)
                segundos_transcurridos = int((datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds())
                actualizar_lectura(
                    pagina_actual=st.session_state.get("lectura_pagina_actual",1),
                    ruta=st.session_state.get("ruta_actual",[]),
                    distancia_km=st.session_state.get("ruta_distancia_km",0),
                    duracion_segundos=segundos_transcurridos
                )
                st.success("Página guardada.")
    else:
        ya_guardado = st.checkbox("¿Ya tienes este libro guardado en el sistema?", key="checkbox_guardado")
        titulo = st.text_input("Ingresa el título del texto:", value=st.session_state.get("lectura_titulo",""), key="lectura_titulo_input")

        if titulo:
            st.session_state["lectura_titulo"] = titulo
            pagina_seleccionada = None
            lectura_seleccionada_id = None

            if ya_guardado:
                lecturas_guardadas = list(lecturas_col.find({"titulo": titulo, "fin": {"$ne": None}}).sort("inicio", -1))
                if lecturas_guardadas:
                    opciones = [
                        f"Pág. {l.get('pagina_final','?')} - Inició: {to_datetime_local(l['inicio']).strftime('%Y-%m-%d')}"
                        for l in lecturas_guardadas
                    ]
                    seleccion = st.selectbox("Selecciona la lectura donde la dejaste:", opciones, key="select_lecturas")
                    idx = opciones.index(seleccion)
                    lectura_seleccionada = lecturas_guardadas[idx]
                    pagina_seleccionada = lectura_seleccionada.get("pagina_final", 1)
                    lectura_seleccionada_id = lectura_seleccionada["_id"]
                else:
                    st.info("No se encontraron lecturas guardadas para este libro.")

            ultima_lectura = lecturas_col.find_one({"titulo": titulo}, sort=[("inicio", -1)])
            paginas_totales = ultima_lectura.get("paginas_totales") if ultima_lectura else None

            if paginas_totales:
                st.session_state["lectura_paginas"] = paginas_totales
                st.write(f"Páginas totales: {paginas_totales}")
            else:
                paginas_manual = st.number_input("No se encontró historial. Ingresa número total de páginas:", min_value=1, step=1, value=1, key="paginas_manual_input")
                st.session_state["lectura_paginas"] = paginas_manual
                st.write(f"Páginas totales: {paginas_manual}")

            pagina_inicial = pagina_seleccionada or st.number_input("Página desde donde empiezas la lectura:", min_value=1, max_value=st.session_state["lectura_paginas"], value=st.session_state.get("lectura_pagina_actual",1), step=1, key="pagina_inicio_input")
            st.session_state["lectura_pagina_actual"] = int(pagina_inicial)

            if st.button("▶️ Iniciar lectura"):
                st.session_state["lectura_titulo"] = titulo
                st.session_state["lectura_inicio"] = datetime.now(tz)
                st.session_state["lectura_en_curso"] = True
                iniciar_lectura(titulo, st.session_state["lectura_paginas"], pagina_inicial=st.session_state["lectura_pagina_actual"])
                st.success("Lectura iniciada.")
                st.experimental_rerun()

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
        st.markdown(f"Ruta guardada con {len(st.session_state['ruta_actual'])} puntos.")
        st.markdown(f"Distancia total: {st.session_state['ruta_distancia_km']:.2f} km")

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
