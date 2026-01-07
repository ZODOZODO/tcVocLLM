import os
import streamlit as st
from dotenv import load_dotenv

from ui.voc_tab import render_voc_tab
from ui.logs_tab import render_logs_tab

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="tcVocLLM", layout="wide")
st.title("VOC Chatbot / EQP Log Viewer")

tab1, tab2 = st.tabs(["VOC Chatbot", "EQP Log Viewer"])

with tab1:
    render_voc_tab(BACKEND_URL)

with tab2:
    render_logs_tab(BACKEND_URL)
