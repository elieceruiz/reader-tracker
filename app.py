# app.py
import streamlit as st
from streamlit_autorefresh import st_autorefresh
from datetime import datetime, timezone, timedelta
import pytz
import pymongo
from bson.objectid import ObjectId
import math
import json

try:
    import folium
    from streamlit_folium import st_folium
    HAS_FOLIUM = True
except Exception:
    HAS_FOLIUM = False

tz = pytz.timezone("America/Bogota")

def now_utc():
    return datetime.utcnow().replace(tzinfo=timezone.utc)

def ensure_aware_utc(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def to_local_str(dt):
    if not dt:
        return "-"
    dt = ensure_aware_utc(dt)
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

def haversine_km(a, b):
    lat1, lon1 = a
    lat2, lon2 = b
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    aa = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(aa))
    return R * c

def route_distance_km(route):
    if not route or len(route) < 2:
        return 0.0
    s = 0.0
    for i in range(len(route) - 1):
        s += haversine_km((route[i]["lat"], route[i]["lng"]), (route[i+1]["lat"], route[i+1]["lng"]))
    return s

# CONFIG
mongo_uri = st.secrets.get("mongo_uri")
google_maps_api_key = st.secrets.get("google_maps_api_key", "")

if not mongo_uri:
    st.error("Falta mongo_uri en st.secrets")
    st.stop()

client = pymongo.MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
try:
    client.server_info()
except Exception as e:
    st.error(f"Error conectando a MongoDB: {e}")
    st.stop()

db = client["reader_tracker"]
col = db["sessions"]
books_col = db["books"]

# Híbrido: cada X segundos o X metros
HYBRID_SECONDS = 30
HYBRID_METERS = 20  # metros

# session_state init + recover active session from DB
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.sid = None
    st.session_state.start = None
    st.session_state.tipo = None
    st.session_state.title = None
    st.session_state.route = []
    st.session_state.distance_km = 0.0
    st.session_state.last_save_time = None
    st.session_state.last_save_point = None

    running = col.find_one({"en_curso": True})
    if running:
        st.session_state.sid = str(running["_id"])
        st.session_state.start = ensure_aware_utc(running["inicio"])
        st.session_state.tipo = running.get("tipo", "lectura")
        st.session_state.title = running.get("title")
        st.session_state.route = running.get("route", []) or []
        st.session_state.distance_km = float(running.get("distance_km", 0.0) or 0.0)
        st.session_state.last_save_time = ensure_aware_utc(running.get("last_save_time"))
        st.session_state.last_save_point = running.get("last_save_point")

# DB helpers
def start_session(tipo, title=None, page_start=1):
    # prevent double-insert
    existing = col.find_one({"tipo": tipo, "en_curso": True})
    if existing:
        # restore into session_state
        st.session_state.sid = str(existing["_id"])
        st.session_state.start = ensure_aware_utc(existing["inicio"])
        st.session_state.tipo = existing.get("tipo")
        st.session_state.title = existing.get("title")
        st.session_state.route = existing.get("route", []) or []
        st.session_state.distance_km = float(existing.get("distance_km", 0.0) or 0.0)
        st.warning("Ya hay una sesión en curso; retomando esa sesión.")
        return st.session_state.sid

    doc = {
        "tipo": tipo,
        "title": title,
        "inicio": now_utc(),
        "fin": None,
        "en_curso": True,
        "route": [],
        "distance_km": 0.0,
        "last_save_time": now_utc(),
        "last_save_point": None,
        "page_start": int(page_start),
        "page_end": None,
        "pages_session": 0,
        "duration_sec": 0
    }
    res = col.insert_one(doc)
    st.session_state.sid = str(res.inserted_id)
    st.session_state.start = ensure_aware_utc(doc["inicio"])
    st.session_state.tipo = tipo
    st.session_state.title = title
    st.session_state.route = []
    st.session_state.distance_km = 0.0
    st.session_state.last_save_time = ensure_aware_utc(doc["last_save_time"])
    st.session_state.last_save_point = None
    return st.session_state.sid

def hybrid_save_point(sid, lat, lng):
    sid_oid = ensure_oid(sid)
    doc = col.find_one({"_id": sid_oid})
    if not doc:
        return
    now = now_utc()
    last_time = ensure_aware_utc(doc.get("last_save_time"))
    last_point = doc.get("last_save_point")
    should_save = False
    if not last_point:
        should_save = True
    else:
        dist_m = haversine_km((last_point["lat"], last_point["lng"]), (lat, lng)) * 1000.0
        if dist_m >= HYBRID_METERS:
            should_save = True
    if not should_save and last_time:
        delta_s = (now - last_time).total_seconds()
        if delta_s >= HYBRID_SECONDS:
            should_save = True
    if should_save:
        col.update_one(
            {"_id": sid_oid},
            {
                "$push": {"route": {"lat": lat, "lng": lng, "t": now}},
                "$set": {"last_save_time": now, "last_save_point": {"lat": lat, "lng": lng}}
            }
        )
        doc2 = col.find_one({"_id": sid_oid})
        dist = route_distance_km(doc2.get("route", []))
        col.update_one({"_id": sid_oid}, {"$set": {"distance_km": dist}})
        st.session_state.route = doc2.get("route", []) or []
        st.session_state.distance_km = float(dist)

