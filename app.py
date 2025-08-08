import streamlit as st
import time
import base64
import json
from datetime import datetime
import pytz
import pymongo
import math
import openai
import requests
from streamlit_js_eval import streamlit_js_eval
import streamlit.components.v1 as components

# Configuración página
st.set_page_config(page_title="📚 Reader Tracker Completo", layout="wide")

# Secrets (minúsculas)
MONGO_URI = st.secrets.get("mongo_uri")
GOOGLE_MAPS_API_KEY = st.secrets.get("google_maps_api_key")
OPENAI_API_KEY = st.secrets.get("openai_api_key")
OPENAI_ORG_ID = st.secrets.get("openai_org_id")

# Inicializar OpenAI
openai.api_key = OPENAI_API_KEY
if OPENAI_ORG_ID:
    openai.organization = OPENAI_ORG_ID

# Conexión MongoDB
mongo_collection_lecturas = None
mongo_collection_libros = None
if MONGO_URI:
    try:
        client = pymongo.MongoClient(MONGO_URI)
        db = client["reader_tracker"]
        mongo_collection_lecturas = db["lecturas"]
        mongo_collection_libros = db["libros"]
    except Exception as e:
        st.warning(f"No se pudo conectar a MongoDB: {e}")

# Función para calcular distancia Haversine en km
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2*math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R*c

# OpenAI GPT-4o extractor título y autor (JSON solo)
def openai_extract_title_author(image_bytes):
    data_uri = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode("utf-8")
    system_prompt = (
        "Eres un extractor que devuelves SOLO JSON con claves 'titulo' y 'autor'. "
        "Si no encuentras autor, devuelve cadena vacía. Ejemplo: {\"titulo\":\"Cien años de soledad\",\"autor\":\"Gabriel García Márquez\"}"
    )
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extrae únicamente título y autor de esta imagen."},
                    {"type": "image_url", "image_url": {"url": data_uri}}
                ]}
            ],
            max_tokens=200,
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        try:
            parsed = json.loads(text)
            titulo = parsed.get("titulo", "") if isinstance(parsed.get("titulo", ""), str) else ""
            autor = parsed.get("autor", "") if isinstance(parsed.get("autor", ""), str) else ""
            return titulo.strip(), autor.strip()
        except Exception:
            try:
                start = text.index("{")
                end = text.rindex("}") + 1
                parsed = json.loads(text[start:end])
                return parsed.get("titulo","").strip(), parsed.get("autor","").strip()
            except Exception:
                return text.replace("\n"," ").strip(), ""
    except Exception as e:
        st.warning(f"Error OpenAI: {e}")
        return "", ""

# HTML+JS para mapa con watchPosition cada 5s y línea + distancia
def render_live_map(api_key):
    return f"""
    <div id="map" style="height:450px; width:100%;"></div>
    <div id="status" style="margin-top:8px; font-weight:bold;"></div>
    <button onclick="stopTracking()" style="margin-top:10px; padding:8px;">⏹ Parar y enviar datos</button>

    <script>
    let map;
    let marker;
    let pathCoords = [];
    let polyline;
    let watchId;
    let totalDistance = 0;

    function initMap() {{
        map = new google.maps.Map(document.getElementById('map'), {{
            zoom: 17,
            center: {{ lat: 0, lng: 0 }}
        }});
        polyline = new google.maps.Polyline({{
            map: map,
            path: [],
            geodesic: true,
            strokeColor: '#1E90FF',
            strokeOpacity: 0.8,
            strokeWeight: 4
        }});

        if (!navigator.geolocation) {{
            document.getElementById('status').innerText = "⚠️ Geolocalización no soportada.";
            return;
        }}

        watchId = navigator.geolocation.watchPosition(
            updatePosition,
            (err) => {{
                document.getElementById('status').innerText = "❌ Error: " + err.message;
            }},
            {{
                enableHighAccuracy: true,
                maximumAge: 0,
                timeout: 10000
            }}
        );
    }}

    function updatePosition(position) {{
        let lat = position.coords.latitude;
        let lng = position.coords.longitude;
        let currentPos = new google.maps.LatLng(lat, lng);

        if (pathCoords.length > 0) {{
            totalDistance += google.maps.geometry.spherical.computeDistanceBetween(
                pathCoords[pathCoords.length - 1],
                currentPos
            );
        }}

        pathCoords.push(currentPos);
        polyline.setPath(pathCoords);

        if (!marker) {{
            marker = new google.maps.Marker({{
                position: currentPos,
                map: map,
                title: "Ubicación actual"
            }});
            map.setCenter(currentPos);
        }} else {{
            marker.setPosition(currentPos);
        }}

        document.getElementById('status').innerText = 
            "📍 Última posición: " + lat.toFixed(5) + ", " + lng.toFixed(5) +
            " | Distancia total: " + (totalDistance/1000).toFixed(3) + " km";
    }}

    function stopTracking() {{
        if (watchId) {{
            navigator.geolocation.clearWatch(watchId);
        }}
        let coordsToSend = pathCoords.map(p => [p.lat(), p.lng()]);
        let payload = {{
            coords: coordsToSend,
            distance_km: (totalDistance/1000).toFixed(3)
        }};
        window.parent.postMessage({{isStreamlitMessage: true, type: "TRACK_DATA", data: payload}}, "*");
    }}

    function gm_authFailure() {{
        document.getElementById('status').innerText = "❌ Error de autenticación con Google Maps API.";
    }}
    </script>
    <script async defer
        src="https://maps.googleapis.com/maps/api/js?key={api_key}&libraries=geometry&callback=initMap">
    </script>
    """

