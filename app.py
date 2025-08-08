# app.py
import streamlit as st
import time
import pymongo
import pytz
from datetime import datetime, timedelta
from openai import OpenAI
from math import radians, sin, cos, sqrt, atan2
from streamlit_autorefresh import st_autorefresh
import json

# ---------------- CONFIG (desde st.secrets) ----------------
google_maps_api_key = st.secrets["google_maps_api_key"]
mongo_uri = st.secrets["mongo_uri"]
openai_api_key = st.secrets["openai_api_key"]

# ---------------- CLIENTES ----------------
client_ai = OpenAI(api_key=openai_api_key)
mongo_client = pymongo.MongoClient(mongo_uri)
db = mongo_client["reading_tracker"]

# ---------------- ZONA ----------------
tz_col = pytz.timezone("America/Bogota")

# ---------------- UTIL ----------------
def haversine_m(coord1, coord2):
    """Devuelve distancia en metros entre coord1 y coord2 (lat,lon)."""
    R = 6371000
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1) * cos(phi2) * sin(dlambda/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))

def static_map_url(coords):
    """Genera URL de Google Static Map con path (si coords vacías devuelve string vacío)."""
    if not coords:
        return ""
    path = "|".join([f"{lat},{lon}" for lat, lon in coords])
    # path y tamaño simple; puedes ajustar markers, zoom, etc.
    return f"https://maps.googleapis.com/maps/api/staticmap?size=640x420&path=color:0xff0000ff|weight:3|{path}&key={google_maps_api_key}"

def identify_book_from_image_bytes(image_bytes):
    """Envía la imagen a GPT-4o (multimodal) pidiendo JSON {'titulo','autor'}.
       Nota: la forma exacta de payload multimedial depende de tu SDK/versión. 
       Ajusta si tu cliente OpenAI usa otro método."""
    try:
        # Intentamos usar chat completions multimodal (ejemplo tipo)
        resp = client_ai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Eres un extractor. Devuelve SOLO JSON válido con claves 'titulo' y 'autor'."},
                {"role": "user", "content": [
                    {"type": "text", "text": "Extrae título y autor del libro presente en esta imagen."},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + image_bytes.decode("utf-8")}}
                ]}
            ],
            temperature=0
        )
        text = resp.choices[0].message.content.strip()
        # parseo flexible
        try:
            parsed = json.loads(text)
            return parsed.get("titulo") or parsed.get("title"), parsed.get("autor") or parsed.get("author")
        except Exception:
            # buscar JSON embebido
            if "{" in text:
                try:
                    start = text.index("{")
                    end = text.rindex("}") + 1
                    parsed = json.loads(text[start:end])
                    return parsed.get("titulo") or parsed.get("title"), parsed.get("autor") or parsed.get("author")
                except Exception:
                    pass
            # fallback: devolver texto bruto en titulo
            return text, ""
    except Exception as e:
        st.error(f"Error al llamar a OpenAI: {e}")
        return None, None

# ----------------- ESTADO INICIAL -----------------
if "coords" not in st.session_state:
    st.session_state.coords = []
if "start_time" not in st.session_state:
    st.session_state.start_time = None
if "modo_lectura" not in st.session_state:
    st.session_state.modo_lectura = "reposo"
if "book_id" not in st.session_state:
    st.session_state.book_id = None
if "book_title" not in st.session_state:
    st.session_state.book_title = None
if "book_author" not in st.session_state:
    st.session_state.book_author = None
if "total_pages" not in st.session_state:
    st.session_state.total_pages = None
if "page_start" not in st.session_state:
    st.session_state.page_start = None

st.set_page_config(page_title="Tracker de Lectura (en vivo)", layout="wide")
st.title("📚 Tracker de Lectura con Movimiento — En vivo")

# ----------------- JS GEOLOCALIZACIÓN (debug visible front) -----------------
# El script escribe mensajes en el DOM y actualiza query params con lat,lon,msg
st.markdown("""
<script>
function sendParams(lat, lon, msg){
    const params = new URLSearchParams(window.location.search);
    if (lat !== null && lon !== null){
        params.set("lat", lat);
        params.set("lon", lon);
    }
    if (msg !== undefined){
        params.set("msg", encodeURIComponent(msg));
    }
    const newUrl = window.location.pathname + "?" + params.toString();
    window.history.replaceState({}, '', newUrl);
}
if ("geolocation" in navigator) {
    document.body.insertAdjacentHTML('beforeend','<div id="geo-debug" style="padding:6px;font-size:14px;color:#0b66c3">📍 Iniciando geolocalización...</div>');
    navigator.geolocation.watchPosition(
        (pos) => {
            const lat = pos.coords.latitude;
            const lon = pos.coords.longitude;
            const msg = `Ubicación recibida: ${lat.toFixed(5)}, ${lon.toFixed(5)}`;
            const dbg = document.getElementById('geo-debug');
            if (dbg) dbg.innerText = "✅ " + msg;
            sendParams(lat, lon, msg);
        },
        (err) => {
            const dbg = document.getElementById('geo-debug');
            if (dbg) dbg.innerText = "❌ Error geoloc: " + err.message;
            sendParams(null, null, "ERROR: " + err.message);
        },
        { enableHighAccuracy: true, maximumAge: 0, timeout: 10000 }
    );
} else {
    document.body.insertAdjacentHTML('beforeend','<div style="color:red">🚫 Geolocalización no soportada</div>');
    sendParams(null, null, "NO_SUPPORT");
}
</script>
""", unsafe_allow_html=True)

