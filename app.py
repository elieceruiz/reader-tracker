import streamlit as st
from PIL import Image
import base64
import openai
import datetime
import pymongo
import requests
import pandas as pd
import math
from streamlit_js_eval import streamlit_js_eval

# ---------------- CONFIGURACIÓN INICIAL ----------------
st.set_page_config(page_title="📚 Seguimiento lector con cronómetro", layout="centered")

# MongoDB (opcional — si no la usas, puedes comentar estas líneas)
mongo_client = None
collection = None
if "mongo_uri" in st.secrets:
    try:
        mongo_client = pymongo.MongoClient(st.secrets["mongo_uri"])
        db = mongo_client["seguimiento_lector"]
        collection = db["registros"]
    except Exception as e:
        st.warning("No se pudo conectar a MongoDB: " + str(e))

# OpenAI
if "openai_api_key" in st.secrets:
    openai.api_key = st.secrets["openai_api_key"]
if "openai_org_id" in st.secrets:
    openai.organization = st.secrets["openai_org_id"]

# Google Maps key
google_maps_key = st.secrets.get("google_maps_api_key", None)
if not google_maps_key:
    st.warning("No encontré google_maps_api_key en st.secrets — el mapa de Google no funcionará hasta que la agregues.")

# ---------------- FUNCIONES ----------------
@st.cache_data(ttl=3600)
def obtener_geolocalizacion_ip():
    """Fallback si no hay geolocalización del navegador: ubica por IP (servidor -> puede ser The Dalles)."""
    try:
        res = requests.get("http://ip-api.com/json/", timeout=5)
        data = res.json()
        if data.get("status") == "success":
            return {"lat": data["lat"], "lon": data["lon"], "city": data.get("city"), "country": data.get("country")}
    except Exception:
        pass
    return None

def haversine(lat1, lon1, lat2, lon2):
    """Distancia en km entre dos coordenadas."""
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2.0)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2.0)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def mostrar_mapa_google_center(lat, lon, zoom=15, height=300):
    if not google_maps_key:
        st.info("No hay API Key de Google Maps. Se omitirá mapa embebido.")
        return
    map_html = f"""
        <iframe
            width="100%"
            height="{height}"
            style="border:0"
            loading="lazy"
            allowfullscreen
            referrerpolicy="no-referrer-when-downgrade"
            src="https://www.google.com/maps/embed/v1/view?key={google_maps_key}&center={lat},{lon}&zoom={zoom}&maptype=roadmap">
        </iframe>
    """
    st.components.v1.html(map_html, height=height)

def mostrar_mapa_google_directions(lat1, lon1, lat2, lon2, mode="walking", height=350):
    if not google_maps_key:
        st.info("No hay API Key de Google Maps. Se omitirá mapa embebido.")
        return
    url = (
        f"https://www.google.com/maps/embed/v1/directions?"
        f"key={google_maps_key}&origin={lat1},{lon1}&destination={lat2},{lon2}&mode={mode}"
    )
    st.components.v1.html(f'<iframe width="100%" height="{height}" src="{url}"></iframe>', height=height)

def detectar_titulo(image_bytes):
    """Usa OpenAI Vision vía chat completions con imagen embebida en data URI.
       Devuelve título detectado o ''."""
    if not getattr(openai, "api_key", None):
        return ""
    try:
        base64_image = base64.b64encode(image_bytes).decode("utf-8")

        # 1) Clasificar tipo
        cls_resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": "Analiza esta imagen y responde SOLO con una de estas opciones: 'portada', 'pagina interior', 'referencia interna', 'otro'. No expliques nada más."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=6,
            temperature=0
        )
        clasificacion = cls_resp.choices[0].message.content.strip().lower()
    except Exception as e:
        st.warning(f"Error clasificando imagen: {e}")
        return ""

    try:
        if clasificacion in ["portada", "referencia interna"]:
            prompt = "Observa la imagen y responde con el título exacto del libro. No incluyas explicaciones ni otro texto."
        elif clasificacion == "pagina interior":
            prompt = "Extrae cualquier texto relevante de esta página y deduce si contiene el título del libro. Si lo encuentras, responde solo con el título; si no, responde 'No encontrado'."
        else:
            return ""

        resp = openai.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=80,
            temperature=0
        )
        titulo = resp.choices[0].message.content.strip()
        return titulo if titulo.lower() != "no encontrado" else ""
    except Exception as e:
        st.warning(f"Error extrayendo título: {e}")
        return ""

