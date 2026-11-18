# Download and prepare SNCF station data and tourism data

## Build if necessary

From the project root:

```
curl -L -o data/raw/gares.csv "https://www.data.gouv.fr/api/1/datasets/r/cbacca02-6925-4a46-aab6-7194debbb9b7"
curl -L -o data/raw/frequentation_latest.csv "https://www.data.gouv.fr/api/1/datasets/r/d4cf16d5-dd91-453c-887e-6084639caac8"
curl -L -o data/raw/v_departement_2026.csv "https://www.insee.fr/fr/statistiques/fichier/8740222/v_departement_2026.csv"
curl -L -o data/raw/v_region_2026.csv "https://www.insee.fr/fr/statistiques/fichier/8740222/v_region_2026.csv"
python scripts/data_prep/build_stations.py
```

To have the tourism data ready, run the following command:
```
curl -L -o data/raw/datatourisme.csv "https://explore.datatourisme.fr/api/export?query=%7B%22match_all%22%3A%7B%7D%7D&format=csv"
curl -L -o data/raw/parcs-du-monde.csv "https://www.data.gouv.fr/api/1/datasets/r/4f04d401-399a-4959-ac4f-d0f626061a7c"
PYTHONPATH=. python scripts/data_prep/pre-traitement-tourism.py
```

To update the SNCF timetable (GTFS) used by the journey planner, run the following command. The zip is read directly by `scripts/itinerary/network.py` (no need to unzip). The current file is valid until 2027-04-30.
```
curl -L -o data/gtfs_sncf.zip "https://www.data.gouv.fr/api/1/datasets/r/9ae758ec-cd7a-40cd-a890-bb3963224942"
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
| `departement` | str | Département (first 2 characters of `insee`, 3 for overseas) | `75` |
| `region` | str | Administrative region, from INSEE's Code officiel géographique 2026 (`v_departement_2026.csv` + `v_region_2026.csv`) | `Île-de-France` |
| `drg` | str | SNCF regional management unit (`Direction Régionale Gares`), not an administrative region | `DEX GIF` |
| `visitors` | float | Passengers in 2025 (`Total Voyageurs 2025`, not including non-travellers) | `22359730.0` |

## Notes

- **Read the ID columns as text:** `pd.read_csv(..., dtype={"station_id": str, "uic": str, "insee": str, "departement": str})`. Otherwise the leading zeros in codes like `01…` are lost.
- **Use `region` for geography, not `drg`:** `drg` groups several regions (e.g. `DRG AURA BFC` = Auvergne-Rhône-Alpes + Bourgogne-Franche-Comté), and `ETAB GARES PARIS` holds the 10 largest Paris-area stations whatever their location. `drg` is missing for the 6 stations without ridership; `region` is filled for all stations (no Corsica or overseas stations in the data).
- **Stations with several UIC codes (11, e.g. Paris Nord, Lyon, Montparnasse):** `visitors` is the sum over all their codes.
- **`visitors` is missing for 6 stations:** 5 tram-train stops on T11/T13 and Le Pont-de-Claix. Another 6 stations have `visitors = 0`.
- **212 ridership rows have no matching station** (0.33% of all passengers). They are left out of the table. The biggest is Monaco–Monte-Carlo.
- **Coordinates:** none are missing, and all are in mainland France (lat 42.4–51.0, lon −4.5–8.2).
- **Ridership values are skewed:** the median is about 82k, the maximum is 263M (Paris Gare du Nord). Use a log scale for maps or rankings.

