import pandas as pd
import streamlit as st
import pydeck as pdk
import numpy as np
from show_map import render_map

def map_selector():
    layers = []
    if "selected_map" not in st.session_state:
        st.session_state.selected_map = None
    if st.sidebar.button("Carte par départements"):
        st.session_state.selected_map = "data/departements-50m.geojson"
    if st.sidebar.button("Carte par régions"):
        st.session_state.selected_map = "data/regions-50m.geojson"
    if st.sidebar.button("Gares"):
        scatter_layer = grab_data()
        layers.append(scatter_layer)

    if st.session_state.selected_map:
        render_map(st.session_state.selected_map, layers)
    else:
        st.write("Sélectionnez une option dans la barre latérale pour afficher la carte correspondante.")

def normalize_visitors(visitors):
    # Increased minimum radius so base stations are visible at national zoom
    min_radius = 500  
    max_radius = 20000
    
    # Using Square Root scaling to prevent Gare du Nord from squashing the rest of the data
    sqrt_visitors = np.sqrt(visitors)
    min_sqrt = np.sqrt(0)
    max_sqrt = np.sqrt(275993741)

    normalized_radius = ((sqrt_visitors - min_sqrt) / (max_sqrt - min_sqrt)) * (max_radius - min_radius) + min_radius
    return normalized_radius

def grab_data():
    df= pd.read_csv("data/stations.csv", sep=",")
    df["map_radius"] = normalize_visitors(df["visitors"])

    scatter_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color=[0, 200, 100, 255],  # Green dots
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        get_radius="[map_radius]",  # Radius in meters
        radius_max_pixels=15,
        pickable=True,     # Allows hovering/clicking
    )
    return scatter_layer

def main():
    map_selector()

if __name__ == "__main__":
    main()