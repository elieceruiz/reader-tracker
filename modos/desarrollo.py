import streamlit as st
from utils.cronometro import iniciar, tiempo_transcurrido, detener
from utils.db import get_db

def run():
    st.header("💻 Modo Desarrollo")
    db = get_db()
    coleccion = db["desarrollo"]

    if "desarrollo" not in st.session_state:
        st.session_state.desarrollo = None

    if st.session_state.desarrollo is None:
        if st.button("▶ Iniciar Desarrollo"):
            st.session_state.desarrollo = iniciar()
            st.rerun()
    else:
        segundos, txt = tiempo_transcurrido(st.session_state.desarrollo)
        st.metric("Tiempo transcurrido", txt)

        if st.button("⏹ Detener Desarrollo"):
            evento = detener(st.session_state.desarrollo)
            coleccion.insert_one(evento)
            st.session_state.desarrollo = None
            st.success("Desarrollo guardado en historial.")
            st.rerun()
