"""
from itinerary_ui import itinerary_sidebar
layers = itinerary_sidebar()  # pydeck layers of the chosen journey ([] if none)
deck = pdk.Deck(layers=[other_layer] + layers, ...)
"""

from datetime import date, time, timedelta

import streamlit as st

from carbon import car_co2, journey_co2, leg_co2
from network import load_network
from planner import describe, plan
from route_map import journey_layers


def co2_text(kg, exact):
    """1.28 -> '1.28 kgCO2e', or '≈1.28 kgCO2e' when the distance is estimated."""
    return f"{'' if exact else '≈'}{kg:.2f} kgCO2e"


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
    summaries = [
        f"{describe(legs, stations, trips).splitlines()[0]} · "
        f"{co2_text(*journey_co2(legs, stations, trips))}"
        for legs in journeys
    ]
    choice = st.sidebar.radio(
        "Journeys",
        range(len(journeys)),
        format_func=lambda i: summaries[i],
        key="itin_choice",
    )
    legs = journeys[choice]
    lines = describe(legs, stations, trips).splitlines()  # line 0 = summary, then 1 line per leg
    for i, leg in enumerate(legs):
        if leg["mode"] == "train":
            lines[i + 1] += "  " + co2_text(*leg_co2(leg, stations, trips))

    # ---- whole journey vs. car
    train_kg, train_exact = journey_co2(legs, stations, trips)
    car_kg, car_exact = car_co2(name_to_id[origin], name_to_id[destination], stations)
    lines.append("")
    lines.append(f"Total (train): {co2_text(train_kg, train_exact)}")
    car_line = f"Car (petrol, 2.2 pers.): {co2_text(car_kg, car_exact)}"
    if train_kg > 0:  # 0 when the journey is only walking
        car_line += f"  (x{car_kg / train_kg:.0f})"
    lines.append(car_line)
    st.sidebar.code("\n".join(lines), language=None)
    st.sidebar.caption("CO2e per traveller, SNCF factors per km. ≈ = estimated distance.")

    return journey_layers(legs, stations, trips)
