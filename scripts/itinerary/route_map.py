"""
Turn a journey (list of legs from planner.py) into pydeck layers.
deck = pdk.Deck(layers=[other_layer] + journey_layers(legs, stations, trips), ...)
"""

from planner import hhmm
import pandas as pd
import pydeck as pdk

COLORS = {
    "TGV INOUI": [200, 30, 60],
    "OUIGO": [0, 160, 220],
    "INTERCITES": [40, 80, 180],
    "INTERCITES de nuit": [40, 80, 180],
    "Train TER": [30, 150, 80],
    "TramTrain": [30, 150, 80],
    "Car TER": [240, 150, 0],
    "Car à réservation": [240, 150, 0],
    "walk": [130, 130, 130],
}
OTHER_COLOR = [90, 60, 160]  # ICE, Lyria, ...


# def hhmm(seconds):
#     return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def leg_stations(leg, trips):
    """Stations passed by a leg, in order (for walking: just start and end)."""
    if leg["mode"] == "walk":
        return [leg["from"], leg["to"]]
    stops = trips[leg["trip"]]["stops"]
    start = stops.index(leg["from"])
    end = stops.index(leg["to"], start + 1)
    return stops[start : end + 1]


def journey_layers(legs, stations, trips):
    lines, small_dots, big_dots = [], [], []

    for leg in legs:
        ids = leg_stations(leg, trips)
        if leg["mode"] == "walk":
            kind, title = "walk", "Walk"
        else:
            kind = trips[leg["trip"]]["kind"]
            title = f"{kind} {trips[leg['trip']]['number']}"
        start, end = stations[leg["from"]]["name"], stations[leg["to"]]["name"]

        lines.append(
            {
                "path": [[stations[s]["lon"], stations[s]["lat"]] for s in ids],
                "color": COLORS.get(kind, OTHER_COLOR),
                "name": f"{title}: {start} {hhmm(leg['dep'])} → {end} {hhmm(leg['arr'])}",
            }
        )
        for s in ids[1:-1]:  # stations where the train stops but we stay on board
            small_dots.append(
                {
                    "lon": stations[s]["lon"],
                    "lat": stations[s]["lat"],
                    "name": stations[s]["name"],
                }
            )
        big_dots.append(  # station where we get on the train
            {
                "lon": stations[leg["from"]]["lon"],
                "lat": stations[leg["from"]]["lat"],
                "name": f"{start} — dep {hhmm(leg['dep'])}",
            }
        )

    last = legs[-1]
    big_dots.append(  # station where we get off the train
        {
            "lon": stations[last["to"]]["lon"],
            "lat": stations[last["to"]]["lat"],
            "name": f"{stations[last['to']]['name']} — arr {hhmm(last['arr'])}",
        }
    )

    return [
        pdk.Layer(
            "PathLayer",
            data=pd.DataFrame(lines),
            get_path="path",
            get_color="color",
            width_min_pixels=5,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=pd.DataFrame(small_dots, columns=["lon", "lat", "name"]),
            get_position="[lon, lat]",
            get_fill_color=[60, 60, 60],
            radius_min_pixels=3,
            pickable=True,
        ),
        pdk.Layer(
            "ScatterplotLayer",
            data=pd.DataFrame(big_dots),
            get_position="[lon, lat]",
            get_fill_color=[255, 255, 255],
            get_line_color=[0, 0, 0],
            stroked=True,
            line_width_min_pixels=2,
            radius_min_pixels=7,
            pickable=True,
        ),
    ]
