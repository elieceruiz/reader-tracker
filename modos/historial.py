import streamlit as st
from utils.db import get_db
from datetime import timedelta

def run():
    st.header("📜 Historial")
    db = get_db()

    st.subheader("Lecturas")
    for item in db["lecturas"].find().sort("inicio", -1):
        inicio = item["inicio"].strftime("%Y-%m-%d %H:%M")
        fin = item.get("fin")
        duracion = str(timedelta(seconds=int((fin - item["inicio"]).total_seconds()))) if fin else "En curso"
        st.write(f"📖 {inicio} — {duracion}")

    st.subheader("Desarrollo")
    for item in db["desarrollo"].find().sort("inicio", -1):
        inicio = item["inicio"].strftime("%Y-%m-%d %H:%M")
        fin = item.get("fin")
        duracion = str(timedelta(seconds=int((fin - item["inicio"]).total_seconds()))) if fin else "En curso"
        st.write(f"💻 {inicio} — {duracion}")
