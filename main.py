from pydeck.types import String  # type: ignore
import pandas as pd  # type: ignore
import streamlit as st  # type: ignore
import pydeck as pdk  # type: ignore
import numpy as np  # type: ignore

from show_map import render_map
from scripts.itinerary.itinerary_ui import itinerary_sidebar,date_time_inputs, journey_panel
from scripts.itinerary.network import uic_to_station_id
from scripts.research.recommender import RecommendationCriteria, TourismRecommender, get_top_pois_for_recommendations
from scripts.research.station_features import load_pois
from datetime import date, time, timedelta

def destination_recommender_ui():
    st.sidebar.header("Recommandation de destination")
    
    # Load stations for the dropdown
    stations_df = pd.read_csv("data/station_features.csv", dtype={"station_id": "string", "departement": "string"})
    station_names = stations_df["name"].sort_values().tolist()

    # 1. User Inputs (Sidebar)
    departure = st.sidebar.selectbox("Gare de départ", station_names, index=station_names.index("Paris Est") if "Paris Est" in station_names else 0)
    max_distance = st.sidebar.slider("Distance max (km)", 10.0, 1000.0, 200.0, step=10.0)
    
    st.sidebar.subheader("Préférences thématiques")
    weight_culture = st.sidebar.slider("Culture", 0.0, 1.0, 0.25)
    weight_nature = st.sidebar.slider("Nature", 0.0, 1.0, 0.25)
    weight_events = st.sidebar.slider("Événements", 0.0, 1.0, 0.25)
    weight_attractions = st.sidebar.slider("Attractions", 0.0, 1.0, 0.25)
    
    exclude_paris_option = st.sidebar.checkbox("Exclure Paris et l'Île-de-France", value=False)

    if st.sidebar.button("Rechercher des gares"):
        if sum([weight_culture, weight_nature, weight_events, weight_attractions]) == 0:
            st.sidebar.error("Veuillez sélectionner au moins une préférence > 0.")
            return None

        # 2. Setup Criteria using max_distance_km
        criteria = RecommendationCriteria(
            culture=weight_culture,
            nature=weight_nature,
            events=weight_events,
            attractions=weight_attractions,
            departure_station=departure,
            max_distance_km=max_distance,
            exclude_paris=exclude_paris_option
        )

        with st.spinner("Recherche des meilleures destinations et activités..."):
            # 3. Run the Recommender for stations
            recommender = TourismRecommender().fit(stations_df)
            results = recommender.recommend(criteria, n_results=5)
            
            # 4. Load POI data and spatial indexes
            pois = load_pois()
            station_poi_index = pd.read_csv("data/station_poi_index.csv", dtype={"station_id": "string"})
            
            # 5. Fetch 20 POIs distributed according to the user's preferences
            top_pois = get_top_pois_for_recommendations(
                results,
                criteria,
                pois,
                station_poi_index,
                n_pois=20,
                favor_poi_with_website=recommender.favor_poi_with_website
            )

            # SAVE TO SESSION STATE
            st.session_state.reco_results = results
            st.session_state.reco_pois = top_pois
            st.session_state.departure_name = departure
            st.session_state.selected_itinerary = None # Reset selected itinerary
                
    if "reco_results" in st.session_state:
            st.success("Destinations recommandées trouvées !")
            results = st.session_state.reco_results
            top_pois = st.session_state.reco_pois
        
            for _, station in results.iterrows():
                # Display the station name and straight-line distance cleanly
                st.subheader(f"{station['name']} — {station['distance_from_departure_km']:.0f} km")

                if st.button(f"Voir les trains pour {station['name']}", key=f"itin_{station['station_id']}"):
                    st.session_state.selected_itinerary = station['name']
                    st.rerun()
                
                # Filter the top_pois dataframe for just this station
                station_pois = top_pois[top_pois["station_name"] == station["name"]]
                
                if not station_pois.empty:
                    # Select relevant columns including the website
                    display_pois = station_pois[["Nom", "category", "distance_km", "Site internet"]].copy()
                    
                    # Format the distance
                    display_pois["distance_km"] = display_pois["distance_km"].round(1).astype(str) + " km"
                    
                    # Internal category codes -> same labels as the preference sliders
                    display_pois["category"] = display_pois["category"].replace({
                        "hpoi": "Culture",
                        "npoi": "Nature",
                        "epoi": "Événements",
                        "attraction": "Attractions",
                    })

                    # Clean up missing websites for a better display
                    display_pois["Site internet"] = display_pois["Site internet"].fillna("-")
                    
                    # Rename columns for the user interface
                    display_pois.rename(columns={
                        "category": "Catégorie", 
                        "distance_km": "Distance",
                        "Site internet": "Site web"
                    }, inplace=True)
                    
                    # Display as a clean table on the main screen
                    st.dataframe(
                        display_pois, 
                        hide_index=True, 
                        use_container_width=True,
                        column_config={
                            "Site web": st.column_config.LinkColumn("Site web")
                        }
                    )
                else:
                    st.write("Aucune activité trouvée selon ces critères.")
                    
                st.divider() # Add a visual separator between destinations
            return results

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
        "Cartes de chaleur :",
        [
            "Aucune",
            "POI naturels",
            "POI historiques",
            "POI événementiels",
            "Parcs d'attractions",
            "Gares et proximité de POI",
        ],
    )
    if heatmap_choice == "POI naturels":
        heatmap_layer = grab_poi_data("npoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "POI historiques":
        heatmap_layer = grab_poi_data("hpoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "POI événementiels":
        heatmap_layer = grab_poi_data("epoi")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "Parcs d'attractions":
        heatmap_layer = grab_poi_data("attractions_france")
        layers = [heatmap_layer] + layers
    if heatmap_choice == "Gares et proximité de POI":
        heatmap_layer = grab_station_proximity_data()
        layers = [heatmap_layer] + layers

    map_layers = []
    
    if st.session_state.get("selected_itinerary"):
        network, start_seconds = date_time_inputs()
        gtfs_stations = network[0]

        # station name -> UIC code -> GTFS station (names differ, e.g. "Paris Gare de Lyon Hall 1 - 2")
        stations_df = pd.read_csv("data/stations.csv", dtype={"uic": "string"})
        name_to_uic = dict(zip(stations_df["name"], stations_df["uic"]))
        origin_id = uic_to_station_id(
            name_to_uic.get(st.session_state.departure_name), gtfs_stations
        )
        destination_id = uic_to_station_id(
            name_to_uic.get(st.session_state.selected_itinerary), gtfs_stations
        )

        if origin_id and destination_id:
            map_layers = journey_panel(network, origin_id, destination_id, start_seconds)
        else:
            st.sidebar.warning("Pas de train SNCF pour cette gare.")

    layers = layers + map_layers # + itinerary_sidebar()

    recommandations = destination_recommender_ui()
    st.write(recommandations)

    if st.session_state.selected_map:
        render_map(display_area, st.session_state.selected_map, layers)
    else:
        display_area.write(
            "Sélectionnez une option dans la barre latérale pour afficher la carte correspondante."
        )


def normalize_visitors(visitors):
    # Increased minimum radius so base stations are visible at national zoom
    min_radius = 3  # 500 for meters
    max_radius = 30  # 20000 for meters

    # Using Square Root scaling to prevent Gare du Nord from squashing the rest of the data
    sqrt_visitors = np.sqrt(visitors)
    min_sqrt = np.sqrt(0)
    max_sqrt = np.sqrt(275993741)

    normalized_radius = ((sqrt_visitors - min_sqrt) / (max_sqrt - min_sqrt)) * (
        max_radius - min_radius
    ) + min_radius
    return normalized_radius


def grab_poi_data(poi_type):
    df = pd.read_csv("data/" + poi_type + ".csv", sep=",")

    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[Longitude, Latitude]",
        opacity=0.9,
        radiusPixels=50,  # Adjust the spread of the heat
    )
    return heatmap_layer


def station_selector(display_area):
    df_dep = pd.read_csv("data/departements-france.csv", sep=",")
    df_stations = pd.read_csv("data/stations.csv", sep=",")
    df_poi = pd.read_csv("data/station_poi_index.csv", sep=",")
    st.session_state.selected_department = st.sidebar.selectbox(
        "Choisissez un département :",
        df_dep["nom_departement"],
        index=None,
        placeholder="Filtrage par département",
    )
    if st.session_state.selected_department:
        dep_number = df_dep[
            df_dep["nom_departement"] == st.session_state.selected_department
        ]["code_departement"].values[0]
        filtered_stations = df_stations[df_stations["departement"] == dep_number]
        st.session_state.selected_station = st.sidebar.selectbox(
            "Choisissez une gare :", filtered_stations["name"]
        )
    else:
        st.session_state.selected_station = st.sidebar.selectbox(
            "Choisissez une gare :", df_stations["name"], index=None, placeholder="Gares"
        )
    if st.session_state.selected_station:
        station_index = df_stations[
            df_stations["name"] == st.session_state.selected_station
        ]["station_id"].values[0]
        poi_list = df_poi[df_poi["station_id"] == station_index]["poi_index"]
        display_area.write(
            f"Les points d'intérêt autour de la gare {st.session_state.selected_station} sont : \n{poi_list.values}"
        )


def weight_poi_prox(poi_count_20km, poi_count_15km, poi_count_10km, poi_count_5km):
    weights = {"20km": 0.2, "15km": 0.3, "10km": 0.4, "5km": 0.5}
    weighted_sum = (
        weights["20km"] * poi_count_20km
        + weights["15km"] * poi_count_15km
        + weights["10km"] * poi_count_10km
        + weights["5km"] * poi_count_5km
    )
    return weighted_sum


def grab_station_proximity_data():
    df = pd.read_csv("data/station_features.csv", sep=",")
    df["weight_proximity"] = weight_poi_prox(
        df["poi_count_20km"],
        df["poi_count_15km"],
        df["poi_count_10km"],
        df["poi_count_5km"],
    )

    heatmap_layer = pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[lon, lat]",
        get_weight="weight_proximity",
        opacity=0.9,
        radiusPixels=100,  # Adjust the spread of the heat
    )
    return heatmap_layer


def grab_station_data():
    df = pd.read_csv("data/stations.csv", sep=",")
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
        radius_units=String("pixels"),
        pickable=True,  # Allows hovering/clicking
    )
    return scatter_layer


def main():
    display_area = st.empty()
    map_selector(display_area)
    # station_selector(display_area)


if __name__ == "__main__":
    main()
