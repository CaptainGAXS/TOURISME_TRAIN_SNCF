"""
streamlit run scripts/itinerary/app.py
"""

import pydeck as pdk
import streamlit as st

from itinerary_ui import itinerary_sidebar

st.set_page_config(page_title="Itinéraire SNCF", layout="wide")

layers = itinerary_sidebar()

st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=46.6, longitude=2.2, zoom=5),
        tooltip={"text": "{name}"},
    ),
    height=700,
)
