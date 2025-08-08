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
import requests

# === CONFIGURACIÓN ===
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# === SECRETS ===
mongo_uri = st.secrets.get("mongo_uri")
openai_api_key = st.secrets.get("openai_api_key")
ocr_space_api_key = st.secrets.get("ocr_space_api_key")
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
    "ocr_text_raw": None,
    "ocr_text_cleaned": None,
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
        "OCR + OpenAI + Cronómetro",
        "Mapa en vivo",
        "Historial de lecturas"
    ]
)

# === FUNCIONES ===

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
                "cronometro_running", "lectura_id", "ocr_text_raw", "ocr_text_cleaned"]:
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
    st.rerun()

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

# ------------------ MÓDULO 2: OCR + OpenAI + Cronómetro ------------------
elif seccion == "OCR + OpenAI + Cronómetro":
    st.header("OCR + OpenAI + Cronómetro")

    # 1. Cargar foto y hacer OCR (si no hay texto raw aún)
    if not st.session_state["ocr_text_raw"]:
        imagen = st.file_uploader("Sube foto portada o parcial del texto (JPG/PNG obligatorio):", type=["jpg", "jpeg", "png"])
        if imagen:
            with st.spinner("Procesando imagen con OCR.space..."):
                bytes_img = imagen.read()
                encoded_image = base64.b64encode(bytes_img).decode("utf-8")
                st.session_state["foto_base64"] = encoded_image

                # Llamar OCR.space
                payload = {
                    "base64Image": f"data:image/jpeg;base64,{encoded_image}",
                    "language": "spa",
                    "apikey": ocr_space_api_key,
                    "isOverlayRequired": False
                }
                response = requests.post("https://api.ocr.space/parse/image", data=payload)
                if response.status_code == 200:
                    result = response.json()
                    parsed_text = ""
                    try:
                        parsed_text = result["ParsedResults"][0]["ParsedText"]
                    except Exception:
                        parsed_text = ""
                    if parsed_text:
                        st.session_state["ocr_text_raw"] = parsed_text
                    else:
                        st.error("OCR no pudo detectar texto. Intenta con otra imagen.")
                else:
                    st.error(f"Ocurrió un error en OCR.space: {response.status_code}")

    # 2. Mostrar texto detectado y opción para limpiar con OpenAI
    if st.session_state["ocr_text_raw"]:
        st.subheader("Texto detectado por OCR:")
        st.text_area("Texto OCR crudo:", st.session_state["ocr_text_raw"], height=150)

        if st.button("🔄 Limpiar y extraer título con OpenAI"):
            prompt = f"Por favor extrae y limpia el título principal de este texto:\n\n{st.session_state['ocr_text_raw']}\n\nSolo responde con el título claro y limpio."
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                )
                titulo_limpio = response.choices[0].message.content.strip()
                st.session_state["ocr_text_cleaned"] = titulo_limpio
                st.success(f"Título limpio detectado: {titulo_limpio}")
            except Exception as e:
                st.error(f"Error llamando a OpenAI: {e}")

    # 3. Mostrar título limpio o usar texto raw si no hay limpio
    titulo_actual = st.session_state.get("ocr_text_cleaned") or st.session_state.get("ocr_text_raw")

    if titulo_actual:
        st.markdown(f"### Texto detectado: **{titulo_actual}**")

        # Pedir número total de páginas (si no está definido aún)
        if not st.session_state["lectura_paginas"]:
            paginas_input = st.number_input("Ingresa número total de páginas del texto:", min_value=1, step=1)
            if paginas_input > 0:
                st.session_state["lectura_paginas"] = paginas_input

    # 4. Botón para iniciar lectura
    if not st.session_state["lectura_en_curso"] and titulo_actual and st.session_state["lectura_paginas"]:
        if st.button("🟢 Iniciar lectura"):
            st.session_state["lectura_en_curso"] = True
            st.session_state["lectura_inicio"] = datetime.now(tz)
            st.session_state["cronometro_segundos"] = 0
            st.session_state["cronometro_running"] = True
            st.session_state["lectura_titulo"] = titulo_actual
            iniciar_lectura(
                st.session_state["lectura_titulo"],
                st.session_state["lectura_paginas"],
                st.session_state["foto_base64"],
            )
            st.rerun()

    # 5. Cronómetro y avance de páginas durante lectura
    if st.session_state["lectura_en_curso"]:
        st.markdown(f"### Leyendo: {st.session_state['lectura_titulo']}")
        minutos = st.session_state["cronometro_segundos"] // 60
        segundos = st.session_state["cronometro_segundos"] % 60
        st.markdown(f"⏱️ Tiempo transcurrido: {minutos:02d}:{segundos:02d}")

        # Cronómetro manual
        if st.session_state["cronometro_running"]:
            st.session_state["cronometro_segundos"] += 1

        pagina_actual = st.number_input(
            "Página actual leída:",
            min_value=0,
            max_value=st.session_state["lectura_paginas"],
            value=st.session_state["lectura_pagina_actual"],
            step=1,
            key="pagina_input",
        )

        if pagina_actual != st.session_state["lectura_pagina_actual"]:
            st.session_state["lectura_pagina_actual"] = pagina_actual
            actualizar_lectura(
                st.session_state["lectura_pagina_actual"],
                st.session_state["ruta_actual"],
                st.session_state["ruta_distancia_km"],
            )

        # Botón para finalizar lectura manualmente
        if st.button("⏹️ Finalizar lectura manualmente"):
            finalizar_lectura()
            st.success("Lectura finalizada manualmente.")
            st.rerun()

# ------------------ MÓDULO 3: Mapa en vivo ------------------
elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo con registro de ruta")

    if not st.session_state["lectura_en_curso"]:
        st.info("No hay lectura en curso. Inicia una lectura en el módulo OCR primero.")
    else:
        render_map_con_dibujo(google_maps_api_key)

# ------------------ MÓDULO 4: Historial de lecturas ------------------
elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas")

    textos = [col for col in db.list_collection_names() if col != "dev_tracker"]
    titulo_sel = st.selectbox("Selecciona texto para ver historial:", textos)

    if titulo_sel:
        mostrar_historial(titulo_sel)
