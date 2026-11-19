"""
from itinerary_ui import itinerary_sidebar
layers = itinerary_sidebar()  # pydeck layers of the chosen journey ([] if none)
deck = pdk.Deck(layers=[other_layer] + layers, ...)

network, start_seconds = date_time_inputs()
layers = journey_panel(network, origin_id, destination_id, start_seconds)

Every function takes an optional `container` where its inputs and results are drawn
(default: the sidebar), e.g. a collapsible box:
layers = itinerary_sidebar(st.sidebar.expander("Itinéraire", expanded=True))

More features (same idea: inputs in `container`, pydeck layers returned):
layers = reachable_panel(st.sidebar.expander("Où aller en train ?"))   # stations within N hours
meeting_sidebar(st.sidebar.expander("Où se retrouver ?"))              # inputs -> st.session_state.meeting
layers = meeting_tab()                                                   # meeting results
day_trip_panel(network, origin_id, destination_id, start_seconds)        # last train back
texts = trip_summaries("Paris Est", ["Reims", "Metz"], day)             # {name: 'dép. 07:16 · 1h02 · ...'}
"""

from datetime import date, time, timedelta

import pandas as pd
import streamlit as st
import sys

sys.path.append("scripts/itinerary")  # for itinerary_ui.py

try:
    from .carbon import car_co2, journey_co2, leg_co2
    from .network import ROOT, load_network, load_stations, uic_to_station_id
    from .planner import (
        describe,
        duration_text,
        earliest_arrival,
        hhmm,
        meeting_points,
        plan,
        return_trip,
        travel_times,
    )
    from .route_map import TIME_COLORS, journey_layers, reachable_layer
except ImportError:
    from carbon import car_co2, journey_co2, leg_co2
    from network import ROOT, load_network, load_stations, uic_to_station_id
    from planner import (
        describe,
        duration_text,
        earliest_arrival,
        hhmm,
        meeting_points,
        plan,
        return_trip,
        travel_times,
    )
    from route_map import TIME_COLORS, journey_layers, reachable_layer

DEFAULT_START = time(7, 0)  # "departure after" when no time is chosen
MIN_VISITORS = 1_000_000  # "Où se retrouver ?": only stations with this many passengers a year


def co2_text(kg):
    """1.2845 -> '1,28 kg CO2e' (French decimal comma)"""
    return f"{kg:.2f}".replace(".", ",") + " kg CO2e"


@st.cache_resource(show_spinner="Chargement des horaires...")
def get_network(day):
    """Loaded once per date, then reused (Streamlit reruns the script on every click)."""
    return load_network(day)


def default_day():
    """Travel date chosen in the recommendation form (st.session_state.travel_date), else tomorrow."""
    return st.session_state.get("travel_date") or date.today() + timedelta(days=1)


def seconds_of(t):
    """datetime.time -> seconds since midnight"""
    return t.hour * 3600 + t.minute * 60


@st.cache_data
def station_choices():
    """{name: GTFS station_id} for the stations of data/stations.csv that have SNCF trains
    (same names as the recommendation, matched by UIC code)."""
    gtfs_stations, _ = load_stations()
    df = pd.read_csv(ROOT / "data" / "stations.csv", dtype={"uic": str})
    ids = {
        name: uic_to_station_id(uic, gtfs_stations)
        for name, uic in zip(df["name"], df["uic"])
    }
    return {name: ids[name] for name in sorted(ids) if ids[name]}


@st.cache_data
def busy_stations():
    """GTFS station_ids of the stations with at least MIN_VISITORS passengers a year."""
    gtfs_stations, _ = load_stations()
    df = pd.read_csv(ROOT / "data" / "stations.csv", dtype={"uic": str})
    df = df[df["visitors"] >= MIN_VISITORS]
    return {uic_to_station_id(uic, gtfs_stations) for uic in df["uic"]} - {None}


def date_time_inputs(container=st.sidebar):
    """Date + earliest departure time. Returns (network of that day, start time in seconds)."""
    # start from the travel date of the recommendation form, and follow it when it changes
    if (
        "itin_date" not in st.session_state
        or st.session_state.get("itin_default_day") != default_day()
    ):
        st.session_state.itin_date = default_day()
        st.session_state.itin_default_day = default_day()
    day = container.date_input("Date", key="itin_date")
    start = container.time_input("Départ après", time(7, 0), key="itin_time")
    network = get_network(day.strftime("%Y%m%d"))
    return network, start.hour * 3600 + start.minute * 60


