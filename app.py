# app.py
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone, timedelta
import pytz
from pymongo import MongoClient
from bson.objectid import ObjectId
import json

try:
    from streamlit_js_eval import streamlit_js_eval
    HAS_JS_EVAL = True
except Exception:
    HAS_JS_EVAL = False

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

tz = pytz.timezone("America/Bogota")

def now_utc():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def to_local_str(dt):
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

def secs_to_hms(s):
    return str(timedelta(seconds=int(s)))

def ensure_oid(x):
    if x is None:
        return None
    if isinstance(x, ObjectId):
        return x
    try:
        return ObjectId(x)
    except Exception:
        return x

def haversine(lat1, lon1, lat2, lon2):
    from math import radians, cos, sin, asin, sqrt
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def route_distance_km(ruta):
    if not ruta or len(ruta) < 2:
        return 0.0
    tot = 0.0
    for i in range(len(ruta)-1):
        p1, p2 = ruta[i], ruta[i+1]
        tot += haversine(p1["lat"], p1["lng"], p2["lat"], p2["lng"])
    return tot

# config / secrets
st.set_page_config(page_title="Reader Tracker", layout="wide")
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key", "")

if not mongo_uri:
    st.error("Falta mongo_uri en st.secrets")
    st.stop()

client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
try:
    client.server_info()
except Exception as e:
    st.error(f"Error conectando a MongoDB: {e}")
    st.stop()

db = client["reader_tracker"]
lecturas_col = db["lecturas"]
dev_col = db["dev_tracker"]
libros_col = db["libros"]

# session init & recovery from DB
if "initialized" not in st.session_state:
    st.session_state["initialized"] = True
    st.session_state["lectura_en_curso"] = False
    st.session_state["lectura_id"] = None
    st.session_state["lectura_inicio"] = None
    st.session_state["lectura_titulo"] = None
    st.session_state["lectura_pagina_actual"] = 1
    st.session_state["ruta_actual"] = []
    st.session_state["ruta_distancia_km"] = 0.0
    st.session_state["dev_en_curso"] = False
    st.session_state["dev_id"] = None
    st.session_state["dev_inicio"] = None

    # restore any active dev or lectura from DB (survive tab close)
    dev_active = dev_col.find_one({"en_curso": True})
    if dev_active:
        st.session_state["dev_en_curso"] = True
        st.session_state["dev_id"] = dev_active["_id"]
        st.session_state["dev_inicio"] = dev_active["inicio"]

    lect_active = lecturas_col.find_one({"en_curso": True})
    if lect_active:
        st.session_state["lectura_en_curso"] = True
        st.session_state["lectura_id"] = lect_active["_id"]
        st.session_state["lectura_inicio"] = lect_active["inicio"]
        st.session_state["lectura_titulo"] = lect_active.get("libro")
        st.session_state["lectura_pagina_actual"] = lect_active.get("pagina_final") or lect_active.get("pagina_inicial", 1)
        st.session_state["ruta_actual"] = lect_active.get("ruta", []) or []
        st.session_state["ruta_distancia_km"] = float(lect_active.get("distancia_km", 0.0) or 0.0)

# helpers DB
def start_lectura(libro, pagina_inicio=1):
    if lecturas_col.find_one({"en_curso": True}):
        st.warning("Ya existe una lectura en curso. Retomá esa o finalizala antes.")
        return None
    doc = {
        "tipo": "lectura",
        "libro": libro,
        "inicio": now_utc(),
        "fin": None,
        "en_curso": True,
        "pagina_inicial": int(pagina_inicio),
        "pagina_final": None,
        "paginas_sesion": 0,
        "paginas_acumuladas": 0,
        "lecturas_completas_total": 0,
        "estatica": True,
        "distancia_km": 0.0,
        "ruta": [],
        "duracion_seg": 0
    }
    res = lecturas_col.insert_one(doc)
    st.session_state["lectura_en_curso"] = True
    st.session_state["lectura_id"] = res.inserted_id
    st.session_state["lectura_inicio"] = doc["inicio"]
    st.session_state["lectura_titulo"] = libro
    st.session_state["lectura_pagina_actual"] = int(pagina_inicio)
    st.session_state["ruta_actual"] = []
    st.session_state["ruta_distancia_km"] = 0.0
    return res.inserted_id

