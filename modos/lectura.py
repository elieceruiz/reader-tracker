import streamlit as st
from utils.cronometro import iniciar, tiempo_transcurrido, detener
from utils.db import get_db
from utils.mapas import mostrar_mapa

def run():
    st.header("📖 Modo Lectura con GPS")
    db = get_db()
    coleccion = db["lecturas"]

    if "lectura" not in st.session_state:
        st.session_state.lectura = None

    if st.session_state.lectura is None:
        if st.button("▶ Iniciar Lectura"):
            st.session_state.lectura = iniciar()
            st.rerun()
    else:
        segundos, txt = tiempo_transcurrido(st.session_state.lectura)
        st.metric("Tiempo transcurrido", txt)
        mostrar_mapa()

        if st.button("⏹ Detener Lectura"):
            evento = detener(st.session_state.lectura)
            coleccion.insert_one(evento)
            st.session_state.lectura = None
            st.success("Lectura guardada en historial.")
            st.rerun()
