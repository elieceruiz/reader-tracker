import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from dateutil.parser import parse
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html
import openai
import base64
import json

# === CONFIGURACIÓN ===
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# === SECRETS ===
mongo_uri = st.secrets.get("mongo_uri")
openai_api_key = st.secrets.get("openai_api_key")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai.organization = st.secrets.get("openai_org_id", None)
openai.api_key = openai_api_key

# === CONEXIONES ===
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]

# === ZONA HORARIA ===
tz = pytz.timezone("America/Bogota")
def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        dt = parse(dt)
    return dt.astimezone(tz)

# === SESIÓN ESTADO BASE ===
for key, default in {
    "dev_start": None,
    # Módulo 2
    "lectura_titulo": None,
    "lectura_paginas": None,
    "lectura_pagina_actual": 0,
    "lectura_inicio": None,
    "lectura_en_curso": False,
    "ruta_actual": [],
    "ruta_distancia_km": 0,
    "foto_base64": None,
    "cronometro_segundos": 0,
    "cronometro_running": False,
    "lectura_id": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# === REFRESCO AUTOMÁTICO PARA CRONÓMETRO ===
count = st_autorefresh(interval=1000, key="cronometro_refresh")

# === DROPDOWN PARA SELECCIONAR MÓDULO ===
seccion = st.selectbox(
    "Selecciona una sección:",
    [
        "Tiempo de desarrollo",
        "GPT-4o y Cronómetro",
        "Mapa en vivo",
        "Historial de lecturas"
    ]
)

# === FUNCIONES MÓDULO 2 ===

def detectar_titulo_con_openai(imagen_bytes):
    base64_image = base64.b64encode(imagen_bytes).decode("utf-8")
    try:
        st.write("🔍 Enviando imagen a OpenAI para detectar título...")
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "¿Cuál es el título del texto que aparece en esta imagen? Solo el título, por favor."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                }
            ],
            max_tokens=50,
        )
        titulo = response.choices[0].message.content.strip()
        st.write("✅ Respuesta recibida de OpenAI:", titulo)
        return titulo
    except Exception as e:
        st.error(f"❌ Error llamando a OpenAI: {e}")
        return None

def coleccion_por_titulo(titulo):
    nombre = titulo.lower().replace(" ", "_")
    return client["reader_tracker"][nombre]

def iniciar_lectura(titulo, paginas_totales, foto_b64):
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
                "ruta_distancia_km", "foto_base64", "cronometro_segundos",
                "cronometro_running", "lectura_id"]:
        st.session_state[key] = None if key != "lectura_pagina_actual" else 0

def mostrar_historial(titulo):
    col = coleccion_por_titulo(titulo)
    lecturas = list(col.find().sort("inicio", -1))
    if not lecturas:
        st.info("No hay registros de lecturas para este texto.")
        return
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

def render_map_con_dibujo(api_key):
    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style> html, body, #map {{ height: 100%; margin: 0; padding: 0; }} </style>
        <script src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=geometry"></script>
    </head>
    <body>
        <div id="map"></div>
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

    # Calcular distancia total con fórmula Haversine
    from math import radians, cos, sin, asin, sqrt
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371  # km
        dlat = radians(lat2 - lat1)
        dlon = radians(lon2 - lon1)
        a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))
        return R * c

    distancia_total = 0
    for i in range(len(ruta) - 1):
        p1 = ruta[i]
        p2 = ruta[i + 1]
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

# ------------------ MÓDULO 1: Tiempo de desarrollo ------------------
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
            st.success(f"✅ Desarrollo finalizado. Duración: {duracion}")
            st.rerun()

    else:
        if st.button("🟢 Iniciar desarrollo"):
            dev_col.insert_one({
                "inicio": datetime.now(tz),
                "fin": None,
                "duracion_segundos": None
            })
            st.rerun()