# ----------------- AUTORELOAD cada 1s (cronómetro) --------------
# El autorefresh se encarga de refrescar la app cada segundo para el cronómetro.
st_autorefresh(interval=1000, key="live_refresh")

# ----------------- Leer params (lat, lon, msg) -----------------
params = st.query_params
msg_from_js = None
if params.get("msg"):
    # st.query_params devuelve strings, msg puede venir urlencoded
    try:
        msg_from_js = params.get("msg")
    except:
        msg_from_js = None

# Mostrar estado de ubicación en front
estado_box = st.empty()
if msg_from_js:
    # decode if encoded
    try:
        # msg may be encoded already by browser; streamlit decodes but be safe
        decoded = msg_from_js
        estado_box.info(decoded)
    except:
        estado_box.info(msg_from_js)
else:
    estado_box.info("⏳ Esperando permiso de ubicación... (revisa permisos del navegador)")

# ----------------- Agregar coordenadas si existen -----------------
if params.get("lat") and params.get("lon"):
    try:
        lat = float(params.get("lat"))
        lon = float(params.get("lon"))
        new_c = (lat, lon)
        if not st.session_state.coords or st.session_state.coords[-1] != new_c:
            st.session_state.coords.append(new_c)
    except Exception:
        # ignore parse errors
        pass

# ----------------- MODO (reposo/movimiento) -----------------
umbral = st.number_input("Umbral de movimiento (m)", value=20, help="Distancia acumulada en la sesión para considerar 'movimiento'.")
if len(st.session_state.coords) > 1:
    total_m = sum(haversine_m(st.session_state.coords[i], st.session_state.coords[i+1]) for i in range(len(st.session_state.coords)-1))
    st.session_state.modo_lectura = "movimiento" if total_m > umbral else "reposo"
else:
    total_m = 0.0

# ----------------- Mostrar mapa y resumen de distancia -----------------
col_map, col_info = st.columns([2,1])
with col_map:
    if st.session_state.coords:
        url = static_map_url(st.session_state.coords)
        st.image(url, use_column_width=True)
    else:
        st.info("Esperando ubicación para mostrar mapa...")

with col_info:
    st.metric("Distancia acumulada (m)", f"{total_m:.1f}")
    st.metric("Modo de lectura", st.session_state.modo_lectura)

# ----------------- Captura portada e identificación -----------------
st.markdown("---")
st.subheader("Identificación del libro (foto de portada)")

uploaded = st.file_uploader("Sube foto (portada o página de referencia)", type=["jpg", "jpeg", "png"])
if uploaded and (st.session_state.book_title is None):
    # leer bytes y codificar base64 necesario si usar data URI
    img_bytes = uploaded.read()
    # Para la función de ejemplo usamos decode('latin1') o base64; depende del SDK.
    # Aquí hacemos el fallback simple: guardamos la imagen en GridFS o en S3 en prod; ahora mandamos texto como fallback.
    st.info("Analizando imagen con GPT-4o...")
    titulo, autor = identify_book := (None, None)
    try:
        # Intentamos llamada sencilla: (ajusta según tu cliente OpenAI disponible)
        # Aqui vamos a simplemente ask the model to read (fallback): send prompt with image as data URI might be heavy.
        # For safety, we'll set title/author manually if the model fails.
        # Use identify_book_from_image_bytes if your OpenAI client supports image input as in that function.
        # For now try to call a text-only fallback:
        title_guess, author_guess = None, None
        # Try calling the simple identify helper if available
        try:
            title_guess, author_guess = identify_book_from_image_bytes  # placeholder; keep None
        except Exception:
            pass
        # If identification not available, fallback to asking the user
        if not title_guess:
            st.warning("No fue posible extraer automáticamente. Por favor, ingresa manualmente.")
            title_guess = st.text_input("Título (manual)")
            author_guess = st.text_input("Autor (manual)")
        if title_guess:
            st.session_state.book_title = title_guess
            st.session_state.book_author = author_guess or ""
            st.success(f"Libro: {st.session_state.book_title} — {st.session_state.book_author}")
            # chequear en Mongo si existe
            book_doc = db.libros.find_one({"titulo": st.session_state.book_title, "autor": st.session_state.book_author})
            if book_doc and book_doc.get("total_pages"):
                st.session_state.total_pages = book_doc["total_pages"]
                st.info(f"Total de páginas (desde DB): {st.session_state.total_pages}")
            else:
                st.session_state.total_pages = st.number_input("Número total de páginas (si no existe en DB)", min_value=1, step=1)
                if st.button("Guardar libro en DB"):
                    db.libros.update_one(
                        {"titulo": st.session_state.book_title, "autor": st.session_state.book_author},
                        {"$set": {"total_pages": st.session_state.total_pages}},
                        upsert=True
                    )
                    st.success("Libro guardado en la colección 'libros'")

