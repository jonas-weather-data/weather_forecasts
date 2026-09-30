# ============================================================
# DWD TAGES- UND MONATSMITTELKARTE
#
# Stationen ausschließlich aus:
#     stationen_extreme.csv
#
# Vergangene Tage:
#     DWD daily/kl/recent/
#
# Laufender Tag:
#     DWD 10_minutes/air_temperature/now/
#
# Deutschland-Tagesmittel:
#     Mittelwert der Stations-Tagesmittel
#     * GERMANY_GRID_FACTOR
#
# Deutschland-Monatsmittel:
#     Wird vollständig aus den Stationsdaten berechnet.
#
# Es wird KEIN vorgegebenes Deutschland-Monatsmittel verwendet.
# ============================================================

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import BytesIO
import os
import re
import threading
import time
import zipfile

import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests


# ============================================================
# KONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)

SHAPEFILE = os.path.join(
    BASE_DIR,
    "gadm41_DEU_1.json"
)

STATION_LIST = os.path.join(
    BASE_DIR,
    "stationen_extreme.csv"
)

DAILY_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "mittel_temp.png"
)

MONTHLY_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "mittel_temp_monat.png"
)

GERMANY_GRID_FACTOR = 1.0028


# ============================================================
# DWD
# ============================================================

STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/historical/"
    "KL_Tageswerte_Beschreibung_Stationen.txt"
)

DAILY_RECENT_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/recent/"
)

AIR_TEMPERATURE_NOW_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "air_temperature/now/"
)


# ============================================================
# TECHNIK
# ============================================================

MAX_WORKERS = 16
REQUEST_TIMEOUT = 120

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "DWD-Temperature-Maps/1.0"
})

LOCK = threading.Lock()
PROGRESS = 0


# ============================================================
# LOGGING
# ============================================================

def log(message):
    print(
        f"[{time.strftime('%H:%M:%S')}] {message}",
        flush=True
    )


# ============================================================
# HTTP
# ============================================================

def get(url):
    response = HTTP.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response


# ============================================================
# STATIONEN AUS CSV
# ============================================================

def load_station_list():

    log("Lade stationen_extreme.csv ...")

    if not os.path.exists(STATION_LIST):
        raise FileNotFoundError(
            f"Datei nicht gefunden: {STATION_LIST}"
        )

    df = pd.read_csv(
        STATION_LIST,
        sep=";",
        dtype=str,
        encoding="utf-8",
        keep_default_na=False
    )

    df.columns = [
        str(c).strip().lower()
        for c in df.columns
    ]

    required = {
        "station_id",
        "name",
        "bundesland"
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            "Fehlende Spalten in stationen_extreme.csv: "
            + ", ".join(sorted(missing))
            + "\nVorhandene Spalten: "
            + ", ".join(df.columns)
        )

    df = df[
        [
            "station_id",
            "name",
            "bundesland"
        ]
    ].copy()

    df["station_id"] = (
        df["station_id"]
        .str.strip()
        .str.zfill(5)
    )

    df["name"] = df["name"].str.strip()

    df["bundesland"] = (
        df["bundesland"].str.strip()
    )

    df = df[
        (df["station_id"] != "")
        & (df["bundesland"] != "")
    ]

    df = df.drop_duplicates(
        subset="station_id",
        keep="first"
    )

    log(
        f"{len(df)} Stationen aus CSV geladen"
    )

    return df


# ============================================================
# STATIONSKOORDINATEN VOM DWD
# ============================================================

