# app.py
import streamlit as st
from modos import lectura, desarrollo, mapa, historial, configuracion

# Título general
st.title("📚 Reader Tracker")

# Menú lateral con dropdown
modo = st.sidebar.selectbox(
    "📌 Selecciona modo",
    ["Lectura", "Desarrollo", "Mapa", "Historial", "Configuración"]
)

# Ruteo por modo
if modo == "Lectura":
    lectura.mostrar()
elif modo == "Desarrollo":
    desarrollo.mostrar()
elif modo == "Mapa":
    mapa.mostrar()
elif modo == "Historial":
    historial.mostrar()
elif modo == "Configuración":
    configuracion.mostrar()
