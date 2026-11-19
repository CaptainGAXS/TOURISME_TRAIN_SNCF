import numpy as np
import pandas as pd
import pydeck as pdk
import streamlit as st
from pydeck.types import String

from scripts.itinerary.itinerary_ui import date_time_inputs, journey_panel
from scripts.itinerary.network import uic_to_station_id
from scripts.research.recommender import (
    RecommendationCriteria,
    TourismRecommender,
    get_top_pois_for_recommendations,
)
from scripts.research.station_features import load_pois
from show_map import render_map
from pathlib import Path

HELP_PATH = Path(__file__).parent / "data/help_button.md"

st.set_page_config(
    page_title="Tourisme Train SNCF",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Cached data & model loaders
# ---------------------------------------------------------------------------


@st.cache_data
def get_station_features():
    return pd.read_csv(
        "data/station_features.csv",
        dtype={"station_id": "string", "departement": "string"},
    )


@st.cache_data
def get_stations_df():
    return pd.read_csv("data/stations.csv", dtype={"uic": "string"})


@st.cache_data
def get_station_poi_index():
    return pd.read_csv("data/station_poi_index.csv", dtype={"station_id": "string"})


@st.cache_data
def get_pois():
    return load_pois()


@st.cache_data
def get_poi_csv(poi_type: str):
    return pd.read_csv(f"data/{poi_type}.csv", sep=",")


@st.cache_resource
def get_recommender():
    stations_df = get_station_features()
    return TourismRecommender().fit(stations_df)


# ---------------------------------------------------------------------------
# Map layer builders
# ---------------------------------------------------------------------------


def normalize_visitors(visitors):
    min_radius, max_radius = 3, 30
    sqrt_visitors = np.sqrt(visitors.fillna(0).clip(lower=0))
    max_sqrt = np.sqrt(275_993_741)
    return (sqrt_visitors / max_sqrt) * (max_radius - min_radius) + min_radius


def weight_poi_prox(poi_count_20km, poi_count_15km, poi_count_10km, poi_count_5km):
    return (
        0.2 * poi_count_20km
        + 0.3 * poi_count_15km
        + 0.4 * poi_count_10km
        + 0.5 * poi_count_5km
    )


def grab_poi_data(poi_type: str):
    df = get_poi_csv(poi_type)
    return pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[Longitude, Latitude]",
        opacity=0.85,
        radiusPixels=50,
    )


def grab_station_proximity_data():
    df = get_station_features().copy()
    df["weight_proximity"] = weight_poi_prox(
        df["poi_count_20km"],
        df["poi_count_15km"],
        df["poi_count_10km"],
        df["poi_count_5km"],
    )
    return pdk.Layer(
        "HeatmapLayer",
        data=df,
        get_position="[lon, lat]",
        get_weight="weight_proximity",
        opacity=0.85,
        radiusPixels=100,
    )


def grab_station_data():
    df = get_stations_df().copy()
    df["map_radius"] = normalize_visitors(df["visitors"])
    return pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color=[0, 180, 100, 200],
        get_line_color=[255, 255, 255],
        line_width_min_pixels=1,
        get_radius="map_radius",
        radius_units=String("pixels"),
        pickable=True,
    )


def grab_recommended_stations_layer(results_df: pd.DataFrame):
    df = results_df.copy()
    df["name"] = df.apply(
        lambda r: f"{r['name']} ({r['distance_from_departure_km']:.0f} km)", axis=1
    )
    return pdk.Layer(
        "ScatterplotLayer",
        data=df,
        get_position="[lon, lat]",
        get_fill_color=[230, 57, 70, 240],
        get_line_color=[255, 255, 255],
        stroked=True,
        line_width_min_pixels=2,
        radius_min_pixels=9,
        pickable=True,
    )


# ---------------------------------------------------------------------------
# Sidebar controls
# ---------------------------------------------------------------------------

PRESETS = {
    "Culture": (0.7, 0.1, 0.1, 0.1),
    "Nature": (0.1, 0.7, 0.1, 0.1),
    "Famille": (0.1, 0.2, 0.2, 0.5),
    "Équilibré": (0.25, 0.25, 0.25, 0.25),
}


