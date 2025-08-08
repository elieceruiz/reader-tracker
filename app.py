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
    response = openai.chat.completions.create(
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
    return titulo

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
from streamlit_js_eval import streamlit_js_eval

mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => {return event.data});", key="js_eval_listener")

if mensaje_js and "type" in mensaje_js and mensaje_js["type"] == "guardar_ruta":
    ruta = json.loads(mensaje_js["ruta"])
    st.session_state["ruta_actual"] = ruta
    from math import radians, cos, sin, asin, sqrt
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371
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
        imagen = st.file_uploader("Sube foto portada o portada parcial del texto (obligatorio JPG/PNG):", type=["jpg","jpeg","png"])
        if imagen:
            bytes_img = imagen.read()
            st.session_state["foto_base64"] = base64.b64encode(bytes_img).decode("utf-8")
            with st.spinner("Detectando título con IA..."):
                titulo = detectar_titulo_con_openai(bytes_img)
                st.session_state["lectura_titulo"] = titulo
                st.success(f"Título detectado: {titulo}")

            # Verificar si colección ya tiene páginas totales
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

    # 3. Durante lectura: cronómetro, mapa con dibujo, página actual, ritmo y proyecciones
    if st.session_state["lectura_en_curso"]:
        # Cronómetro (simple)
        if st.session_state["cronometro_running"]:
            tiempo_transcurrido = (datetime.now(tz) - st.session_state["lectura_inicio"]).total_seconds()
            st.session_state["cronometro_segundos"] = int(tiempo_transcurrido)

        duracion_str = str(timedelta(seconds=st.session_state["cronometro_segundos"]))
        st.markdown(f"**⏱ Tiempo de lectura:** {duracion_str}")

        # Página actual (input)
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

        # Ritmo de lectura y proyección
        if st.session_state["cronometro_segundos"] > 0 and pagina_actual > 0:
            ritmo = pagina_actual / (st.session_state["cronometro_segundos"] / 60)  # páginas por minuto
            paginas_restantes = st.session_state["lectura_paginas"] - pagina_actual
            minutos_restantes = paginas_restantes / ritmo if ritmo > 0 else 0
            proyeccion = datetime.now(tz) + timedelta(minutes=minutos_restantes)
            st.markdown(f"**📊 Ritmo:** {ritmo:.2f} páginas/minuto")
            st.markdown(f"**📅 Proyección fin lectura:** {proyeccion.strftime('%Y-%m-%d %H:%M:%S')}")

        # Mapa con ruta y botón finalizar lectura
        if google_maps_api_key:
            render_map_con_dibujo(google_maps_api_key)
        else:
            st.warning("No hay API key de Google Maps para mostrar mapa.")

    # 4. Botón finalizar lectura (si no ya enviado desde JS)
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
            <div id="map"></div>
            <script>
              let map;
              let marker;
              let path = [];

              function initMap() {{
                map = new google.maps.Map(document.getElementById('map'), {{
                  zoom: 17,
                  center: {{lat:{center_lat}, lng:{center_lon}}},
                  mapTypeId: 'roadmap'
                }});
                marker = new google.maps.Marker({{ map: map, position: {{lat:{center_lat}, lng:{center_lon}}}, title: "Tú" }});
              }}

              function updatePosition(pos) {{
                const lat = pos.coords.latitude;
                const lng = pos.coords.longitude;
                const latlng = new google.maps.LatLng(lat, lng);
                marker.setPosition(latlng);
                map.setCenter(latlng);
              }}

              function handleError(err) {{
                console.error('Geolocation error', err);
              }}

              if (navigator.geolocation) {{
                navigator.geolocation.getCurrentPosition(
                  function(p) {{
                    initMap();
                    updatePosition(p);
                    navigator.geolocation.watchPosition(updatePosition, handleError, {{ enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 }});
                  }},
                  function(e) {{
                    initMap();
                    console.error('Error getCurrentPosition', e);
                  }},
                  {{ enableHighAccuracy: true, maximumAge: 1000, timeout: 10000 }}
                );
              }} else {{
                initMap();
                console.error('Navegador no soporta geolocalización');
              }}
            </script>
          </body>
        </html>
        """
        html(html_code, height=height)

    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

# ------------------ MÓDULO 4: Historial de lecturas ------------------
elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas")
    st.info("Aquí irá el historial completo de lecturas (pendiente implementar).")
