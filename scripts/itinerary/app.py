"""
Sample page: how to use the journey planner and recommendation modules.

Run from the repo root:
    venv/Scripts/python.exe -m streamlit run scripts/itinerary/app.py

Modules
    scripts/itinerary/network.py       SNCF timetable of one day -> network (no Streamlit)
    scripts/itinerary/planner.py       journeys, travel times to all stations (no Streamlit)
    scripts/itinerary/carbon.py        CO2e of a journey, comparison with the car (no Streamlit)
    scripts/itinerary/route_map.py     journey -> pydeck layers (no Streamlit)
    scripts/itinerary/itinerary_ui.py  Streamlit sidebar: journey between two stations
    scripts/research/recommend_ui.py   Streamlit sidebar: recommended stations + travel time

The *_ui functions draw their inputs in the sidebar and return pydeck layers, so the
layers can be added to any map, e.g. render_map(mappath, layers) in show_map.py.
From a file in another folder (e.g. main.py at the repo root), add both folders first:
    sys.path.append("scripts/itinerary")
    sys.path.append("scripts/research")

Without Streamlit:
    from network import load_network
    from planner import describe, find_station, plan, travel_times
    network = load_network("20261120")
    stations, connections, trips, footpaths = network
    nancy, metz = find_station("Nancy", stations), find_station("Metz", stations)
    journeys = plan(network, nancy, metz, 7 * 3600)        # list of journeys (lists of legs)
    print(describe(journeys[0], stations, trips))
    times = travel_times(network, nancy, 7 * 3600)         # {station_id: seconds}
"""

import sys
from pathlib import Path

import pydeck as pdk
import streamlit as st

sys.path.append(str(Path(__file__).resolve().parents[2] / "scripts" / "research"))
from itinerary_ui import date_time_inputs, itinerary_sidebar, journey_panel  # noqa: E402
from recommend_ui import recommend_sidebar  # noqa: E402

st.set_page_config(page_title="Itinéraire SNCF", layout="wide")

example = st.sidebar.radio(
    "Example", ["Journey (A -> B)", "Recommendation -> journey"], key="app_example"
)

if example == "Journey (A -> B)":
    # Example 1: one call. The function has its own date, time, From and To inputs.
    layers = itinerary_sidebar()

else:
    # Example 2: pieces combined. One date/time for both, the recommended station
    # chosen by the user becomes the destination of the journey.
    st.sidebar.header("Trip")
    network, start_seconds = date_time_inputs()
    origin, destination, layers = recommend_sidebar(network, start_seconds)
    if destination is not None:  # None: no train to that station on that day
        st.sidebar.header("Itinéraire")
        layers = layers + journey_panel(network, origin, destination, start_seconds)

# Any pydeck map can show the layers. Every layer has a "name" column for the tooltip.
st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=46.6, longitude=2.2, zoom=5),
        tooltip={"text": "{name}"},
    ),
    height=700,
)
