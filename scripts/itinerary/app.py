"""
Sample page: how to use the journey planner modules.

Run from the repo root:
    venv/Scripts/python.exe -m streamlit run scripts/itinerary/app.py

Modules
    scripts/itinerary/network.py       SNCF timetable of one day -> network (no Streamlit)
    scripts/itinerary/planner.py       journeys, travel times to all stations (no Streamlit)
    scripts/itinerary/carbon.py        CO2e of a journey, comparison with the car (no Streamlit)
    scripts/itinerary/route_map.py     journey -> pydeck layers (no Streamlit)
    scripts/itinerary/itinerary_ui.py  Streamlit inputs: journey between two stations

itinerary_sidebar() draws its inputs (in the sidebar by default, or in the container
given as argument) and returns pydeck layers, so the layers can be added to any map,
e.g. render_map(display_area, mappath, layers) in show_map.py.
From a file in another folder (e.g. main.py at the repo root), add the folder first:
    sys.path.append("scripts/itinerary")

The pieces can also be combined (e.g. with your own station choice):
    network, start_seconds = date_time_inputs(container)
    layers = journey_panel(network, origin_id, destination_id, start_seconds, container)

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

import pydeck as pdk
import streamlit as st

from itinerary_ui import itinerary_sidebar

st.set_page_config(page_title="Itinéraire SNCF", layout="wide")

example = st.sidebar.radio(
    "Example", ["In the sidebar", "In a collapsible box"], key="app_example"
)

if example == "In the sidebar":
    # Example 1: default, the inputs are drawn directly in the sidebar.
    layers = itinerary_sidebar()
else:
    # Example 2: the same inputs inside a collapsible box (expander) of the sidebar.
    layers = itinerary_sidebar(st.sidebar.expander("Itinéraire", expanded=True))

# Any pydeck map can show the layers. Every layer has a "name" column for the tooltip.
st.pydeck_chart(
    pdk.Deck(
        layers=layers,
        initial_view_state=pdk.ViewState(latitude=46.6, longitude=2.2, zoom=5),
        tooltip={"text": "{name}"},
    ),
    width="stretch",
    height=700,
)
