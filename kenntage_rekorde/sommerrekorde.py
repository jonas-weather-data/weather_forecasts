import os
import re
import zipfile
import threading
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import requests
import pandas as pd
import geopandas as gpd
import matplotlib

import matplotlib.pyplot as plt
import matplotlib.patheffects as path_effects
from matplotlib.patches import Circle


# ============================================================
# MATPLOTLIB: GitHub Actions
# ============================================================

if os.environ.get("GITHUB_ACTIONS") == "true":
    matplotlib.use("Agg")


# ============================================================
# KONFIGURATION
# ============================================================

MAX_WORKERS = 16

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

STATIONEN_CSV = os.path.join(
    BASE_DIR,
    "stationen.csv"
)

SOMMERTAGE_REKORDE = os.path.join(
    BASE_DIR,
    "sommertagrekorde.txt"
)

HITZETAGE_REKORDE = os.path.join(
    BASE_DIR,
    "hitzetagrekorde.txt"
)

SHAPEFILE = os.path.join(
    BASE_DIR,
    "gadm41_DEU_1.json"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)


# ============================================================
# DWD OPEN DATA
# ============================================================

STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/historical/"
    "KL_Tageswerte_Beschreibung_Stationen.txt"
)

RECENT_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/recent/"
)


# ============================================================
# JAHR
# ============================================================

CURRENT_YEAR = 2026


# ============================================================
# AUSWERTUNGSSTICHTAG
#
# Es wird immer bis einschließlich VORTAG ausgewertet.
# Der aktuelle Tag wird nicht berücksichtigt.
# ============================================================

TODAY = date.today()

DATA_DATE = TODAY.fromordinal(
    TODAY.toordinal() - 1
)


# ============================================================
# FORTSCHRITTSANZEIGE
# ============================================================

progress_lock = threading.Lock()

completed = 0


def log(message):
    print(message, flush=True)


# ============================================================
# 1) STATIONEN.CSV LADEN
#
# Format:
#
# Wangerland-Hooksiel;06157
# Warburg;05347
# Waren (Müritz);05349
#
# Die Datei enthält keinen Header.
# ============================================================

def load_station_csv():

    log("[1/7] Lade stationen.csv ...")

    df = pd.read_csv(
        STATIONEN_CSV,
        sep=";",
        header=None,
        names=[
            "name",
            "station_id"
        ],
        dtype=str,
        encoding="utf-8"
    )

    df["name"] = (
        df["name"]
        .str.strip()
    )

    df["station_id"] = (
        df["station_id"]
        .str.strip()
        .str.zfill(5)
    )

    log(
        f"      {len(df)} Stationen geladen."
    )

    return df


# ============================================================
# 2) REKORDDATEIEN EINLESEN
#
# Format:
#
# Hamburg-Neuwiedenthal: 77 (2018)
# Leipzig-Holzhausen: 89 (2018)
# Marnitz: 77 (2018)
#
# Ergebnis:
#
# {
#     "Hamburg-Neuwiedenthal": {
#         "record": 77,
#         "record_year": 2018
#     }
# }
# ============================================================

def parse_record_file(filename):

    records = {}

    with open(
        filename,
        "r",
        encoding="utf-8"
    ) as f:

        for line_number, line in enumerate(
            f,
            start=1
        ):

            line = line.strip()

            if not line:
                continue

            match = re.match(
                r"^(.*?):\s*(-?\d+)\s*\((\d{4})\)\s*$",
                line
            )

            if not match:

                log(
                    f"      WARNUNG: "
                    f"{filename}, "
                    f"Zeile {line_number} "
                    f"nicht lesbar: {line}"
                )

                continue

            name = match.group(1).strip()

            record = int(
                match.group(2)
            )

            record_year = int(
                match.group(3)
            )

            records[name] = {
                "record": record,
                "record_year": record_year
            }

    return records


# ============================================================
# REKORDDATEIEN LADEN
# ============================================================

def load_records():

    log("[2/7] Lade Rekorddateien ...")

    summer_records = parse_record_file(
        SOMMERTAGE_REKORDE
    )

    heat_records = parse_record_file(
        HITZETAGE_REKORDE
    )

    log(
        f"      Sommertagsrekorde: "
        f"{len(summer_records)}"
    )

    log(
        f"      Hitzetagsrekorde:  "
        f"{len(heat_records)}"
    )

    return (
        summer_records,
        heat_records
    )


