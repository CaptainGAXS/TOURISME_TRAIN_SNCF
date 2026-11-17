from scripts.research.station_features import (
    ROOT,
    build_proximity_indexes,
    load_pois,
    load_stations,
)


def main() -> None:
    stations = load_stations()
    pois = load_pois()
    station_poi_index, poi_nearest_station = build_proximity_indexes(stations, pois)

    station_poi_path = ROOT / "data" / "station_poi_index.csv"
    nearest_station_path = ROOT / "data" / "poi_nearest_station.csv"
    station_poi_index.to_csv(station_poi_path, index=False)
    poi_nearest_station.to_csv(nearest_station_path, index=False)

    print(f"Station-POI links: {len(station_poi_index)}")
    print(f"POIs indexed: {len(poi_nearest_station)}")
    print(f"Saved to {station_poi_path}")
    print(f"Saved to {nearest_station_path}")


if __name__ == "__main__":
    main()