def live_update_lectura_db():
    if not st.session_state.get("lectura_en_curso") or not st.session_state.get("lectura_id"):
        return
    lid = ensure_oid(st.session_state["lectura_id"])
    seg = int((now_utc() - st.session_state["lectura_inicio"]).total_seconds())
    lecturas_col.update_one({"_id": lid}, {"$set": {
        "pagina_final": st.session_state.get("lectura_pagina_actual"),
        "ruta": st.session_state.get("ruta_actual", []),
        "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
        "duracion_seg": seg
    }})

def finish_lectura(paginas_sesion=0, lectura_completa=False, estatico=True):
    lid = ensure_oid(st.session_state.get("lectura_id"))
    if lid:
        seg = int((now_utc() - st.session_state["lectura_inicio"]).total_seconds())
        titulo = st.session_state.get("lectura_titulo")
        book = libros_col.find_one({"nombre": titulo}) or {}
        paginas_prev = book.get("paginas_acumuladas", 0)
        lect_prev = book.get("lecturas_completas", 0)
        paginas_acum = paginas_prev + int(paginas_sesion or 0)
        lects_tot = lect_prev + (1 if lectura_completa else 0)
        lecturas_col.update_one({"_id": lid}, {"$set": {
            "fin": now_utc(),
            "pagina_final": st.session_state.get("lectura_pagina_actual", st.session_state.get("lectura_pagina_inicio",1)),
            "paginas_sesion": int(paginas_sesion or 0),
            "paginas_acumuladas": paginas_acum,
            "lecturas_completas_total": lects_tot,
            "duracion_seg": seg,
            "distancia_km": st.session_state.get("ruta_distancia_km", 0.0),
            "ruta": st.session_state.get("ruta_actual", []),
            "estatica": bool(estatico),
            "en_curso": False
        }})
        libros_col.update_one({"nombre": titulo}, {"$set": {
            "nombre": titulo,
            "paginas_acumuladas": paginas_acum,
            "lecturas_completas": lects_tot
        }}, upsert=True)
    st.session_state["lectura_en_curso"] = False
    st.session_state["lectura_id"] = None
    st.session_state["lectura_inicio"] = None
    st.session_state["lectura_titulo"] = None
    st.session_state["lectura_pagina_actual"] = 1
    st.session_state["ruta_actual"] = []
    st.session_state["ruta_distancia_km"] = 0.0

def start_dev(nombre="Desarrollo App"):
    if dev_col.find_one({"en_curso": True}):
        st.warning("Ya existe una sesión de desarrollo en curso.")
        return None
    doc = {"tipo": "desarrollo_app", "nombre": nombre, "inicio": now_utc(), "fin": None, "duracion_seg": 0, "en_curso": True}
    res = dev_col.insert_one(doc)
    st.session_state["dev_en_curso"] = True
    st.session_state["dev_id"] = res.inserted_id
    st.session_state["dev_inicio"] = doc["inicio"]
    return res.inserted_id

def live_update_dev_db():
    if not st.session_state.get("dev_en_curso") or not st.session_state.get("dev_id"):
        return
    did = ensure_oid(st.session_state["dev_id"])
    seg = int((now_utc() - st.session_state["dev_inicio"]).total_seconds())
    dev_col.update_one({"_id": did}, {"$set": {"duracion_seg": seg}})

def finish_dev():
    did = ensure_oid(st.session_state.get("dev_id"))
    if did:
        seg = int((now_utc() - st.session_state["dev_inicio"]).total_seconds())
        dev_col.update_one({"_id": did}, {"$set": {"fin": now_utc(), "duracion_seg": seg, "en_curso": False}})
    st.session_state["dev_en_curso"] = False
    st.session_state["dev_id"] = None
    st.session_state["dev_inicio"] = None

