import streamlit as st
from st_autorefresh import st_autorefresh
import modos.lectura as lectura
import modos.desarrollo as desarrollo
import modos.mapa as mapa
import modos.historial as historial
import modos.configuracion as configuracion

modo = st.sidebar.radio(
    "Selecciona modo",
    ["Lectura", "Desarrollo", "Mapa", "Historial", "Configuración"]
)

if modo in ["Lectura", "Desarrollo"]:
    st_autorefresh(interval=10000, key=f"refresh_{modo}")

if modo == "Lectura":
    lectura.run()
elif modo == "Desarrollo":
    desarrollo.run()
elif modo == "Mapa":
    mapa.run()
elif modo == "Historial":
    historial.run()
elif modo == "Configuración":
    configuracion.run()
