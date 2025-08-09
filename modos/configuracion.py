import streamlit as st

def run():
    st.header("⚙ Configuración")
    st.write("Llaves cargadas desde secrets:")
    st.code({
        "mongo_uri": bool(st.secrets.get("mongo_uri")),
        "google_maps_api_key": bool(st.secrets.get("google_maps_api_key", ""))
    })