# receive points: via streamlit_js_eval (postMessage) or via query params fallback
def process_incoming_route_message(msg):
    # msg expected {type: "guardar_ruta", ruta: JSONstring or list}
    try:
        if not isinstance(msg, dict):
            return
        if msg.get("type") != "guardar_ruta":
            return
        ruta = msg.get("ruta")
        if isinstance(ruta, str):
            ruta = json.loads(ruta)
    except Exception:
        ruta = []
    if ruta and isinstance(ruta, list):
        st.session_state["ruta_actual"] = ruta
        st.session_state["ruta_distancia_km"] = round(route_distance_km(ruta), 4)
        if st.session_state.get("lectura_en_curso") and st.session_state.get("lectura_id"):
            lid = ensure_oid(st.session_state["lectura_id"])
            lecturas_col.update_one({"_id": lid}, {"$set": {"ruta": ruta, "distancia_km": st.session_state["ruta_distancia_km"]}})

def process_query_params():
    qp = st.experimental_get_query_params()
    lat = qp.get("lat", [None])[0]
    lng = qp.get("lng", [None])[0]
    if lat and lng:
        try:
            latf = float(lat)
            lngf = float(lng)
        except Exception:
            return
        point = {"lat": latf, "lng": lngf, "t": now_utc()}
        ruta = st.session_state.get("ruta_actual", [])
        ruta.append({"lat": latf, "lng": lngf, "t": now_utc()})
        st.session_state["ruta_actual"] = ruta
        st.session_state["ruta_distancia_km"] = round(route_distance_km(ruta), 4)
        if st.session_state.get("lectura_en_curso") and st.session_state.get("lectura_id"):
            lid = ensure_oid(st.session_state["lectura_id"])
            lecturas_col.update_one({"_id": lid}, {"$push": {"ruta": {"lat": latf, "lng": lngf, "t": now_utc()}}, "$set": {"distancia_km": st.session_state["ruta_distancia_km"]}})

# UI and flow
st.title("Reader Tracker")

seccion = st.sidebar.selectbox("Sección", ["Tiempo de desarrollo", "Lectura con Cronómetro", "Mapa en vivo", "Historial", "Configuración"])

# if active session(s), refresh each second
if st.session_state.get("lectura_en_curso") or st.session_state.get("dev_en_curso"):
    st_autorefresh(interval=1000, key="live_refresh")

# attempt to read postMessage via streamlit_js_eval if available
if HAS_JS_EVAL:
    try:
        incoming = streamlit_js_eval(js="window.addEventListener('message', (event) => event.data);", key="js_incoming")
    except Exception:
        incoming = None
else:
    incoming = None

# query params fallback (useful for fetch("/?lat=..&lng=..") fallback)
process_query_params()

if incoming:
    process_incoming_route_message(incoming)

# sections
if seccion == "Tiempo de desarrollo":
    st.header("Tiempo de desarrollo")
    if not st.session_state.get("dev_en_curso"):
        if st.button("Iniciar desarrollo"):
            start_dev()
    else:
        seg = int((now_utc() - st.session_state["dev_inicio"]).total_seconds())
        st.metric("Duración", secs_to_hms(seg))
        if st.button("Finalizar desarrollo"):
            finish_dev()
    # live update db
    live_update_dev_db()

    rows = list(dev_col.find().sort("inicio", -1).limit(50))
    st.markdown("---")
    st.subheader("Últimas sesiones de desarrollo")
    for r in rows:
        inicio = to_local_str(r["inicio"])
        fin = to_local_str(r.get("fin"))
        dur = secs_to_hms(r.get("duracion_seg", 0)) if r.get("duracion_seg") else ("En curso" if r.get("en_curso") else "-")
        st.write(f"{r.get('nombre','-')} | {inicio} → {fin} | {dur}")

