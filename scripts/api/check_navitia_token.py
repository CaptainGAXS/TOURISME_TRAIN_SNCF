"""Check whether a Navitia / SNCF API token works and fetch one station-to-station journey.

Usage (from the repo root):
    python scripts/api/check_navitia_token.py
    python scripts/api/check_navitia_token.py "Nancy" "Paris Est"

The token is read from the NAVITIA_TOKEN environment variable, or from a `.env`
file at the repo root containing a line `NAVITIA_TOKEN=xxxx`. Never commit it.
"""

import base64
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GARES_CSV = ROOT / "data" / "raw" / "gares.csv"

BASES = {
    "api.sncf.com": "https://api.sncf.com/v1",
    "api.navitia.io": "https://api.navitia.io/v1",
}


def load_token() -> str:
    token = os.environ.get("NAVITIA_TOKEN")
    env_file = ROOT / ".env"
    if not token and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("NAVITIA_TOKEN="):
                token = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not token:
        sys.exit("NAVITIA_TOKEN not found (set the env var or add it to .env)")
    return token


def get(url: str, token: str):
    """GET with Basic auth (token as user, empty password). Returns (status, json|None)."""
    auth = base64.b64encode(f"{token}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = None
        return e.code, body


def find_station(name: str) -> dict:
    with open(GARES_CSV, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    exact = [r for r in rows if r["Nom_Gare"].lower() == name.lower()]
    partial = [r for r in rows if name.lower() in r["Nom_Gare"].lower()]
    match = (exact or partial or [None])[0]
    if match is None:
        sys.exit(f"Station not found in gares.csv: {name}")
    lat, lon = [s.strip() for s in match["Position géographique"].split(",")]
    uic = match["Code_UIC"].split(";")[0].strip()
    return {"name": match["Nom_Gare"], "uic": uic, "lon": lon, "lat": lat}


def print_journeys(data: dict) -> None:
    for i, j in enumerate(data.get("journeys", [])[:3], 1):
        dep, arr = j["departure_date_time"], j["arrival_date_time"]
        print(f"  #{i} {dep[9:11]}:{dep[11:13]} -> {arr[9:11]}:{arr[11:13]}"
              f"  ({j['duration'] // 60} min, {j.get('nb_transfers', 0)} transfer(s))")
        for s in j.get("sections", []):
            if s.get("type") == "public_transport":
                info = s.get("display_informations", {})
                print(f"      {info.get('commercial_mode', '')} {info.get('headsign', '')}: "
                      f"{s['from']['name']} -> {s['to']['name']}")


def main() -> None:
    token = load_token()
    src = find_station(sys.argv[1] if len(sys.argv) > 1 else "Nancy")
    dst = find_station(sys.argv[2] if len(sys.argv) > 2 else "Paris Est")
    when = (datetime.now() + timedelta(days=1)).strftime("%Y%m%dT080000")
    print(f"From {src['name']} (UIC {src['uic']}) to {dst['name']} (UIC {dst['uic']}) at {when}\n")

    for label, base in BASES.items():
        print(f"=== {label} ===")
        status, cov = get(f"{base}/coverage", token)
        if status != 200:
            msg = (cov or {}).get("message", "") if isinstance(cov, dict) else ""
            print(f"  /coverage -> {status} {msg}\n")
            continue
        regions = [r["id"] for r in cov.get("regions", [])]
        print(f"  token OK, coverages: {', '.join(regions[:15])}{' ...' if len(regions) > 15 else ''}")

        if "sncf" in regions:
            params = {"from": f"stop_area:SNCF:{src['uic']}", "to": f"stop_area:SNCF:{dst['uic']}"}
            url = f"{base}/coverage/sncf/journeys"
        else:  # let Navitia pick the coverage from coordinates
            params = {"from": f"{src['lon']};{src['lat']}", "to": f"{dst['lon']};{dst['lat']}"}
            url = f"{base}/journeys"
        params["datetime"] = when
        status, data = get(f"{url}?{urllib.parse.urlencode(params)}", token)
        if status == 200 and data.get("journeys"):
            print(f"  journeys -> OK ({url})")
            print_journeys(data)
        else:
            err = (data or {}).get("error") or (data or {}).get("message")
            print(f"  journeys -> {status} {err}")
        print()


if __name__ == "__main__":
    main()
