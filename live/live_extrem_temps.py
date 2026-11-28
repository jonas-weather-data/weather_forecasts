import os
import re
import zipfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
from scipy.spatial import cKDTree
from pyproj import Transformer
from shapely.ops import unary_union
from shapely import vectorized

from matplotlib.colors import (
    LinearSegmentedColormap,
    Normalize
)


# ============================================================
# KONFIGURATION
# ============================================================

NOW_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "extreme_temperature/now/"
)

STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/historical/"
    "KL_Tageswerte_Beschreibung_Stationen.txt"
)

# Alle lokalen Dateien liegen im GitHub-Ordner "live"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SHAPEFILE = os.path.join(
    BASE_DIR,
    "gadm41_DEU_1.json"
)

STATION_LIST = os.path.join(
    BASE_DIR,
    "stationen_extreme.csv"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)

TXK_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "extrema_txk.png"
)

TNK_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "extrema_tnk.png"
)

MAX_WORKERS = 16
REQUEST_TIMEOUT = 120


# ============================================================
# HTTP
# ============================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "DWD-Extrema-Map/1.0"
})


def get(url):

    response = HTTP.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response


# ============================================================
# LOGGING
# ============================================================

def log(message):

    print(
        message,
        flush=True
    )


# ============================================================
# STATIONEN.CSV
# ============================================================

def load_station_list():

    log(
        "[1/8] Lade stationen_extreme.csv ..."
    )

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
        str(column).strip().lower()
        for column in df.columns
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
            "Fehlende Spalten in stationen_extreme.csv: "
            + ", ".join(sorted(missing))
            + "\nGefundene Spalten: "
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
        f"      {len(df)} Stationen aus CSV geladen."
    )

    return df


# ============================================================
# DWD-NOW-DATEIEN
# ============================================================

# ============================================================
# ZUSÄTZLICHE DWD-NOW-DATENSÄTZE
# ============================================================

PARAMETER_DATASETS = {
    "TTT": {
        "directory": "air_temperature",
        "pattern": r'10minutenwerte_TU_(\d{5})_now\.zip',
        "prefix": "10minutenwerte_TU_",
        "field": "TT_10",
        "index": 4,
        "aggregation": "mean",
        "title": "Tagesmitteltemperatur (°C)",
        "filename": "ttt"
    },
    "SunD1": {
        "directory": "solar",
        "pattern": r'10minutenwerte_SOLAR_(\d{5})_now\.zip',
        "prefix": "10minutenwerte_SOLAR_",
        "field": "SD_10",
        "index": 5,
        "aggregation": "sum",
        "title": "Sonnenscheindauer (h)",
        "filename": "sund1"
    },
    "RR1c": {
        "directory": "precipitation",
        "pattern": r'10minutenwerte_nieder_(\d{5})_now\.zip',
        "prefix": "10minutenwerte_nieder_",
        "field": "RWS_10",
        "index": 4,
        "aggregation": "sum",
        "title": "Niederschlagsmenge (mm)",
        "filename": "rr1c"
    },
    "FX1": {
        "directory": "extreme_wind",
        "pattern": r'10minutenwerte_extrema_wind_(\d{5})_now\.zip',
        "prefix": "10minutenwerte_extrema_wind_",
        "field": "FX_10",
        "index": 3,
        "aggregation": "max",
        "title": "Stärkste Windböe (km/h)",
        "filename": "fx1"
    }
}

DWD_10MINUTES_BASE_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
)


def get_parameter_now_files(parameter, station_ids):

    config = PARAMETER_DATASETS[parameter]
    url = (
        DWD_10MINUTES_BASE_URL
        + config["directory"]
        + "/now/"
    )

    response = get(url)
    matches = re.findall(
        config["pattern"],
        response.text,
        flags=re.IGNORECASE
    )

    station_ids = set(station_ids)
    files = {
        station_id: config["prefix"] + station_id + "_now.zip"
        for station_id in matches
        if station_id in station_ids
    }

    log(
        f"      {parameter}: {len(files)} passende DWD-Stationsdateien."
    )

    if not files:
        raise RuntimeError(
            f"Keine DWD-now-Dateien für {parameter} in stationen_extreme.csv gefunden."
        )

    return files


def process_parameter_station(
    parameter,
    station_id,
    filename,
    target_date
):

    config = PARAMETER_DATASETS[parameter]
    url = (
        DWD_10MINUTES_BASE_URL
        + config["directory"]
        + "/now/"
        + filename
    )

    response = get(url)
    day_start = pd.Timestamp(target_date, tz="UTC")
    day_end = day_start + pd.Timedelta(hours=23, minutes=50)
    values = []

    with zipfile.ZipFile(BytesIO(response.content)) as archive:
        entry = next(
            (
                item for item in archive.infolist()
                if item.filename.lower().endswith(".txt")
                and os.path.basename(item.filename).lower().startswith("produkt_zehn_")
            ),
            None
        )

        if entry is None:
            raise RuntimeError("Keine produkt_zehn_*.txt-Datei gefunden.")

        with archive.open(entry) as stream:
            for raw_line in stream:
                line = raw_line.decode("cp1252", errors="replace").strip()
                if not line or line.startswith("STATIONS_ID"):
                    continue

                fields = [field.strip() for field in line.split(";")]
                if fields and fields[-1].lower() == "eor":
                    fields = fields[:-1]

                if len(fields) <= config["index"]:
                    continue

                try:
                    timestamp = pd.to_datetime(
                        fields[1],
                        format="%Y%m%d%H%M",
                        utc=True
                    )
                except (ValueError, TypeError):
                    try:
                        timestamp = pd.to_datetime(
                            fields[1],
                            format="%Y%m%d%H",
                            utc=True
                        )
                    except (ValueError, TypeError):
                        continue

                if timestamp < day_start or timestamp > day_end:
                    continue

                value = parse_nullable_decimal(fields[config["index"]])
                if value is None:
                    continue

                if parameter == "FX1":
                    value *= 3.6

                values.append((timestamp, value))

    if not values:
        raise RuntimeError(f"Keine gültigen {config['field']}-Werte für {target_date}.")

    values.sort(key=lambda item: item[0])
    numeric_values = [value for _, value in values]

    if config["aggregation"] == "mean":
        result_value = sum(numeric_values) / len(numeric_values)
    elif config["aggregation"] == "sum":
        result_value = sum(numeric_values)
    else:
        result_value = max(numeric_values)

    return {
        "station_id": station_id,
        "value": result_value,
        "data_until": values[-1][0].tz_convert("Europe/Berlin")
    }


