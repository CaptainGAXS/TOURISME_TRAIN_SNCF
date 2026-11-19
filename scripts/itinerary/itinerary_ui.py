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
    from .planner import describe, hhmm, mode_name, plan
    from .route_map import journey_layers
except ImportError:
    from carbon import car_co2, journey_co2, leg_co2
    from network import load_network
    from planner import describe, hhmm, mode_name, plan
    from route_map import journey_layers


def co2_text(kg):
    """1.2845 -> '1,28 kg CO2e' (French decimal comma)"""
    return f"{kg:.2f}".replace(".", ",") + " kg CO2e"

@st.cache_data(show_spinner="Calcul des trajets...")
def cached_plan(_network, day_key, origin, destination, start_seconds, n=5):
    return plan(_network, origin, destination, start_seconds, n=n)

@st.cache_resource(show_spinner="Chargement des horaires...")
def get_network(day):
    """Loaded once per date, then reused (Streamlit reruns the script on every click)."""
    return load_network(day)


def date_time_inputs(container=st.sidebar):
    """Date + earliest departure time. Returns (network of that day, start time in seconds)."""
    day = container.date_input(
        "Date", date.today() + timedelta(days=1), key="itin_date"
    )
    start = container.time_input("Départ après", time(7, 0), key="itin_time")
    network = get_network(day.strftime("%Y%m%d"))
    return network, start.hour * 3600 + start.minute * 60


def journey_panel(network, origin, destination, start_seconds, container=st.sidebar):
    """Journeys between two GTFS station_ids: choose one, show details + CO2.
    Returns the pydeck layers of the chosen journey ([] if none)."""
    stations, connections, trips, footpaths = network

    # ---- search
    day_key = str(st.session_state.get("itin_date", ""))
    journeys = cached_plan(network, day_key, origin, destination, start_seconds, n=5)
    if not journeys:
        container.warning("Aucun trajet trouvé.")
        return []

    # ---- choose one journey
    summaries = [
        f"{describe(legs, stations, trips).splitlines()[0]} · "
        f"{co2_text(journey_co2(legs, stations, trips))}"
        for legs in journeys
    ]
    choice = container.radio(
        "Trajets",
        range(len(journeys)),
        format_func=lambda i: summaries[i],
        key="itin_choice",
    )
    legs = journeys[choice]

    # ---- whole journey vs. car
    train_kg = journey_co2(legs, stations, trips)
    car_kg = car_co2(origin, destination, stations)
    col1, col2 = container.columns(2)
    col1.metric("Train", co2_text(train_kg))
    if train_kg > 0:
        ratio = car_kg / train_kg
        col2.metric(
            "Voiture (2,2 pers.)",
            co2_text(car_kg),
            delta=f"×{ratio:.0f} plus élevé",
            delta_color="inverse",
        )
    else:
        col2.metric("Voiture (2,2 pers.)", co2_text(car_kg))

    # ---- Step-by-step itinerary card
    with container.container(border=True):
        st.markdown("**Détail du trajet**")
        for leg in legs:
            start_name = stations[leg["from"]]["name"]
            end_name = stations[leg["to"]]["name"]
            dep_str = hhmm(leg["dep"])
            arr_str = hhmm(leg["arr"])

            if leg["mode"] == "train":
                trip = trips[leg["trip"]]
                label = f"{trip['kind']} {trip['number']}"
                co2_str = f" · *{co2_text(leg_co2(leg, stations, trips))}*"
            else:
                mins = (leg["arr"] - leg["dep"]) // 60
                label = f"{mode_name(leg['mode']).capitalize()} ({mins} min)"
                co2_str = ""

            st.markdown(
                f"**{label}**{co2_str}  \n"
                f"`{dep_str}` {start_name} → `{arr_str}` {end_name}"
            )

    container.caption(
        "Estimation du CO₂e par voyageur (facteurs SNCF par km × distance)."
    )


    return journey_layers(legs, stations, trips)


def itinerary_sidebar(container=st.sidebar):
    """Stand-alone version: its own date, time, From and To inputs, drawn in `container`."""
    container.header("Itinéraire")
    network, start_seconds = date_time_inputs(container)
    stations = network[0]

    name_to_id = {s["name"]: sid for sid, s in stations.items()}
    names = sorted(name_to_id)
    origin = container.selectbox(
        "Départ", names, index=names.index("Nancy"), key="itin_from"
    )
    destination = container.selectbox(
        "Arrivée", names, index=names.index("Paris Est"), key="itin_to"
    )
    return journey_panel(
        network, name_to_id[origin], name_to_id[destination], start_seconds, container
    )