def load_station_meta(station_ids):

    log("Lade DWD-Stationskoordinaten ...")

    station_ids = {
        str(x).zfill(5)
        for x in station_ids
    }

    response = get(STATIONS_URL)

    txt = response.content.decode(
        "cp1252",
        errors="replace"
    )

    lines = (
        txt
        .replace("\r\n", "\n")
        .split("\n")
    )

    header_index = None

    for i, line in enumerate(lines):
        if line.startswith("Stations_id"):
            header_index = i
            break

    if header_index is None:
        raise RuntimeError(
            "Stations_id-Header nicht gefunden."
        )

    result = {}

    for line in lines[header_index + 1:]:

        if len(line) < 60:
            continue

        sid = (
            line[0:5]
            .strip()
            .zfill(5)
        )

        if sid not in station_ids:
            continue

        try:
            lat = float(
                line[43:50]
                .strip()
                .replace(",", ".")
            )

            lon = float(
                line[53:60]
                .strip()
                .replace(",", ".")
            )

        except ValueError:
            continue

        result[sid] = {
            "lat": lat,
            "lon": lon
        }

        if len(result) == len(station_ids):
            break

    missing = station_ids - set(result)

    if missing:
        log(
            "WARNUNG: Keine Koordinaten für: "
            + ", ".join(sorted(missing))
        )

    log(
        f"{len(result)} von "
        f"{len(station_ids)} Stationen mit Koordinaten"
    )

    return result


# ============================================================
# DATEIEN AUS DWD DAILY/RECENT
# ============================================================

def get_daily_files(station_ids):

    log("Lade DWD-Dateiliste für Tageswerte ...")

    response = get(DAILY_RECENT_URL)

    matches = re.findall(
        r'href="([^"]+\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    station_ids = {
        str(x).zfill(5)
        for x in station_ids
    }

    files = {}

    for filename in matches:

        match = re.search(
            r"tageswerte_KL_(\d{5})_",
            filename,
            flags=re.IGNORECASE
        )

        if not match:
            continue

        sid = match.group(1)

        if sid not in station_ids:
            continue

        files[sid] = filename

    log(
        f"{len(files)} relevante Tageswert-Dateien gefunden"
    )

    return files


# ============================================================
# DATEIEN AUS DWD 10-MINUTEN/NOW
# ============================================================

def get_air_temperature_files(station_ids):

    log(
        "Lade DWD-Dateiliste für "
        "10-Minuten-Lufttemperatur ..."
    )

    response = get(
        AIR_TEMPERATURE_NOW_URL
    )

    matches = re.findall(
        r'href="([^"]+\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    station_ids = {
        str(x).zfill(5)
        for x in station_ids
    }

    files = {}

    for filename in matches:

        match = re.search(
            r"10minutenwerte_TU_(\d{5})_now\.zip",
            filename,
            flags=re.IGNORECASE
        )

        if not match:
            continue

        sid = match.group(1)

        if sid not in station_ids:
            continue

        files[sid] = filename

    log(
        f"{len(files)} relevante "
        "10-Minuten-Dateien gefunden"
    )

    return files


# ============================================================
# DWD-TAGESDATEI EINLESEN
# ============================================================

def read_daily_file(
    station_id,
    filename,
    month_start,
    yesterday
):

    url = DAILY_RECENT_URL + filename

    response = get(url)

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as archive:

        csv_file = None

        for name in archive.namelist():

            base = os.path.basename(
                name
            ).lower()

            if (
                base.startswith("produkt_klima_tag")
                and base.endswith(".txt")
            ):
                csv_file = name
                break

        if csv_file is None:
            raise RuntimeError(
                f"Keine Tageswert-TXT in {filename}"
            )

        with archive.open(csv_file) as stream:

            df = pd.read_csv(
                stream,
                sep=";",
                encoding="cp1252",
                dtype=str
            )

    df.columns = [
        str(c).strip()
        for c in df.columns
    ]

    if "MESS_DATUM" not in df.columns:
        raise RuntimeError(
            f"MESS_DATUM fehlt in {filename}"
        )

    if "TMK" not in df.columns:
        raise RuntimeError(
            f"TMK fehlt in {filename}"
        )

    df["MESS_DATUM"] = pd.to_datetime(
        df["MESS_DATUM"],
        format="%Y%m%d",
        errors="coerce"
    )

    df["TMK"] = pd.to_numeric(
        df["TMK"],
        errors="coerce"
    )

    df.loc[
        df["TMK"] <= -999,
        "TMK"
    ] = np.nan

    df = df[
        (df["MESS_DATUM"].dt.date >= month_start)
        & (df["MESS_DATUM"].dt.date <= yesterday)
    ].copy()

    df = df.dropna(
        subset=["TMK"]
    )

    if df.empty:
        return None

    daily_values = {}

    for _, row in df.iterrows():

        d = row["MESS_DATUM"].date()

        daily_values[d] = float(
            row["TMK"]
        )

    return daily_values if daily_values else None


