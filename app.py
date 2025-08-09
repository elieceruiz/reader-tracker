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
MONGO_URI = st.secrets["mongo_uri"]
client = MongoClient(MONGO_URI)
db = client["lecturas_db"]
coleccion = db["lecturas"]

# === FUNCIONES ===
def obtener_ultima_pagina(libro):
    ultimo = coleccion.find_one(
        {"libro": libro, "en_curso": False},
        sort=[("fin", -1)]
    )
    if ultimo:
        return ultimo.get("pagina_fin", ultimo["pagina_inicio"])
    return 1

def tiempo_formateado(delta_segundos):
    """Convierte segundos en formato amigable."""
    minutos = delta_segundos // 60
    if minutos < 60:
        return f"{minutos} min"
    horas = minutos // 60
    minutos_rest = minutos % 60
    if horas < 24:
        return f"{horas}h {minutos_rest}m"
    dias = horas // 24
    if dias < 30:
        return f"{dias} días"
    meses = dias // 30
    if meses < 12:
        return f"{meses} meses"
    años = meses // 12
    return f"{años} años"

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
    pagina_fin = st.number_input("Página en la que terminas", min_value=pagina_inicio, max_value=total_paginas, step=1)
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
                        "pagina_fin": pagina_fin,
                        "duracion_segundos": (ahora - hora_inicio).total_seconds()
                    }
                }
            )
            st.success("✅ Lectura finalizada.")
            time.sleep(1)
            st.rerun()

        duracion = str(timedelta(seconds=i))
        cronometro.markdown(f"### ⏱️ Tiempo leyendo: {duracion}")
        time.sleep(1)

else:
    # === SELECCIÓN DE LIBRO O NUEVO ===
    libros_guardados = sorted({e["libro"] for e in coleccion.find()})
    opcion = st.selectbox("📚 ¿Existente o Nuevo?", ["Selecciona...", "Nuevo libro"] + libros_guardados)

    if opcion not in ["Selecciona...", "Nuevo libro"]:
        ultima_pag = obtener_ultima_pagina(opcion)
        total_paginas = coleccion.find_one({"libro": opcion})["total_paginas"]

        if ultima_pag >= total_paginas:
            st.warning("⚠️ Ya habías terminado este libro.")
            modo = st.radio(
                "¿Qué quieres hacer?",
                ("Empezar desde página 1", "Elegir página manualmente")
            )

            if modo == "Elegir página manualmente":
                nueva_pagina = st.number_input("Página desde donde empiezas", min_value=1, max_value=total_paginas, step=1)
            else:
                nueva_pagina = 1

            if st.button("🟢 Iniciar lectura nuevamente"):
                coleccion.insert_one({
                    "libro": opcion,
                    "total_paginas": total_paginas,
                    "pagina_inicio": nueva_pagina,
                    "inicio": datetime.now(tz),
                    "en_curso": True
                })
                st.success(f"Lectura de **{opcion}** iniciada desde la página {nueva_pagina}.")
                time.sleep(1)
                st.rerun()

        else:
            if st.button("🟢 Continuar lectura"):
                coleccion.insert_one({
                    "libro": opcion,
                    "total_paginas": total_paginas,
                    "pagina_inicio": ultima_pag + 1,
                    "inicio": datetime.now(tz),
                    "en_curso": True
                })
                st.success(f"Lectura de **{opcion}** reanudada desde la página {ultima_pag + 1}.")
                time.sleep(1)
                st.rerun()

    elif opcion == "Nuevo libro":
        with st.form("nueva_lectura"):
            libro = st.text_input("📚 Nombre del libro")
            total_paginas = st.number_input("Número total de páginas", min_value=1, step=1)
            pagina_inicio = st.number_input("Página desde donde comienzas", min_value=1, step=1)
            iniciar = st.form_submit_button("🟢 Iniciar lectura")

            if iniciar:
                if not libro.strip():
                    st.error("El nombre del libro no puede estar vacío.")
                elif coleccion.find_one({"libro": libro, "en_curso": True}):
                    st.warning(f"⚠️ El libro **{libro}** ya está en curso.")
                else:
                    coleccion.insert_one({
                        "libro": libro.strip(),
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

libros_historial = sorted({e["libro"] for e in coleccion.find()})

if libros_historial:
    opciones = ["Selecciona un libro..."] + libros_historial
    libro_filtro = st.selectbox("Libro:", opciones, index=0)

    if libro_filtro != "Selecciona un libro...":
        # Incluye tanto finalizadas como en curso
        filtro_query = {"libro": libro_filtro}
        historial = list(coleccion.find(filtro_query).sort("inicio", -1))

        if historial:
            total_sesiones = len(historial)
            total_paginas = historial[0]["total_paginas"]
            paginas_leidas = 0
            total_segundos = 0

            data = []
            for e in historial:
                inicio = e["inicio"].astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')

                if e.get("fin"):
                    fin = e["fin"].astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')
                    duracion_seg = int((e["fin"] - e["inicio"]).total_seconds())
                    pag_fin = e.get("pagina_fin", e["pagina_inicio"])
                else:
                    # Sesión en curso
                    fin = "(en curso)"
                    duracion_seg = int((datetime.now(tz) - e["inicio"]).total_seconds())
                    pag_fin = e.get("pagina_fin", e["pagina_inicio"])  # podría ir actualizando

                # Cálculo de páginas leídas
                pag_inicio = e["pagina_inicio"]
                leidas_sesion = max(pag_fin - pag_inicio + 1, 0)

                if paginas_leidas + leidas_sesion > total_paginas:
                    leidas_sesion = max(total_paginas - paginas_leidas, 0)

                paginas_leidas += leidas_sesion
                total_segundos += duracion_seg

                horas, resto = divmod(duracion_seg, 3600)
                minutos, segundos = divmod(resto, 60)
                duracion = f"{horas:02d}h {minutos:02d}m {segundos:02d}s"

                fila = {
                    "Inicio": inicio,
                    "Fin": fin,
                    "Duración": duracion,
                    "Pág. Inicio": pag_inicio,
                    "Pág. Fin": pag_fin
                }
                data.append(fila)

            # Resumen limpio
            st.markdown(f"### 📜 Historial de *{libro_filtro}*")
            st.markdown(
                f"**📄 Total:** {total_paginas} pág. &nbsp;|&nbsp; "
                f"✅ **Leídas:** {paginas_leidas} pág. &nbsp;|&nbsp; "
                f"📚 **Restantes:** {max(total_paginas - paginas_leidas, 0)} pág."
            )
            st.markdown(
                f"**📊 Sesiones:** {total_sesiones} &nbsp;|&nbsp; "
                f"⏱ **Promedio/pág:** {(total_segundos / paginas_leidas / 60 if paginas_leidas > 0 else 0):.2f} min"
            )

            st.dataframe(data, use_container_width=True)
        else:
            st.info("No hay registros para este libro.")
    else:
        st.info("Selecciona un libro para ver el historial.")
else:
    st.info("No hay lecturas registradas.")