def obtener_ubicacion_navegador():
    """Pide coordenadas al navegador via streamlit_js_eval.
       Devuelve dict {'lat':..., 'lon': ...} o None."""
    try:
        # Ejecuta getCurrentPosition y devuelve coords; si falla, None.
        coords = streamlit_js_eval(
            js_expressions="""
            new Promise((resolve, reject) => {
                if (!navigator.geolocation) { resolve(null); return; }
                navigator.geolocation.getCurrentPosition(
                    (pos) => resolve({latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
                    (err) => resolve(null),
                    {enableHighAccuracy: true, timeout: 10000}
                );
            })
            """,
            key="get_geo"
        )
        if coords and "latitude" in coords and "longitude" in coords:
            return {"lat": float(coords["latitude"]), "lon": float(coords["longitude"])}
    except Exception:
        pass
    return None

# ---------------- ESTADO ----------------
if "inicio_lectura" not in st.session_state:
    st.session_state.inicio_lectura = None
if "geo_inicio" not in st.session_state:
    st.session_state.geo_inicio = None
if "registro_parcial" not in st.session_state:
    st.session_state.registro_parcial = None
if "historial" not in st.session_state:
    st.session_state.historial = []

# ---------------- PÁGINA DE INICIO ----------------
st.title("📚 Seguimiento lector con cronómetro y ubicación")

col1, col2 = st.columns([2,1])

with col1:
    st.markdown("**Mapa (ubicación del dispositivo — pide permiso en el navegador)**")
    # Intentamos obtener ubicación desde navegador:
    browser_geo = obtener_ubicacion_navegador()
    if browser_geo:
        st.success("Ubicación del dispositivo obtenida ✅")
        st.write(f"Lat: {browser_geo['lat']:.6f}, Lon: {browser_geo['lon']:.6f}")
        mostrar_mapa_google_center(browser_geo['lat'], browser_geo['lon'], zoom=16, height=300)
    else:
        st.info("No se obtuvo ubicación del navegador. Usando fallback por IP (puede ser la ubicación del servidor).")
        geo_ip = obtener_geolocalizacion_ip()
        if geo_ip:
            st.write(f"Ciudad: **{geo_ip.get('city','?')}**, País: **{geo_ip.get('country','?')}**")
            mostrar_mapa_google_center(geo_ip['lat'], geo_ip['lon'], zoom=13, height=300)
        else:
            st.warning("No se pudo determinar ninguna ubicación.")

with col2:
    st.markdown("### Controles")
    st.write("Pulsa **Iniciar lectura** cuando comiences a leer. Pulsa **Detener lectura** cuando finalices.")
    if not st.session_state.inicio_lectura:
        if st.button("▶️ Iniciar lectura"):
            # toma la ubicación actual del navegador si existe, si no, fallback IP
            inicio_geo = browser_geo or obtener_geolocalizacion_ip()
            if not inicio_geo:
                st.error("No se pudo obtener ubicación de inicio.")
            else:
                st.session_state.inicio_lectura = datetime.datetime.now()
                st.session_state.geo_inicio = inicio_geo
                st.success("Lectura iniciada.")
    else:
        tiempo_transcurrido = datetime.datetime.now() - st.session_state.inicio_lectura
        st.info(f"⏱ Tiempo de lectura: {str(tiempo_transcurrido).split('.')[0]}")
        if st.button("⏹ Detener lectura"):
            # al detener pedimos nuevamente coords del navegador para fin
            fin_geo_browser = obtener_ubicacion_navegador()
            fin_geo = fin_geo_browser or obtener_geolocalizacion_ip()
            tiempo_total = datetime.datetime.now() - st.session_state.inicio_lectura
            distancia = None
            if st.session_state.geo_inicio and fin_geo:
                try:
                    distancia = haversine(
                        st.session_state.geo_inicio["lat"], st.session_state.geo_inicio["lon"],
                        fin_geo["lat"], fin_geo["lon"]
                    )
                except Exception:
                    distancia = None

            # crear registro parcial
            st.session_state.registro_parcial = {
                "fecha_inicio": st.session_state.inicio_lectura,
                "fecha_fin": datetime.datetime.now(),
                "lat_inicio": st.session_state.geo_inicio.get("lat") if st.session_state.geo_inicio else None,
                "lon_inicio": st.session_state.geo_inicio.get("lon") if st.session_state.geo_inicio else None,
                "lat_fin": fin_geo.get("lat") if fin_geo else None,
                "lon_fin": fin_geo.get("lon") if fin_geo else None,
                "tiempo_total": str(tiempo_total).split('.')[0],
                "distancia_km": round(distancia, 3) if distancia else None
            }
            # reset inicio
            st.session_state.inicio_lectura = None
            st.success("Lectura detenida. Completa los datos del libro para guardar el registro.")