# ============================================================
# LAUFENDER TAG
# ============================================================

def read_current_day_file(
    station_id,
    filename,
    target_date
):

    url = AIR_TEMPERATURE_NOW_URL + filename

    response = get(url)

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as archive:

        txt_file = None

        for info in archive.infolist():

            base = os.path.basename(
                info.filename
            ).lower()

            if (
                base.endswith(".txt")
                and base.startswith("produkt_")
            ):
                txt_file = info
                break

        if txt_file is None:
            raise RuntimeError(
                f"Keine Produkt-TXT in {filename}"
            )

        rows = []

        with archive.open(txt_file) as stream:

            for raw_line in stream:

                line = raw_line.decode(
                    "cp1252",
                    errors="replace"
                ).strip()

                if not line:
                    continue

                if line.startswith("STATIONS_ID"):
                    continue

                fields = [
                    x.strip()
                    for x in line.split(";")
                ]

                if len(fields) < 5:
                    continue

                if fields[-1].lower() == "eor":
                    fields = fields[:-1]

                if len(fields) < 5:
                    continue

                timestamp_string = fields[1]

                timestamp = None

                for fmt in (
                    "%Y%m%d%H%M",
                    "%Y%m%d%H"
                ):

                    try:

                        timestamp = pd.to_datetime(
                            timestamp_string,
                            format=fmt,
                            utc=True
                        )

                        break

                    except ValueError:
                        pass

                if timestamp is None:
                    continue

                timestamp = timestamp.tz_convert(
                    "Europe/Berlin"
                )

                if timestamp.date() != target_date:
                    continue

                try:
                    temperature = float(
                        fields[4].replace(",", ".")
                    )
                except (
                    ValueError,
                    AttributeError
                ):
                    continue

                if temperature <= -999:
                    continue

                rows.append(
                    (
                        timestamp,
                        temperature
                    )
                )

    if not rows:
        return None, None

    rows.sort(
        key=lambda x: x[0]
    )

    temperatures = [
        x[1]
        for x in rows
    ]

    daily_mean = (
        sum(temperatures)
        / len(temperatures)
    )

    last_timestamp = rows[-1][0]

    return (
        daily_mean,
        last_timestamp
    )


# ============================================================
# STATION BERECHNEN
# ============================================================

def process_station(
    station_id,
    daily_filename,
    current_filename,
    month_start,
    yesterday,
    today
):

    try:

        historical = read_daily_file(
            station_id,
            daily_filename,
            month_start,
            yesterday
        )

        if not historical:
            raise RuntimeError(
                "Keine historischen TMK-Werte gefunden"
            )

        today_mean, data_until = (
            read_current_day_file(
                station_id,
                current_filename,
                today
            )
        )

        if today_mean is None:
            raise RuntimeError(
                "Kein TT_10-Tagesmittel für heute"
            )

        historical_sum = sum(
            historical.values()
        )

        completed_days = len(
            historical
        )

        midnight = pd.Timestamp(
            today,
            tz="Europe/Berlin"
        )

        elapsed_seconds = (
            data_until - midnight
        ).total_seconds()

        elapsed_seconds = max(
            0.0,
            min(
                elapsed_seconds,
                24 * 60 * 60
            )
        )

        day_fraction = (
            elapsed_seconds
            / (24 * 60 * 60)
        )

        denominator = (
            completed_days
            + day_fraction
        )

        if denominator <= 0:
            monthly_mean = None
        else:
            monthly_mean = (
                historical_sum
                + today_mean * day_fraction
            ) / denominator

        return {
            "station_id": station_id,
            "daily_mean": today_mean,
            "monthly_mean": monthly_mean,
            "historical_sum": historical_sum,
            "historical_days": completed_days,
            "day_fraction": day_fraction,
            "data_until": data_until
        }

    except Exception as exc:

        log(
            f"Fehler Station {station_id}: {exc}"
        )

        return None


