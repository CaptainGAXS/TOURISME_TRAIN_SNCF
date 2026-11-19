from pathlib import Path
import pandas as pd

# Project root = two levels above scripts/data_prep/ (works from any working directory)
ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"

def load_dept_to_region(dep_path, reg_path):
    """Département code -> region name, from INSEE's Code officiel géographique (COG)."""
    dep = pd.read_csv(dep_path, dtype=str)[["DEP", "REG"]]
    reg = pd.read_csv(reg_path, dtype=str)[["REG", "LIBELLE"]]
    return dep.merge(reg, on="REG").set_index("DEP")["LIBELLE"]


def load_stations(path, dept_to_region):
    gares = pd.read_csv(path, sep=";", dtype=str)
    st = gares[
        ["Id_Gare", "Nom_Gare", "Code_UIC", "Position géographique", "Code commune"]
    ].copy()
    st.columns = ["station_id", "name", "uic", "position", "insee"]

    # "48.84, 2.37" -> lat, lon
    st[["lat", "lon"]] = st["position"].str.split(",", expand=True).astype(float)
    st = st.drop(columns="position")

    bad = st[
        st["lat"].isna() | ~st["lat"].between(41, 52) | ~st["lon"].between(-5.5, 10)
    ]
    if len(bad):
        print(f"[warn] {len(bad)} stations with missing/invalid coordinates")

    # Département = first 2 characters of the INSEE code ("75113" -> "75", "2A004" -> "2A"),
    # or 3 characters overseas ("97411" -> "974")
    st["departement"] = st["insee"].str[:2].where(
        ~st["insee"].str.startswith("97"), st["insee"].str[:3]
    )
    st["region"] = st["departement"].map(dept_to_region)
    if st["region"].isna().any():
        print(f"[warn] {st['region'].isna().sum()} stations without a region")

    # Some stations have several UIC codes ("87547026;87547000") -> one row per code
    return st.assign(uic=st["uic"].str.split(r"[;,| ]+")).explode("uic")


def load_ridership(path):
    freq = pd.read_csv(path, sep=";", dtype=str)
    f = freq[["Code UIC", "Total Voyageurs 2025"]].rename(
        columns={
            "Code UIC": "uic",
            "Total Voyageurs 2025": "visitors",
        }
    )
    f["visitors"] = pd.to_numeric(f["visitors"], errors="coerce")
    return f


def attach_riderships(st_uic, f):
    if f["uic"].duplicated().any():
        print(f"[warn] {f['uic'].duplicated().sum()} duplicated UIC codes in ridership")
    shared = st_uic.dropna(subset=["uic"]).drop_duplicates(["station_id", "uic"])
    if shared["uic"].duplicated().any():
        print(
            f"[warn] {shared['uic'].duplicated().sum()} UIC codes shared by several stations"
        )

    missing = f[~f["uic"].isin(st_uic["uic"])]
    print(
        f"Ridership rows without a station: {len(missing)} "
        f"({missing['visitors'].sum() / f['visitors'].sum():.2%} of visitors)"
    )

    merged = st_uic.merge(f, on="uic", how="left")

    # Back to one row per station (sum the visitors of all its UIC codes)
    return merged.groupby("station_id", as_index=False).agg(
        name=("name", "first"),
        uic=("uic", lambda s: ";".join(s.dropna())),  # to find the station in the GTFS timetable
        lat=("lat", "first"),
        lon=("lon", "first"),
        departement=("departement", "first"),
        region=("region", "first"),
        visitors=("visitors", lambda s: s.sum(min_count=1)),
    )


def main():
    dept_to_region = load_dept_to_region(
        RAW / "v_departement_2026.csv", RAW / "v_region_2026.csv"
    )
    st_uic = load_stations(RAW / "gares.csv", dept_to_region)
    f = load_ridership(RAW / "frequentation_latest.csv")
    stations = attach_riderships(st_uic, f)

    OUT.mkdir(parents=True, exist_ok=True)
    stations.to_csv(OUT / "stations.csv", index=False)

    print(
        f"Stations: {len(stations)} (without visitors: {stations['visitors'].isna().sum()})"
    )
    print(stations.nlargest(5, "visitors")[["name", "visitors"]].to_string(index=False))
    print(f"Saved to {OUT / 'stations.csv'}")


if __name__ == "__main__":
    main()
