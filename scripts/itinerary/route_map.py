"""
Turn a journey (list of legs from planner.py) into pydeck layers.
deck = pdk.Deck(layers=[other_layer] + journey_layers(legs, stations, trips), ...)
"""

try:
    from .planner import duration_text, hhmm, leg_stations, mode_name
except ImportError:
    from planner import duration_text, hhmm, leg_stations, mode_name
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
}
OTHER_COLOR = [90, 60, 160]  # ICE, Lyria, ...
LOCAL_COLOR = [130, 130, 130]  # walk, metro, tram, bus between stations of the same city

# travel time -> color: (up to this many hours, color, label for the legend)
TIME_COLORS = [
    (1, [40, 160, 70], "🟢 < 1h"),
    (2, [240, 200, 0], "🟡 1-2h"),
    (3, [245, 130, 30], "🟠 2-3h"),
    (float("inf"), [215, 40, 40], "🔴 > 3h"),
]


# def hhmm(seconds):
#     return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}"


def reachable_layer(times, stations, max_seconds):
    """Stations reachable within max_seconds, colored by travel time (TIME_COLORS).
    times: {station_id: seconds}, from planner.travel_times()"""
    dots = []
    for s, seconds in times.items():
        if seconds > max_seconds:
            continue
        color = next(c for hours, c, _ in TIME_COLORS if seconds < hours * 3600)
        dots.append(
            {
                "lon": stations[s]["lon"],
                "lat": stations[s]["lat"],
                "name": f"{stations[s]['name']} — {duration_text(seconds)}",
                "color": color,
            }
        )
    return pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame(dots, columns=["lon", "lat", "name", "color"]),
        get_position="[lon, lat]",
        get_fill_color="color",
        get_line_color=[255, 255, 255],
        stroked=True,
        line_width_min_pixels=1,
        radius_min_pixels=5,
        pickable=True,
    )


def journey_layers(legs, stations, trips):
    lines, small_dots, big_dots = [], [], []

    for leg in legs:
        ids = leg_stations(leg, trips)
        if leg["mode"] != "train":  # "walk", "metro/RER", "tram", "bus"...
            name = mode_name(leg["mode"])
            color, title = LOCAL_COLOR, name[0].upper() + name[1:]  # "À pied", "Métro/RER"
        else:
            kind = trips[leg["trip"]]["kind"]
            color, title = COLORS.get(kind, OTHER_COLOR), f"{kind} {trips[leg['trip']]['number']}"
        start, end = stations[leg["from"]]["name"], stations[leg["to"]]["name"]

        lines.append(
            {
                "path": [[stations[s]["lon"], stations[s]["lat"]] for s in ids],
                "color": color,
                "name": f"{title} : {start} {hhmm(leg['dep'])} → {end} {hhmm(leg['arr'])}",
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
                "name": f"{start} — dép. {hhmm(leg['dep'])}",
            }
        )

    last = legs[-1]
    big_dots.append(  # station where we get off the train
        {
            "lon": stations[last["to"]]["lon"],
            "lat": stations[last["to"]]["lat"],
            "name": f"{stations[last['to']]['name']} — arr. {hhmm(last['arr'])}",
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