# ============================================================
# ALLE STATIONEN VERARBEITEN
# ============================================================

def process_all_stations(
    station_list,
    daily_files,
    current_files,
    month_start,
    yesterday,
    today
):

    log("Berechne Stationswerte ...")

    station_ids = set(
        station_list["station_id"]
    )

    usable_ids = (
        station_ids
        & set(daily_files)
        & set(current_files)
    )

    log(
        f"{len(usable_ids)} Stationen besitzen "
        "sowohl Tages- als auch 10-Minuten-Datei"
    )

    results = {}

    global PROGRESS

    PROGRESS = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for station_id in sorted(
            usable_ids
        ):

            future = executor.submit(
                process_station,
                station_id,
                daily_files[station_id],
                current_files[station_id],
                month_start,
                yesterday,
                today
            )

            futures[future] = station_id

        for future in as_completed(
            futures
        ):

            result = future.result()

            with LOCK:
                PROGRESS += 1

                print(
                    f"[{PROGRESS}/{len(futures)}] "
                    f"{PROGRESS * 100 / len(futures):.1f}%",
                    flush=True
                )

            if result is not None:
                results[
                    result["station_id"]
                ] = result

    log(
        f"{len(results)} Stationen erfolgreich ausgewertet"
    )

    return results


# ============================================================
# GEODATEN
# ============================================================

def create_geodata(
    results,
    station_list,
    station_meta
):

    rows = []

    station_info = (
        station_list
        .set_index("station_id")
        .to_dict("index")
    )

    for station_id, result in results.items():

        meta = station_meta.get(
            station_id
        )

        info = station_info.get(
            station_id
        )

        if meta is None or info is None:
            continue

        rows.append({
            "station_id": station_id,
            "name": info["name"],
            "bundesland": info["bundesland"],
            "lat": meta["lat"],
            "lon": meta["lon"],
            "daily_mean": result["daily_mean"],
            "monthly_mean": result["monthly_mean"],
            "historical_sum": result["historical_sum"],
            "historical_days": result["historical_days"],
            "day_fraction": result["day_fraction"],
            "data_until": result["data_until"]
        })

    if not rows:
        raise RuntimeError(
            "Keine Stationen mit vollständigen "
            "Geodaten verfügbar."
        )

    df = pd.DataFrame(rows)

    geometry = gpd.points_from_xy(
        df["lon"],
        df["lat"]
    )

    return gpd.GeoDataFrame(
        df,
        geometry=geometry,
        crs="EPSG:4326"
    )


# ============================================================
# DEUTSCHLAND-TAGESMITTEL
# ============================================================

def calculate_germany_daily_mean(gdf):

    values = pd.to_numeric(
        gdf["daily_mean"],
        errors="coerce"
    ).dropna()

    if values.empty:
        raise RuntimeError(
            "Keine gültigen Stations-Tagesmittel vorhanden."
        )

    raw_mean = float(
        values.mean()
    )

    return (
        raw_mean
        * GERMANY_GRID_FACTOR
    )


# ============================================================
# DEUTSCHLAND-MONATSMITTEL
#
# KOMPLETT AUS DEN STATIONSDATEN.
#
# Für jede Station:
#
#   historische_summe
#   + heutiges_stationsmittel * anteil_heute
#
# wird über die Stationen gemittelt.
#
# Danach:
#
#   * GERMANY_GRID_FACTOR
#
# Der laufende Tag wird nur mit seinem tatsächlichen
# Zeitanteil berücksichtigt.
# ============================================================