def process_parameter_all(parameter, files, target_date):

    results = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(
                process_parameter_station,
                parameter,
                station_id,
                filename,
                target_date
            ): station_id
            for station_id, filename in files.items()
        }

        for future in as_completed(futures):
            station_id = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                log(f"      FEHLER {parameter} {station_id}: {exc}")

    if not results:
        raise RuntimeError(f"Keine Station konnte für {parameter} verarbeitet werden.")

    counts = pd.Series(
        [result["data_until"] for result in results]
    ).value_counts()
    data_until = counts.index[0]

    log(
        f"      {parameter}: {len(results)} Stationen erfolgreich; "
        f"Daten bis {data_until.strftime('%d.%m.%Y %H:%M')} Uhr."
    )

    return results, data_until


def get_now_files():

    log(
        "[2/8] Lade DWD-now-Dateiliste ..."
    )

    response = get(NOW_URL)

    matches = re.findall(
        r'href="(10minutenwerte_extrema_temp_(\d{5})_now\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    files = {}

    for filename, station_id in matches:

        files[station_id] = filename

    if not files:

        raise RuntimeError(
            "Keine DWD-now-Dateien gefunden."
        )

    log(
        f"      {len(files)} Stationsdateien gefunden."
    )

    return files


# ============================================================
# STATIONSKOORDINATEN
# ============================================================

def load_station_meta(station_ids):

    log(
        "[3/8] Lade DWD-Stationskoordinaten ..."
    )

    station_ids = set(
        station_ids
    )

    response = get(STATIONS_URL)

    txt = response.content.decode(
        "cp1252"
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

    for line in lines[
        header_index + 1:
    ]:

        if len(line) < 60:

            continue

        station_id = (
            line[0:5]
            .strip()
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
        - set(result.keys())
    )

    if missing:

        log(
            "      WARNUNG: Keine Koordinaten für: "
            + ", ".join(sorted(missing))
        )

    log(
        f"      {len(result)} von "
        f"{len(station_ids)} Stationen gefunden."
    )

    return result


# ============================================================
# DEZIMALWERT
# ============================================================

def parse_nullable_decimal(value):

    if value is None:

        return None

    value = value.strip()

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
# EINZELNE NOW-DATEI
#
# fields[1] = Messdatum
# fields[3] = TX10
# fields[5] = TN10
#
# Eine Station wird nur berücksichtigt, wenn:
#
# 1. für jeden eingelesenen Messzeitpunkt TX10 UND TN10
#    gültig sind
#
# 2. zwischen den Messzeitpunkten keine Lücke im
#    10-Minuten-Raster besteht
#
# Zusätzlich wird der tatsächlich letzte Messzeitpunkt
# zurückgegeben. Dieser wird später für den globalen
# Datenstand verwendet.
# ============================================================

def process_station(
    station_id,
    filename,
    target_date
):

    day_start = pd.Timestamp(
        target_date,
        tz="UTC"
    )

    day_end = (
        day_start
        + pd.Timedelta(
            hours=23,
            minutes=50
        )
    )

    url = NOW_URL + filename

    response = get(url)

    with zipfile.ZipFile(
        BytesIO(response.content)
    ) as archive:

        entry = next(
            (
                e
                for e in archive.infolist()
                if (
                    e.filename.lower().endswith(".txt")
                    and os.path.basename(
                        e.filename
                    ).lower().startswith(
                        "produkt_zehn_"
                    )
                )
            ),
            None
        )

        if entry is None:

            raise RuntimeError(
                "Keine produkt_zehn_*.txt-Datei gefunden."
            )

        rows = []

        with archive.open(entry) as stream:

            for raw_line in stream:

                line = raw_line.decode(
                    "cp1252",
                    errors="replace"
                ).strip()

                if not line:

                    continue

                if line.startswith(
                    "STATIONS_ID"
                ):

                    continue

                raw_fields = line.split(";")

                if len(raw_fields) < 7:

                    continue

                if (
                    raw_fields[-1]
                    .strip()
                    .lower()
                    == "eor"
                ):

                    raw_fields = raw_fields[:-1]

                fields = [
                    field.strip()
                    for field in raw_fields
                ]

                if len(fields) < 6:

                    continue

                date_string = fields[1]

                mess_datum = None

                for date_format in (
                    "%Y%m%d%H%M",
                    "%Y%m%d%H"
                ):

                    try:

                        mess_datum = pd.to_datetime(
                            date_string,
                            format=date_format,
                            utc=True
                        )

                        break

                    except ValueError:

                        pass

                if mess_datum is None:

                    continue

                if (
                    mess_datum < day_start
                    or mess_datum > day_end
                ):

                    continue

                mess_datum = (
                    mess_datum
                    .tz_convert(
                        "Europe/Berlin"
                    )
                )

                tx10 = parse_nullable_decimal(
                    fields[3]
                )

                tn10 = parse_nullable_decimal(
                    fields[5]
                )

                # ------------------------------------------------
                # Beide für uns relevanten Parameter müssen
                # gleichzeitig gültig sein.
                # ------------------------------------------------

                if (
                    tx10 is None
                    or tn10 is None
                ):

                    raise RuntimeError(
                        "Messlücke bei TX10/TN10"
                    )

                rows.append(
                    (
                        mess_datum,
                        tx10,
                        tn10
                    )
                )

    if not rows:

        raise RuntimeError(
            f"Keine Daten für {target_date}."
        )

    # --------------------------------------------------------
    # Chronologisch sortieren
    # --------------------------------------------------------

    rows.sort(
        key=lambda row: row[0]
    )

    timestamps = [
        row[0]
        for row in rows
    ]

    # --------------------------------------------------------
    # Prüfen, ob zwischen den vorhandenen Messwerten
    # irgendwo eine Lücke im 10-Minuten-Raster existiert.
    # --------------------------------------------------------

    for previous, current in zip(
        timestamps,
        timestamps[1:]
    ):

        difference = (
            current - previous
        )

        if difference != pd.Timedelta(
            minutes=10
        ):

            raise RuntimeError(
                "Messlücke im 10-Minuten-Raster"
            )

    tx_values = [
        tx
        for _, tx, _ in rows
    ]

    tn_values = [
        tn
        for _, _, tn in rows
    ]

    if not tx_values or not tn_values:

        raise RuntimeError(
            "Keine vollständigen TX10/TN10-Werte"
        )

    txk = max(
        tx_values
    )

    tnk = min(
        tn_values
    )

    # --------------------------------------------------------
    # WICHTIG:
    #
    # Tatsächlich letzter Messzeitpunkt der Station.
    # Der Timestamp ist bereits auf deutsche Zeit umgestellt.
    # --------------------------------------------------------

    data_until = timestamps[-1]

    return {
        "station_id": station_id,
        "date": target_date,
        "txk": txk,
        "tnk": tnk,
        "data_until": data_until
    }


# ============================================================
# ALLE STATIONEN PARALLEL
# ============================================================

def process_all(
    files,
    target_date
):

    log(
        "[4/8] Verarbeite aktuelle DWD-Daten ..."
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                process_station,
                station_id,
                filename,
                target_date
            ): station_id

            for station_id, filename
            in files.items()
        }

        for future in as_completed(
            futures
        ):

            station_id = futures[
                future
            ]

            try:

                result = future.result()

                if (
                    result["txk"] is not None
                    and result["tnk"] is not None
                    and result["data_until"] is not None
                ):

                    results.append(
                        result
                    )

            except Exception as exc:

                log(
                    f"      FEHLER {station_id}: "
                    f"{exc}"
                )

    if not results:

        raise RuntimeError(
            "Keine Station konnte verarbeitet werden."
        )

    results.sort(
        key=lambda x: x["station_id"]
    )

    # ========================================================
    # GLOBALER DATENSTAND
    # ========================================================

    data_until_values = [
        result["data_until"]
        for result in results
        if result["data_until"] is not None
    ]

    if not data_until_values:

        raise RuntimeError(
            "Kein gültiger Datenstand ermittelbar."
        )

    data_until_counts = (
        pd.Series(
            data_until_values
        )
        .value_counts()
    )

    data_until = (
        data_until_counts
        .index[0]
    )

    matching_count = int(
        data_until_counts.iloc[0]
    )

    log(
        f"      {len(results)} Stationen erfolgreich."
    )

    log(
        "      Daten bis: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
    )

    log(
        f"      Stationen mit diesem Datenstand: "
        f"{matching_count}/{len(results)}"
    )

    return results, data_until


# ============================================================
# GEODATEN
# ============================================================

def create_geodata(
    results,
    station_meta,
    station_list
):

    rows = []

    station_info = (
        station_list
        .set_index("station_id")
        .to_dict("index")
    )

    for result in results:

        station_id = result[
            "station_id"
        ]

        meta = station_meta.get(
            station_id
        )

        if meta is None:

            continue

        info = station_info.get(
            station_id
        )

        if info is None:

            continue

        rows.append({
            "station_id": station_id,
            "name": info["name"],
            "bundesland": info["bundesland"],
            "txk": result["txk"],
            "tnk": result["tnk"],
            "lat": meta["lat"],
            "lon": meta["lon"]
        })

    if not rows:

        raise RuntimeError(
            "Keine Stationen mit Koordinaten "
            "und CSV-Zuordnung."
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
# TEMPERATUR FORMATIEREN
# ============================================================

def format_temperature(value):

    return (
        f"{value:.1f}"
        .replace(".", ",")
    )


# ============================================================
# FARBSKALEN UND INTERPOLATION
# ============================================================

PLOT_STYLES = {

    "TXK": {
        "vmin": -20,
        "vmax": 50,
        "colors": [
            (0.00, "#08306b"),
            (0.20, "#6baed6"),
            (0.35, "#31a354"),
            (0.50, "#ffff66"),
            (0.64, "#fdae61"),
            (0.71, "#e31a1c"),
            (0.79, "#99000d"),
            (0.86, "#6a3d9a"),
            (0.93, "#c51b8a"),
            (1.00, "#f768a1")
        ]
    },

    # --------------------------------------------------------
    # TAGESTIEFSTTEMPERATUR – TN
    # Exakt deine bisherige Farbskala
    # --------------------------------------------------------,

    "TNK": {
        "vmin": -30,
        "vmax": 30,
        "colors": [
            (0.00, "#6a00a8"),
            (0.17, "#084594"),
            (0.33, "#2171b5"),
            (0.50, "#9ecae1"),
            (0.58, "#238b45"),
            (0.67, "#ffff66"),
            (0.75, "#fd8d3c"),
            (0.83, "#e31a1c"),
            (0.92, "#99000d"),
            (1.00, "#67000d")
        ]
    },

    # --------------------------------------------------------
    # TAGESMITTELTEMPERATUR – TTT
    # Gleiche Farbfolge wie TX, aber bis +35 °C
    # --------------------------------------------------------


    "TTT": {
        "vmin": -20,
        "vmax": 35,
        "colors": [
            (0.000, "#08306b"),  # -20
            (0.255, "#6baed6"),  # -6
            (0.405, "#31a354"),  #  2
            (0.520, "#ffff66"),  #  8,6
            (0.655, "#fdae61"),  # 16
            (0.735, "#e31a1c"),  # 20,4
            (0.815, "#99000d"),  # 24,8
            (0.880, "#6a3d9a"),  # 28,4
            (0.945, "#c51b8a"),  # 32
            (1.000, "#f768a1")   # 35
        ]
    },

    "SunD1": {
        "vmin": 0,
        "vmax": 16,
        "colors": [
            (0.00, "#303030"),
            (0.10, "#555555"),
            (0.20, "#858585"),
            (0.28, "#aaaaaa"),
            (0.35, "#d6c94c"),
            (0.43, "#ffe600"),
            (0.55, "#ffc400"),
            (0.65, "#ff9f00"),
            (0.75, "#ff7300"),
            (0.84, "#ed3b18"),
            (0.92, "#b80000"),
            (1.00, "#650000")
        ]
    },

    "RR1c": {
        "vmin": 0,
        "vmax": 50,
        "colors": [
            (0.00, "#a6d8f0"),
            (0.08, "#65b9e5"),
            (0.18, "#258bd0"),
            (0.30, "#0868b2"),
            (0.42, "#084b91"),
            (0.55, "#08306b"),
            (0.68, "#302080"),
            (0.80, "#653399"),
            (0.90, "#a83fa5"),
            (0.96, "#d45eae"),
            (1.00, "#f080c5")
        ]
    },

    "FX1": {
        "vmin": 0,
        "vmax": 140,
        "colors": [
            (0.0000, "#e2e2e2"),  # 0 Bft
            (0.0071, "#d9d9d9"),

            (0.0357, "#b8d8e8"),  # 1 Bft
            (0.0429, "#8fc5df"),

            (0.0786, "#70b5d8"),  # 2 Bft
            (0.0857, "#4299c8"),

            (0.1357, "#55b96b"),  # 3 Bft
            (0.1429, "#238b45"),

            (0.2000, "#c6df42"),  # 4 Bft
            (0.2071, "#e4df35"),

            (0.2714, "#ffff66"),  # 5 Bft
            (0.2786, "#ffca45"),

            (0.3500, "#ffad32"),  # 6 Bft
            (0.3571, "#ff8225"),

            (0.4357, "#ff641e"),  # 7 Bft
            (0.4429, "#ed351c"),

            (0.5286, "#e51d25"),  # 8 Bft
            (0.5357, "#bd0026"),

            (0.6286, "#a50026"),  # 9 Bft
            (0.6357, "#800026"),

            (0.7286, "#702080"),  # 10 Bft
            (0.7357, "#54278f"),

            (0.8357, "#a32ca5"),  # 11 Bft
            (0.8429, "#c51b8a"),

            (0.8500, "#e45ca8"),  # 12 Bft
            (1.0000, "#f768a1")
        ]
    },
}


def get_parameter_cmap(parameter):

    style = PLOT_STYLES[parameter]

    return LinearSegmentedColormap.from_list(
        parameter,
        style["colors"]
    )


def get_parameter_norm(parameter):

    style = PLOT_STYLES[parameter]

    return Normalize(
        vmin=style["vmin"],
        vmax=style["vmax"],
        clip=True
    )


def interpolate(
    germany,
    gdf,
    parameter,
    resolution_x=400,
    resolution_y=500,
    neighbors=8,
    power=2.0
):

    valid = gdf[
        gdf[parameter].notna()
    ].copy()

    if len(valid) < 3:
        return None

    if gdf.crs is None:
        raise ValueError(
            "Stationsdaten besitzen kein Koordinatenreferenzsystem."
        )

    transformer = Transformer.from_crs(
        gdf.crs,
        "EPSG:3035",
        always_xy=True
    )

    station_x, station_y = transformer.transform(
        valid.geometry.x.to_numpy(),
        valid.geometry.y.to_numpy()
    )

    station_coordinates = np.column_stack((
        station_x,
        station_y
    ))

    station_values = valid[parameter].to_numpy(
        dtype=float
    )

    xmin, ymin, xmax, ymax = germany.total_bounds

    x_values = np.linspace(
        xmin,
        xmax,
        resolution_x
    )

    y_values = np.linspace(
        ymin,
        ymax,
        resolution_y
    )

    grid_x, grid_y = np.meshgrid(
        x_values,
        y_values
    )

    grid_x_projected, grid_y_projected = (
        transformer.transform(
            grid_x,
            grid_y
        )
    )

    grid_coordinates = np.column_stack((
        grid_x_projected.ravel(),
        grid_y_projected.ravel()
    ))

    tree = cKDTree(
        station_coordinates
    )

    k = min(
        neighbors,
        len(valid)
    )

    distances, indices = tree.query(
        grid_coordinates,
        k=k
    )

    if k == 1:
        distances = distances[:, None]
        indices = indices[:, None]

    weights = 1.0 / np.maximum(
        distances,
        0.001
    ) ** power

    exact = distances[:, 0] < 0.001

    interpolated = np.sum(
        weights * station_values[indices],
        axis=1
    ) / np.sum(
        weights,
        axis=1
    )

    interpolated[exact] = station_values[
        indices[exact, 0]
    ]

    interpolated = interpolated.reshape(
        grid_x.shape
    )

    germany_geometry = unary_union(
        germany.geometry
    )

    inside = vectorized.contains(
        germany_geometry,
        grid_x,
        grid_y
    )

    interpolated = np.ma.masked_where(
        ~inside,
        interpolated
    )

    return (
        grid_x,
        grid_y,
        interpolated
    )


def draw_parameter_legend(
    ax,
    parameter,
    number_of_days=None
):

    style = PLOT_STYLES[parameter]

    cmap = get_parameter_cmap(parameter)

    # --------------------------------------------------------
    # NORMIERUNG UND BESCHRIFTUNGEN
    # --------------------------------------------------------

    if number_of_days is None:

        norm = get_parameter_norm(parameter)

    else:

        norm = get_period_norm(
            parameter,
            number_of_days
        )

    if parameter == "TXK":

        ticks = list(range(-20, 51, 5))
        title = "Höchsttemperatur in °C"

    elif parameter == "TNK":

        ticks = list(range(-30, 31, 5))
        title = "Tiefsttemperatur in °C"

    elif parameter == "TTT":

        ticks = list(range(-20, 36, 5))
        title = "Tagesmitteltemperatur in °C"

    elif parameter == "SunD1":

        if number_of_days is None:

            ticks = list(range(0, 17, 2))
            title = "Sonnenscheindauer in Stunden"

        else:

            ticks = list(
                range(
                    0,
                    16 * number_of_days + 1,
                    2 * number_of_days
                )
            )

            title = (
                f"Sonnenscheindauer in Stunden "
                f"({number_of_days} Tage)"
            )

    elif parameter == "RR1c":

        if number_of_days is None:

            ticks = list(range(0, 51, 5))
            title = "Niederschlagsmenge in mm"

        else:

            maximum = norm.vmax

            step = get_legend_step(maximum)

            ticks = list(
                range(
                    0,
                    int(maximum) + 1,
                    step
                )
            )

            title = (
                f"Niederschlagsmenge in mm "
                f"({number_of_days} Tage)"
            )

    elif parameter == "FX1":

        ticks = list(range(13))
        title = "Windböe in km/h"

    else:

        return

    # --------------------------------------------------------
    # ACHSE VORBEREITEN
    # --------------------------------------------------------

    ax.clear()

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.axis("off")

    # --------------------------------------------------------
    # TITEL
    # --------------------------------------------------------

    ax.text(
        0.5,
        0.91,
        title,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=11,
        fontweight="bold",
        color="#333333"
    )

    # --------------------------------------------------------
    # FARBVERLAUF
    # --------------------------------------------------------

    from matplotlib.colors import (
        ListedColormap,
        BoundaryNorm
    )

    if parameter == "FX1":

        boundaries = [
            0, 1, 5, 11, 19, 28, 38,
            49, 61, 74, 88, 102, 117, 140
        ]

        bft_colors = []

        for i in range(13):

            if i == 0:
                midpoint = 0.5

            elif i == 12:
                midpoint = 128.5

            else:
                midpoint = (
                    boundaries[i]
                    + boundaries[i + 1]
                ) / 2

            bft_colors.append(
                cmap(
                    get_parameter_norm(parameter)(
                        midpoint
                    )
                )
            )

        legend_cmap = ListedColormap(
            bft_colors
        )

        ax.imshow(
            [list(range(13))],
            extent=[0.08, 0.92, 0.48, 0.72],
            aspect="auto",
            cmap=legend_cmap,
            norm=BoundaryNorm(
                range(14),
                legend_cmap.N
            ),
            interpolation="nearest"
        )

        labels = [
            "<1",
            "1–5",
            "6–11",
            "12–19",
            "20–28",
            "29–38",
            "39–49",
            "50–61",
            "62–74",
            "75–88",
            "89–102",
            "103–117",
            ">117"
        ]

        for i, label in enumerate(labels):

            x = 0.08 + (
                (i + 0.5) / 13
            ) * 0.84

            ax.text(
                x,
                0.34,
                str(i),
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=9.5,
                fontweight="bold",
                color="#333333"
            )

            ax.text(
                x,
                0.19,
                label,
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=10,
                color="#333333"
            )

        ax.text(
            0.5,
            0.07,
            "Beaufort",
            transform=ax.transAxes,
            ha="center",
            fontsize=9.5,
            color="#555555"
        )

        return

    else:

        gradient_array = [
            [
                cmap(
                    norm(
                        norm.vmin
                        + (
                            norm.vmax - norm.vmin
                        ) * i / 255
                    )
                )
                for i in range(256)
            ]
        ]

        ax.imshow(
            gradient_array,
            extent=[0.08, 0.92, 0.48, 0.72],
            aspect="auto",
            interpolation="nearest"
        )

    # --------------------------------------------------------
    # ZAHLENMARKIERUNGEN
    # --------------------------------------------------------

    for value in ticks:

        x = 0.08 + (
            (value - norm.vmin)
            / (norm.vmax - norm.vmin)
        ) * 0.84

        if x < 0.08 or x > 0.92:
            continue

        ax.plot(
            [x, x],
            [0.44, 0.48],
            transform=ax.transAxes,
            color="#555555",
            linewidth=0.6
        )

        ax.text(
            x,
            0.34,
            str(value),
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=10.5,
            color="#333333"
        )




# ============================================================
# BUNDESLAND- UND DEUTSCHLAND-STATISTIK
# ============================================================

def calculate_state_extremes(
    gdf,
    parameter
):

    states = []

    bundeslaender = sorted(
        gdf["bundesland"]
        .dropna()
        .unique()
    )

    for bundesland in bundeslaender:

        values = gdf.loc[
            gdf["bundesland"] == bundesland,
            parameter
        ].dropna()

        states.append({

            "bundesland": bundesland,

            "min": (
                values.min()
                if not values.empty
                else None
            ),

            "mean": (
                values.mean()
                if not values.empty
                else None
            ),

            "max": (
                values.max()
                if not values.empty
                else None
            )

        })

    return pd.DataFrame(states)


def calculate_germany_extremes(
    gdf,
    parameter
):

    values = gdf[parameter].dropna()

    return {

        "min": (
            values.min()
            if not values.empty
            else None
        ),

        "mean": (
            values.mean()
            if not values.empty
            else None
        ),

        "max": (
            values.max()
            if not values.empty
            else None
        )

    }


# ============================================================
# BESCHRIFTUNGS-POSITIONEN
# ============================================================

def calculate_label_positions(
    ax,
    gdf,
    column,
    min_distance=25,
    iterations=8
):

    valid = gdf[
        gdf[column].notna()
    ].copy()

    if valid.empty:

        return {}

    xy = ax.transData.transform(
        valid.geometry.apply(
            lambda p: (
                p.x,
                p.y
            )
        ).tolist()
    )

    positions = xy.copy()

    count = len(
        positions
    )

    for _ in range(
        iterations
    ):

        moved = False

        for i in range(
            count
        ):

            xi, yi = positions[i]

            for j in range(
                i + 1,
                count
            ):

                xj, yj = positions[j]

                dx = xi - xj
                dy = yi - yj

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
                    distance_sq
                    ** 0.5
                )

                push = (
                    min_distance
                    - distance
                ) * 0.55

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

            xi, yi = positions[i]

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

        x, y = inverse.transform(
            position
        )

        result[index] = (
            x,
            y
        )

    return result


# ============================================================
# BUNDESLAND-LISTE
# ============================================================

def draw_state_summary(
    ax,
    state_df,
    germany_extremes,
    parameter,
    created_at,
    data_until
):

    ax.axis("off")

    accent = "#a50026"

    ax.text(
        0.0, 0.995,
        "Datenstand",
        transform=ax.transAxes,
        fontsize=11,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        0.0, 0.963,
        "Daten bis",
        transform=ax.transAxes,
        fontsize=10.5,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0, 0.963,
        data_until.strftime("%d.%m.%Y %H:%M") + " Uhr",
        transform=ax.transAxes,
        fontsize=10.5,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.text(
        0.0, 0.925,
        "Erstellt am",
        transform=ax.transAxes,
        fontsize=10.5,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0, 0.925,
        created_at.strftime("%d.%m.%Y %H:%M:%S") + " Uhr",
        transform=ax.transAxes,
        fontsize=10.5,
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
        0.0, 0.845,
        "Bundesland",
        transform=ax.transAxes,
        fontsize=11,
        fontweight="bold",
        va="top",
        color="#333333"
    )

    columns = [
        (0.68, "MAX"),
        (0.84, "Ø"),
        (0.98, "MIN")
    ]

    for x, label in columns:
        ax.text(
            x, 0.845,
            label,
            transform=ax.transAxes,
            fontsize=10.5,
            fontweight="bold",
            ha="center",
            va="top",
            color=accent
        )

    ax.plot(
        [0.0, 1.0],
        [0.805, 0.805],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    y = 0.775
    line_height = 0.0415

    for _, row in state_df.iterrows():

        ax.text(
            0.0,
            y,
            row["bundesland"],
            transform=ax.transAxes,
            fontsize=10.5,
            va="center",
            color="#333333"
        )

        values = [
            row["max"],
            row["mean"],
            row["min"]
        ]

        for (x, _), value in zip(columns, values):
            text = (
                format_temperature(value)
                if pd.notna(value)
                else "–"
            )

            ax.text(
                x,
                y,
                text,
                transform=ax.transAxes,
                fontsize=10.5,
                ha="center",
                va="center",
                color="#333333"
            )

        y -= line_height

    y -= 0.012

    ax.plot(
        [0.0, 1.0],
        [y + 0.021, y + 0.021],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    ax.text(
        0.0,
        y,
        "Deutschland",
        transform=ax.transAxes,
        fontsize=10.5,
        fontweight="bold",
        va="center",
        color="#222222"
    )

    values = [
        germany_extremes["max"],
        germany_extremes["mean"],
        germany_extremes["min"]
    ]

    for (x, _), value in zip(columns, values):
        text = (
            format_temperature(value)
            if pd.notna(value)
            else "–"
        )

        ax.text(
            x,
            y,
            text,
            transform=ax.transAxes,
            fontsize=10.5,
            fontweight="bold",
            ha="center",
            va="center",
            color=accent
        )


# ============================================================
# KARTE
# ============================================================

def plot_map(
    germany,
    gdf,
    state_df,
    germany_extremes,
    parameter,
    target_date,
    title,
    output_file,
    created_at,
    data_until
):

    log(
        f"      Erstelle {output_file} ..."
    )

    column = {
        "TXK": "txk",
        "TNK": "tnk",
        "TTT": "TTT",
        "SunD1": "SunD1",
        "RR1c": "RR1c",
        "FX1": "FX1"
    }[parameter]

    cmap = get_parameter_cmap(parameter)
    norm = get_parameter_norm(parameter)

    fig = plt.figure(
        figsize=(15, 14),
        facecolor="white"
    )

    gs = fig.add_gridspec(
        2,
        2,
        height_ratios=[12, 1.25],
        width_ratios=[4.7, 2.25],
        hspace=0.06,
        wspace=0.005
    )

    ax = fig.add_subplot(gs[0, 0])
    summary_ax = fig.add_subplot(gs[0, 1])
    legend_ax = fig.add_subplot(gs[1, :])

    germany.plot(
        ax=ax,
        color="#e2e2e2",
        edgecolor="#555555",
        linewidth=0.55,
        zorder=1
    )

    xmin, ymin, xmax, ymax = germany.total_bounds

    padx = (xmax - xmin) * 0.025
    pady = (ymax - ymin) * 0.025

    ax.set_xlim(
        xmin - padx,
        xmax + padx
    )

    ax.set_ylim(
        ymin - pady,
        ymax + pady
    )

    ax.set_xlabel(
        "Längengrad (°)",
        fontsize=11,
        color="#555555",
        labelpad=5
    )

    ax.set_ylabel(
        "Breitengrad (°)",
        fontsize=11,
        color="#555555",
        labelpad=5
    )

    ax.tick_params(
        axis="both",
        labelsize=10,
        colors="#555555"
    )

    interpolation = interpolate(
        germany=germany,
        gdf=gdf,
        parameter=column,
        resolution_x=400,
        resolution_y=500,
        neighbors=8,
        power=2.0
    )

    if interpolation is not None:

        grid_x, grid_y, interpolated_values = interpolation

        ax.pcolormesh(
            grid_x,
            grid_y,
            interpolated_values,
            cmap=cmap,
            norm=norm,
            shading="auto",
            alpha=0.96,
            zorder=2
        )

        germany.boundary.plot(
            ax=ax,
            color="#555555",
            linewidth=0.55,
            zorder=4
        )

    valid = gdf[
        gdf[column].notna()
    ].copy()

    label_positions = calculate_label_positions(
        ax,
        valid,
        column,
        min_distance=24,
        iterations=7
    )

    for index, row in valid.iterrows():

        value = row[column]

        if index in label_positions:
            text_x, text_y = label_positions[index]
        else:
            text_x = row.geometry.x
            text_y = row.geometry.y

        ax.text(
            text_x,
            text_y,
            format_temperature(value),
            fontsize=10,
            fontfamily="DejaVu Sans",
            fontweight="bold",
            ha="center",
            va="center",
            color="#000000",
            zorder=10
        )

    date_string = target_date.strftime("%d.%m.%Y")

    ax.set_title(
        f"{title}\n{date_string}",
        fontsize=18,
        fontweight="bold",
        pad=4
    )

    draw_state_summary(
        summary_ax,
        state_df,
        germany_extremes,
        parameter,
        created_at,
        data_until
    )

    draw_parameter_legend(
        legend_ax,
        parameter
    )

    fig.subplots_adjust(
        left=0.02,
        right=0.97,
        top=0.96,
        bottom=0.025
    )

    fig.savefig(
        output_file,
        dpi=65,
        facecolor="white",
        edgecolor="none",
        format="png"
    )

    plt.close(fig)

    log(
        f"      Fertig: {output_file}"
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("DWD EXTREMWERTE – NOW")
    log("=" * 70)
    log("")

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # ========================================================
    # 1. STATIONSLISTE
    # ========================================================

    station_list = (
        load_station_list()
    )

    # ========================================================
    # 2. AKTUELLES DATUM
    # ========================================================

    target_date = (
        pd.Timestamp.now(
            tz="UTC"
        ).date()
    )

    log(
        "Auswertungstag: "
        + target_date.strftime(
            "%d.%m.%Y"
        )
    )

    # ========================================================
    # 3. NOW-DATEIEN
    # ========================================================

    files = get_now_files()

    # ========================================================
    # 4. KOORDINATEN
    # ========================================================

    station_meta = (
        load_station_meta(
            files.keys()
        )
    )

    # ========================================================
    # 5. AKTUELLE DATEN
    # ========================================================

    results, data_until = process_all(
        files,
        target_date
    )

    # ========================================================
    # ZEITPUNKT DER KARTENERSTELLUNG
    # ========================================================

    created_at = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).to_pydatetime().replace(
        tzinfo=None
    )

    # ========================================================
    # 6. GEODATEN
    # ========================================================

    log(
        "[5/8] Erstelle Geodaten ..."
    )

    gdf = create_geodata(
        results,
        station_meta,
        station_list
    )

    log(
        f"      {len(gdf)} Stationen "
        "mit Koordinaten und CSV-Zuordnung."
    )

    # ========================================================
    # SHAPEFILE EINMALIG LADEN
    # ========================================================

    log(
        "[6/8] Lade Deutschland-Geometrie ..."
    )

    germany = gpd.read_file(
        SHAPEFILE
    )

    log(
        "      Deutschland-Geometrie geladen."
    )

    # ========================================================
    # 7. KARTEN
    # ========================================================

    log(
        "[7/8] Erstelle Karten ..."
    )

    for parameter, title, output_file in [
        (
            "TXK",
            "Höchsttemperatur (°C)",
            TXK_OUTPUT
        ),
        (
            "TNK",
            "Tiefsttemperatur (°C)",
            TNK_OUTPUT
        )
    ]:

        state_df = calculate_state_extremes(
            gdf,
            parameter.lower()
        )

        germany_extremes = calculate_germany_extremes(
            gdf,
            parameter.lower()
        )

        plot_map(
            germany=germany,
            gdf=gdf,
            state_df=state_df,
            germany_extremes=germany_extremes,
            parameter=parameter,
            target_date=target_date,
            title=title,
            output_file=output_file,
            created_at=created_at,
            data_until=data_until
        )

    # ========================================================
    # 7b. WEITERE MESSPARAMETER
    # ========================================================

    for parameter in ("TTT", "SunD1", "RR1c", "FX1"):

        log("")
        log("-" * 60)
        log(f"Verarbeite zusätzlichen Parameter: {parameter}")

        parameter_files = get_parameter_now_files(
            parameter,
            station_list["station_id"]
        )

        missing_meta = set(
            station_list["station_id"]
        ) - set(station_meta)

        if missing_meta:
            station_meta.update(
                load_station_meta(missing_meta)
            )

        parameter_results, parameter_data_until = process_parameter_all(
            parameter,
            parameter_files,
            target_date
        )

        values_by_station = {
            result["station_id"]: result["value"]
            for result in parameter_results
        }

        parameter_gdf = station_list.copy()
        parameter_gdf[parameter] = parameter_gdf["station_id"].map(
            values_by_station
        )
        parameter_gdf["lat"] = parameter_gdf["station_id"].map(
            lambda station_id: station_meta.get(station_id, {}).get("lat")
        )
        parameter_gdf["lon"] = parameter_gdf["station_id"].map(
            lambda station_id: station_meta.get(station_id, {}).get("lon")
        )
        parameter_gdf = parameter_gdf.dropna(
            subset=[parameter, "lat", "lon"]
        ).copy()

        if parameter_gdf.empty:
            raise RuntimeError(
                f"Keine Stationen mit Messwerten und Geodaten für {parameter} vorhanden."
            )

        parameter_gdf = gpd.GeoDataFrame(
            parameter_gdf,
            geometry=gpd.points_from_xy(
                parameter_gdf["lon"],
                parameter_gdf["lat"]
            ),
            crs="EPSG:4326"
        )

        state_df = calculate_state_extremes(
            parameter_gdf,
            parameter
        )

        germany_extremes = calculate_germany_extremes(
            parameter_gdf,
            parameter
        )

        config = PARAMETER_DATASETS[parameter]
        output_file = os.path.join(
            OUTPUT_DIR,
            f"extrema_{config['filename']}.png"
        )

        plot_map(
            germany=germany,
            gdf=parameter_gdf,
            state_df=state_df,
            germany_extremes=germany_extremes,
            parameter=parameter,
            target_date=target_date,
            title=config["title"],
            output_file=output_file,
            created_at=created_at,
            data_until=parameter_data_until
        )

    # ========================================================
    # 8. FERTIG
    # ========================================================

    log("")
    log("=" * 70)
    log("FERTIG")
    log("=" * 70)

    log(
        f"Stationen: {len(gdf)}"
    )

    log(
        "Daten bis: "
        + data_until.strftime(
            "%d.%m.%Y %H:%M"
        )
        + " Uhr"
    )

    log(
        "Erstellt am: "
        + created_at.strftime(
            "%d.%m.%Y %H:%M:%S"
        )
        + " Uhr"
    )

    log(
        f"TXK-Karte: {TXK_OUTPUT}"
    )

    log(
        f"TNK-Karte: {TNK_OUTPUT}"
    )

    for parameter in ("TTT", "SunD1", "RR1c", "FX1"):
        filename = PARAMETER_DATASETS[parameter]["filename"]
        log(
            f"{parameter}-Karte: "
            + os.path.join(OUTPUT_DIR, f"extrema_{filename}.png")
        )

    log("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