def process_query_params():
    params = st.query_params  # <- updated API
    lat = params.get("lat", [None])[0]
    lng = params.get("lng", [None])[0]
    sid = params.get("sid", [None])[0]
    if lat and lng and sid:
        try:
            latf = float(lat); lngf = float(lng)
            hybrid_save_point(sid, latf, lngf)
        except Exception:
            pass

process_query_params()

# UI
st.set_page_config(page_title="Reader Tracker", layout="wide")
st.title("Reader Tracker")

seccion = st.sidebar.selectbox("Sección", ["Lectura", "Desarrollo", "Mapa en vivo", "Historial", "Configuración"])

# autorefresh only if an active session exists
if st.session_state.sid is not None:
    st_autorefresh(interval=1000, key="live_refresh")

# SECCIÓN: Lectura
if seccion == "Lectura":
    st.header("Lectura")
    if not st.session_state.sid:
        title = st.text_input("Título")
        page_start = st.number_input("Página inicio", min_value=1, value=1)
        if st.button("Iniciar lectura"):
            if not title or not title.strip():
                st.warning("Ingresa título")
            else:
                start_session("lectura", title.strip(), page_start)
                st.experimental_rerun()
    else:
        # show only if current session is tipo lectura
        sid = st.session_state.sid
        doc = col.find_one({"_id": ensure_oid(sid)})
        if doc and doc.get("en_curso") and doc.get("tipo") == "lectura":
            start_dt = ensure_aware_utc(doc["inicio"])
            elapsed = int((now_utc() - start_dt).total_seconds())
            st.metric("Duración", secs_to_hms(elapsed))
            st.markdown(f"**Distancia guardada:** {st.session_state.distance_km:.3f} km")
            page_now = st.number_input("Página actual", min_value=1, value=int(doc.get("page_start",1)), key="page_now")
            if st.button("Finalizar lectura"):
                pages = int(st.session_state.get("page_now", page_now))
                duration = int((now_utc() - start_dt).total_seconds())
                col.update_one({"_id": ensure_oid(sid)}, {"$set": {"fin": now_utc(), "en_curso": False, "page_end": pages, "pages_session": pages - doc.get("page_start",1) + 0, "duration_sec": duration}})
                # update book accum
                title = doc.get("title")
                if title:
                    book = books_col.find_one({"name": title}) or {}
                    prev = book.get("pages_accum", 0)
                    books_col.update_one({"name": title}, {"$set": {"name": title, "pages_accum": prev + (pages - doc.get("page_start",1) + 0)}}, upsert=True)
                # clear state
                st.session_state.sid = None
                st.session_state.start = None
                st.session_state.route = []
                st.session_state.distance_km = 0.0
                st.success("Lectura finalizada y guardada.")
        else:
            st.info("No hay una sesión de lectura en curso.")

# SECCIÓN: Desarrollo
elif seccion == "Desarrollo":
    st.header("Desarrollo")
    if not st.session_state.sid:
        name = st.text_input("Nombre de la tarea", value="Trabajo")
        if st.button("Iniciar desarrollo"):
            start_session("dev", name, 0)
            st.experimental_rerun()
    else:
        sid = st.session_state.sid
        doc = col.find_one({"_id": ensure_oid(sid)})
        if doc and doc.get("en_curso") and doc.get("tipo") == "dev":
            elapsed = int((now_utc() - ensure_aware_utc(doc["inicio"])).total_seconds())
            st.metric("Duración", secs_to_hms(elapsed))
            if st.button("Finalizar desarrollo"):
                duration = int((now_utc() - ensure_aware_utc(doc["inicio"])).total_seconds())
                col.update_one({"_id": ensure_oid(sid)}, {"$set": {"fin": now_utc(), "en_curso": False, "duration_sec": duration}})
                st.session_state.sid = None
                st.session_state.start = None
                st.success("Desarrollo finalizado y guardado.")
        else:
            st.info("No hay una sesión de desarrollo en curso.")