def calculate_germany_month_mean(
    gdf,
    target_date,
    data_until
):

    if gdf.empty:
        raise RuntimeError(
            "GeoDataFrame ist leer."
        )

    required_columns = {
        "historical_sum",
        "historical_days",
        "day_fraction",
        "daily_mean",
        "data_until"
    }

    missing = (
        required_columns
        - set(gdf.columns)
    )

    if missing:
        raise RuntimeError(
            "Fehlende Spalten für "
            "Deutschland-Monatsmittel: "
            + ", ".join(sorted(missing))
        )

    # --------------------------------------------------------
    # Die Stationswerte werden jeweils mit ihrem eigenen
    # Datenstand berechnet. Dadurch wird nicht versehentlich
    # ein globaler "today"-Wert innerhalb der Funktion
    # vorausgesetzt.
    # --------------------------------------------------------

    valid = gdf[
        gdf["historical_sum"].notna()
        & gdf["historical_days"].notna()
        & gdf["day_fraction"].notna()
        & gdf["daily_mean"].notna()
    ].copy()

    if valid.empty:
        raise RuntimeError(
            "Keine vollständigen Stationswerte "
            "für das Monatsmittel vorhanden."
        )

    # --------------------------------------------------------
    # Für jede Station:
    #
    # historische_sum
    # + heutiges Stationsmittel * day_fraction
    #
    # --------------------------------------------------------

    station_sums = (
        pd.to_numeric(
            valid["historical_sum"],
            errors="coerce"
        )
        + pd.to_numeric(
            valid["daily_mean"],
            errors="coerce"
        )
        * pd.to_numeric(
            valid["day_fraction"],
            errors="coerce"
        )
    )

    station_denominators = (
        pd.to_numeric(
            valid["historical_days"],
            errors="coerce"
        )
        + pd.to_numeric(
            valid["day_fraction"],
            errors="coerce"
        )
    )

    valid_values = (
        station_sums.notna()
        & station_denominators.notna()
        & (station_denominators > 0)
    )

    station_sums = station_sums[
        valid_values
    ]

    station_denominators = (
        station_denominators[
            valid_values
        ]
    )

    if station_sums.empty:
        raise RuntimeError(
            "Keine gültigen Stations-Monatswerte."
        )

    # --------------------------------------------------------
    # Gemeinsamer Monatsstand:
    #
    # Die Stationen haben normalerweise denselben
    # historischen Tagesbereich. Falls einzelne Stationen
    # geringfügig andere Datenstände besitzen, wird jede
    # Station mit ihrem tatsächlich vorhandenen Zeitraum
    # berücksichtigt.
    #
    # Für den normalen Fall sind alle Denominatoren identisch.
    # --------------------------------------------------------

    station_monthly_means = (
        station_sums
        / station_denominators
    )

    raw_germany_month_mean = float(
        station_monthly_means.mean()
    )

    germany_month_mean = (
        raw_germany_month_mean
        * GERMANY_GRID_FACTOR
    )

    return germany_month_mean


# ============================================================
# LABEL-POSITIONEN
# ============================================================

def calculate_label_positions(
    ax,
    gdf,
    column,
    min_distance=24,
    iterations=8
):

    valid = gdf[
        gdf[column].notna()
    ].copy()

    if valid.empty:
        return {}

    xy = ax.transData.transform(
        [
            (
                p.x,
                p.y
            )
            for p in valid.geometry
        ]
    )

    positions = xy.copy()

    for _ in range(iterations):

        moved = False

        for i in range(len(positions)):

            for j in range(
                i + 1,
                len(positions)
            ):

                dx = (
                    positions[i][0]
                    - positions[j][0]
                )

                dy = (
                    positions[i][1]
                    - positions[j][1]
                )

                distance_sq = (
                    dx * dx
                    + dy * dy
                )

                if distance_sq >= (
                    min_distance
                    * min_distance
                ):
                    continue

                if distance_sq < 0.01:

                    dx = 1.0
                    dy = 0.0
                    distance_sq = 1.0

                distance = (
                    distance_sq ** 0.5
                )

                push = (
                    min_distance
                    - distance
                ) * 0.5

                nx = dx / distance
                ny = dy / distance

                positions[i][0] += (
                    nx * push
                )

                positions[i][1] += (
                    ny * push
                )

                positions[j][0] -= (
                    nx * push
                )

                positions[j][1] -= (
                    ny * push
                )

                moved = True

        if not moved:
            break

    inverse = (
        ax.transData.inverted()
    )

    result = {}

    for index, position in zip(
        valid.index,
        positions
    ):

        result[index] = tuple(
            inverse.transform(
                position
            )
        )

    return result


