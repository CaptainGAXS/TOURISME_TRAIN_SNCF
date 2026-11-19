#!/usr/bin/env python3
"""Telecharger les sources et reconstruire toutes les donnees du projet."""

import argparse
import os
import subprocess
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
TRANSIT = RAW / "transit"
VENV = ROOT / "venv"

DOWNLOADS = {
    RAW / "gares.csv": "https://www.data.gouv.fr/api/1/datasets/r/cbacca02-6925-4a46-aab6-7194debbb9b7",
    RAW / "frequentation_latest.csv": "https://www.data.gouv.fr/api/1/datasets/r/d4cf16d5-dd91-453c-887e-6084639caac8",
    RAW / "v_departement_2026.csv": "https://www.insee.fr/fr/statistiques/fichier/8740222/v_departement_2026.csv",
    RAW / "v_region_2026.csv": "https://www.insee.fr/fr/statistiques/fichier/8740222/v_region_2026.csv",
    RAW / "datatourisme.csv": "https://explore.datatourisme.fr/api/export?query=%7B%22match_all%22%3A%7B%7D%7D&format=csv",
    RAW / "parcs-du-monde.csv": "https://www.data.gouv.fr/api/1/datasets/r/4f04d401-399a-4959-ac4f-d0f626061a7c",
    ROOT / "data" / "gtfs_sncf.zip": "https://www.data.gouv.fr/api/1/datasets/r/9ae758ec-cd7a-40cd-a890-bb3963224942",
    ROOT / "data" / "emission_co2_sncf.csv": "https://data.sncf.com/api/explore/v2.1/catalog/datasets/emission-co2-perimetre-complet/exports/csv?delimiter=%2C",
    ROOT / "data" / "regions-50m.geojson": "https://www.data.gouv.fr/api/1/datasets/r/a0fdb1a8-ad6a-44b6-aa89-c9454f3a1626",
    ROOT / "data" / "departements-50m.geojson": "https://www.data.gouv.fr/api/1/datasets/r/14587662-7136-44c7-954c-3080baa1886e",
    TRANSIT / "paris_idfm.zip": "https://www.data.gouv.fr/api/1/datasets/r/413988ed-d340-467b-8be2-7b999fcd207a",
    TRANSIT / "lyon_tcl.zip": "https://www.data.gouv.fr/api/1/datasets/r/abebedc6-28cf-4e2e-9c64-db57a40156f8",
    TRANSIT / "lille_ilevia.zip": "https://www.data.gouv.fr/api/1/datasets/r/c9e5dd3f-8eed-4ad7-aec2-915240599cf6",
    TRANSIT / "toulouse_tisseo.zip": "https://www.data.gouv.fr/api/1/datasets/r/64318177-f5b5-4144-a6be-2d0f22d26c77",
    TRANSIT / "montpellier_tam.zip": "https://www.data.gouv.fr/api/1/datasets/r/93a29ce2-cfc8-44ff-b712-bcfd814b7f00",
    TRANSIT / "clermont_t2c.zip": "https://www.data.gouv.fr/api/1/datasets/r/4e237a58-cd14-4746-b729-1337a40a8a7b",
    TRANSIT / "macon_trema.zip": "https://www.data.gouv.fr/api/1/datasets/r/0a01b036-796f-43a3-9c64-a2f6024427b0",
    TRANSIT / "aix_marseille.zip": "https://www.data.gouv.fr/api/1/datasets/r/0d9a808a-9a9b-4fa1-b04f-339bbf2cfeb1",
}


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def download(path: Path, url: str, refresh: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not refresh:
        print(f"[skip] {path.relative_to(ROOT)} existe deja")
        return

    temporary = path.with_suffix(path.suffix + ".part")
    print(f"[download] {path.relative_to(ROOT)}")
    try:
        subprocess.run(
            [
                "curl",
                "--fail",
                "--location",
                "--retry",
                "5",
                "--retry-all-errors",
                "--retry-delay",
                "3",
                "--connect-timeout",
                "30",
                "--max-time",
                "900",
                "--output",
                str(temporary),
                url,
            ],
            cwd=ROOT,
            check=True,
        )
    except subprocess.CalledProcessError as error:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(
            f"Telechargement echoue (HTTP/curl) : {url}"
        ) from error
    if temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Le telechargement est vide : {url}")
    temporary.replace(path)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="Retelecharger les fichiers existants")
    parser.add_argument("--skip-transfers", action="store_true", help="Ne pas reconstruire station_transfers.csv")
    args = parser.parse_args()

    for path, url in DOWNLOADS.items():
        download(path, url, args.refresh)

    if not VENV.exists():
        print(f"[venv] Creation de {VENV.relative_to(ROOT)}")
        venv.EnvBuilder(with_pip=True).create(VENV)

    python = venv_python()
    if not python.exists():
        raise RuntimeError(f"Python du venv introuvable : {python}")

    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    run([str(python), "scripts/data_prep/build_stations.py"], env)
    run([str(python), "scripts/data_prep/pre-traitement-tourism.py"], env)
    run([str(python), "scripts/research/station_features.py"], env)
    if not args.skip_transfers:
        run([str(python), "scripts/data_prep/build_station_transfers.py"], env)

    print("\nTermine : les donnees brutes et prepares sont dans data/")


if __name__ == "__main__":
    main()