# SECCIÓN: Mapa en vivo
elif seccion == "Mapa en vivo":
    st.header("Mapa en vivo")
    if not google_maps_api_key:
        st.error("Falta google_maps_api_key en st.secrets")
    else:
        SID = st.session_state.sid or ""
        # JS must use doubled braces for JS object literals inside f-string
        js = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"/></head>
<body>
<div id="map" style="height:70vh;"></div>
<div style="position:absolute;top:10px;left:10px;background:white;padding:8px;z-index:5;">
<button onclick="finalizar()">Finalizar y enviar</button>
<span id="dist" style="display:block;margin-top:6px"></span>
</div>
<script src="https://maps.googleapis.com/maps/api/js?key={google_maps_api_key}&libraries=geometry"></script>
<script>
let map, poly, path=[];
function initMap(){{
  map = new google.maps.Map(document.getElementById('map'), {{zoom:17, center: {{lat:4.65,lng:-74.05}} }});
  poly = new google.maps.Polyline({{strokeColor:'#FF0000', strokeOpacity:1.0, strokeWeight:3, map:map}});
  if(navigator.geolocation){{
    navigator.geolocation.getCurrentPosition(p => {{
      let latlng = new google.maps.LatLng(p.coords.latitude,p.coords.longitude);
      map.setCenter(latlng);
      poly.getPath().push(latlng);
      path.push({{lat:p.coords.latitude,lng:p.coords.longitude}});
      updateDist();
    }});
    navigator.geolocation.watchPosition(p => {{
      let latlng = new google.maps.LatLng(p.coords.latitude,p.coords.longitude);
      poly.getPath().push(latlng);
      path.push({{lat:p.coords.latitude,lng:p.coords.longitude}});
      updateDist();
      if('{SID}') {{
        fetch('/?lat='+p.coords.latitude+'&lng='+p.coords.longitude+'&sid='+encodeURIComponent('{SID}')).catch(()=>{{}});
      }}
    }}, e => console.error(e), {{enableHighAccuracy:true, maximumAge:10000, timeout:5000}});
  }} else {{ alert('Geolocalización no soportada'); }}
}}
function updateDist(){{
  let dist = google.maps.geometry.spherical.computeLength(poly.getPath());
  document.getElementById('dist').innerText = 'Distancia (m): ' + (dist).toFixed(1);
}}
function finalizar(){{
  if('{SID}' && path.length>0){{
    const last = path[path.length-1];
    fetch('/?lat='+last.lat+'&lng='+last.lng+'&sid='+encodeURIComponent('{SID}')).catch(()=>{{}});
  }}
  alert('Ruta enviada (último punto).');
}}
window.onload = initMap;
</script>
</body>
</html>
"""
        st.components.v1.html(js, height=700)
        if st.session_state.route:
            st.markdown(f"Puntos guardados: {len(st.session_state.route)} — distancia guardada: {st.session_state.distance_km:.3f} km")

# SECCIÓN: Historial
elif seccion == "Historial":
    st.header("Historial")
    rows = list(col.find().sort("inicio", -1).limit(200))
    for r in rows:
        inicio = to_local_str(r["inicio"])
        fin = to_local_str(r.get("fin"))
        dur = secs_to_hms(r.get("duration_sec", 0)) if r.get("duration_sec") else ("En curso" if r.get("en_curso") else "-")
        tipo = r.get("tipo","-")
        title = r.get("title","-")
        dist = f"{float(r.get('distance_km',0.0)):.3f} km"
        st.write(f"{tipo} | {title} | {inicio} → {fin} | {dur} | {dist}")
    if HAS_FOLIUM:
        st.markdown("---")
        st.subheader("Ver ruta histórica")
        sesiones_ruta = list(col.find({"route": {"$exists": True, "$ne": []}}).sort("inicio",-1).limit(200))
        labels = [f"{to_local_str(s['inicio'])} — {s.get('title','-')} — {s.get('distance_km',0.0):.3f} km" for s in sesiones_ruta]
        sel = st.selectbox("Elige sesión", [""] + labels)
        if sel:
            idx = labels.index(sel) - 1
            if idx >= 0:
                sdoc = sesiones_ruta[idx]
                coords = [(p["lat"], p["lng"]) for p in sdoc.get("route", [])]
                if coords:
                    m = folium.Map(location=coords[0], zoom_start=15)
                    folium.PolyLine(coords, color="red", weight=3).add_to(m)
                    folium.Marker(coords[0], popup="Inicio").add_to(m)
                    folium.Marker(coords[-1], popup="Fin").add_to(m)
                    st_folium(m, width=700, height=450)

# SECCIÓN: Configuración
elif seccion == "Configuración":
    st.header("Configuración")
    st.write({"mongo_uri": bool(mongo_uri), "google_maps_api_key": bool(google_maps_api_key)})
