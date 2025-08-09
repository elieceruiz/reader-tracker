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
import folium
from streamlit.components.v1 import html
from streamlit_folium import st_folium

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
libros_col = db["libros"]

# Zona horaria
tz = pytz.timezone("America/Bogota")

# -----------------------
# HELPERS
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
    # distancia en km entre dos puntos
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def distancia_total_de_ruta(ruta):
    # ruta: lista de {"lat":.., "lng":..}
    if not ruta or len(ruta) < 2:
        return 0.0
    total = 0.0
    for i in range(len(ruta)-1):
        p1 = ruta[i]; p2 = ruta[i+1]
        total += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
    return total

# -----------------------
# CRONÓMETRO GENÉRICO
# -----------------------
def iniciar_evento():
    return {"inicio": utc_now(), "en_curso": True}

def tiempo_transcurrido_evento(evento):
    if not evento or not evento.get("inicio"):
        return 0, "0:00:00"
    inicio_local = to_datetime_local(evento["inicio"])
    segundos = int((utc_now() - inicio_local).total_seconds())
    return segundos, formatear_tiempo(segundos)

def finalizar_evento(evento):
    evento["fin"] = utc_now()
    evento["en_curso"] = False
    return evento

# -----------------------
# SESSION STATE defaults
# -----------------------
defaults = {
    # Lectura
    "lectura_titulo": None,
    "lectura_en_curso": False,
    "lectura_inicio": None,
    "lectura_id": None,
    "lectura_pagina_inicio": 1,
    "lectura_pagina_actual": 1,
    "ruta_actual": [],
    "ruta_distancia_km": 0.0,
    # Desarrollo
    "dev_en_curso": False,
    "dev_inicio": None,
    "dev_id": None,
    # Flags
    "_flag_start_dev": False,
    "_flag_stop_dev": False,
    "_flag_start_lectura": False,
    "_flag_stop_lectura": False,
    # Pending inputs
    "_pending_dev_name": None,
    "_pending_lectura_title": None,
    "_pending_lectura_page_start": None,
    "_pending_lectura_pages_total": None
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Auto refresh cada 1s para mostrar cronómetros actualizados
st_autorefresh(interval=1000, key="cronometro_refresh")

# -----------------------
# JS message listener (recibe ruta desde Google Maps snippet)
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
    st.session_state["ruta_distancia_km"] = distancia_total_de_ruta(ruta)
    st.success(f"Ruta recibida ({st.session_state['ruta_distancia_km']:.2f} km).")
    # si hay lectura en curso, marcamos stop para que el UI pida confirmar
    if st.session_state.get("lectura_en_curso"):
        st.session_state["_flag_stop_lectura"] = True

# -----------------------
# DB: operaciones para lecturas y desarrollo
# -----------------------
def iniciar_lectura_db(titulo, pagina_inicial=1):
    evento = iniciar_evento()
    doc = {
        "tipo": "lectura",
        "libro": titulo,
        "inicio": evento["inicio"],
        "fin": None,
        "duracion_seg": 0,
        "pagina_inicial": int(pagina_inicial),
        "pagina_final": None,
        "paginas_sesion": 0,
        "paginas_acumuladas": 0,          # se llenará al finalizar
        "lecturas_completas_total": 0,    # se actualizará al finalizar si corresponde
        "estatica": True,
        "distancia_km": 0.0,
        "ruta": []
    }
    res = lecturas_col.insert_one(doc)
    st.session_state.update({
        "lectura_id": res.inserted_id,
        "lectura_inicio": evento["inicio"],
        "lectura_en_curso": True,
        "lectura_titulo": titulo,
        "lectura_pagina_inicio": int(pagina_inicial),
        "lectura_pagina_actual": int(pagina_inicial),
        "ruta_actual": [],
        "ruta_distancia_km": 0.0
    })

def actualizar_lectura_db_once():
    if st.session_state.get("lectura_en_curso") and st.session_state.get("lectura_id"):
        seg, _ = tiempo_transcurrido_evento({"inicio": st.session_state["lectura_inicio"]})
        lid = ensure_objectid(st.session_state["lectura_id"])
        if lid:
            lecturas_col.update_one({"_id": lid}, {"$set": {
                "pagina_final": st.session_state.get("lectura_pagina_actual"),
                "ruta": st.session_state.get("ruta_actual", []),
                "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
                "duracion_seg": seg
            }})

def finalizar_lectura_db_and_state(paginas_sesion=0, lectura_completa=False):
    lid = ensure_objectid(st.session_state.get("lectura_id"))
    if lid:
        seg, _ = tiempo_transcurrido_evento({"inicio": st.session_state["lectura_inicio"]})
        # calcular paginas acumuladas y lecturas completas totales desde coleccion libros
        titulo = st.session_state.get("lectura_titulo")
        paginas_previas = 0
        lecturas_completas_previas = 0
        libro_doc = libros_col.find_one({"nombre": titulo})
        if libro_doc:
            paginas_previas = libro_doc.get("paginas_acumuladas", 0)
            lecturas_completas_previas = libro_doc.get("lecturas_completas", 0)
        paginas_acumuladas = paginas_previas + int(paginas_sesion or 0)
        lecturas_completas_total = lecturas_completas_previas + (1 if lectura_completa else 0)

        # actualizar lectura
        lecturas_col.update_one({"_id": lid}, {"$set": {
            "fin": utc_now(),
            "pagina_final": st.session_state.get("lectura_pagina_actual", st.session_state.get("lectura_pagina_inicio", 1)),
            "paginas_sesion": int(paginas_sesion or 0),
            "paginas_acumuladas": paginas_acumuladas,
            "lecturas_completas_total": lecturas_completas_total,
            "duracion_seg": seg,
            "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
            "ruta": st.session_state.get("ruta_actual", [])
        }})

        # actualizar/crear doc del libro (totales)
        libros_col.update_one({"nombre": titulo}, {"$set": {
            "nombre": titulo,
            "paginas_acumuladas": paginas_acumuladas,
            "lecturas_completas": lecturas_completas_total
        }}, upsert=True)

    # limpiar estado
    st.session_state.update({
        "lectura_titulo": None,
        "lectura_en_curso": False,
        "lectura_inicio": None,
        "lectura_id": None,
        "lectura_pagina_inicio": 1,
        "lectura_pagina_actual": 1,
        "ruta_actual": [],
        "ruta_distancia_km": 0.0
    })

def iniciar_desarrollo_db(nombre="Desarrollo"):
    evento = iniciar_evento()
    doc = {"tipo": "desarrollo_app", "nombre": nombre, "inicio": evento["inicio"], "fin": None, "duracion_seg": 0}
    res = dev_col.insert_one(doc)
    st.session_state.update({
        "dev_en_curso": True,
        "dev_inicio": evento["inicio"],
        "dev_id": res.inserted_id
    })

def actualizar_desarrollo_db_once():
    if st.session_state.get("dev_en_curso") and st.session_state.get("dev_id"):
        seg, _ = tiempo_transcurrido_evento({"inicio": st.session_state["dev_inicio"]})
        did = ensure_objectid(st.session_state["dev_id"])
        if did:
            dev_col.update_one({"_id": did}, {"$set": {"duracion_seg": seg}})

def finalizar_desarrollo_db_and_state():
    did = ensure_objectid(st.session_state.get("dev_id"))
    if did:
        seg, _ = tiempo_transcurrido_evento({"inicio": st.session_state["dev_inicio"]})
        dev_col.update_one({"_id": did}, {"$set": {"fin": utc_now(), "duracion_seg": seg}})
    st.session_state.update({
        "dev_en_curso": False,
        "dev_inicio": None,
        "dev_id": None
    })

# -----------------------
# Callbacks (marcar flags / inputs)
# -----------------------
def cb_mark_start_dev():
    st.session_state["_flag_start_dev"] = True

def cb_mark_stop_dev():
    st.session_state["_flag_stop_dev"] = True

def cb_mark_start_lectura():
    st.session_state["_flag_start_lectura"] = True
    st.session_state["_pending_lectura_title"] = st.session_state.get("input_lectura_titulo")
    st.session_state["_pending_lectura_page_start"] = st.session_state.get("input_lectura_pagina_inicio")

def cb_mark_stop_lectura():
    st.session_state["_flag_stop_lectura"] = True

# -----------------------
# Procesar flags (se ejecuta antes de mostrar UI que depende de estado)
# -----------------------
# Iniciar desarrollo
if st.session_state.get("_flag_start_dev"):
    iniciar_desarrollo_db()
    st.session_state["_flag_start_dev"] = False

# Finalizar desarrollo
if st.session_state.get("_flag_stop_dev"):
    finalizar_desarrollo_db_and_state()
    st.session_state["_flag_stop_dev"] = False

# Iniciar lectura
if st.session_state.get("_flag_start_lectura"):
    titulo = st.session_state.get("_pending_lectura_title") or "Sin título"
    pagina_inicio = int(st.session_state.get("_pending_lectura_page_start") or 1)
    iniciar_lectura_db(titulo, pagina_inicio)
    st.session_state["_flag_start_lectura"] = False
    st.session_state["_pending_lectura_title"] = None
    st.session_state["_pending_lectura_page_start"] = None

# Finalizar lectura (flag marcado por UI o por mensaje del mapa)
if st.session_state.get("_flag_stop_lectura"):
    # Abrir un pequeño modal-like UI (usamos expanders + condicional) para pedir páginas y si fue completa
    st.session_state["_flag_stop_lectura"] = False
    st.session_state["_ask_finalize_lectura"] = True

# -----------------------
# Auto-update DB mientras hay sesiones activas
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
# Render Map con dibujo (Google Maps JS) - unchanged, integrado
# -----------------------
def render_map_con_dibujo(api_key):
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
# UI Layout: selector de sección
# -----------------------
seccion = st.selectbox("Selecciona una sección:", ["Tiempo de desarrollo", "Lectura con Cronómetro", "Mapa en vivo", "Historial de lecturas"])

# -----------------------
# MÓDULO 1: Tiempo de desarrollo
# -----------------------
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo dedicado al desarrollo (de la App)")

    # Restaurar sesión en curso desde DB si aplica
    if not st.session_state.get("dev_en_curso"):
        doc = dev_col.find_one({"fin": None}, sort=[("inicio", -1)])
        if doc:
            st.session_state["dev_en_curso"] = True
            st.session_state["dev_inicio"] = doc["inicio"]
            st.session_state["dev_id"] = doc["_id"]

    if st.session_state.get("dev_en_curso"):
        seg, txt = tiempo_transcurrido_evento({"inicio": st.session_state["dev_inicio"]})
        inicio_local = to_datetime_local(st.session_state["dev_inicio"])
        st.success(f"🧠 Desarrollo en curso (desde {inicio_local.strftime('%Y-%m-%d %H:%M:%S')})")
        st.markdown(f"### ⏱️ Duración: {txt}")
        st.button("⏹️ Finalizar desarrollo", on_click=cb_mark_stop_dev)
    else:
        st.button("🟢 Iniciar desarrollo", on_click=cb_mark_start_dev)

    st.markdown("---")
    st.subheader("Historial (Desarrollos)")
    rows = list(dev_col.find().sort("inicio", -1).limit(200))
    if rows:
        for r in rows:
            inicio = to_datetime_local(r["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
            if r.get("fin"):
                dur = formatear_tiempo(r.get("duracion_seg", 0))
                st.write(f"**{r.get('nombre','Desarrollo')}** | {inicio} | ⏱ {dur}")
            else:
                st.write(f"**{r.get('nombre','Desarrollo')}** | {inicio} | ⏳ En curso")
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
            st.session_state["lectura_titulo"] = doc.get("libro")
            st.session_state["lectura_pagina_inicio"] = doc.get("pagina_inicial", 1)
            st.session_state["lectura_pagina_actual"] = doc.get("pagina_final") or doc.get("pagina_inicial", 1)
            st.session_state["ruta_actual"] = doc.get("ruta", [])
            st.session_state["ruta_distancia_km"] = doc.get("distancia_km", 0.0)

    if st.session_state.get("lectura_en_curso"):
        seg, txt = tiempo_transcurrido_evento({"inicio": st.session_state["lectura_inicio"]})
        inicio_local = to_datetime_local(st.session_state["lectura_inicio"])
        st.success(f"📖 {st.session_state.get('lectura_titulo','—')}")
        st.markdown(f"### ⏱️ Duración: {txt}")
        # Página actual input
        pagina_actual = st.number_input("Página actual:", min_value=1,
                        value=st.session_state.get("lectura_pagina_actual", 1),
                        key="lectura_pagina_actual")
        st.markdown(f"Distancia registrada: {st.session_state.get('ruta_distancia_km',0.0):.2f} km")
        st.button("⏹️ Finalizar lectura", on_click=cb_mark_stop_lectura)
    else:
        st.text_input("Ingresa el título del texto:", key="input_lectura_titulo")
        st.number_input("Página desde donde empiezas la lectura:", min_value=1, value=1, key="input_lectura_pagina_inicio")
        st.button("▶️ Iniciar lectura", on_click=cb_mark_start_lectura)

    # Si se pidió finalizar: pedir datos finales
    if st.session_state.get("_ask_finalize_lectura"):
        with st.expander("Finalizar lectura — confirma datos", expanded=True):
            paginas_leidas = st.number_input("¿Cuántas páginas leíste en esta sesión?", min_value=0, value=0, key="final_paginas_sesion")
            lectura_completa = st.checkbox("Marcar como lectura COMPLETA (terminé el texto)", key="final_lectura_completa")
            estatico = st.checkbox("Lectura estática (sin movimiento/GPS)", value=(st.session_state.get("ruta_distancia_km",0.0) == 0.0), key="final_estatica")
            st.markdown(f"Distancia detectada: **{st.session_state.get('ruta_distancia_km',0.0):.2f} km**")
            if st.button("Confirmar y guardar lectura"):
                # calcular tiempo y tiempo por página
                seg, _ = tiempo_transcurrido_evento({"inicio": st.session_state["lectura_inicio"]})
                tpp = None
                if paginas_leidas > 0:
                    tpp = seg / float(paginas_leidas)
                # actualizar en DB y libro
                finalizar_lectura_db_and_state(paginas_sesion=paginas_leidas, lectura_completa=lectura_completa)
                st.session_state["_ask_finalize_lectura"] = False
                st.success("Lectura finalizada y guardada.")
            if st.button("Cancelar"):
                st.session_state["_ask_finalize_lectura"] = False

# -----------------------
# MÓDULO 3: Mapa en vivo (para trazar ruta y enviar al servidor)
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
# MÓDULO 4: Historial de lecturas y desarrollo
# -----------------------
elif seccion == "Historial de lecturas":
    st.header("Historial")

    st.subheader("Lecturas por título")
    # obtener lista de libros ordenada alfabéticamente con totales
    libros = list(libros_col.find().sort("nombre", 1))
    if not libros:
        st.info("No hay lecturas registradas aún.")
    else:
        opciones = [f"{b['nombre']} (Pág acum: {b.get('paginas_acumuladas',0)} / Lecturas: {b.get('lecturas_completas',0)})" for b in libros]
        elegido = st.selectbox("Selecciona un libro:", opciones)
        if elegido:
            nombre = elegido.split(" (")[0]
            lects = list(lecturas_col.find({"libro": nombre}).sort("inicio", -1))
            if not lects:
                st.info("No hay sesiones para este libro.")
            else:
                for l in lects:
                    inicio = to_datetime_local(l["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
                    dur = formatear_tiempo(l.get("duracion_seg", 0)) if l.get("duracion_seg") else "-"
                    paginas = f"{l.get('paginas_sesion', 0)} pág (Acum: {l.get('paginas_acumuladas', 0)})" if l.get("paginas_sesion", 0) else "-"
                    tpp_txt = "-"
                    if l.get("paginas_sesion"):
                        tpp = l.get("duracion_seg", 0) / float(l.get("paginas_sesion", 1))
                        tpp_txt = f"{int(tpp)} s/pág"
                    modo_txt = "Estática" if l.get("estatica", True) else f"En movimiento ({l.get('distancia_km',0.0):.2f} km)"
                    lectura_completa_txt = f"Lectura completa #{l.get('lecturas_completas_total',0)}" if l.get("lecturas_completas_total",0)>0 else ""
                    st.write(f"• {inicio} | {dur} | {paginas} | {tpp_txt} | {modo_txt} {lectura_completa_txt}")

    st.markdown("---")
    st.subheader("Sesiones de Desarrollo")
    devs = list(dev_col.find().sort("inicio", -1).limit(200))
    if not devs:
        st.info("No hay sesiones de desarrollo registradas.")
    else:
        for d in devs:
            inicio = to_datetime_local(d["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
            if d.get("fin"):
                dur = formatear_tiempo(d.get("duracion_seg", 0))
                st.write(f"• {inicio} | ⏱ {dur}")
            else:
                st.write(f"• {inicio} | ⏳ En curso")

# -----------------------
# Mapa histórico: ver ruta de una sesión concreta (opcional)
# -----------------------
st.markdown("---")
st.subheader("Visualizar ruta de una sesión (opcional)")
session_type = st.selectbox("Tipo de sesión", ["lectura", "desarrollo"], index=0, key="viz_session_type")
if session_type == "lectura":
    sesiones = list(lecturas_col.find({"ruta": {"$exists": True, "$ne": []}}).sort("inicio", -1).limit(200))
    if sesiones:
        labels = [f"{to_datetime_local(s['inicio']).strftime('%Y-%m-%d %H:%M:%S')} — {s.get('libro','-')} — {s.get('distancia_km',0.0):.2f} km" for s in sesiones]
        sel = st.selectbox("Elige sesión con ruta:", labels)
        if sel:
            idx = labels.index(sel)
            ruta_doc = sesiones[idx].get("ruta", [])
            if ruta_doc:
                # centrar en primer punto
                lat0, lng0 = ruta_doc[0]["lat"], ruta_doc[0]["lng"]
                m = folium.Map(location=[lat0, lng0], zoom_start=15)
                coords = [(p["lat"], p["lng"]) for p in ruta_doc]
                folium.PolyLine(coords, color="red", weight=3).add_to(m)
                folium.Marker(coords[0], popup="Inicio").add_to(m)
                folium.Marker(coords[-1], popup="Fin").add_to(m)
                st_folium(m, width=700, height=450)
            else:
                st.info("No hay ruta guardada para esa sesión.")
    else:
        st.info("No hay sesiones con ruta guardada.")
else:
    st.info("Solo las lecturas pueden tener ruta asociada.")

# -----------------------
# FIN
# -----------------------