elif seccion == "Lectura con Cronómetro":
    st.header("Lectura")
    if not st.session_state.get("lectura_en_curso"):
        titulo = st.text_input("Título", value=st.session_state.get("lectura_titulo") or "")
        pagina_inicio = st.number_input("Página inicial", min_value=1, value=1)
        if st.button("Iniciar lectura"):
            if not titulo.strip():
                st.warning("Ingresá título")
            else:
                start_lectura(titulo.strip(), pagina_inicio)
    else:
        seg = int((now_utc() - st.session_state["lectura_inicio"]).total_seconds())
        st.metric("Duración", secs_to_hms(seg))
        st.number_input("Página actual", min_value=1, value=st.session_state.get("lectura_pagina_actual",1), key="lectura_pagina_actual")
        st.markdown(f"Distancia actual: **{st.session_state.get('ruta_distancia_km',0.0):.2f} km**")
        if st.button("Finalizar lectura"):
            st.session_state["_ask_finalize"] = True
        if st.session_state.get("_ask_finalize"):
            with st.expander("Confirmar finalización", expanded=True):
                paginas = st.number_input("Páginas leídas en la sesión", min_value=0, value=0, key="final_paginas")
                completa = st.checkbox("Lectura completa", key="final_completa")
                estatico = st.checkbox("Estática (sin movimiento)", value=(st.session_state.get("ruta_distancia_km",0.0)==0.0), key="final_estatica")
                if st.button("Confirmar y guardar"):
                    finish_lectura(paginas_sesion=paginas, lectura_completa=completa, estatico=estatico)
                    st.success("Lectura guardada.")
                    st.session_state["_ask_finalize"] = False
                if st.button("Cancelar"):
                    st.session_state["_ask_finalize"] = False
        live_update_lectura_db()

elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo")
    if not google_maps_api_key:
        st.error("Falta google_maps_api_key en st.secrets")
    else:
        map_html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8" />
            <style> html, body, #map {{ height: 100%; margin:0; padding:0 }} </style>
            <script src="https://maps.googleapis.com/maps/api/js?key={google_maps_api_key}&libraries=geometry"></script>
        </head>
        <body>
            <div id="map" style="height:90vh; width:100%;"></div>
            <div style="position:absolute;top:10px;left:10px;background:white;padding:8px;z-index:5;border-radius:6px;">
                <button onclick="finalizarLectura()">Finalizar lectura</button>
                <div id="distancia" style="margin-top:6px;"></div>
            </div>
            <script>
                let map, poly, path=[];
                let watchId;
                function initMap(){{
                    map = new google.maps.Map(document.getElementById('map'), {{
                        zoom:17,
                        center: {{lat:4.65, lng:-74.05}},
                        mapTypeId:'roadmap'
                    }});
                    poly = new google.maps.Polyline({{strokeColor:'#FF0000', strokeOpacity:1.0, strokeWeight:3, map:map}});
                    if(navigator.geolocation){{
                        navigator.geolocation.getCurrentPosition(pos=>{{
                            let latlng = new google.maps.LatLng(pos.coords.latitude, pos.coords.longitude);
                            map.setCenter(latlng);
                            poly.getPath().push(latlng);
                            path.push({{lat:pos.coords.latitude, lng:pos.coords.longitude}});
                            actualizarDistancia();
                        }}, console.error, {{enableHighAccuracy:true, maximumAge:1000, timeout:5000}});
                        watchId = navigator.geolocation.watchPosition(pos=>{{
                            let latlng = new google.maps.LatLng(pos.coords.latitude, pos.coords.longitude);
                            poly.getPath().push(latlng);
                            path.push({{lat:pos.coords.latitude, lng:pos.coords.longitude}});
                            actualizarDistancia();
                        }}, console.error, {{enableHighAccuracy:true, maximumAge:1000, timeout:5000}});
                    }} else {{ alert("Geolocalización no soportada"); }}
                }}
                function actualizarDistancia(){{
                    let distanciaMetros = google.maps.geometry.spherical.computeLength(poly.getPath());
                    document.getElementById('distancia').innerHTML = "Distancia: " + (distanciaMetros/1000).toFixed(2) + " km";
                }}
                function finalizarLectura(){{
                    if(watchId) navigator.geolocation.clearWatch(watchId);
                    const rutaJson = JSON.stringify(path);
                    window.parent.postMessage({{type:'guardar_ruta', ruta: rutaJson}}, "*");
                    // fallback: also call same page with query params to ensure server receives at least last point
                    if(path.length>0){{
                        const last = path[path.length-1];
                        fetch(`/?lat=${{last.lat}}&lng=${{last.lng}}`).catch(()=>{});
                    }}
                    alert("Ruta enviada al servidor.");
                }}
                window.onload = initMap;
            </script>
        </body>
        </html>
        """
        st.components.v1.html(map_html, height=700)
    if st.session_state.get("ruta_actual"):
        st.markdown(f"Ruta guardada: {len(st.session_state['ruta_actual'])} puntos — {st.session_state['ruta_distancia_km']:.2f} km")

elif seccion == "Historial":
    st.header("Historial")
    libros = list(libros_col.find().sort("nombre",1))
    if libros:
        sel = st.selectbox("Elige libro", [f"{b['nombre']} (Pág acum {b.get('paginas_acumuladas',0)} / Lecturas {b.get('lecturas_completas',0)})" for b in libros])
        if sel:
            nombre = sel.split(" (")[0]
            sesiones = list(lecturas_col.find({"libro": nombre}).sort("inicio",-1))
            for s in sesiones:
                inicio = to_local_str(s["inicio"])
                dur = secs_to_hms(s.get("duracion_seg",0)) if s.get("duracion_seg") else "-"
                paginas = f"{s.get('paginas_sesion',0)} pág (Acum: {s.get('paginas_acumuladas',0)})" if s.get("paginas_sesion") else "-"
                modo_txt = "Estática" if s.get("estatica",True) else f"En movimiento ({s.get('distancia_km',0.0):.2f} km)"
                st.write(f"• {inicio} | {dur} | {paginas} | {modo_txt}")
    else:
        st.info("No hay lecturas registradas todavía.")
    st.markdown("---")
    st.subheader("Sesiones de desarrollo")
    devs = list(dev_col.find().sort("inicio",-1).limit(200))
    for d in devs:
        inicio = to_local_str(d["inicio"])
        dur = secs_to_hms(d.get("duracion_seg",0)) if d.get("duracion_seg") else ("En curso" if d.get("en_curso") else "-")
        st.write(f"• {inicio} | {dur}")
    if HAS_FOLIUM:
        st.markdown("---")
        st.subheader("Visualizar ruta de una sesión")
        sesiones_ruta = list(lecturas_col.find({"ruta": {"$exists": True, "$ne": []}}).sort("inicio",-1).limit(200))
        labels = [f"{to_local_str(s['inicio'])} — {s.get('libro','-')} — {s.get('distancia_km',0.0):.2f} km" for s in sesiones_ruta]
        sel = st.selectbox("Elige sesión con ruta", [""] + labels)
        if sel:
            idx = labels.index(sel)
            ruta_doc = sesiones_ruta[idx].get("ruta",[])
            if ruta_doc:
                lat0, lng0 = ruta_doc[0]["lat"], ruta_doc[0]["lng"]
                m = folium.Map(location=[lat0, lng0], zoom_start=15)
                coords = [(p["lat"], p["lng"]) for p in ruta_doc]
                folium.PolyLine(coords, color="red", weight=3).add_to(m)
                folium.Marker(coords[0], popup="Inicio").add_to(m)
                folium.Marker(coords[-1], popup="Fin").add_to(m)
                st_folium(m, width=700, height=450)
    else:
        st.info("Instalá folium+streamlit-folium para ver rutas históricas.")

elif seccion == "Configuración":
    st.header("Configuración")
    st.write({"mongo_uri": bool(mongo_uri), "google_maps_api_key": bool(google_maps_api_key)})

# End of file