# Cronómetro simple que corre al segundo (usa session_state)
def cronometro():
    if "start_time" not in st.session_state:
        st.session_state.start_time = None
    if "running" not in st.session_state:
        st.session_state.running = False

    col1, col2 = st.columns(2)
    with col1:
        if not st.session_state.running:
            if st.button("▶️ Iniciar lectura"):
                st.session_state.start_time = time.time()
                st.session_state.running = True
        else:
            elapsed = int(time.time() - st.session_state.start_time)
            hh = elapsed // 3600
            mm = (elapsed % 3600) // 60
            ss = elapsed % 60
            st.metric("⏳ Tiempo de lectura", f"{hh:02d}:{mm:02d}:{ss:02d}")

    with col2:
        if st.session_state.running:
            if st.button("⏹ Detener lectura"):
                st.session_state.running = False
                return True
    return False

# --------- APP UI ---------
st.title("📚 Reader Tracker Completo")

col_map, col_ctrl = st.columns([2,1])

with col_map:
    st.subheader("Mapa en vivo con ruta (actualiza cada 5s)")
    map_component = components.html(render_live_map(GOOGLE_MAPS_API_KEY), height=520)

with col_ctrl:
    st.subheader("Control de lectura")

    # 1. Subir portada y extraer título y autor
    uploaded_file = st.file_uploader("📸 Foto portada o página", type=["jpg","jpeg","png"])
    titulo_extraido, autor_extraido = "", ""
    if uploaded_file:
        st.image(uploaded_file, caption="Portada subida", use_column_width=True)
        if st.button("🔎 Detectar título y autor con GPT-4o"):
            bytes_im = uploaded_file.read()
            titulo_extraido, autor_extraido = openai_extract_title_author(bytes_im)
            st.success(f"Detectado título: {titulo_extraido}")
            st.success(f"Detectado autor: {autor_extraido}")

    # 2. Campos título y autor (editable)
    titulo = st.text_input("Título del libro", value=titulo_extraido)
    autor = st.text_input("Autor del libro", value=autor_extraido)

    # 3. Consultar Mongo si ya hay total páginas para este libro
    paginas_totales = None
    if titulo.strip():
        libro_db = mongo_collection_libros.find_one({"titulo": {"$regex": f"^{titulo.strip()}$", "$options":"i"}}) if mongo_collection_libros else None
        if libro_db and "paginas_totales" in libro_db:
            paginas_totales = libro_db["paginas_totales"]
            st.info(f"Libro ya registrado con {paginas_totales} páginas.")
        else:
            paginas_totales = st.number_input("Número total de páginas (no encontrado en DB)", min_value=1, step=1)

    # 4. Páginas leídas
    pagina_inicio = st.number_input("Página inicio", min_value=1, max_value=paginas_totales or 9999, step=1, value=1)
    pagina_fin = st.number_input("Página final", min_value=pagina_inicio, max_value=paginas_totales or 9999, step=1, value=pagina_inicio)

    # 5. Resumen / reflexión
    resumen = st.text_area("¿Qué se te quedó de la lectura?")

    # 6. Cronómetro
    lectura_parada = cronometro()

    # 7. Recibir datos JS desde el mapa (ruta y distancia)
    from streamlit_javascript import st_javascript
    tracking_data = st_javascript("""
    new Promise((resolve) => {
        window.addEventListener("message", (event) => {
            if (event.data && event.data.type === "TRACK_DATA") {
                resolve(event.data.data);
            }
        });
    })
    """)

    if lectura_parada:
        if not tracking_data:
            st.warning("No se han recibido datos de ubicación desde el navegador.")
        else:
            # Guardar registro completo en MongoDB
            zona_co = pytz.timezone("America/Bogota")
            now = datetime.now(tz=zona_co)

            paginas_leidas = pagina_fin - pagina_inicio + 1
            duracion_seg = int(time.time() - st.session_state.start_time)

            registro = {
                "titulo": titulo.strip(),
                "autor": autor.strip(),
                "inicio_ts": now,
                "duracion_seg": duracion_seg,
                "paginas_leidas": paginas_leidas,
                "resumen": resumen.strip(),
                "ruta": tracking_data.get("coords", []),
                "distancia_km": float(tracking_data.get("distance_km", 0)),
                "pagina_inicio": pagina_inicio,
                "pagina_fin": pagina_fin,
            }

            # Guardar libro con paginas totales si no existe
            if mongo_collection_libros:
                if not libro_db or "paginas_totales" not in libro_db:
                    mongo_collection_libros.update_one(
                        {"titulo": titulo.strip()},
                        {"$set": {"paginas_totales": paginas_totales}},
                        upsert=True
                    )

            # Guardar lectura
            if mongo_collection_lecturas:
                try:
                    mongo_collection_lecturas.insert_one(registro)
                    st.success("✅ Registro guardado en MongoDB.")
                except Exception as e:
                    st.error(f"Error guardando en MongoDB: {e}")
            else:
                st.info("No hay conexión a MongoDB, registro no guardado.")

            # Limpiar estado
            st.session_state.start_time = None
            st.session_state.running = False

