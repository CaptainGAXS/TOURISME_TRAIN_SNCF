"""
from itinerary_ui import itinerary_sidebar
layers = itinerary_sidebar()  # pydeck layers of the chosen journey ([] if none)
deck = pdk.Deck(layers=[other_layer] + layers, ...)

network, start_seconds = date_time_inputs()
layers = journey_panel(network, origin_id, destination_id, start_seconds)

Every function takes an optional `container` where its inputs and results are drawn
(default: the sidebar), e.g. a collapsible box:
layers = itinerary_sidebar(st.sidebar.expander("Itinéraire", expanded=True))
"""

from datetime import date, time, timedelta

import streamlit as st
import sys

sys.path.append("scripts/itinerary")  # for itinerary_ui.py

try:
    from .carbon import car_co2, journey_co2, leg_co2
    from .network import load_network
    from .planner import describe, plan
    from .route_map import journey_layers
except ImportError:
    from carbon import car_co2, journey_co2, leg_co2
    from network import load_network
    from planner import describe, plan
    from route_map import journey_layers


def co2_text(kg):
    """1.2845 -> '1.28 kgCO2e'"""
    return f"{kg:.2f} kgCO2e"


@st.cache_resource(show_spinner="Loading timetable (about 10 s)...")
def get_network(day):
    """Loaded once per date, then reused (Streamlit reruns the script on every click)."""
    return load_network(day)


def date_time_inputs(container=st.sidebar):
    """Date + earliest departure time. Returns (network of that day, start time in seconds)."""
    day = container.date_input(
        "Date", date.today() + timedelta(days=1), key="itin_date"
    )
    start = container.time_input("Departure after", time(7, 0), key="itin_time")
    network = get_network(day.strftime("%Y%m%d"))
    return network, start.hour * 3600 + start.minute * 60


def journey_panel(network, origin, destination, start_seconds, container=st.sidebar):
    """Journeys between two GTFS station_ids: choose one, show details + CO2.
    Returns the pydeck layers of the chosen journey ([] if none)."""
    stations, connections, trips, footpaths = network

    # ---- search
    journeys = plan(network, origin, destination, start_seconds, n=5)
    if not journeys:
        container.warning("No journey found.")
        return []

    # ---- choose one journey
    summaries = [
        f"{describe(legs, stations, trips).splitlines()[0]} · "
        f"{co2_text(journey_co2(legs, stations, trips))}"
        for legs in journeys
    ]
    choice = container.radio(
        "Journeys",
        range(len(journeys)),
        format_func=lambda i: summaries[i],
        key="itin_choice",
    )
    legs = journeys[choice]
    lines = describe(
        legs, stations, trips
    ).splitlines()  # line 0 = summary, then 1 line per leg
    for i, leg in enumerate(legs):
        if leg["mode"] == "train":
            lines[i + 1] += "  " + co2_text(leg_co2(leg, stations, trips))

    # ---- whole journey vs. car
    train_kg = journey_co2(legs, stations, trips)
    car_kg = car_co2(origin, destination, stations)
    lines.append("")
    lines.append(f"Total (train): {co2_text(train_kg)}")
    car_line = f"Car (petrol, 2.2 pers.): {co2_text(car_kg)}"
    if train_kg > 0:  # 0 when the journey is only walking
        car_line += f"  (x{car_kg / train_kg:.0f})"
    lines.append(car_line)
    container.code("\n".join(lines), language=None)
    container.caption("Estimated CO2e per traveller (SNCF factors per km x distance).")

    return journey_layers(legs, stations, trips)


def itinerary_sidebar(container=st.sidebar):
    """Stand-alone version: its own date, time, From and To inputs, drawn in `container`."""
    container.header("Itinéraire")
    network, start_seconds = date_time_inputs(container)
    stations = network[0]

    name_to_id = {s["name"]: sid for sid, s in stations.items()}
    names = sorted(name_to_id)
    origin = container.selectbox(
        "From", names, index=names.index("Nancy"), key="itin_from"
    )
    destination = container.selectbox(
        "To", names, index=names.index("Paris Est"), key="itin_to"
    )
    return journey_panel(
        network, name_to_id[origin], name_to_id[destination], start_seconds, container
    )
