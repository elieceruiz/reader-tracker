import pymongo
import streamlit as st

mongo_uri = st.secrets.get("mongo_uri")

@st.cache_resource
def get_db():
    client = pymongo.MongoClient(mongo_uri)
    return client["tracker_app"]