# Historial - mostrar últimas 10 sesiones
st.markdown("---")
st.subheader("📜 Historial de lecturas recientes")
historial = []
if mongo_collection_lecturas:
    try:
        cursor = mongo_collection_lecturas.find().sort("inicio_ts", -1).limit(10)
        historial = list(cursor)
    except Exception as e:
        st.warning(f"No se pudo obtener historial: {e}")

if historial:
    for reg in historial:
        dur_seg = reg.get("duracion_seg", 0)
        hh = dur_seg // 3600
        mm = (dur_seg % 3600) // 60
        ss = dur_seg % 60
        paginas = reg.get("paginas_leidas", "?")
        dist_km = reg.get("distancia_km", 0)

        st.markdown(f"**{reg.get('titulo','Sin título')}** — {reg.get('autor','')}")
        st.write(f"Duración: {hh:02d}:{mm:02d}:{ss:02d} | Páginas leídas: {paginas} | Distancia: {dist_km:.2f} km")
        st.write(f"Resumen: {reg.get('resumen','(vacío)')}")

        # Mostrar ruta con Google Maps Embed (si hay ruta)
        ruta = reg.get("ruta", [])
        if ruta and GOOGLE_MAPS_API_KEY:
            origen = f"{ruta[0][0]},{ruta[0][1]}"
            destino = f"{ruta[-1][0]},{ruta[-1][1]}"
            url_map = (
                f"https://www.google.com/maps/embed/v1/directions?key={GOOGLE_MAPS_API_KEY}"
                f"&origin={origen}&destination={destino}&mode=walking"
            )
            components.html(f'<iframe width="100%" height="220" src="{url_map}" style="border:0"></iframe>', height=220)

        st.markdown("---")
else:
    st.info("No hay lecturas registradas aún.")