"""
Recommendation (recommender.py) + travel time (scripts/itinerary), as a Streamlit sidebar.
network, start_seconds = date_time_inputs()                  # from itinerary_ui
origin, destination, layers = recommend_sidebar(network, start_seconds)
if destination:
    layers += journey_panel(network, origin, destination, start_seconds)

"""

import sys
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

from recommender import RADIUSES_KM, RecommendationCriteria, TourismRecommender

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "scripts" / "itinerary"))
from network import load_stations, uic_to_station_id  # noqa: E402
from planner import travel_times  # noqa: E402


@st.cache_resource(show_spinner="Preparing recommendations (about 5 s)...")
def get_recommender():
    """Fitted once. Adds 'gtfs_id' (station id in the timetable, None if not in it)."""
    features = pd.read_csv(
        ROOT / "data" / "station_features.csv",
        dtype={"station_id": str, "uic": str, "insee": str},
    )
    gtfs_stations, _ = load_stations()
    features["gtfs_id"] = features["uic"].map(
        lambda u: uic_to_station_id(u, gtfs_stations)
    )
    return TourismRecommender().fit(features), features


def recommend_sidebar(network, start_seconds):
    """Inputs -> list of recommended stations -> choose one.
    Returns (origin gtfs_id, chosen destination gtfs_id or None, pydeck layers)."""
    st.sidebar.header("Recommendation")
    recommender, features = get_recommender()

    # ---- departure: only stations that are in the timetable
    departures = features[features["gtfs_id"].notna()].sort_values("name")
    names = dict(zip(departures["station_id"], departures["name"]))
    ids = list(names)
    default = ids.index(
        departures.loc[departures["name"] == "Nancy", "station_id"].iloc[0]
    )
    origin_sid = st.sidebar.selectbox(
        "From", ids, index=default, format_func=names.get, key="rec_from"
    )
    origin = departures.set_index("station_id").loc[origin_sid, "gtfs_id"]

    # ---- preferences
    culture = st.sidebar.slider(
        "Culture / history", 0.0, 1.0, 0.5, 0.1, key="rec_culture"
    )
    nature = st.sidebar.slider("Nature", 0.0, 1.0, 0.5, 0.1, key="rec_nature")
    events = st.sidebar.slider("Events", 0.0, 1.0, 0.5, 0.1, key="rec_events")
    attractions = st.sidebar.slider(
        "Attractions", 0.0, 1.0, 0.5, 0.1, key="rec_attractions"
    )
    radius = st.sidebar.select_slider(
        "POI radius around the station (km)", sorted(RADIUSES_KM), 10, key="rec_radius"
    )
    exclude_idf = st.sidebar.checkbox("Exclude Île-de-France", key="rec_no_idf")

    # ---- filter: none / distance / travel time
    mode = st.sidebar.radio(
        "Limit by", ["None", "Distance", "Travel time"], horizontal=True, key="rec_mode"
    )
    max_km = max_hours = None
    if mode == "Distance":
        max_km = st.sidebar.slider("Max distance (km)", 50, 1000, 300, 50, key="rec_km")
    if mode == "Travel time":
        max_hours = st.sidebar.slider(
            "Max travel time (h)", 0.5, 8.0, 3.0, 0.5, key="rec_hours"
        )
    n_results = st.sidebar.slider("Number of results", 3, 20, 10, key="rec_n")

    # ---- recommend (all ranked stations, then filter by travel time and keep the best ones)
    try:
        recs = recommender.recommend(
            RecommendationCriteria(
                culture=culture,
                nature=nature,
                events=events,
                attractions=attractions,
                radius_km=radius,
                departure_station_id=origin_sid,
                max_distance_km=max_km,
                exclude_ile_de_france=exclude_idf,
                n_results=len(features),
            )
        )
    except (
        ValueError
    ) as error:  # e.g. all preferences at 0, or nothing in the search scope
        st.sidebar.warning(str(error))
        return origin, None, []

    times = travel_times(network, origin, start_seconds)  # seconds, same day only
    recs["travel_seconds"] = recs["gtfs_id"].map(
        times
    )  # NaN: not reachable / not in timetable
    if max_hours is not None:
        recs = recs[recs["travel_seconds"] <= max_hours * 3600]
    recs = recs.head(n_results).reset_index(drop=True)
    if recs.empty:
        st.sidebar.warning("No station matches. Try a larger limit.")
        return origin, None, []

    # ---- choose one recommended station
    def label(i):
        row = recs.loc[i]
        seconds = row["travel_seconds"]
        travel = (
            "no train"
            if pd.isna(seconds)
            else f"{int(seconds) // 3600}h{int(seconds) % 3600 // 60:02d}"
        )
        return f"{row['name']} · {travel} · {row['distance_from_departure_km']:.0f} km"

    choice = st.sidebar.radio(
        "Recommended stations", recs.index, format_func=label, key="rec_choice"
    )
    chosen = recs.loc[choice]
    destination = None if pd.isna(chosen["travel_seconds"]) else chosen["gtfs_id"]
    if destination is None:
        st.sidebar.info("No train to this station on this day from the departure time.")

    return origin, destination, [recommendation_layer(recs, choice)]


def recommendation_layer(recs, chosen_index):
    """Recommended stations as dots (the chosen one in another color), tooltip 'name'."""
    dots = [
        {
            "lon": row["lon"],
            "lat": row["lat"],
            "name": f"#{i + 1} {row['name']} ({row['dominant_category']})",
            "color": [230, 120, 0] if i == chosen_index else [250, 190, 80],
        }
        for i, row in recs.iterrows()
    ]
    return pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame(dots),
        get_position="[lon, lat]",
        get_fill_color="color",
        get_line_color=[0, 0, 0],
        stroked=True,
        line_width_min_pixels=1,
        radius_min_pixels=6,
        pickable=True,
    )