# ============================================================
# 3) RELEVANTE STATIONEN ERMITTELN
#
# Eine Station ist relevant, wenn sie in mindestens einer
# der beiden Rekorddateien vorkommt.
#
# stationen.csv verbindet den Namen mit der DWD station_id.
# ============================================================

def build_target_stations(
    stationen,
    summer_records,
    heat_records
):

    log("[3/7] Ermittle relevante Stationen ...")

    relevant_names = (
        set(summer_records.keys())
        |
        set(heat_records.keys())
    )

    station_lookup = {}

    for _, row in stationen.iterrows():

        name = row["name"]

        sid = row["station_id"]

        station_lookup[name] = sid

    targets = {}

    for name in sorted(
        relevant_names
    ):

        if name not in station_lookup:

            log(
                f"      WARNUNG: Station nicht in "
                f"stationen.csv: {name}"
            )

            continue

        sid = station_lookup[name]

        targets[sid] = {

            "name": name,

            "summer_record": (
                summer_records.get(name)
            ),

            "heat_record": (
                heat_records.get(name)
            )
        }

    log(
        f"      Relevante Stationen: "
        f"{len(targets)}"
    )

    return targets


# ============================================================
# 4) DWD-STATIONSMETADATEN LADEN
#
# WICHTIG:
# Die Koordinaten kommen hier direkt aus den DWD-Metadaten.
#
# DWD-Dateiformat:
#
# Stations_id
# ...
# Latitude
# Longitude
# Stationsname
# ============================================================

def load_dwd_station_meta(
    target_stations
):

    log(
        "[4/7] Lade DWD-Stationsmetadaten ..."
    )

    response = requests.get(
        STATIONS_URL,
        timeout=120
    )

    response.raise_for_status()

    txt = response.content.decode(
        "cp1252"
    )

    lines = (
        txt
        .replace("\r\n", "\n")
        .split("\n")
    )

    header = next(
        i
        for i, line in enumerate(lines)
        if line.startswith("Stations_id")
    )

    target_ids = set(
        target_stations.keys()
    )

    result = {}

    for line in lines[
        header + 1:
    ]:

        try:

            sid = line[
                0:5
            ].strip()

            if sid not in target_ids:
                continue

            lat = float(
                line[
                    43:50
                ]
                .strip()
                .replace(",", ".")
            )

            lon = float(
                line[
                    53:60
                ]
                .strip()
                .replace(",", ".")
            )

            dwd_name = line[
                61:101
            ].strip()

            result[sid] = {

                "lat": lat,

                "lon": lon,

                "dwd_name": dwd_name
            }

        except (
            ValueError,
            IndexError
        ):

            continue

    log(
        f"      {len(result)} von "
        f"{len(target_ids)} Stationen gefunden."
    )

    missing = (
        target_ids
        - set(result)
    )

    if missing:

        log(
            "      WARNUNG: Nicht gefundene "
            "DWD-Stationen: "
            + ", ".join(
                sorted(missing)
            )
        )

    return result


# ============================================================
# 5) DWD-DATEIEN ERMITTELN
# ============================================================

def get_dwd_files(
    target_stations
):

    log(
        "[5/7] Ermittle DWD-Stationsdateien ..."
    )

    response = requests.get(
        RECENT_URL,
        timeout=120
    )

    response.raise_for_status()

    files = re.findall(
        r'href="(tageswerte_KL_\d+_.*?\.zip)"',
        response.text
    )

    target_ids = set(
        target_stations.keys()
    )

    station_files = []

    for filename in files:

        parts = filename.split("_")

        if len(parts) < 3:
            continue

        sid = parts[2]

        if sid in target_ids:

            station_files.append(
                filename
            )

    log(
        f"      {len(station_files)} passende "
        f"DWD-Dateien gefunden."
    )

    return station_files


# ============================================================
# 6) EINZELNE STATION VERARBEITEN
#
# TXK:
#
# Sommertag: TXK >= 25
# Hitzetag:  TXK >= 30
#
# Es werden ausschließlich Daten aus 2026 bis einschließlich
# DATA_DATE verwendet.
# ============================================================