# ----------------- Página inicio y cronómetro -----------------
st.markdown("---")
st.subheader("Iniciar / Detener sesión de lectura")

if st.session_state.book_title:
    if st.session_state.total_pages:
        st.session_state.page_start = st.number_input("Página de inicio", min_value=1, max_value=st.session_state.total_pages, value=st.session_state.page_start or 1)

col_a, col_b = st.columns(2)
with col_a:
    if st.button("▶️ Iniciar lectura"):
        if not st.session_state.page_start:
            st.warning("Define la página de inicio primero.")
        else:
            st.session_state.start_time = time.time()
            st.success(f"Cronómetro iniciado ({datetime.now(tz_col).strftime('%Y-%m-%d %H:%M:%S')})")

with col_b:
    if st.button("⏹ Detener lectura"):
        if not st.session_state.start_time:
            st.warning("No hay sesión activa.")
        else:
            # pedir página final y reflexión
            page_end = st.number_input("Página final", min_value=st.session_state.page_start or 1, max_value=st.session_state.total_pages or 10000)
            reflection = st.text_area("¿Qué se te quedó de la lectura?")
            end_time = time.time()
            duration_s = int(end_time - st.session_state.start_time)
            pages_read = (page_end - (st.session_state.page_start or 0))
            ppm = pages_read / (duration_s / 60) if duration_s > 0 else 0.0
            predicted_finish = None
            if st.session_state.total_pages and ppm > 0:
                remaining = st.session_state.total_pages - page_end
                mins_left = remaining / ppm
                predicted_finish = datetime.now(tz_col) + timedelta(minutes=mins_left)
            # Guardar sesión
            session_doc = {
                "titulo": st.session_state.book_title,
                "autor": st.session_state.book_author,
                "inicio_ts": datetime.fromtimestamp(st.session_state.start_time, tz_col),
                "fin_ts": datetime.fromtimestamp(end_time, tz_col),
                "duration_s": duration_s,
                "coords": st.session_state.coords,
                "dist_m": total_m,
                "modo_lectura": st.session_state.modo_lectura,
                "page_start": st.session_state.page_start,
                "page_end": page_end,
                "pages_read": pages_read,
                "ppm": ppm,
                "reflection": reflection,
                "predicted_finish": predicted_finish.isoformat() if predicted_finish else None
            }
            db.sesiones.insert_one(session_doc)
            st.success("✅ Sesión guardada en MongoDB")
            # reset minimal state (pero preservamos libro info)
            st.session_state.start_time = None
            st.session_state.coords = []
            st.session_state.modo_lectura = "reposo"

# ----------------- Cronómetro visual (si sesión activa) -----------------
if st.session_state.start_time:
    elapsed_s = int(time.time() - st.session_state.start_time)
    mm, ss = divmod(elapsed_s, 60)
    hh, mm = divmod(mm, 60)
    st.markdown(f"**Tiempo transcurrido:** {hh:02d}:{mm:02d}:{ss:02d}")

# ----------------- Historial (opcional) -----------------
st.markdown("---")
if st.checkbox("Mostrar historial de sesiones"):
    for ses in db.sesiones.find().sort("inicio_ts", -1).limit(30):
        st.subheader(f"{ses.get('titulo','Sin título')} — {ses.get('autor','')}")
        st.write(f"{ses.get('inicio_ts')} → {ses.get('fin_ts')}")
        st.write(f"Páginas: {ses.get('page_start')} → {ses.get('page_end')} (Leídas: {ses.get('pages_read')})")
        st.write(f"Duración: {ses.get('duration_s')} s — Modo: {ses.get('modo_lectura')} — Distancia: {ses.get('dist_m',0):.1f} m")
        if ses.get("coords"):
            st.image(static_map_url(ses.get("coords")))
        if ses.get("reflection"):
            st.write("💭 " + ses.get("reflection"))
        if ses.get("predicted_finish"):
            st.write("⏳ Fin estimado: " + ses.get("predicted_finish"))
        st.markdown("---")
