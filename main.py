from pydeck.types import String
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
        scatter_layer = grab_station_data()
        layers.append(scatter_layer)
    heatmap_choice = st.sidebar.radio(
        "Quelle carte de chaleur souhaitez-vous afficher ?", 
        ["Aucune", "POI naturels", "POI historiques", "POI évenementiels", "Parcs d'attraction"]
    )
    if heatmap_choice == "POI naturels":
        heatmap_layer = grab_poi_data("npoi")
        layers.append(heatmap_layer)
    if heatmap_choice == "POI historiques":
        heatmap_layer = grab_poi_data("hpoi")
        layers.append(heatmap_layer)
    if heatmap_choice == "POI évenementiels":
        heatmap_layer = grab_poi_data("epoi")
        layers.append(heatmap_layer)
    if heatmap_choice == "Parcs d'attraction":
        heatmap_layer = grab_poi_data("attractions_france")
        layers.append(heatmap_layer)

    if st.session_state.selected_map:
        render_map(st.session_state.selected_map, layers)
    else:
        st.write("Sélectionnez une option dans la barre latérale pour afficher la carte correspondante.")

def normalize_visitors(visitors):
    # Increased minimum radius so base stations are visible at national zoom
    min_radius = 3 # 500 for meters
    max_radius = 30 # 20000 for meters
    
    # Using Square Root scaling to prevent Gare du Nord from squashing the rest of the data
    sqrt_visitors = np.sqrt(visitors)
    min_sqrt = np.sqrt(0)
    max_sqrt = np.sqrt(275993741)

    normalized_radius = ((sqrt_visitors - min_sqrt) / (max_sqrt - min_sqrt)) * (max_radius - min_radius) + min_radius
    return normalized_radius

def grab_poi_data(poi_type):
    df=pd.read_csv("data/"+poi_type+".csv", sep=",")

    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[Longitude, Latitude]",
        opacity=0.9,
        radiusPixels=50,     # Adjust the spread of the heat
    )
    return heatmap_layer

def grab_station_data():
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
        # radius_max_pixels=30,
        # radius_min_pixels=3,
        radius_units = String("pixels"),
        pickable=True,     # Allows hovering/clicking
    )
    return scatter_layer

def main():
    map_selector()

if __name__ == "__main__":
    main()