import json # type: ignore
import pydeck as pdk # type: ignore
import streamlit as st # type: ignore
import streamlit.components.v1 as components # type: ignore

@st.cache_data
def load_geojson(mappath):
    with open(mappath, "r", encoding="utf-8") as f:
        return json.load(f)

def map_layer(mappath):
    geojson_data = load_geojson(mappath)

    layer = pdk.Layer(
        "GeoJsonLayer",
        data=geojson_data,
        get_fill_color=[255,255,255],
        get_line_color=[0,0,0],
        line_width_min_pixels=2,
    )
    return layer

def render_map(display_area, mappath, layers = []):
    maplayer = map_layer(mappath)

    view_state = pdk.ViewState(latitude=46.6, longitude=2.2, zoom=4.5)

    custom_tooltip = {
    "html": "{name}",
    }

    deck = pdk.Deck(
        layers=[maplayer] + layers,
        initial_view_state=view_state,
        map_provider=None,
        map_style=None,
        tooltip=custom_tooltip
    )

    with display_area:
        pdk.chart(deck, height=800)