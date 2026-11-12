# ============================================================
# DWD LIVE-MONATSKARTE SONNENSCHEINDAUER
#
# DATENLOGIK
#
#   TAGE < GESTERN:
#       DWD daily/kl/recent/
#       Parameter SDK
#
#   GESTERN:
#       1. Wenn SDK in daily/kl/recent vorhanden:
#              SDK verwenden
#
#       2. Wenn SDK für diese Station noch NICHT vorhanden:
#              Fallback auf
#              10_minutes/solar/recent/
#              Parameter SD_10
#
#       Der Fallback erfolgt PRO STATION.
#
#   HEUTE:
#       10_minutes/solar/now/
#       Parameter SD_10
#
# Monatswert pro Station:
#
#       SDK aller Tage < gestern
#       +
#       gestern: SDK ODER SD_10-Fallback
#       +
#       heute: SD_10 aus solar/now
#
# Fehlende Werte einzelner Stationen werden nicht als
# globaler Fehler behandelt.
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

MONTHLY_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "sonnenschein_monat.png"
)


# ============================================================
# DWD
# ============================================================

DAILY_RECENT_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/recent/"
)

# Gestern:
# 10-Minuten-Sonnenschein als Fallback,
# falls für die Station noch kein SDK vorliegt.
SOLAR_RECENT_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "solar/recent/"
)

# Heute:
# laufende 10-Minuten-Sonnenscheindaten.
SOLAR_NOW_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "solar/now/"
)

SOLAR_STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "solar/historical/"
    "zehn_min_sd_Beschreibung_Stationen.txt"
)


# ============================================================
# TECHNIK
# ============================================================