# ------------------ MÓDULO 2: GPT-4o y Cronómetro ------------------
elif seccion == "GPT-4o y Cronómetro":
    st.header("GPT-4o y Cronómetro")

    # 1. Cargar foto y detectar título (solo si no hay título en sesión)
    if not st.session_state["lectura_titulo"]:
        imagen = st.file_uploader("Sube foto portada o parcial del texto (JPG/PNG obligatorio):", type=["jpg", "jpeg", "png"])
        if imagen:
            bytes_img = imagen.read()
            st.session_state["foto_base64"] = base64.b64encode(bytes_img).decode("utf-8")
            with st.spinner("Detectando título con IA..."):
                titulo = detectar_titulo_con_openai(bytes_img)
            if titulo:
                st.session_state["lectura_titulo"] = titulo
                st.success(f"Título detectado: {titulo}")
            else:
                st.error("No se pudo detectar el título. Intenta con una imagen más clara o prueba luego.")

            # Verificar si ya hay páginas totales guardadas
            if titulo:
                col = coleccion_por_titulo(titulo)
                info = col.find_one({})
                if info and info.get("paginas_totales"):
                    st.session_state["lectura_paginas"] = info["paginas_totales"]
                else:
                    paginas_input = st.number_input("Ingresa número total de páginas del texto:", min_value=1, step=1)
                    if paginas_input > 0:
                        st.session_state["lectura_paginas"] = paginas_input

    else:
        st.markdown(f"### Texto: **{st.session_state['lectura_titulo']}**")
        st.markdown(f"Total páginas: **{st.session_state['lectura_paginas']}**")

    # 2. Botón para iniciar lectura
    if not st.session_state["lectura_en_curso"] and st.session_state["lectura_titulo"] and st.session_state["lectura_paginas"]:
        if st.button("🟢 Iniciar lectura"):
            st.session_state["lectura_en_curso"] = True
            st.session_state["lectura_inicio"] = datetime.now(tz)
            st.session_state["cronometro_segundos"] = 0
            st.session_state["cronometro_running"] = True
            iniciar_lectura(
                st.session_state["lectura_titulo"],
                st.session_state["lectura_paginas"],
                st.session_state["foto_base64"]
            )
            st.experimental_rerun()

    # 3. Durante la lectura (cronómetro, página actual, mapa, etc.)
    if st.session_state["lectura_en_curso"]:
        if st.session_state["cronometro_running"]:
            tiempo_transcurrido = (datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds()
            st.session_state["cronometro_segundos"] = int(tiempo_transcurrido)

        duracion_str = str(timedelta(seconds=st.session_state["cronometro_segundos"]))
        st.markdown(f"**⏱ Tiempo de lectura:** {duracion_str}")

        pagina_actual = st.number_input(
            "Página actual que llevas leyendo:",
            min_value=1,
            max_value=st.session_state["lectura_paginas"],
            value=st.session_state["lectura_pagina_actual"],
            step=1
        )
        if pagina_actual != st.session_state["lectura_pagina_actual"]:
            st.session_state["lectura_pagina_actual"] = pagina_actual
            actualizar_lectura(pagina_actual, st.session_state["ruta_actual"], st.session_state["ruta_distancia_km"])

        if st.session_state["cronometro_segundos"] > 0 and pagina_actual > 0:
            ritmo = pagina_actual / (st.session_state["cronometro_segundos"] / 60)  # páginas/minuto
            paginas_restantes = st.session_state["lectura_paginas"] - pagina_actual
            minutos_restantes = paginas_restantes / ritmo if ritmo > 0 else 0
            proyeccion = datetime.now(tz) + timedelta(minutes=minutos_restantes)
            st.markdown(f"**📊 Ritmo:** {ritmo:.2f} páginas/minuto")
            st.markdown(f"**📅 Proyección fin lectura:** {proyeccion.strftime('%Y-%m-%d %H:%M:%S')}")

        if google_maps_api_key:
            render_map_con_dibujo(google_maps_api_key)
        else:
            st.warning("No hay API key de Google Maps para mostrar mapa.")

    # 4. Botón para finalizar lectura manualmente
    if st.session_state["lectura_en_curso"]:
        if st.button("⏹️ Finalizar lectura manualmente"):
            finalizar_lectura()
            st.success("Lectura finalizada y guardada.")
            st.experimental_rerun()

    # 5. Mostrar historial de lecturas para este título
    if st.session_state["lectura_titulo"]:
        st.markdown("---")
        st.subheader(f"Historial de lecturas: {st.session_state['lectura_titulo']}")
        mostrar_historial(st.session_state["lectura_titulo"])

# ------------------ MÓDULO 3: Mapa en vivo ------------------
elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo")

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
            <div id="map" style="height:{height}px;"></div>
            <script>
              function initMap() {{
                var map = new google.maps.Map(document.getElementById('map'), {{
                  zoom: 15,
                  center: new google.maps.LatLng({center_lat}, {center_lon}),
                  mapTypeId: 'roadmap'
                }});
              }}
              window.onload = initMap;
            </script>
          </body>
        </html>
        """
        html(html_code, height=height)

    if google_maps_api_key:
        render_live_map(google_maps_api_key, center_coords=(4.65, -74.05))
    else:
        st.error("Falta clave API de Google Maps para mostrar mapa en vivo.")

# ------------------ MÓDULO 4: Historial de lecturas ------------------
elif seccion == "Historial de lecturas":
    st.header("Historial de todas las lecturas")

    colecciones = db.list_collection_names()
    titulos = [c.replace("_", " ").title() for c in colecciones if c != "dev_tracker"]

    titulo_seleccionado = st.selectbox("Selecciona texto para historial:", titulos)

    if titulo_seleccionado:
        col_name = titulo_seleccionado.lower().replace(" ", "_")
        col = db[col_name]
        lecturas = list(col.find().sort("inicio", -1))
        if not lecturas:
            st.info("No hay registros para este texto.")
        else:
            data = []
            for i, l in enumerate(lecturas):
                inicio = to_datetime_local(l["inicio"]).strftime("%Y-%m-%d %H:%M:%S")
                fin = to_datetime_local(l["fin"]).strftime("%Y-%m-%d %H:%M:%S") if l.get("fin") else "-"
                duracion = str(timedelta(seconds=l.get("duracion_segundos", 0))) if l.get("duracion_segundos") else "-"
                paginas = f"{l.get('pagina_final', '-')}/{l.get('paginas_totales', '-')}"
                distancia = f"{l.get('distancia_km', 0):.2f} km"
                data.append({
                    "#": len(lecturas) - i,
                    "Inicio": inicio,
                    "Fin": fin,
                    "Duración": duracion,
                    "Páginas": paginas,
                    "Distancia": distancia
                })
            st.dataframe(data)