def init_state():
    defaults = {
        "w_culture": 0.25,
        "w_nature": 0.25,
        "w_events": 0.25,
        "w_attractions": 0.25,
        "selected_itinerary": None,
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


@st.fragment
def render_recommender_section():
    with st.expander("Trouver une destination", expanded=False):
        stations_df = get_station_features()
        station_names = stations_df["name"].sort_values().tolist()
        default_idx = (
            station_names.index("Paris Est") if "Paris Est" in station_names else 0
        )

        # Presets rerun ONLY this fragment (the HTML map does not reload)
        st.caption("Profils rapides :")
        cols = st.columns(2)
        for i, (label, weights) in enumerate(PRESETS.items()):
            if cols[i % 2].button(label, use_container_width=True):
                (
                    st.session_state.w_culture,
                    st.session_state.w_nature,
                    st.session_state.w_events,
                    st.session_state.w_attractions,
                ) = weights
                st.rerun(scope="fragment")

        # Sliders and inputs inside st.form trigger NO rerun until submitted
        with st.form("recommender_form", border=False):
            departure = st.selectbox("Gare de départ", station_names, index=default_idx)
            max_distance = st.slider("Distance max (km)", 10.0, 1000.0, 250.0, step=10.0)
            radius_km = st.select_slider(
                "Rayon autour de la gare (km)",
                options=[2, 5, 10, 15, 20],
                value=10,
            )
            exclude_paris = st.checkbox("Exclure Paris et l'Île-de-France", value=False)

            weight_culture = st.slider("Culture", 0.0, 1.0, key="w_culture")
            weight_nature = st.slider("Nature", 0.0, 1.0, key="w_nature")
            weight_events = st.slider("Événements", 0.0, 1.0, key="w_events")
            weight_attractions = st.slider("Attractions", 0.0, 1.0, key="w_attractions")

            submitted = st.form_submit_button(
                "Rechercher des gares", type="primary", use_container_width=True
            )

        if submitted:
            if (weight_culture + weight_nature + weight_events + weight_attractions) == 0:
                st.error("Veuillez sélectionner au moins une préférence > 0.")
            else:
                criteria = RecommendationCriteria(
                    culture=weight_culture,
                    nature=weight_nature,
                    events=weight_events,
                    attractions=weight_attractions,
                    radius_km=radius_km,
                    departure_station=departure,
                    max_distance_km=max_distance,
                    exclude_paris=exclude_paris,
                )
                with st.spinner("Recherche des meilleures destinations..."):
                    try:
                        recommender = get_recommender()
                        results = recommender.recommend(criteria, n_results=5)
                        top_pois = get_top_pois_for_recommendations(
                            results,
                            criteria,
                            get_pois(),
                            get_station_poi_index(),
                            n_pois=20,
                            favor_poi_with_website=recommender.favor_poi_with_website,
                        )
                        st.session_state.reco_results = results
                        st.session_state.reco_pois = top_pois
                        st.session_state.departure_name = departure
                        st.session_state.selected_itinerary = None
                        # Full app rerun so the map and tabs update with new results
                        st.rerun(scope="app")
                    except ValueError as err:
                        st.warning(str(err))


def render_sidebar():
    st.sidebar.title("Tourisme Train SNCF")

    # Call the fragment inside the sidebar context
    with st.sidebar:
        render_help_button()

    with st.sidebar.expander("Couches de la carte", expanded=True):
        map_choice = st.radio(
            "Fond de carte",
            ["Régions", "Départements"],
            horizontal=True,
        )
        mappath = (
            "data/regions-50m.geojson"
            if map_choice == "Régions"
            else "data/departements-50m.geojson"
        )

        show_stations = st.checkbox("Afficher toutes les gares", value=False)
        heatmap_choice = st.radio(
            "Carte de chaleur",
            [
                "Aucune",
                "POI naturels",
                "POI historiques",
                "POI événementiels",
                "Parcs d'attractions",
                "Gares et proximité de POI",
            ],
        )

    with st.sidebar:
        render_recommender_section()

    layers = []
    heatmap_map = {
        "POI naturels": "npoi",
        "POI historiques": "hpoi",
        "POI événementiels": "epoi",
        "Parcs d'attractions": "attractions_france",
    }
    if heatmap_choice in heatmap_map:
        layers.append(grab_poi_data(heatmap_map[heatmap_choice]))
    elif heatmap_choice == "Gares et proximité de POI":
        layers.append(grab_station_proximity_data())

    if show_stations:
        layers.append(grab_station_data())

    if "reco_results" in st.session_state:
        layers.append(grab_recommended_stations_layer(st.session_state.reco_results))

    return mappath, layers


# ---------------------------------------------------------------------------
# Main page tabs
# ---------------------------------------------------------------------------

def select_itinerary(station_name: str):
    st.session_state.selected_itinerary = station_name
    st.toast(f"Itinéraire prêt pour {station_name} — ouvrez l'onglet Itinéraire & CO₂.")

def render_recommendations_tab():
    if "reco_results" not in st.session_state:
        st.info(
            "Configurez vos préférences dans la barre latérale puis cliquez sur **Rechercher des gares**."
        )
        return

    results = st.session_state.reco_results
    top_pois = st.session_state.reco_pois
    departure = st.session_state.departure_name

    st.subheader(f"Top {len(results)} destinations au départ de {departure}")

    for idx, (_, station) in enumerate(results.iterrows()):
        with st.container(border=True):
            col_info, col_btn = st.columns([3, 1], vertical_alignment="center")
            with col_info:
                st.markdown(
                    f"### {idx + 1}. {station['name']} "
                    f"— `{station['distance_from_departure_km']:.0f} km`"
                )
            with col_btn:
                st.button(
                    "Voir les trains",
                    key=f"itin_{station['station_id']}",
                    use_container_width=True,
                    on_click=select_itinerary,
                    args=(station["name"],),
                )

            station_pois = top_pois[top_pois["station_name"] == station["name"]]
            with st.expander(
                f"Activités recommandées à proximité ({len(station_pois)})",
                expanded=(idx == 0),
            ):
                if not station_pois.empty:
                    display_pois = station_pois[
                        ["Nom", "category", "distance_km", "Site internet"]
                    ].copy()
                    display_pois["distance_km"] = (
                        display_pois["distance_km"].round(1).astype(str) + " km"
                    )
                    display_pois["category"] = display_pois["category"].replace(
                        {
                            "hpoi": "Culture",
                            "npoi": "Nature",
                            "epoi": "Événements",
                            "attraction": "Attractions",
                        }
                    )
                    display_pois["Site internet"] = display_pois["Site internet"].fillna(
                        ""
                    )
                    display_pois.rename(
                        columns={
                            "category": "Catégorie",
                            "distance_km": "Distance",
                            "Site internet": "Site web",
                        },
                        inplace=True,
                    )
                    st.dataframe(
                        display_pois,
                        hide_index=True,
                        use_container_width=True,
                        column_config={
                            "Site web": st.column_config.LinkColumn("Site web")
                        },
                    )
                else:
                    st.write("Aucune activité trouvée selon ces critères.")


def render_itinerary_tab():
    if not st.session_state.get("selected_itinerary"):
        st.info(
            "Sélectionnez une destination dans l'onglet **Destinations recommandées** "
            "en cliquant sur **Voir les trains**."
        )
        return []

    origin_name = st.session_state.departure_name
    dest_name = st.session_state.selected_itinerary
    st.subheader(f"{origin_name} → {dest_name}")

    col_inputs, col_results = st.columns([1, 2])
    with col_inputs:
        network, start_seconds = date_time_inputs(container=col_inputs)

    gtfs_stations = network[0]
    stations_df = get_stations_df()
    name_to_uic = dict(zip(stations_df["name"], stations_df["uic"]))

    origin_id = uic_to_station_id(name_to_uic.get(origin_name), gtfs_stations)
    destination_id = uic_to_station_id(name_to_uic.get(dest_name), gtfs_stations)

    if origin_id and destination_id:
        with col_results:
            return journey_panel(
                network, origin_id, destination_id, start_seconds, container=col_results
            )

    col_results.warning("Pas de train SNCF trouvé pour cette paire de gares.")
    return []

# ---------------------------------------------------------------------------
# Help button
# ---------------------------------------------------------------------------

@st.dialog("Aide & Guide d'utilisation")
def show_help_dialog():
    st.markdown(HELP_PATH.read_text(encoding="utf-8"))


@st.fragment
def render_help_button():
    if st.button("Aide", use_container_width=True):
        show_help_dialog()


def main():
    init_state()
    mappath, base_layers = render_sidebar()

    has_reco = "reco_results" in st.session_state
    has_itin = bool(st.session_state.get("selected_itinerary"))

    # Show only the map (no empty tab bar) until a search is made
    if not has_reco and not has_itin:
        render_map(st.container(), mappath, base_layers)
        return

    tab_labels = ["Carte & Exploration"]
    if has_reco:
        tab_labels.append("Destinations recommandées")
    if has_itin:
        tab_labels.append("Itinéraire & CO₂")

    tabs = st.tabs(tab_labels)
    tab_by_label = dict(zip(tab_labels, tabs))

    route_layers = []
    if has_itin:
        with tab_by_label["Itinéraire & CO₂"]:
            route_layers = render_itinerary_tab()

    if has_reco:
        with tab_by_label["Destinations recommandées"]:
            render_recommendations_tab()

    with tab_by_label["Carte & Exploration"]:
        render_map(st.container(), mappath, base_layers + route_layers)


if __name__ == "__main__":
    main()