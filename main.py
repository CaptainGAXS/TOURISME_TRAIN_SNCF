import pandas as pd
from scripts.research.station_features import (
    find_nearby_pois_from_index,
    load_pois,
    load_stations,
)

def main():
    nearby = find_nearby_pois_from_index(
        load_stations(),
        load_pois(),
        pd.read_csv("data/station_poi_index.csv"),
        station_name="Nancy",
        radius_km=1,
    )
    print(nearby)


if __name__ == "__main__":
    main()