def process_station(
    filename,
    target,
    meta,
    total_stations
):

    global completed

    sid = filename.split("_")[2]

    station_name = target["name"]

    log(
        f"      [{sid}] Download gestartet: "
        f"{station_name}"
    )

    response = requests.get(
        RECENT_URL + filename,
        timeout=120
    )

    response.raise_for_status()

    log(
        f"      [{sid}] Download fertig – "
        f"lese Messdaten ..."
    )

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as z:

        csv_file = next(
            filename
            for filename in z.namelist()
            if filename.startswith(
                "produkt_klima_tag"
            )
        )

        with z.open(csv_file) as f:

            df = pd.read_csv(
                f,
                sep=";",
                encoding="cp1252",
                dtype=str
            )

    df.columns = [
        column.strip()
        for column in df.columns
    ]

    # --------------------------------------------------------
    # Datum
    # --------------------------------------------------------

    df["MESS_DATUM"] = pd.to_datetime(
        df["MESS_DATUM"],
        format="%Y%m%d",
        errors="coerce"
    )

    # --------------------------------------------------------
    # TXK
    # --------------------------------------------------------

    df["TXK"] = pd.to_numeric(
        df["TXK"],
        errors="coerce"
    )

    # DWD-Fehlwert
    df["TXK"] = df[
        "TXK"
    ].replace(
        -999,
        pd.NA
    )

    # --------------------------------------------------------
    # 2026 BIS DATENSTAND
    # --------------------------------------------------------

    data = df[
        (df["MESS_DATUM"].dt.year == CURRENT_YEAR)
        &
        (
            df["MESS_DATUM"].dt.date
            <= DATA_DATE
        )
    ].copy()

    # --------------------------------------------------------
    # SOMMERTAGE
    #
    # TXK >= 25 °C
    # --------------------------------------------------------

    summer_days = int(
        (
            data["TXK"] >= 25
        ).sum()
    )

    # --------------------------------------------------------
    # HITZETAGE
    #
    # TXK >= 30 °C
    # --------------------------------------------------------

    heat_days = int(
        (
            data["TXK"] >= 30
        ).sum()
    )

    # --------------------------------------------------------
    # SOMMERTAGSREKORD
    # --------------------------------------------------------

    summer_record_data = (
        target["summer_record"]
    )

    if summer_record_data is not None:

        summer_record = (
            summer_record_data["record"]
        )

        summer_record_year = (
            summer_record_data[
                "record_year"
            ]
        )

        summer_diff = (
            summer_days
            - summer_record
        )

    else:

        summer_record = None

        summer_record_year = None

        summer_diff = None

    # --------------------------------------------------------
    # HITZETAGSREKORD
    # --------------------------------------------------------

    heat_record_data = (
        target["heat_record"]
    )

    if heat_record_data is not None:

        heat_record = (
            heat_record_data["record"]
        )

        heat_record_year = (
            heat_record_data[
                "record_year"
            ]
        )

        heat_diff = (
            heat_days
            - heat_record
        )

    else:

        heat_record = None

        heat_record_year = None

        heat_diff = None

    # --------------------------------------------------------
    # ERGEBNIS
    # --------------------------------------------------------

    result = {

        "station_id": sid,

        "name": station_name,

        # KOORDINATEN AUS DWD
        "lat": meta[sid]["lat"],

        "lon": meta[sid]["lon"],

        # SOMMERTAGE
        "summer_days": summer_days,

        "summer_record": summer_record,

        "summer_record_year":
            summer_record_year,

        "summer_diff": summer_diff,

        # HITZETAGE
        "heat_days": heat_days,

        "heat_record": heat_record,

        "heat_record_year":
            heat_record_year,

        "heat_diff": heat_diff
    }

    # --------------------------------------------------------
    # FORTSCHRITT
    # --------------------------------------------------------

    with progress_lock:

        completed += 1

        summer_text = (
            f"{summer_days} Sommertage"
        )

        heat_text = (
            f"{heat_days} Hitzetage"
        )

        if summer_diff is not None:

            summer_text += (
                f" ({summer_diff:+d} "
                f"zum Rekord)"
            )

        if heat_diff is not None:

            heat_text += (
                f" ({heat_diff:+d} "
                f"zum Rekord)"
            )

        log(
            f"      [{completed}/"
            f"{total_stations}] "
            f"{sid} fertig: "
            f"{summer_text}, "
            f"{heat_text}"
        )

    return result


# ============================================================
# FARBEN
# ============================================================

def color_summer_days(
    value
):

    if value >= 60:
        return "#800026"

    if value >= 50:
        return "#BD0026"

    if value >= 40:
        return "#E31A1C"

    if value >= 30:
        return "#FC4E2A"

    if value >= 20:
        return "#FD8D3C"

    if value >= 10:
        return "#FEB24C"

    return "#FED976"