# ---------------- REGISTRO DE LIBRO (si hay registro parcial) ----------------
if st.session_state.registro_parcial:
    st.subheader("📖 Detalles de la lectura (registro parcial)")

    uploaded_file = st.file_uploader("Sube portada o página interior del libro (opcional)", type=["jpg", "jpeg", "png"])
    book_title = ""
    if uploaded_file:
        try:
            image_bytes = uploaded_file.read()
            st.image(Image.open(uploaded_file), caption="Imagen subida", use_container_width=True)
            st.text("🧠 Detectando título...")
            book_title = detectar_titulo(image_bytes)
            if book_title:
                st.success(f"Título detectado: *{book_title}*")
            else:
                st.warning("No se pudo detectar el título automáticamente.")
        except Exception as e:
            st.warning("Error procesando imagen: " + str(e))

    titulo_final = st.text_input("Título del libro", value=book_title)
    comentario = st.text_area("Comentario o reflexión", height=140)

    col_save1, col_save2 = st.columns([1,1])
    with col_save1:
        if st.button("💾 Guardar registro completo"):
            datos = {**st.session_state.registro_parcial,
                     "titulo": titulo_final.strip(),
                     "comentario": comentario.strip(),
                     "guardado_en": "local" if not collection else "mongodb"
                     }
            # guardar en Mongo si está configurado
            if collection:
                try:
                    collection.insert_one(datos)
                    st.success("✅ Registro guardado en MongoDB.")
                except Exception as e:
                    st.warning("No se pudo guardar en MongoDB: " + str(e))
                    st.session_state.historial.insert(0, datos)
                    st.success("✅ Registro guardado en historial de sesión.")
            else:
                st.session_state.historial.insert(0, datos)
                st.success("✅ Registro guardado en historial de sesión.")

            # limpiar registro parcial
            st.session_state.registro_parcial = None
            # opcional: mostrar mapa de la sesión guardada
    with col_save2:
        if st.button("✖ Cancelar y descartar"):
            st.session_state.registro_parcial = None
            st.warning("Registro descartado.")

# ---------------- HISTORIAL ----------------
st.subheader("🕓 Historial de lecturas")

# Cargar historial desde Mongo si existe (mostramos ambos: local + mongo)
hist = list(st.session_state.historial)  # copia local
if collection:
    try:
        docs = list(collection.find().sort("fecha_inicio", -1).limit(50))
        # transformar ObjectId y fechas para mostrar
        for d in docs:
            # si ya está en historial local no repetir (comprobando fecha_inicio)
            if not any(h.get("fecha_inicio") == d.get("fecha_inicio") for h in hist):
                hist.append(d)
    except Exception:
        pass

if hist:
    for r in hist:
        titulo = r.get("titulo", "Sin título")
        st.markdown(f"**📖 {titulo}**")
        # formatear fechas si vienen como datetime
        fi = r.get("fecha_inicio")
        ff = r.get("fecha_fin")
        try:
            fi_str = fi.strftime("%Y-%m-%d %H:%M:%S") if hasattr(fi, "strftime") else str(fi)
            ff_str = ff.strftime("%Y-%m-%d %H:%M:%S") if hasattr(ff, "strftime") else str(ff)
        except Exception:
            fi_str = str(fi)
            ff_str = str(ff)
        st.caption(f"{fi_str} → {ff_str}")
        if r.get("tiempo_total"):
            st.write(f"⏱ {r['tiempo_total']}")
        if r.get("distancia_km") is not None:
            st.write(f"🚶 Distancia: {r['distancia_km']} km")
        if r.get("comentario"):
            st.write(r["comentario"])

        # Mostrar mapa con ruta si hay inicio y fin
        if r.get("lat_inicio") and r.get("lon_inicio") and r.get("lat_fin") and r.get("lon_fin"):
            try:
                mostrar_mapa_google_directions(r["lat_inicio"], r["lon_inicio"], r["lat_fin"], r["lon_fin"], mode="walking", height=220)
            except Exception:
                # fallback: mostrar marcador del inicio
                mostrar_mapa_google_center(r["lat_inicio"], r["lon_inicio"], zoom=14, height=220)
        elif r.get("lat_inicio") and r.get("lon_inicio"):
            mostrar_mapa_google_center(r["lat_inicio"], r["lon_inicio"], zoom=14, height=220)

        st.markdown("---")
else:
    st.info("No hay lecturas registradas.")