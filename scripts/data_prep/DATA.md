# `data/processed/stations.csv` — SNCF stations + 2025 ridership

## Build

From the project root:

```
curl -L -o data/raw/gares.csv "https://www.data.gouv.fr/api/1/datasets/r/cbacca02-6925-4a46-aab6-7194debbb9b7"
curl -L -o data/raw/frequentation_latest.csv "https://www.data.gouv.fr/api/1/datasets/r/d4cf16d5-dd91-453c-887e-6084639caac8"
python scripts/data_prep/build_stations.py
```

## Shape

2,792 rows, one per station (`station_id` is unique).

| Column | Type | Description | Example |
|---|---|---|---|
| `station_id` | str | SNCF station ID (UUID, from `Id_Gare`) | `002271ab-2ed4-…` |
| `name` | str | Station name | `Paris Austerlitz` |
| `uic` | str | UIC code(s), `;`-separated when there are several | `87547026;87547000` |
| `lat` | float | Latitude (WGS84) | `48.842285` |
| `lon` | float | Longitude (WGS84) | `2.364891` |
| `insee` | str | INSEE code of the commune (5 characters) | `75113` |
| `visitors` | float | Passengers in 2025 (`Total Voyageurs 2025`, not including non-travellers) | `22359730.0` |

## Notes

- **Read the ID columns as text:** `pd.read_csv(..., dtype={"station_id": str, "uic": str, "insee": str})`. Otherwise the leading zeros in INSEE codes like `01…` are lost.
- **Stations with several UIC codes (11, e.g. Paris Nord, Lyon, Montparnasse):** `visitors` is the sum over all their codes.
- **`visitors` is missing for 6 stations:** 5 tram-train stops on T11/T13 and Le Pont-de-Claix. Another 6 stations have `visitors = 0`.
- **212 ridership rows have no matching station** (0.33% of all passengers). They are left out of the table. The biggest is Monaco–Monte-Carlo.
- **Coordinates:** none are missing, and all are in mainland France (lat 42.4–51.0, lon −4.5–8.2).
- **Ridership values are skewed:** the median is about 82k, the maximum is 263M (Paris Gare du Nord). Use a log scale for maps or rankings.
