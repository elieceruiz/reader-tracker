import streamlit as st
from datetime import datetime, timedelta
import pytz
from pymongo import MongoClient
from dateutil.parser import parse
from streamlit_autorefresh import st_autorefresh
from streamlit.components.v1 import html
import base64
import json
import requests
import io
from PIL import Image

# Configuración de la página
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

# Obtención de llaves y URIs desde secretos
mongo_uri = st.secrets.get("mongo_uri")
ocr_space_api_key = st.secrets.get("ocr_space_api_key")
google_maps_api_key = st.secrets.get("google_maps_api_key")

# Conexión a MongoDB
client = MongoClient(mongo_uri)
db = client["reader_tracker"]
dev_col = db["dev_tracker"]

# Zona horaria local
tz = pytz.timezone("America/Bogota")

# Función para convertir a datetime local
def to_datetime_local(dt):
    if not isinstance(dt, datetime):
        dt = parse(dt)
    return dt.astimezone(tz)

# Inicialización de variables en sesión si no existen
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
    "ocr_response_raw": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# Autorefresh cada segundo para cronómetro
count = st_autorefresh(interval=1000, key="cronometro_refresh")

# Función para reducir tamaño de imagen a menos de 1MB (JPEG con compresión progresiva)
def reducir_a_menos_de_1mb(imagen_bytes, max_size_bytes=1_000_000, step=5):
    image = Image.open(io.BytesIO(imagen_bytes))
    calidad = 95
    buffer = io.BytesIO()
    while calidad > 10:
        buffer.seek(0)
        buffer.truncate()
        image.save(buffer, format="JPEG", quality=calidad)
        size = buffer.tell()
        if size <= max_size_bytes:
            return buffer.getvalue()
        calidad -= step
    return buffer.getvalue()

# Función para llamar a OCR.space y extraer texto
def ocr_space_api(imagen_bytes, api_key):
    imagen_bytes = reducir_a_menos_de_1mb(imagen_bytes)
    payload = {
        'isOverlayRequired': True,
        'apikey': api_key,
        'language': 'spa',
        'OCREngine': 2
    }
    files = {
        'filename': ('image.jpg', imagen_bytes)
    }
    try:
        response = requests.post('https://api.ocr.space/parse/image', files=files, data=payload)
        result = response.json()
        st.session_state["ocr_response_raw"] = result  # Guardar JSON para debug
        if result.get("IsErroredOnProcessing"):
            st.error(f"Error OCR.space: {result.get('ErrorMessage')}")
            return None
        parsed_results = result.get("ParsedResults")
        if not parsed_results:
            st.error("No se obtuvo texto del OCR.")
            return None
        texto = parsed_results[0].get("ParsedText", "").strip()
        return texto
    except Exception as e:
        st.error(f"Error llamando OCR.space: {e}")
        return None

# Función para obtener colección MongoDB basada en título de lectura
def coleccion_por_titulo(titulo):
    nombre = titulo.lower().replace(" ", "_")
    return client["reader_tracker"][nombre]

# Función para iniciar una sesión de lectura (guardar inicio y datos base)
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

# Función para actualizar la sesión de lectura con página actual, ruta y distancia
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

# Función para finalizar la lectura (guardar fin y resetear estados)
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

# Función para mostrar el historial de lecturas de un título
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

# Función para renderizar mapa con dibujo de ruta y botones para finalizar lectura
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

# Manejo de mensajes desde JS para recibir la ruta dibujada en el mapa
try:
    from streamlit_js_eval import streamlit_js_eval
    mensaje_js = streamlit_js_eval(js="window.addEventListener('message', (event) => {return event.data});", key="js_eval_listener")
except ImportError:
    mensaje_js = None
    st.warning("Módulo 'streamlit_js_eval' no instalado: no se podrá recibir ruta desde mapa.")

# Si llegó la ruta desde JS, procesarla y actualizar MongoDB
if mensaje_js and isinstance(mensaje_js, dict) and "type" in mensaje_js and mensaje_js["type"] == "guardar_ruta":
    ruta = json.loads(mensaje_js["ruta"])
    st.session_state["ruta_actual"] = ruta

    # Cálculo de distancia total usando fórmula haversine
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

