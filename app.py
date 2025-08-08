import streamlit as st
import time
import base64
import json
import math
from datetime import datetime
import pytz
import pymongo
import openai
from streamlit_js_eval import streamlit_js_eval
from streamlit.components.v1 import html

# ---------------- CONFIG ----------------
st.set_page_config(page_title="Reader Tracker (dinámico)", layout="wide")

# Secrets
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key")
openai_api_key = st.secrets.get("openai_api_key")
openai.organization = st.secrets.get("openai_org_id", None)

if not google_maps_api_key:
    st.error("Agrega google_maps_api_key en tus secrets para que funcione el mapa.")
if not openai_api_key:
    st.error("Agrega openai_api_key en tus secrets para que funcione OpenAI.")

# Conexión MongoDB
mongo_collection = None
if mongo_uri:
    try:
        client = pymongo.MongoClient(mongo_uri)
        db = client["reader_tracker"]
        mongo_collection = db["lecturas"]
    except Exception as e:
        st.warning(f"No se pudo conectar a MongoDB: {e}")

# ---------------- UTILIDADES ----------------
def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def openai_extract_title_author(image_bytes):
    openai.api_key = openai_api_key
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
        st.warning(f"Error al llamar a OpenAI: {e}")
        return "", ""

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
          let poly;
          let path = [];

          function initMap() {{
            map = new google.maps.Map(document.getElementById('map'), {{
              zoom: 17,
              center: {{lat:{center_lat}, lng:{center_lon}}},
              mapTypeId: 'roadmap'
            }});
            marker = new google.maps.Marker({{ map: map, position: {{lat:{center_lat}, lng:{center_lon}}}, title: "Tú" }});
            poly = new google.maps.Polyline({{
              strokeColor: '#FF0000',
              strokeOpacity: 1.0,
              strokeWeight: 3,
              path: path
            }});
            poly.setMap(map);
          }}

          function updatePosition(pos) {{
            const lat = pos.coords.latitude;
            const lng = pos.coords.longitude;
            const latlng = new google.maps.LatLng(lat, lng);
            marker.setPosition(latlng);
            map.setCenter(latlng);
            path.push(latlng);
            poly.setPath(path);
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

# ---------------- UI & FLUJO ----------------
st.title("📚 Reader Tracker — Mapa dinámico + GPT-4o (título y autor)")

col_map, col_ctrl = st.columns((2,1))

with col_map:
    st.subheader("Mapa en vivo (permite seguimiento del movimiento del celu)")
    if google_maps_api_key:
        render_live_map(google_maps_api_key, height=520, center_coords=st.session_state.get("start_coords"))
    else:
        st.info("Añadí google_maps_api_key en st.secrets para ver el mapa dinámico.")

with col_ctrl:
    st.subheader("Controles")

    st.markdown("**1)** Capturar ubicación de inicio (botón). Esto toma una lectura puntual del navegador y la guarda como inicio.")

    if "start_coords" not in st.session_state:
        st.session_state["start_coords"] = None

    if st.button("📍 Capturar ubicación inicio"):
        js_getpos = """
        new Promise((resolve) => {
          if (!navigator.geolocation) { resolve(null); return; }
          navigator.geolocation.getCurrentPosition(
            (pos) => resolve({latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
            (err) => resolve(null),
            {enableHighAccuracy: true, timeout:10000}
          );
        })
        """
        coords = streamlit_js_eval(js_expressions=js_getpos, key="getpos_start")
        if coords:
            st.session_state["start_coords"] = (float(coords["latitude"]), float(coords["longitude"]))
            st.success(f"📍 Ubicación de inicio confirmada: Latitude {st.session_state['start_coords'][0]:.6f}, Longitude {st.session_state['start_coords'][1]:.6f} ✔️")
        else:
            st.error("No se pudo obtener la ubicación desde el navegador. Asegurate de dar permiso.")

    if st.session_state["start_coords"]:
        lat, lon = st.session_state["start_coords"]
        st.markdown(f"### 📍 Ubicación confirmada: **Lat {lat:.6f}**, **Lon {lon:.6f}** ✔️")

    st.markdown("---")
    st.markdown("**2)** Sube la foto de la portada (opcional) y detectá título/autor con GPT-4o.")

    uploaded = st.file_uploader("Foto (portada o página interior clara)", type=["jpg","jpeg","png"])

    titulo_sugerido = ""
    autor_sugerido = ""

    if uploaded:
        # No mostramos la imagen para que no quede visible en la UI
        if st.button("🔎 Detectar título y autor (GPT-4o)"):
            image_bytes = uploaded.read()
            with st.spinner("Analizando imagen con GPT-4o..."):
                t, a = openai_extract_title_author(image_bytes)
            if t or a:
                titulo_sugerido = t
                autor_sugerido = a
                st.success("Detección completada.")
            else:
                st.warning("No se detectó título/autor con confianza.")
        uploaded = None

    titulo = st.text_input("Título (confirmá o edita)", value=titulo_sugerido)
    autor = st.text_input("Autor (confirmá o edita)", value=autor_sugerido)

    # Verificamos en MongoDB si ya tenemos páginas para el libro
    paginas_totales = None
    if mongo_collection is not None and titulo.strip() != "":
        libro = mongo_collection.database["libros"].find_one({"titulo": titulo})
        if libro and "paginas_totales" in libro:
            paginas_totales = libro["paginas_totales"]

    if paginas_totales is not None:
        st.info(f"Número total de páginas registrado: {paginas_totales}")
    else:
        paginas_totales = st.number_input("Número total de páginas (si no está registrado)", min_value=1, step=1)

    st.markdown("---")
    st.markdown("**3)** Cronómetro manual — iniciar cuando comiences a leer.")
    if "reading_started" not in st.session_state:
        st.session_state["reading_started"] = False
    if not st.session_state["reading_started"]:
        if st.button("▶️ Iniciar lectura"):
            if "start_coords" not in st.session_state or st.session_state["start_coords"] is None:
                st.error("Primero capturá la ubicación de inicio con 'Capturar ubicación inicio'.")
            elif titulo.strip() == "":
                st.error("Por favor ingresá o detectá el título del libro antes de iniciar.")
            else:
                st.session_state["reading_started"] = True
                st.session_state["start_time"] = time.time()
                st.session_state["titulo"] = titulo
                st.session_state["autor"] = autor
                st.session_state["paginas_totales"] = paginas_totales
                st.success("Cronómetro iniciado.")
    else:
        elapsed = int(time.time() - st.session_state["start_time"])
        hh = elapsed // 3600
        mm = (elapsed % 3600) // 60
        ss = elapsed % 60
        st.metric("Tiempo transcurrido", f"{hh:02d}:{mm:02d}:{ss:02d}")

        if st.button("⏹ Detener lectura"):
            js_getpos_end = """
            new Promise((resolve) => {
              if (!navigator.geolocation) { resolve(null); return; }
              navigator.geolocation.getCurrentPosition(
                (pos) => resolve({latitude: pos.coords.latitude, longitude: pos.coords.longitude}),
                (err) => resolve(null),
                {enableHighAccuracy: true, timeout:10000}
              );
            })
            """
            coords_end = streamlit_js_eval(js_expressions=js_getpos_end, key="getpos_end")
            if not coords_end:
                st.error("No se pudo obtener ubicación final desde el navegador.")
            else:
                end_coords = (float(coords_end["latitude"]), float(coords_end["longitude"]))
                start_coords = st.session_state["start_coords"]
                duration_sec = int(time.time() - st.session_state["start_time"])
                duration_str = f"{duration_sec//3600:02d}:{(duration_sec%3600)//60:02d}:{duration_sec%60:02d}"
                distancia_km = haversine_km(start_coords[0], start_coords[1], end_coords[0], end_coords[1])
                modo = "En movimiento" if (distancia_km * 1000) > 10 else "En reposo"

                # Página inicio y final
                pagina_inicio = st.number_input("Página de inicio", min_value=1, max_value=paginas_totales or 10000, value=1)
                pagina_fin = st.number_input("Página final", min_value=pagina_inicio, max_value=paginas_totales or 10000, value=pagina_inicio)

                paginas_leidas = pagina_fin - pagina_inicio + 1

                resumen = st.text_area("¿Qué se te quedó de la lectura?")

                registro = {
                    "titulo": st.session_state.get("titulo", ""),
                    "autor": st.session_state.get("autor", ""),
                    "inicio_ts": datetime.utcnow().replace(tzinfo=pytz.UTC),
                    "inicio_coords": {"lat": start_coords[0], "lon": start_coords[1]},
                    "fin_ts": datetime.utcnow().replace(tzinfo=pytz.UTC),
                    "fin_coords": {"lat": end_coords[0], "lon": end_coords[1]},
                    "duracion_sec": duration_sec,
                    "duracion_str": duration_str,
                    "distancia_km": round(distancia_km, 4),
                    "modo": modo,
                    "pagina_inicio": pagina_inicio,
                    "pagina_fin": pagina_fin,
                    "paginas_leidas": paginas_leidas,
                    "resumen": resumen,
                    "paginas_totales": paginas_totales,
                }

                # Guardar páginas totales en colección libros si no estaba registrado
                if mongo_collection is not None:
                    try:
                        if paginas_totales is not None:
                            libros_col = mongo_collection.database["libros"]
                            libros_col.update_one(
                                {"titulo": registro["titulo"]},
                                {"$set": {"paginas_totales": paginas_totales}},
                                upsert=True,
                            )
                    except Exception as e:
                        st.warning(f"No se pudo actualizar colección libros: {e}")

                # Guardar lectura en Mongo o local
                if mongo_collection is not None:
                    try:
                        mongo_collection.insert_one(registro)
                        st.success("Registro guardado en MongoDB ✅")
                    except Exception as e:
                        st.warning(f"No se pudo guardar en MongoDB: {e}")
                        st.session_state.setdefault("historia_local", []).insert(0, registro)
                else:
                    st.session_state.setdefault("historia_local", []).insert(0, registro)
                    st.success("Registro guardado (local en sesión).")

                # Mostrar resumen y mapa con ruta
                st.write(f"**Resumen:** {registro['titulo']} — {registro['autor']}")
                st.write(f"Duración: {registro['duracion_str']} — Distancia: {registro['distancia_km']*1000:.1f} m — {registro['modo']}")
                
                if google_maps_api_key:
                    origin = f"{start_coords[0]},{start_coords[1]}"
                    dest = f"{end_coords[0]},{end_coords[1]}"
                    directions_url = (
                        f"https://www.google.com/maps/embed/v1/directions?key={google_maps_api_key}"
                        f"&origin={origin}&destination={dest}&mode=walking"
                    )
                    st.components.v1.html(f'<iframe width="100%" height="320" src="{directions_url}" style="border:0"></iframe>', height=320)
                else:
                    st.warning("No hay google_maps_api_key para mostrar ruta.")

                st.session_state["reading_started"] = False
                if "start_coords" in st.session_state:
                    del st.session_state["start_coords"]

    st.markdown("---")
    st.subheader("Historial (local + Mongo)")
    historia = st.session_state.get("historia_local", [])
    if mongo_collection is not None:
        try:
            docs = list(mongo_collection.find().sort("inicio_ts", -1).limit(30))
            for d in docs:
                historia.append({
                    "titulo": d.get("titulo", ""),
                    "autor": d.get("autor", ""),
                    "duracion_str": f"{int(d.get('duracion_sec', 0)//3600):02d}:{int(d.get('duracion_sec',0)%3600//60):02d}:{int(d.get('duracion_sec',0)%60):02d}",
                    "distancia_km": d.get("distancia_km", 0),
                    "inicio_coords": d.get("inicio_coords"),
                    "fin_coords": d.get("fin_coords"),
                    "modo": d.get("modo", "")
                })
        except Exception:
            pass

    if historia:
        for h in historia:
            st.markdown(f"**{h.get('titulo','Sin título')}** — {h.get('autor','')}")
            st.write(f"Duración: {h.get('duracion_str','?')} — Distancia: {round(h.get('distancia_km',0)*1000,1)} m — {h.get('modo','')}")
            if h.get("inicio_coords") and h.get("fin_coords"):
                o = h["inicio_coords"]
                d = h["fin_coords"]
                if google_maps_api_key:
                    origin = f"{o['lat']},{o['lon']}"
                    dest = f"{d['lat']},{d['lon']}"
                    directions_url = (
                        f"https://www.google.com/maps/embed/v1/directions?key={google_maps_api_key}"
                        f"&origin={origin}&destination={dest}&mode=walking"
                    )
                    st.components.v1.html(f'<iframe width="100%" height="220" src="{directions_url}" style="border:0"></iframe>', height=220)
            st.markdown("---")
    else:
        st.info("Aún no hay registros