def color_heat_days(
    value
):

    if value >= 30:
        return "#800026"

    if value >= 25:
        return "#BD0026"

    if value >= 20:
        return "#E31A1C"

    if value >= 15:
        return "#FC4E2A"

    if value >= 10:
        return "#FD8D3C"

    if value >= 5:
        return "#FEB24C"

    return "#FED976"


def color_diff(
    value
):

    if value >= 20:
        return "#1a9850"

    if value >= 10:
        return "#66bd63"

    if value >= 5:
        return "#a6d96a"

    if value >= 1:
        return "#d9ef8b"

    if value == 0:
        return "#fee08b"

    if value >= -5:
        return "#fdae61"

    return "#d73027"


# ============================================================
# 7) KARTE ERSTELLEN
#
# Flache Kreise wie im ursprünglichen Skript.
# ============================================================

def plot_map(
    results,
    value_key,
    color_function,
    title,
    filename
):

    log(
        f"      Erstelle {filename} ..."
    )

    # --------------------------------------------------------
    # Deutschlandkarte
    # --------------------------------------------------------

    gdf = gpd.read_file(
        SHAPEFILE
    )

    fig, ax = plt.subplots(
        figsize=(10, 12)
    )

    gdf.plot(
        ax=ax,
        color="#f0f0f0",
        edgecolor="black",
        linewidth=0.5
    )

    # --------------------------------------------------------
    # Kreise
    # --------------------------------------------------------

    for result in results.values():

        value = result[
            value_key
        ]

        if value is None:
            continue

        circ = Circle(
            (
                result["lon"],
                result["lat"]
            ),
            radius=0.12,
            facecolor=color_function(
                value
            ),
            edgecolor=None,
            zorder=5
        )

        ax.add_patch(
            circ
        )

    # --------------------------------------------------------
    # Zahlen
    # --------------------------------------------------------

    for result in results.values():

        value = result[
            value_key
        ]

        if value is None:
            continue

        txt = ax.text(
            result["lon"],
            result["lat"],
            str(value),
            fontsize=10,
            ha="center",
            va="center",
            color="white",
            zorder=10
        )

        txt.set_path_effects([
            path_effects.Stroke(
                linewidth=2.0,
                foreground="black"
            ),
            path_effects.Normal()
        ])

    # --------------------------------------------------------
    # Titel
    # --------------------------------------------------------

    ax.set_title(
        title,
        fontsize=16,
        pad=20
    )

    ax.set_xticks([])

    ax.set_yticks([])

    ax.axis("off")

    plt.tight_layout()

    plt.savefig(
        filename,
        dpi=200,
        bbox_inches="tight"
    )

    plt.close()

    log(
        f"      Fertig: {filename}"
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

log("")

log("=" * 70)

log(
    "SOMMER- UND HITZETAGE 2026"
)

log("=" * 70)

log(
    f"Datum:              "
    f"{TODAY.strftime('%d.%m.%Y')}"
)

log(
    f"Datenstand:         "
    f"{DATA_DATE.strftime('%d.%m.%Y')}"
)

log(
    f"Auswertung:         "
    f"01.01.{CURRENT_YEAR} bis "
    f"{DATA_DATE.strftime('%d.%m.%Y')}"
)

log(
    "Sommertag:          TXK >= 25 °C"
)

log(
    "Hitzetag:           TXK >= 30 °C"
)

log("=" * 70)

log("")


# ============================================================
# 1. STATIONEN.CSV
# ============================================================

stationen = load_station_csv()


# ============================================================
# 2. REKORDDATEIEN
# ============================================================

(
    summer_records,
    heat_records
) = load_records()


# ============================================================
# 3. RELEVANTE STATIONEN
# ============================================================

targets = build_target_stations(
    stationen,
    summer_records,
    heat_records
)

if not targets:

    log(
        "FEHLER: Keine relevanten "
        "Stationen gefunden."
    )

    raise SystemExit(1)


# ============================================================
# 4. DWD-STATIONSMETADATEN
# ============================================================

meta = load_dwd_station_meta(
    targets
)

if not meta:

    log(
        "FEHLER: Keine DWD-"
        "Stationsmetadaten gefunden."
    )

    raise SystemExit(1)


# Nur Stationen verarbeiten,
# für die DWD-Metadaten vorhanden sind.

targets = {

    sid: target

    for sid, target
    in targets.items()

    if sid in meta
}


# ============================================================
# 5. DWD-DATEIEN
# ============================================================

files = get_dwd_files(
    targets
)

if not files:

    log(
        "FEHLER: Keine passenden "
        "DWD-Stationsdateien gefunden."
    )

    raise SystemExit(1)


# ============================================================
# 6. STATIONEN PARALLEL VERARBEITEN
# ============================================================

log("")

log(
    "[6/7] Verarbeite DWD-Tagesdaten ..."
)

log(
    f"      Max. parallele Downloads: "
    f"{MAX_WORKERS}"
)

log("")

files_to_process = []

for filename in files:

    sid = filename.split("_")[2]

    if (
        sid in targets
        and sid in meta
    ):

        files_to_process.append(
            filename
        )


total_stations = len(
    files_to_process
)

results = {}


with ThreadPoolExecutor(
    max_workers=MAX_WORKERS
) as pool:

    futures = {

        pool.submit(
            process_station,

            filename,

            targets[
                filename.split("_")[2]
            ],

            meta,

            total_stations

        ): filename

        for filename
        in files_to_process
    }

    for future in as_completed(
        futures
    ):

        filename = futures[
            future
        ]

        sid = filename.split(
            "_"
        )[2]

        try:

            result = (
                future.result()
            )

            results[
                result["station_id"]
            ] = result

        except Exception as exc:

            log(
                f"      FEHLER bei Station "
                f"{sid}: {exc}"
            )


# ============================================================
# ERGEBNISSE PRÜFEN
# ============================================================

log("")

log(
    "[7/7] Erzeuge Karten ..."
)

if not results:

    log(
        "FEHLER: Keine Station konnte "
        "verarbeitet werden."
    )

    raise SystemExit(1)


log(
    f"      Erfolgreich verarbeitet: "
    f"{len(results)} / {len(targets)}"
)


missing_results = (
    set(targets.keys())
    -
    set(results.keys())
)

if missing_results:

    log(
        "      WARNUNG: Keine Ergebnisse für: "
        + ", ".join(
            sorted(missing_results)
        )
    )


# ============================================================
# OUTPUT-VERZEICHNIS
# ============================================================

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)