# Menú principal para seleccionar sección
seccion = st.selectbox(
    "Selecciona una sección:",
    [
        "Tiempo de desarrollo",
        "OCR y Lectura",
        "Mapa en vivo",
        "Historial de lecturas"
    ]
)

# Sección: tiempo dedicado al desarrollo
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

# Sección: OCR y gestión de lectura
elif seccion == "OCR y Lectura":
    st.header("Detección de título con OCR.space y gestión de lectura")

    # Si no hay lectura en curso, pedir foto para OCR
    if not st.session_state["lectura_titulo"]:
        imagen = st.file_uploader("Sube foto portada o parcial del texto (JPG/PNG obligatorio):", type=["jpg", "jpeg", "png"])
        if imagen:
            bytes_img = imagen.read()
            st.session_state["foto_base64"] = base64.b64encode(bytes_img).decode("utf-8")
            with st.spinner("Procesando imagen con OCR.space..."):
                texto_detectado = ocr_space_api(bytes_img, ocr_space_api_key)
            if texto_detectado:
                titulo = texto_detectado.split("\n")[0]
                st.session_state["lectura_titulo"] = titulo
                st.success(f"Título detectado: **{titulo}**")
                paginas = st.number_input("Número total de páginas del texto:", min_value=1, step=1)
                if paginas > 0:
                    st.session_state["lectura_paginas"] = paginas
                    if st.button("Iniciar lectura"):
                        iniciar_lectura(titulo, paginas, st.session_state["foto_base64"])
                        st.session_state["lectura_en_curso"] = True
                        st.session_state["lectura_inicio"] = datetime.now(tz)
                        st.session_state["cronometro_segundos"] = 0
                        st.session_state["cronometro_running"] = True
                        st.rerun()
            else:
                st.error("No se detectó texto en la imagen. Intenta otra foto.")
    else:
        # Mostrar lectura en curso y control del cronómetro y página actual
        st.markdown(f"### Leyendo: **{st.session_state['lectura_titulo']}**")
        st.markdown(f"Total páginas: {st.session_state['lectura_paginas']}")
        pagina = st.number_input("Página actual que lees:", min_value=1, max_value=st.session_state["lectura_paginas"], value=st.session_state["lectura_pagina_actual"] or 1, step=1)
        st.session_state["lectura_pagina_actual"] = pagina

        if st.session_state["cronometro_running"]:
            st.markdown(f"⏳ Tiempo de lectura: {str(timedelta(seconds=st.session_state['cronometro_segundos']))}")

        if st.button("Pausar cronómetro"):
            st.session_state["cronometro_running"] = False

        if st.button("Reanudar cronómetro"):
            st.session_state["cronometro_running"] = True

        if st.button("Finalizar lectura"):
            finalizar_lectura()
            st.success("Lectura finalizada y datos guardados.")
            st.rerun()

        # Actualizar lectura con ruta y distancia si hay ruta actual
        if st.session_state["ruta_actual"]:
            actualizar_lectura(pagina, st.session_state["ruta_actual"], st.session_state["ruta_distancia_km"])

        # Mostrar JSON completo de respuesta OCR para debug
        with st.expander("Mostrar respuesta completa OCR.space (debug)"):
            st.json(st.session_state.get("ocr_response_raw", {}))

# Sección: mapa en vivo para dibujo de ruta
elif seccion == "Mapa en vivo":
    st.header("Dibuja tu ruta en el mapa (Google Maps)")
    render_map_con_dibujo(google_maps_api_key)

# Sección: historial de lecturas guardadas
elif seccion == "Historial de lecturas":
    st.header("Historial de lecturas guardadas")
    titulo_hist = st.text_input("Ingrese el título del texto para mostrar historial")
    if titulo_hist:
        mostrar_historial(titulo_hist)

# Cronómetro: si está corriendo, sumar un segundo cada refresh
if st.session_state["cronometro_running"]:
    st.session_state["cronometro_segundos"] += 1
    st.rerun()