def journey_panel(network, origin, destination, start_seconds, container=st.sidebar):
    """Journeys between two GTFS station_ids: choose one, show details + CO2.
    Returns the pydeck layers of the chosen journey ([] if none)."""
    stations, connections, trips, footpaths = network

    # ---- search
    journeys = plan(network, origin, destination, start_seconds, n=5)
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
    lines.append(f"Total (train) : {co2_text(train_kg)}")
    car_line = f"Voiture : {co2_text(car_kg)}"
    if train_kg > 0:  # 0 when the journey is only walking
        car_line += f"  (x{car_kg / train_kg:.0f})"
    lines.append(car_line)
    container.code("\n".join(lines), language=None)
    container.caption(
        "Estimation du CO2e par voyageur (facteurs SNCF par km x distance)."
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


# ---------------------------------------------------------------------------
# More features
# ---------------------------------------------------------------------------


def reachable_panel(container=st.sidebar):
    """'Où aller en train ?': every station reachable from one station within N hours,
    colored by travel time. Returns the pydeck layers ([] if not shown)."""
    if not container.checkbox("Afficher les gares accessibles", key="reach_show"):
        return []
    choices = station_choices()
    names = list(choices)
    default = st.session_state.get("departure_name", "Paris Est")
    name = container.selectbox(
        "Gare de départ",
        names,
        index=names.index(default) if default in names else 0,
        key="reach_from",
    )
    day = container.date_input("Date", default_day(), key="reach_date")
    start = container.time_input("Départ après", DEFAULT_START, key="reach_time")
    max_hours = container.slider("Temps de trajet max (h)", 1, 8, 3, key="reach_hours")

    network = get_network(day.strftime("%Y%m%d"))
    times = travel_times(network, choices[name], seconds_of(start))
    count = sum(seconds <= max_hours * 3600 for seconds in times.values())
    legend = "  ".join(label for _, _, label in TIME_COLORS)
    container.caption(f"{count} gares accessibles · {legend}")
    return [reachable_layer(times, network[0], max_hours * 3600)]


def trip_summaries(origin_name, destination_names, day, start=DEFAULT_START):
    """Earliest journey (leaving after `start`) from one station to each destination,
    by station name (data/stations.csv). Returns {name: 'dép. 07:16 · 1h02 · 1,54 kg CO2e'}."""
    network = get_network(day.strftime("%Y%m%d"))
    stations, connections, trips, footpaths = network
    choices = station_choices()
    origin = choices.get(origin_name)
    texts = {}
    for name in destination_names:
        destination = choices.get(name)
        legs = None
        if origin and destination:
            legs = earliest_arrival(
                connections, footpaths, origin, destination, seconds_of(start)
            )
        if legs is None:
            texts[name] = "pas de train"
        else:
            texts[name] = (
                f"dép. {hhmm(legs[0]['dep'])} · "
                f"{duration_text(legs[-1]['arr'] - legs[0]['dep'])} · "
                f"{co2_text(journey_co2(legs, stations, trips))}"
            )
    return texts


def day_trip_panel(network, origin, destination, start_seconds, container=st.sidebar):
    """Day trip: after the journey chosen in journey_panel, the last journey back home
    arriving before a chosen time, and the time we can spend there."""
    stations, connections, trips, footpaths = network
    journeys = plan(network, origin, destination, start_seconds, n=5)  # as journey_panel
    if not journeys:
        return
    legs = journeys[min(st.session_state.get("itin_choice", 0), len(journeys) - 1)]

    container.markdown("**Aller-retour dans la journée**")
    latest = container.time_input("Retour avant", time(21, 0), key="itin_back")
    back = return_trip(network, origin, destination, legs[-1]["arr"], seconds_of(latest))
    if back is None:
        container.warning("Pas de retour possible dans la journée.")
        return

    on_site = back[0]["dep"] - legs[-1]["arr"]
    container.success(f"Aller-retour possible : {duration_text(on_site)} sur place")
    total_kg = journey_co2(legs, stations, trips) + journey_co2(back, stations, trips)
    lines = describe(back, stations, trips).splitlines()
    lines.append("")
    lines.append(f"Total aller-retour (train) : {co2_text(total_kg)}")
    container.code("\n".join(lines), language=None)


def meeting_sidebar(container=st.sidebar):
    """'Où se retrouver ?' inputs: 2 to 4 departure stations. On submit, the best meeting
    stations are saved in st.session_state.meeting (shown by meeting_tab)."""
    choices = station_choices()
    form = container.form("meeting_form", border=False)
    people = [
        form.selectbox(
            f"Personne {i + 1}",
            list(choices),
            index=None,
            placeholder="Gare de départ" + (" (optionnel)" if i >= 2 else ""),
            key=f"meet_{i}",
        )
        for i in range(4)
    ]
    day = form.date_input("Date", default_day(), key="meet_date")
    start = form.time_input("Départ après", DEFAULT_START, key="meet_time")
    if not form.form_submit_button("Trouver un lieu de rendez-vous", type="primary"):
        return

    people = [p for p in people if p]
    if len(people) < 2:
        container.error("Choisissez au moins deux gares de départ.")
        return
    origins = [choices[p] for p in people]
    network = get_network(day.strftime("%Y%m%d"))
    st.session_state.meeting = {
        "day": day,
        "start": seconds_of(start),
        "people": people,
        "origins": origins,
        "points": meeting_points(
            network, origins, seconds_of(start), candidates=busy_stations()
        ),
    }


def meeting_tab(container=st):
    """Results of 'Où se retrouver ?': choose a meeting station, see everyone's journey
    and the CO2 of the group. Returns the pydeck layers of everyone's journeys."""
    meeting = st.session_state.get("meeting")
    if not meeting:
        return []
    if not meeting["points"]:
        container.warning("Aucun lieu de rendez-vous trouvé. Essayez de partir plus tôt.")
        return []

    network = get_network(meeting["day"].strftime("%Y%m%d"))
    stations, connections, trips, footpaths = network

    def label(i):
        station, seconds = meeting["points"][i]
        return f"{stations[station]['name']} — trajet le plus long : {duration_text(max(seconds))}"

    choice = container.radio(
        "Lieux de rendez-vous",
        range(len(meeting["points"])),
        format_func=label,
        key="meet_choice",
    )
    station, _ = meeting["points"][choice]

    layers, total_kg = [], 0
    for person, origin in zip(meeting["people"], meeting["origins"]):
        legs = earliest_arrival(connections, footpaths, origin, station, meeting["start"])
        if legs is None:  # leaves from the meeting station itself
            container.markdown(f"**{person}** : déjà sur place")
            continue
        kg = journey_co2(legs, stations, trips)
        total_kg += kg
        container.markdown(f"**{person}** · {co2_text(kg)}")
        container.code(describe(legs, stations, trips), language=None)
        layers += journey_layers(legs, stations, trips)
    container.markdown(f"**Total du groupe (train) : {co2_text(total_kg)}**")
    return layers