# ============================================================
# KARTE 1:
# SOMMERTAGE 2026
# ============================================================

plot_map(
    results,

    "summer_days",

    color_summer_days,

    (
        f"Sommertage 2026 "
        f"bis {DATA_DATE.strftime('%d.%m.%Y')}"
    ),

    os.path.join(
        OUTPUT_DIR,
        "karte_sommertage_2026.png"
    )
)


# ============================================================
# KARTE 2:
# DIFFERENZ SOMMERTAGE ZUM REKORD
# ============================================================

plot_map(
    results,

    "summer_diff",

    color_diff,

    (
        "Differenz der Sommertage 2026 "
        "zum Stationsrekord"
    ),

    os.path.join(
        OUTPUT_DIR,
        "karte_sommertage_diff.png"
    )
)


# ============================================================
# KARTE 3:
# HITZETAGE 2026
# ============================================================

plot_map(
    results,

    "heat_days",

    color_heat_days,

    (
        f"Hitzetage 2026 "
        f"bis {DATA_DATE.strftime('%d.%m.%Y')}"
    ),

    os.path.join(
        OUTPUT_DIR,
        "karte_hitzetage_2026.png"
    )
)


# ============================================================
# KARTE 4:
# DIFFERENZ HITZETAGE ZUM REKORD
# ============================================================

plot_map(
    results,

    "heat_diff",

    color_diff,

    (
        "Differenz der Hitzetage 2026 "
        "zum Stationsrekord"
    ),

    os.path.join(
        OUTPUT_DIR,
        "karte_hitzetage_diff.png"
    )
)


# ============================================================
# ABSCHLUSS
# ============================================================

log("")

log("=" * 70)

log("FERTIG")

log("=" * 70)

log(
    f"Datenstand: "
    f"{DATA_DATE.strftime('%d.%m.%Y')}"
)

log(
    f"Stationen: "
    f"{len(results)} / {len(targets)}"
)

log("")

log("Ausgabedateien:")

log(
    f"  {OUTPUT_DIR}/"
    f"karte_sommertage_2026.png"
)

log(
    f"  {OUTPUT_DIR}/"
    f"karte_sommertage_diff.png"
)

log(
    f"  {OUTPUT_DIR}/"
    f"karte_hitzetage_2026.png"
)

log(
    f"  {OUTPUT_DIR}/"
    f"karte_hitzetage_diff.png"
)

log("=" * 70)
