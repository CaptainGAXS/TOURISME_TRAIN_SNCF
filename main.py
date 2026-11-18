from pydeck.types import String # type: ignore
import pandas as pd # type: ignore
import streamlit as st # type: ignore
import pydeck as pdk # type: ignore
import numpy as np # type: ignore

from show_map import render_map
from scripts.itinerary.itinerary_ui import itinerary_sidebar

def map_selector(display_area):
    st.sidebar.write("Choisissez un fond avant les données.")
    st.sidebar.divider()
    st.sidebar.write("Fonds de carte :")

    layers = []
    if "selected_map" not in st.session_state:
        st.session_state.selected_map = None
    if st.sidebar.button("Carte par départements"):
        st.session_state.selected_map = "data/departements-50m.geojson"
    if st.sidebar.button("Carte par régions"):
        st.session_state.selected_map = "data/regions-50m.geojson"

    st.sidebar.divider()
    st.sidebar.write("Choisissez les données à afficher sur la carte :")

    if st.sidebar.checkbox("Gares"):
        scatter_layer = grab_station_data()
        layers.append(scatter_layer)

    heatmap_choice = st.sidebar.radio(
        "Cartes de chaleur:", 
        ["Aucune", "POI naturels", "POI historiques", "POI évenementiels", "Parcs d'attraction", "Gares et proximité de POI"]
    )
    if heatmap_choice == "POI naturels":
        heatmap_layer = grab_poi_data("npoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "POI historiques":
        heatmap_layer = grab_poi_data("hpoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "POI évenementiels":
        heatmap_layer = grab_poi_data("epoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "Parcs d'attraction":
        heatmap_layer = grab_poi_data("attractions_france")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "Gares et proximité de POI":
        heatmap_layer = grab_station_proximity_data()
        layers = [heatmap_layer] + layers

    layers = layers + itinerary_sidebar()

    if st.session_state.selected_map:
        render_map(display_area, st.session_state.selected_map, layers)
    else:
        display_area.write("Sélectionnez une option dans la barre latérale pour afficher la carte correspondante.")


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

def station_selector(display_area):
    df_dep= pd.read_csv("data/departements-france.csv", sep=",")
    df_stations = pd.read_csv("data/stations.csv", sep=",")
    df_poi = pd.read_csv("data/station_poi_index.csv", sep=",")
    st.session_state.selected_department = st.sidebar.selectbox("Choisissez un département:", df_dep["nom_departement"], index = None, placeholder="Filtrage par département")
    if st.session_state.selected_department:
        dep_number = df_dep[df_dep["nom_departement"] == st.session_state.selected_department]["code_departement"].values[0]
        filtered_stations = df_stations[df_stations["departement"] == dep_number]
        st.session_state.selected_station = st.sidebar.selectbox("Choisissez une gare:", filtered_stations["name"])
    else:
        st.session_state.selected_station = st.sidebar.selectbox("Choisissez une gare:", df_stations["name"], index = None, placeholder = "Gares")
    if st.session_state.selected_station:
        station_index = df_stations[df_stations["name"] == st.session_state.selected_station]["station_id"].values[0]
        poi_list = df_poi[df_poi["station_id"] == station_index]["poi_index"]
        display_area.write(f"Les points d'intérêt autour de la gare {st.session_state.selected_station} sont : \n{poi_list.values}")

def weight_poi_prox(poi_count_20km,poi_count_15km,poi_count_10km,poi_count_5km):
    weights = {
        '20km': 0.2,
        '15km': 0.3,
        '10km': 0.4,
        '5km': 0.5
    }
    weighted_sum = (weights['20km'] * poi_count_20km +
                    weights['15km'] * poi_count_15km +
                    weights['10km'] * poi_count_10km +
                    weights['5km'] * poi_count_5km)
    return weighted_sum

def grab_station_proximity_data():
    df = pd.read_csv("data/station_features.csv", sep=",")
    df["weight_proximity"] = weight_poi_prox(df["poi_count_20km"], df["poi_count_15km"], df["poi_count_10km"], df["poi_count_5km"])

    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[lon, lat]",
        get_weight="weight_proximity",
        opacity=0.9,
        radiusPixels=100,     # Adjust the spread of the heat
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
    display_area = st.empty()
    map_selector(display_area)
    station_selector(display_area)

if __name__ == "__main__":
    main()