import json
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

def map_layer(mappath):
    with open(mappath, "r", encoding="utf-8") as f:
        geojson_data = json.load(f)

    layer = pdk.Layer(
        "GeoJsonLayer",
        data=geojson_data,
        get_fill_color=[200, 30, 0, 160],
        get_line_color=[255, 255, 255],
        line_width_min_pixels=2,
    )
    return layer

def render_map(mappath):
    maplayer = map_layer(mappath)

    view_state = pdk.ViewState(latitude=46.6, longitude=2.2, zoom=4.5)

    deck = pdk.Deck(
        layers=[maplayer],
        initial_view_state=view_state,
        map_provider=None,
        map_style=None
    )

    deck_html = deck.to_html(as_string=True)
    components.html(deck_html, height=800)

#Si on veut utiliser un sélecteur à la place

# map_choice = st.radio(
#     "Choisissez une carte :",
#     ["Aucune", "Carte par départements", "Carte par régions"]
# )

# if map_choice == "Carte par départements":
#     render_map("departements-50m.geojson")
# elif map_choice == "Carte par régions":
#     render_map("regions-50m.geojson")
# else:
#     st.write("Sélectionnez une option pour afficher la carte correspondante.")

def map_selector():
    if "selected_map" not in st.session_state:
        st.session_state.selected_map = None
    if st.sidebar.button("Carte par départements"):
        st.session_state.selected_map = "data/departements-50m.geojson"
    if st.sidebar.button("Carte par régions"):
        st.session_state.selected_map = "data/regions-50m.geojson"

    if st.session_state.selected_map:
        render_map(st.session_state.selected_map)
    else:
        st.write("Sélectionnez une option dans la barre latérale pour afficher la carte correspondante.")