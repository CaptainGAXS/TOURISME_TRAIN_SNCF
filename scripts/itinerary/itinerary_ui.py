"""
from itinerary_ui import itinerary_sidebar
layers = itinerary_sidebar()  # pydeck layers of the chosen journey ([] if none)
deck = pdk.Deck(layers=[other_layer] + layers, ...)
"""

from datetime import date, time, timedelta

import streamlit as st

from network import load_network
from planner import describe, plan
from route_map import journey_layers


@st.cache_resource(show_spinner="Loading timetable (about 10 s)...")
def get_network(day):
    """Loaded once per date, then reused (Streamlit reruns the script on every click)."""
    return load_network(day)


def itinerary_sidebar():
    st.sidebar.header("Itinéraire")

    # ---- inputs
    day = st.sidebar.date_input(
        "Date", date.today() + timedelta(days=1), key="itin_date"
    )
    start = st.sidebar.time_input("Departure after", time(7, 0), key="itin_time")
    network = get_network(day.strftime("%Y%m%d"))
    stations, connections, trips, footpaths = network

    name_to_id = {s["name"]: sid for sid, s in stations.items()}
    names = sorted(name_to_id)
    origin = st.sidebar.selectbox(
        "From", names, index=names.index("Nancy"), key="itin_from"
    )
    destination = st.sidebar.selectbox(
        "To", names, index=names.index("Paris Est"), key="itin_to"
    )

    # ---- search
    journeys = plan(
        network,
        name_to_id[origin],
        name_to_id[destination],
        start.hour * 3600 + start.minute * 60,
        n=5,
    )
    if not journeys:
        st.sidebar.warning("No journey found.")
        return []

    # ---- choose one journey
    summaries = [describe(legs, stations, trips).splitlines()[0] for legs in journeys]
    choice = st.sidebar.radio(
        "Journeys",
        range(len(journeys)),
        format_func=lambda i: summaries[i],
        key="itin_choice",
    )
    legs = journeys[choice]
    st.sidebar.code(describe(legs, stations, trips), language=None)

    return journey_layers(legs, stations, trips)