MAX_WORKERS = 16
REQUEST_TIMEOUT = 120

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "DWD-Sunshine-Monthly-Map/4.0"
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

    log(
        "Lade stationen_extreme.csv ..."
    )

    if not os.path.exists(
        STATION_LIST
    ):

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

    missing = (
        required
        - set(df.columns)
    )

    if missing:

        raise ValueError(
            "Fehlende Spalten in "
            "stationen_extreme.csv: "
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

    df["name"] = (
        df["name"]
        .str.strip()
    )

    df["bundesland"] = (
        df["bundesland"]
        .str.strip()
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
# DWD DAILY-RECENT-DATEIEN
# ============================================================

def get_daily_files(
    station_ids
):

    log(
        "Lade DWD Tageswert-Dateiliste ..."
    )

    response = get(
        DAILY_RECENT_URL
    )

    matches = re.findall(
        r'href="([^"]+\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    wanted = {
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

        station_id = (
            match.group(1)
            .zfill(5)
        )

        if station_id in wanted:

            files[station_id] = filename

    log(
        f"{len(files)} relevante Tageswert-Dateien gefunden"
    )

    return files


# ============================================================
# DWD SOLAR-NOW-DATEIEN
#
# HEUTE
# ============================================================

def get_solar_now_files(
    station_ids
):

    log(
        "Lade DWD Solar-now-Dateiliste ..."
    )

    response = get(
        SOLAR_NOW_URL
    )

    matches = re.findall(
        r'href="([^"]*10minutenwerte_SOLAR_(\d{5})_now\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    wanted = {
        str(x).zfill(5)
        for x in station_ids
    }

    files = {}

    for filename, station_id in matches:

        station_id = (
            station_id.zfill(5)
        )

        if station_id in wanted:

            files[station_id] = filename

    log(
        f"{len(files)} relevante Solar-now-Dateien gefunden"
    )

    return files


# ============================================================
# DWD SOLAR-RECENT-DATEIEN
#
# GESTERN
#
# Wird nur als Fallback verwendet, wenn für die Station
# gestern noch kein SDK vorliegt.
# ============================================================

def get_solar_recent_files(
    station_ids
):

    log(
        "Lade DWD Solar-recent-Dateiliste ..."
    )

    response = get(
        SOLAR_RECENT_URL
    )

    matches = re.findall(
        r'href="([^"]*10minutenwerte_SOLAR_(\d{5})_akt\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    wanted = {
        str(x).zfill(5)
        for x in station_ids
    }

    files = {}

    for filename, station_id in matches:

        station_id = (
            station_id.zfill(5)
        )

        if station_id in wanted:

            files[station_id] = filename

    log(
        f"{len(files)} relevante Solar-recent-Dateien gefunden"
    )

    return files


# ============================================================
# STATIONSKOORDINATEN
# ============================================================

def load_station_meta(
    station_ids
):

    log(
        "Lade DWD-Stationskoordinaten ..."
    )

    station_ids = {
        str(x).zfill(5)
        for x in station_ids
    }

    response = get(
        SOLAR_STATIONS_URL
    )

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

        if line.startswith(
            "Stations_id"
        ):

            header_index = i
            break

    if header_index is None:

        raise RuntimeError(
            "Stations_id-Header nicht gefunden."
        )

    result = {}

    for line in lines[
        header_index + 1:
    ]:

        if len(line) < 60:
            continue

        station_id = (
            line[0:5]
            .strip()
            .zfill(5)
        )

        if station_id not in station_ids:
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

        result[station_id] = {
            "lat": lat,
            "lon": lon
        }

        if len(result) == len(
            station_ids
        ):

            break

    missing = (
        station_ids
        - set(result)
    )

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
# DWD ZAHL PARSEN
# ============================================================

def parse_dwd_number(
    value
):

    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace(
        ",",
        "."
    )

    try:

        number = float(value)

    except ValueError:

        return None

    if number <= -999:
        return None

    return number


# ============================================================
# DAILY SDK EINLESEN
#
# Gibt alle verfügbaren SDK-Werte des Monats zurück.
#
# Wichtig:
# Fehlende einzelne Tage sind erlaubt.
# ============================================================

def read_daily_sunshine_file(
    station_id,
    filename,
    month_start,
    yesterday
):

    url = (
        DAILY_RECENT_URL
        + filename
    )

    response = get(url)

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as archive:

        txt_entry = None

        for info in archive.infolist():

            base = os.path.basename(
                info.filename
            ).lower()

            if (
                base.startswith(
                    "produkt_klima_tag"
                )
                and base.endswith(".txt")
            ):

                txt_entry = info
                break

        if txt_entry is None:

            txt_entry = next(
                (
                    info
                    for info in archive.infolist()
                    if info.filename
                    .lower()
                    .endswith(".txt")
                ),
                None
            )

        if txt_entry is None:

            raise RuntimeError(
                f"Keine Tageswert-TXT in {filename}"
            )

        with archive.open(
            txt_entry
        ) as stream:

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

    if "SDK" not in df.columns:

        raise RuntimeError(
            f"SDK fehlt in {filename}"
        )

    df["MESS_DATUM"] = pd.to_datetime(
        df["MESS_DATUM"],
        format="%Y%m%d",
        errors="coerce"
    )

    df["SDK"] = pd.to_numeric(
        df["SDK"],
        errors="coerce"
    )

    df.loc[
        df["SDK"] <= -999,
        "SDK"
    ] = np.nan

    df = df[
        (df["MESS_DATUM"].dt.date >= month_start)
        & (df["MESS_DATUM"].dt.date <= yesterday)
    ].copy()

    df = df.dropna(
        subset=["SDK"]
    )

    result = {}

    for _, row in df.iterrows():

        d = row[
            "MESS_DATUM"
        ].date()

        result[d] = float(
            row["SDK"]
        )

    return result


# ============================================================
# SOLAR-DATEI EINLESEN
#
# Funktioniert für:
#
#   solar/recent/
#   solar/now/
#
# DWD MESS_DATUM wird als UTC interpretiert.
# Anschließend erfolgt die Zuordnung zum lokalen
# Kalendertag Europe/Berlin.
#
# SD_10 wird direkt in Stunden summiert.
# ============================================================

def read_solar_recent_file(
    station_id,
    filename,
    base_url
):

    url = (
        base_url
        + filename
    )

    response = get(url)

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as archive:

        entry = None

        for info in archive.infolist():

            base = os.path.basename(
                info.filename
            ).lower()

            if (
                base.endswith(".txt")
                and base.startswith(
                    "produkt_"
                )
            ):

                entry = info
                break

        if entry is None:

            entry = next(
                (
                    info
                    for info in archive.infolist()
                    if info.filename
                    .lower()
                    .endswith(".txt")
                ),
                None
            )

        if entry is None:

            raise RuntimeError(
                f"Keine TXT-Datei in {filename}"
            )

        rows = []

        with archive.open(
            entry
        ) as stream:

            for raw_line in stream:

                line = raw_line.decode(
                    "cp1252",
                    errors="replace"
                ).strip()

                if not line:
                    continue

                if line.upper().startswith(
                    "STATIONS_ID"
                ):
                    continue

                fields = [
                    field.strip()
                    for field in line.split(";")
                ]

                if fields and (
                    fields[-1]
                    .lower()
                    == "eor"
                ):

                    fields = fields[:-1]

                if len(fields) < 6:
                    continue

                timestamp_string = (
                    fields[1]
                )

                timestamp = pd.to_datetime(
                    timestamp_string,
                    format="%Y%m%d%H%M",
                    utc=True,
                    errors="coerce"
                )

                if pd.isna(timestamp):
                    continue

                sd10 = parse_dwd_number(
                    fields[5]
                )

                if sd10 is None:
                    continue

                local_timestamp = (
                    timestamp
                    .tz_convert(
                        "Europe/Berlin"
                    )
                )

                rows.append(
                    (
                        local_timestamp,
                        sd10
                    )
                )

    if not rows:

        log(
            f"Station {station_id}: "
            f"keine gültigen SD_10-Werte in "
            f"{filename}"
        )

        return {}

    # ========================================================
    # Nach lokalem Kalendertag gruppieren
    # ========================================================

    by_date = {}

    for timestamp, sunshine in rows:

        d = timestamp.date()

        by_date.setdefault(
            d,
            []
        ).append(
            (
                timestamp,
                sunshine
            )
        )

    result = {}

    for d, values in by_date.items():

        values.sort(
            key=lambda x: x[0]
        )

        result[d] = {

            "sunshine_hours":
                sum(
                    sunshine
                    for _, sunshine in values
                ),

            "valid_values":
                len(values),

            "data_from":
                values[0][0],

            "data_until":
                values[-1][0]
        }

    return result


# ============================================================
# STATION BERECHNEN
#
# QUELLENLOGIK:
#
#   < gestern:
#       daily / SDK
#
#   gestern:
#       daily / SDK
#       ODER
#       solar/recent / SD_10
#
#   heute:
#       solar/now / SD_10
# ============================================================

def process_station(
    station_id,
    daily_filename,
    solar_recent_filename,
    solar_now_filename,
    month_start,
    today,
    yesterday
):

    try:

        # ====================================================
        # 1. DAILY
        # ====================================================

        daily = {}

        if daily_filename:

            try:

                daily = (
                    read_daily_sunshine_file(
                        station_id,
                        daily_filename,
                        month_start,
                        yesterday
                    )
                )

            except Exception as exc:

                log(
                    f"Station {station_id}: "
                    f"Daily konnte nicht gelesen werden: "
                    f"{exc}"
                )

                daily = {}

        # ====================================================
        # 2. SOLAR RECENT
        #
        # NUR FÜR GESTERN
        # ====================================================

        solar_recent = {}

        if solar_recent_filename:

            try:

                solar_recent = (
                    read_solar_recent_file(
                        station_id,
                        solar_recent_filename,
                        SOLAR_RECENT_URL
                    )
                )

            except Exception as exc:

                log(
                    f"Station {station_id}: "
                    f"Solar-recent konnte nicht gelesen "
                    f"werden: {exc}"
                )

                solar_recent = {}

        # ====================================================
        # 3. SOLAR NOW
        #
        # NUR FÜR HEUTE
        # ====================================================

        solar_now = {}

        if solar_now_filename:

            try:

                solar_now = (
                    read_solar_recent_file(
                        station_id,
                        solar_now_filename,
                        SOLAR_NOW_URL
                    )
                )

            except Exception as exc:

                log(
                    f"Station {station_id}: "
                    f"Solar-now konnte nicht gelesen "
                    f"werden: {exc}"
                )

                solar_now = {}

        # ====================================================
        # 4. MONATSSUMME
        # ====================================================

        monthly_sum = 0.0

        historical_days = 0

        yesterday_sunshine = None

        today_sunshine = None

        yesterday_fallback = False

        data_until = None

        # ====================================================
        # 5. ALLE TAGE VOR GESTERN
        #
        # NUR SDK
        # ====================================================

        for d, value in daily.items():

            if (
                month_start
                <= d
                < yesterday
            ):

                monthly_sum += float(
                    value
                )

                historical_days += 1

        # ====================================================
        # 6. GESTERN
        #
        # PRIORITÄT:
        #
        #     SDK
        #
        # FALLBACK:
        #
        #     SD_10 aus solar/recent
        # ====================================================

        if yesterday in daily:

            yesterday_sunshine = float(
                daily[yesterday]
            )

            monthly_sum += (
                yesterday_sunshine
            )

            historical_days += 1

            log(
                f"Station {station_id}: "
                f"GESTERN SDK = "
                f"{yesterday_sunshine:.2f} h"
            )

            data_until = pd.Timestamp(
                yesterday
            )

        elif yesterday in solar_recent:

            yesterday_sunshine = float(
                solar_recent[yesterday][
                    "sunshine_hours"
                ]
            )

            monthly_sum += (
                yesterday_sunshine
            )

            historical_days += 1

            yesterday_fallback = True

            data_until = (
                solar_recent[yesterday][
                    "data_until"
                ]
            )

            log(
                f"Station {station_id}: "
                f"GESTERN SD_10-FALLBACK = "
                f"{yesterday_sunshine:.2f} h "
                f"("
                f"{solar_recent[yesterday]['valid_values']}"
                f" Intervalle)"
            )

        else:

            log(
                f"Station {station_id}: "
                f"GESTERN {yesterday:%d.%m.%Y}: "
                "keine Daten "
                "(weder SDK noch SD_10)"
            )

        # ====================================================
        # 7. HEUTE
        #
        # AUSSCHLIESSLICH solar/now
        # ====================================================

        if today in solar_now:

            today_sunshine = float(
                solar_now[today][
                    "sunshine_hours"
                ]
            )

            monthly_sum += (
                today_sunshine
            )

            today_until = (
                solar_now[today][
                    "data_until"
                ]
            )

            if (
                data_until is None
                or today_until > data_until
            ):

                data_until = today_until

            log(
                f"Station {station_id}: "
                f"HEUTE SD_10 = "
                f"{today_sunshine:.2f} h "
                f"("
                f"{solar_now[today]['valid_values']}"
                f" Intervalle)"
            )

        else:

            log(
                f"Station {station_id}: "
                "HEUTE noch keine Solar-now-Daten"
            )

        # ====================================================
        # 8. FALLBACK FÜR DATENSTAND
        # ====================================================

        if data_until is None:

            if daily:

                latest_daily_date = max(
                    daily.keys()
                )

                data_until = pd.Timestamp(
                    latest_daily_date
                )

            else:

                data_until = pd.Timestamp(
                    yesterday
                )

        # ====================================================
        # 9. STATION NUR VERWERFEN,
        #    WENN GAR KEINE DATEN VORHANDEN SIND
        # ====================================================

        if (
            historical_days == 0
            and yesterday_sunshine is None
            and today_sunshine is None
        ):

            raise RuntimeError(
                "Keine verwertbaren Monatsdaten."
            )

        # ====================================================
        # 10. ERGEBNIS
        # ====================================================

        return {

            "station_id":
                station_id,

            "monthly_sunshine":
                float(monthly_sum),

            "historical_sum":
                float(
                    monthly_sum
                    - (
                        today_sunshine or 0.0
                    )
                ),

            "current_sunshine":
                today_sunshine,

            "yesterday_sunshine":
                yesterday_sunshine,

            "yesterday_fallback":
                yesterday_fallback,

            "historical_days":
                historical_days,

            "data_until":
                data_until
        }

    except Exception as exc:

        log(
            f"Fehler Station {station_id}: {exc}"
        )

        return None


# ============================================================
# ALLE STATIONEN
# ============================================================

def process_all_stations(
    station_list,
    daily_files,
    solar_recent_files,
    solar_now_files,
    month_start,
    today,
    yesterday
):

    log(
        "Berechne Stationswerte ..."
    )

    station_ids = set(
        station_list[
            "station_id"
        ]
    )

    # --------------------------------------------------------
    # Eine Station ist verwendbar, wenn mindestens eine
    # Datenquelle vorhanden ist.
    #
    # Die eigentliche Entscheidung SDK/Fallback erfolgt
    # anschließend pro Station.
    # --------------------------------------------------------

    usable_ids = (
        station_ids
        & (
            set(daily_files)
            | set(solar_recent_files)
            | set(solar_now_files)
        )
    )

    log(
        f"{len(usable_ids)} Stationen besitzen "
        "mindestens eine benötigte Datenquelle"
    )

    if not usable_ids:

        raise RuntimeError(
            "Keine Station besitzt Daily-, "
            "Solar-recent- oder Solar-now-Daten."
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

                # ältere Tage + gestern SDK
                daily_files.get(
                    station_id
                ),

                # gestern Fallback
                solar_recent_files.get(
                    station_id
                ),

                # heute
                solar_now_files.get(
                    station_id
                ),

                month_start,
                today,
                yesterday
            )

            futures[future] = station_id

        for future in as_completed(
            futures
        ):

            station_id = futures[
                future
            ]

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

    if not results:

        raise RuntimeError(
            "Keine Station konnte erfolgreich "
            "ausgewertet werden."
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
        .set_index(
            "station_id"
        )
        .to_dict(
            "index"
        )
    )

    for station_id, result in results.items():

        meta = station_meta.get(
            station_id
        )

        info = station_info.get(
            station_id
        )

        if (
            meta is None
            or info is None
        ):
            continue

        rows.append({

            "station_id":
                station_id,

            "name":
                info["name"],

            "bundesland":
                info["bundesland"],

            "lat":
                meta["lat"],

            "lon":
                meta["lon"],

            "monthly_sunshine":
                result[
                    "monthly_sunshine"
                ],

            "historical_sum":
                result[
                    "historical_sum"
                ],

            "current_sunshine":
                result[
                    "current_sunshine"
                ],

            "yesterday_sunshine":
                result[
                    "yesterday_sunshine"
                ],

            "yesterday_fallback":
                result[
                    "yesterday_fallback"
                ],

            "historical_days":
                result[
                    "historical_days"
                ],

            "data_until":
                result[
                    "data_until"
                ]

        })

    if not rows:

        raise RuntimeError(
            "Keine Stationen mit vollständigen "
            "Geodaten verfügbar."
        )

    df = pd.DataFrame(
        rows
    )

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
# DEUTSCHLAND-MONATSMITTEL
# ============================================================

def calculate_germany_month_mean(
    gdf
):

    values = pd.to_numeric(
        gdf[
            "monthly_sunshine"
        ],
        errors="coerce"
    ).dropna()

    if values.empty:

        raise RuntimeError(
            "Keine gültigen "
            "Stations-Monatssummen."
        )

    return float(
        values.mean()
    )


# ============================================================
# HEUTIGER SOLARWERT
# ============================================================

def calculate_current_mean(
    gdf
):

    values = pd.to_numeric(
        gdf[
            "current_sunshine"
        ],
        errors="coerce"
    ).dropna()

    if values.empty:

        return None

    return float(
        values.mean()
    )


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

    for _ in range(
        iterations
    ):

        moved = False

        for i in range(
            len(positions)
        ):

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

def sunshine_text_color(
    value
):

    if value >= 180:
        return "#b35a00"

    if value >= 140:
        return "#d97900"

    if value >= 100:
        return "#e89b00"

    if value >= 60:
        return "#b87900"

    return "#555555"


# ============================================================
# SIDEBAR
# ============================================================

def draw_monthly_summary(
    ax,
    germany_month_mean,
    current_mean,
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
        "Monat:",
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
            f"{germany_month_mean:.1f}"
            .replace(".", ",")
            + " h"
        ),
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        ha="right",
        va="top",
        color="#d97900"
    )

    ax.text(
        0.0,
        0.775,
        "Heute:",
        transform=ax.transAxes,
        fontsize=8.5,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    if current_mean is None:

        current_text = "–"

    else:

        current_text = (
            f"{current_mean:.1f}"
            .replace(".", ",")
            + " h"
        )

    ax.text(
        1.0,
        0.775,
        current_text,
        transform=ax.transAxes,
        fontsize=8.5,
        ha="right",
        va="top",
        color="#333333"
    )


# ============================================================
# KARTE
# ============================================================

def plot_sunshine_map(
    germany,
    gdf,
    title,
    output_file,
    created_at,
    data_until,
    germany_month_mean,
    current_mean
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
        gdf["monthly_sunshine"].notna()
    ].copy()

    if valid.empty:

        raise RuntimeError(
            "Keine gültigen Werte "
            "für Sonnenscheindauer."
        )

    label_positions = (
        calculate_label_positions(
            ax,
            valid,
            "monthly_sunshine",
            min_distance=24,
            iterations=8
        )
    )

    for index, row in valid.iterrows():

        value = row[
            "monthly_sunshine"
        ]

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
                + " h"
            ),
            fontsize=8.0,
            fontweight="bold",
            ha="center",
            va="center",
            color=sunshine_text_color(
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

    draw_monthly_summary(
        summary_ax,
        germany_month_mean,
        current_mean,
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
    log("DWD LIVE-MONATSKARTE SONNENSCHEINDAUER")
    log("=" * 70)

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # ========================================================
    # DATUM
    # ========================================================

    now = pd.Timestamp.now(
        tz="Europe/Berlin"
    )

    today = now.date()

    month_start = date(
        today.year,
        today.month,
        1
    )

    yesterday = (
        today
        - timedelta(days=1)
    )

    log(
        "Heute: "
        + today.strftime(
            "%d.%m.%Y"
        )
    )

    log(
        "Gestern: "
        + yesterday.strftime(
            "%d.%m.%Y"
        )
    )

    log(
        "Monatsbeginn: "
        + month_start.strftime(
            "%d.%m.%Y"
        )
    )

    # ========================================================
    # 1. STATIONEN
    # ========================================================

    station_list = (
        load_station_list()
    )

    station_ids = set(
        station_list[
            "station_id"
        ]
    )

    # ========================================================
    # 2. KOORDINATEN
    # ========================================================

    station_meta = (
        load_station_meta(
            station_ids
        )
    )

    # ========================================================
    # 3. DAILY RECENT
    #
    # Quelle für:
    #   - alle vergangenen Tage
    #   - gestern, wenn SDK bereits vorhanden
    # ========================================================

    daily_files = (
        get_daily_files(
            station_ids
        )
    )

    # ========================================================
    # 4. SOLAR RECENT
    #
    # NUR FALLBACK FÜR GESTERN
    # ========================================================

    solar_recent_files = (
        get_solar_recent_files(
            station_ids
        )
    )

    # ========================================================
    # 5. SOLAR NOW
    #
    # NUR HEUTE
    # ========================================================

    solar_now_files = (
        get_solar_now_files(
            station_ids
        )
    )

    # ========================================================
    # 6. STATIONEN BERECHNEN
    # ========================================================

    results = (
        process_all_stations(
            station_list,
            daily_files,
            solar_recent_files,
            solar_now_files,
            month_start,
            today,
            yesterday
        )
    )

    # ========================================================
    # 7. GEODATEN
    # ========================================================

    log(
        "Erstelle Geodaten ..."
    )

    gdf = create_geodata(
        results,
        station_list,
        station_meta
    )

    log(
        f"{len(gdf)} Stationen "
        "für Karte verfügbar"
    )

    # ========================================================
    # 8. DATENSTAND
    # ========================================================

    data_until_values = (
        pd.to_datetime(
            gdf["data_until"],
            errors="coerce"
        )
        .dropna()
    )

    if data_until_values.empty:

        raise RuntimeError(
            "Kein gültiger Datenstand."
        )

    data_until = (
        data_until_values.max()
    )

    log(
        "Datenstand: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
    )

    # ========================================================
    # 9. FALLBACK-STATISTIK
    # ========================================================

    fallback_count = int(
        gdf[
            "yesterday_fallback"
        ]
        .fillna(False)
        .sum()
    )

    yesterday_count = int(
        gdf[
            "yesterday_sunshine"
        ]
        .notna()
        .sum()
    )

    today_count = int(
        gdf[
            "current_sunshine"
        ]
        .notna()
        .sum()
    )

    log(
        f"Gestern verwertbare Werte: "
        f"{yesterday_count} Stationen"
    )

    log(
        f"Gestern davon SD_10-Fallback: "
        f"{fallback_count} Stationen"
    )

    log(
        f"Heute verwertbare SD_10-Werte: "
        f"{today_count} Stationen"
    )

    # ========================================================
    # 10. DEUTSCHLAND-MONATSMITTEL
    # ========================================================

    germany_month_mean = (
        calculate_germany_month_mean(
            gdf
        )
    )

    log(
        "Deutschland-Monatssumme "
        "(Stationsmittel): "
        f"{germany_month_mean:.3f} h"
    )

    # ========================================================
    # 11. HEUTIGER WERT
    # ========================================================

    current_mean = (
        calculate_current_mean(
            gdf
        )
    )

    if current_mean is not None:

        log(
            "Deutschland-Mittel heute: "
            f"{current_mean:.3f} h"
        )

    # ========================================================
    # 12. ERSTELLUNGSZEIT
    # ========================================================

    created_at = (
        pd.Timestamp.now(
            tz="Europe/Berlin"
        )
        .to_pydatetime()
        .replace(
            tzinfo=None
        )
    )

    # ========================================================
    # 13. DEUTSCHLAND-GEOMETRIE
    # ========================================================

    log(
        "Lade Deutschland-Geometrie ..."
    )

    germany = gpd.read_file(
        SHAPEFILE
    )

    # ========================================================
    # 14. KARTE
    # ========================================================

    plot_sunshine_map(
        germany=germany,
        gdf=gdf,
        title=(
            "Sonnenscheindauer\n"
            + today.strftime(
                "%B %Y"
            )
        ),
        output_file=MONTHLY_OUTPUT,
        created_at=created_at,
        data_until=data_until,
        germany_month_mean=germany_month_mean,
        current_mean=current_mean
    )

    # ========================================================
    # ABSCHLUSS
    # ========================================================

    log("")
    log("=" * 70)
    log("FERTIG")
    log("=" * 70)

    log(
        f"Stationen: {len(gdf)}"
    )

    log(
        "Gestern verwertbare Werte: "
        f"{yesterday_count}"
    )

    log(
        "Gestern SD_10-Fallback: "
        f"{fallback_count}"
    )

    log(
        "Heute SD_10-Werte: "
        f"{today_count}"
    )

    log(
        "Deutschland-Monatssumme "
        "(Stationsmittel): "
        + f"{germany_month_mean:.2f} h"
    )

    log(
        "Daten bis: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
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
