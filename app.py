import streamlit as st
from pymongo import MongoClient
from datetime import datetime, timedelta
import pytz
import time

# === CONFIGURACIÓN GENERAL ===
st.set_page_config("Seguimiento de Lectura", layout="centered")
st.title("📚 Seguimiento de Lectura")

# Zona horaria
tz = pytz.timezone("America/Bogota")

# Conexión a MongoDB
MONGO_URI = st.secrets["mongo_uri"]  # O reemplaza con tu cadena directa
client = MongoClient(MONGO_URI)
db = client["lecturas_db"]
coleccion = db["lecturas"]

# === VERIFICAR SI HAY LECTURA ACTIVA ===
evento = coleccion.find_one({"en_curso": True})

if evento:
    libro = evento["libro"]
    total_paginas = evento["total_paginas"]
    pagina_inicio = evento["pagina_inicio"]
    hora_inicio = evento["inicio"].astimezone(tz)

    segundos_transcurridos = int((datetime.now(tz) - hora_inicio).total_seconds())

    st.success(f"📖 Leyendo **{libro}** — desde la página {pagina_inicio} / {total_paginas}")
    st.info(f"Iniciado a las {hora_inicio.strftime('%H:%M:%S')}")

    cronometro = st.empty()
    stop_button = st.button("⏹️ Finalizar lectura")

    for i in range(segundos_transcurridos, segundos_transcurridos + 100000):
        if stop_button:
            ahora = datetime.now(tz)
            coleccion.update_one(
                {"_id": evento["_id"]},
                {
                    "$set": {
                        "fin": ahora,
                        "en_curso": False,
                        "duracion_segundos": (ahora - hora_inicio).total_seconds()
                    }
                }
            )
            st.success("✅ Lectura finalizada.")
            time.sleep(1)  # Pausa breve para mostrar el mensaje
            st.rerun()  # Restablecer estado

        duracion = str(timedelta(seconds=i))
        cronometro.markdown(f"### ⏱️ Tiempo leyendo: {duracion}")
        time.sleep(1)

else:
    # === FORMULARIO DE INICIO ===
    with st.form("iniciar_lectura"):
        libro = st.text_input("📚 Nombre del libro")
        total_paginas = st.number_input("Número total de páginas", min_value=1, step=1)
        pagina_inicio = st.number_input("Página desde donde comienzas", min_value=1, step=1)
        iniciar = st.form_submit_button("🟢 Iniciar lectura")

        if iniciar:
            libro = libro.strip()
            if not libro:
                st.error("El nombre del libro no puede estar vacío.")
            else:
                # Verificar si el libro ya está en curso
                existente = coleccion.find_one({"libro": libro, "en_curso": True})
                if existente:
                    st.warning(f"⚠️ El libro **{libro}** ya está en curso desde {existente['inicio'].astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')}")
                else:
                    coleccion.insert_one({
                        "libro": libro,
                        "total_paginas": total_paginas,
                        "pagina_inicio": pagina_inicio,
                        "inicio": datetime.now(tz),
                        "en_curso": True
                    })
                    st.success(f"Lectura de **{libro}** iniciada.")
                    time.sleep(1)
                    st.rerun()

# === HISTORIAL DE LECTURAS ===
st.subheader("📜 Historial de Lecturas")
historial = list(coleccion.find({"en_curso": False}).sort("inicio", -1))

if historial:
    data = []
    for e in historial:
        inicio = e["inicio"].astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
        fin = e["fin"].astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
        total_segundos = int((e["fin"] - e["inicio"]).total_seconds())
        horas, resto = divmod(total_segundos, 3600)
        minutos, segundos = divmod(resto, 60)
        duracion = f"{horas:02d}h {minutos:02d}m {segundos:02d}s"

        fila = {
            "Libro": e["libro"],
            "Inicio": inicio,
            "Fin": fin,
            "Duración": duracion,
            "Pág. Inicio": e["pagina_inicio"],
            "Total Páginas": e["total_paginas"]
        }
        data.append(fila)

    st.dataframe(data, use_container_width=True)
else:
    st.info("No hay lecturas finalizadas.")