# ============================================================
# TEXTFARBE
# ============================================================

def temperature_text_color(value):

    if value >= 35:
        return "#7f0000"

    if value >= 30:
        return "#a50026"

    if value >= 25:
        return "#c63d17"

    if value >= 20:
        return "#8c2d04"

    if value <= 0:
        return "#225ea8"

    return "#333333"


# ============================================================
# SIDEBAR TAGESKARTE
# ============================================================

def draw_daily_summary(
    ax,
    germany_mean,
    data_until,
    created_at
):

    ax.axis("off")

    ax.text(
        0.0,
        0.995,
        "Datenstand",
        transform=ax.transAxes,
        fontsize=8.5,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        0.0,
        0.963,
        "Daten bis",
        transform=ax.transAxes,
        fontsize=8.0,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0,
        0.963,
        data_until.strftime(
            "%d.%m.%Y %H:%M"
        ) + " Uhr",
        transform=ax.transAxes,
        fontsize=8.0,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.text(
        0.0,
        0.925,
        "Erstellt am",
        transform=ax.transAxes,
        fontsize=8.0,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0,
        0.925,
        created_at.strftime(
            "%d.%m.%Y %H:%M:%S"
        ) + " Uhr",
        transform=ax.transAxes,
        fontsize=8.0,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.plot(
        [0.0, 1.0],
        [0.875, 0.875],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    ax.text(
        0.0,
        0.825,
        "Mittel:",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        va="top",
        color="#333333"
    )

    ax.text(
        1.0,
        0.825,
        (
            f"{germany_mean:.2f}"
            .replace(".", ",")
            + " °C"
        ),
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        ha="right",
        va="top",
        color="#a50026"
    )


# ============================================================
# SIDEBAR MONATSKARTE
# ============================================================

def draw_monthly_summary(
    ax,
    germany_month_mean,
    today_germany_mean,
    data_until,
    created_at
):

    ax.axis("off")

    ax.text(
        0.0,
        0.995,
        "Datenstand",
        transform=ax.transAxes,
        fontsize=8.5,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        0.0,
        0.963,
        "Daten bis",
        transform=ax.transAxes,
        fontsize=8.0,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0,
        0.963,
        data_until.strftime(
            "%d.%m.%Y %H:%M"
        ) + " Uhr",
        transform=ax.transAxes,
        fontsize=8.0,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.text(
        0.0,
        0.925,
        "Erstellt am",
        transform=ax.transAxes,
        fontsize=8.0,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0,
        0.925,
        created_at.strftime(
            "%d.%m.%Y %H:%M:%S"
        ) + " Uhr",
        transform=ax.transAxes,
        fontsize=8.0,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.plot(
        [0.0, 1.0],
        [0.875, 0.875],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    ax.text(
        0.0,
        0.825,
        "Mittel:",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        va="top",
        color="#333333"
    )

    ax.text(
        1.0,
        0.825,
        (
            f"{germany_month_mean:.2f}"
            .replace(".", ",")
            + " °C"
        ),
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        ha="right",
        va="top",
        color="#a50026"
    )

    ax.text(
        0.0,
        0.775,
        "Tagesmittel",
        transform=ax.transAxes,
        fontsize=8.5,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        1.0,
        0.775,
        (
            f"{today_germany_mean:.2f}"
            .replace(".", ",")
            + " °C"
        ),
        transform=ax.transAxes,
        fontsize=8.5,
        ha="right",
        va="top",
        color="#333333"
    )


# ============================================================
# KARTE
# ============================================================

def plot_temperature_map(
    germany,
    gdf,
    parameter,
    title,
    output_file,
    created_at,
    data_until,
    germany_mean,
    today_germany_mean=None
):

    log(
        f"Erzeuge {output_file}"
    )

    fig = plt.figure(
        figsize=(15, 13),
        facecolor="white"
    )

    gs = fig.add_gridspec(
        1,
        2,
        width_ratios=[
            4.7,
            1.55
        ],
        wspace=0.025
    )

    ax = fig.add_subplot(
        gs[0, 0]
    )

    summary_ax = fig.add_subplot(
        gs[0, 1]
    )

    germany.plot(
        ax=ax,
        color="#eeeeee",
        edgecolor="#555555",
        linewidth=0.55
    )

    xmin, ymin, xmax, ymax = (
        germany.total_bounds
    )

    padx = (
        xmax - xmin
    ) * 0.025

    pady = (
        ymax - ymin
    ) * 0.025

    ax.set_xlim(
        xmin - padx,
        xmax + padx
    )

    ax.set_ylim(
        ymin - pady,
        ymax + pady
    )

    valid = gdf[
        gdf[parameter].notna()
    ].copy()

    if valid.empty:
        raise RuntimeError(
            f"Keine gültigen Werte für {parameter}"
        )

    label_positions = (
        calculate_label_positions(
            ax,
            valid,
            parameter,
            min_distance=24,
            iterations=8
        )
    )

    for index, row in valid.iterrows():

        value = row[parameter]

        if index in label_positions:
            text_x, text_y = (
                label_positions[index]
            )
        else:
            text_x = row.geometry.x
            text_y = row.geometry.y

        ax.text(
            text_x,
            text_y,
            (
                f"{value:.1f}"
                .replace(".", ",")
                + "°"
            ),
            fontsize=8.0,
            fontweight="bold",
            ha="center",
            va="center",
            color=temperature_text_color(
                value
            ),
            zorder=10
        )

    ax.set_title(
        title,
        fontsize=18,
        fontweight="bold",
        pad=14
    )

    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis("off")

    if parameter == "daily_mean":

        draw_daily_summary(
            summary_ax,
            germany_mean,
            data_until,
            created_at
        )

    else:

        draw_monthly_summary(
            summary_ax,
            germany_mean,
            today_germany_mean,
            data_until,
            created_at
        )

    fig.subplots_adjust(
        left=0.02,
        right=0.985,
        top=0.94,
        bottom=0.02
    )

    fig.savefig(
        output_file,
        dpi=200,
        facecolor="white"
    )

    plt.close(fig)

    log(
        f"{output_file} gespeichert"
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("DWD TAGES- UND MONATSMITTEL")
    log("=" * 70)

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # DATUM / UHRZEIT
    # --------------------------------------------------------

    now = pd.Timestamp.now(
        tz="Europe/Berlin"
    )

    today = now.date()

    yesterday = (
        today
        - timedelta(days=1)
    )

    month_start = date(
        today.year,
        today.month,
        1
    )

    log(
        "Heute: "
        + today.strftime("%d.%m.%Y")
    )

    log(
        "Gestern: "
        + yesterday.strftime("%d.%m.%Y")
    )

    log(
        "Monatsbeginn: "
        + month_start.strftime("%d.%m.%Y")
    )

    # --------------------------------------------------------
    # 1. STATIONEN AUS CSV
    # --------------------------------------------------------

    station_list = (
        load_station_list()
    )

    station_ids = set(
        station_list["station_id"]
    )

    # --------------------------------------------------------
    # 2. KOORDINATEN
    # --------------------------------------------------------

    station_meta = (
        load_station_meta(
            station_ids
        )
    )

    # --------------------------------------------------------
    # 3. HISTORISCHE TAGESDATEIEN
    # --------------------------------------------------------

    daily_files = (
        get_daily_files(
            station_ids
        )
    )

    # --------------------------------------------------------
    # 4. AKTUELLE 10-MINUTEN-DATEIEN
    # --------------------------------------------------------

    current_files = (
        get_air_temperature_files(
            station_ids
        )
    )

    # --------------------------------------------------------
    # 5. STATIONEN AUSWERTEN
    # --------------------------------------------------------

    results = process_all_stations(
        station_list,
        daily_files,
        current_files,
        month_start,
        yesterday,
        today
    )

    if not results:
        raise RuntimeError(
            "Keine Station konnte erfolgreich "
            "ausgewertet werden."
        )

    # --------------------------------------------------------
    # 6. GEODATAFRAME
    # --------------------------------------------------------

    log(
        "Erstelle Geodaten ..."
    )

    gdf = create_geodata(
        results,
        station_list,
        station_meta
    )

    log(
        f"{len(gdf)} Stationen für Karten verfügbar"
    )

    # --------------------------------------------------------
    # 7. GLOBALER DATENSTAND
    #
    # Häufigster letzter Messzeitpunkt.
    # --------------------------------------------------------

    data_until_counts = (
        gdf["data_until"]
        .value_counts()
    )

    data_until = (
        data_until_counts
        .index[0]
    )

    log(
        "Datenstand: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
    )

    # --------------------------------------------------------
    # 8. DEUTSCHLAND-TAGESMITTEL
    #
    # Mittel der Stations-Tagesmittel
    # * Rasterfaktor
    #
    # Dieser Wert wird für Tages- und Monatskarte
    # identisch verwendet.
    # --------------------------------------------------------

    germany_daily_mean = (
        calculate_germany_daily_mean(
            gdf
        )
    )

    log(
        "Deutschland-Tagesmittel: "
        f"{germany_daily_mean:.3f} °C"
    )

    # --------------------------------------------------------
    # 9. DEUTSCHLAND-MONATSMITTEL
    #
    # Vollständig aus den Stationsdaten berechnet.
    #
    # KEIN vorgegebenes 15,80 °C.
    # --------------------------------------------------------

    germany_month_mean = (
        calculate_germany_month_mean(
            gdf=gdf,
            target_date=today,
            data_until=data_until
        )
    )

    log(
        "Deutschland-Monatsmittel: "
        f"{germany_month_mean:.3f} °C"
    )

    # --------------------------------------------------------
    # 10. ERSTELLUNGSZEIT
    # --------------------------------------------------------

    created_at = (
        pd.Timestamp.now(
            tz="Europe/Berlin"
        )
        .to_pydatetime()
        .replace(
            tzinfo=None
        )
    )

    # --------------------------------------------------------
    # 11. DEUTSCHLAND-GEOMETRIE
    # --------------------------------------------------------

    germany = gpd.read_file(
        SHAPEFILE
    )

    # --------------------------------------------------------
    # 12. TAGESKARTE
    # --------------------------------------------------------

    plot_temperature_map(
        germany=germany,
        gdf=gdf,
        parameter="daily_mean",
        title=(
            "Tagesmitteltemperatur\n"
            + today.strftime(
                "%d.%m.%Y"
            )
        ),
        output_file=DAILY_OUTPUT,
        created_at=created_at,
        data_until=data_until,
        germany_mean=germany_daily_mean
    )

    # --------------------------------------------------------
    # 13. MONATSKARTE
    # --------------------------------------------------------

    plot_temperature_map(
        germany=germany,
        gdf=gdf,
        parameter="monthly_mean",
        title=(
            "Monatsmittel\n"
            + today.strftime(
                "%B %Y"
            )
        ),
        output_file=MONTHLY_OUTPUT,
        created_at=created_at,
        data_until=data_until,
        germany_mean=germany_month_mean,
        today_germany_mean=germany_daily_mean
    )

    # --------------------------------------------------------
    # ABSCHLUSS
    # --------------------------------------------------------

    log("")
    log("=" * 70)
    log("FERTIG")
    log("=" * 70)

    log(
        f"Stationen: {len(gdf)}"
    )

    log(
        "Tagesmittel Deutschland: "
        + f"{germany_daily_mean:.2f} °C"
    )

    log(
        "Monatsmittel Deutschland: "
        + f"{germany_month_mean:.2f} °C"
    )

    log(
        "Daten bis: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
    )

    log(
        f"Tageskarte: {DAILY_OUTPUT}"
    )

    log(
        f"Monatskarte: {MONTHLY_OUTPUT}"
    )

    log("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
