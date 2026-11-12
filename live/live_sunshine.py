import os
import re
import zipfile
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt


# ============================================================
# KONFIGURATION
# ============================================================

NOW_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "solar/now/"
)

STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/10_minutes/"
    "solar/historical/"
    "zehn_min_sd_Beschreibung_Stationen.txt"
)

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

SHAPEFILE = os.path.join(
    BASE_DIR,
    "gadm41_DEU_1.json"
)

STATION_LIST = os.path.join(
    BASE_DIR,
    "stationen_sunshine.csv"
)

OUTPUT_DIR = os.path.join(
    BASE_DIR,
    "output"
)

SUNSHINE_OUTPUT = os.path.join(
    OUTPUT_DIR,
    "sonnenscheindauer.png"
)

MAX_WORKERS = 16
REQUEST_TIMEOUT = 120

# Faktor für das gerasterte Deutschlandmittel
GRID_FACTOR = 0.9897


# ============================================================
# HTTP
# ============================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "DWD-Sonnenschein-Karte/1.0"
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
        "[1/8] Lade stationen_sunshine.csv ..."
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
        str(column)
        .strip()
        .lower()
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
            "Fehlende Spalten in stationen_sunshine.csv: "
            + ", ".join(
                sorted(missing)
            )
            + "\nGefundene Spalten: "
            + ", ".join(
                df.columns
            )
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
# DWD-SOLAR-NOW-DATEIEN
# ============================================================

def get_now_files():

    log(
        "[2/8] Lade DWD-Solar-now-Dateiliste ..."
    )

    response = get(
        NOW_URL
    )

    matches = re.findall(
        r'href="(10minutenwerte_SOLAR_(\d{5})_now\.zip)"',
        response.text,
        flags=re.IGNORECASE
    )

    files = {}

    for filename, station_id in matches:

        files[station_id] = filename

    if not files:

        raise RuntimeError(
            "Keine DWD-Solar-now-Dateien gefunden."
        )

    log(
        f"      {len(files)} Stationsdateien gefunden."
    )

    return files


# ============================================================
# STATIONSKOORDINATEN
# ============================================================

def load_station_meta(
    station_ids
):

    log(
        "[3/8] Lade DWD-Stationskoordinaten ..."
    )

    station_ids = set(
        station_ids
    )

    response = get(
        STATIONS_URL
    )

    txt = response.content.decode(
        "cp1252",
        errors="replace"
    )

    lines = (
        txt
        .replace(
            "\r\n",
            "\n"
        )
        .split("\n")
    )

    header_index = None

    for i, line in enumerate(
        lines
    ):

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
            + ", ".join(
                sorted(missing)
            )
        )

    log(
        f"      {len(result)} von "
        f"{len(station_ids)} Stationen gefunden."
    )

    return result


# ============================================================
# DEZIMALWERT
# ============================================================

def parse_nullable_decimal(
    value
):

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

        number = float(
            value
        )

    except ValueError:

        return None

    # DWD Missing Value
    if number <= -999:

        return None

    return number


# ============================================================
# EINZELNE SOLAR-NOW-DATEI
#
# DWD-Solar-Datensatz:
#
# fields[0] = STATIONS_ID
# fields[1] = MESS_DATUM
# fields[2] = QN
# fields[3] = DS_10
# fields[4] = GS_10
# fields[5] = SD_10
# fields[6] = LS_10
#
# SD_10 = Sonnenscheindauer der vorherigen 10 Minuten
# Einheit: Stunden
#
# Für den Tageswert werden alle SD_10-Werte addiert.
# ============================================================

def process_station(
    station_id,
    filename,
    target_date
):

    url = (
        NOW_URL
        + filename
    )

    response = get(
        url
    )

    with zipfile.ZipFile(
        BytesIO(
            response.content
        )
    ) as archive:

        entry = next(
            (
                e
                for e in archive.infolist()
                if (
                    e.filename
                    .lower()
                    .endswith(".txt")
                    and os.path.basename(
                        e.filename
                    )
                    .lower()
                    .startswith(
                        "produkt_zehn_min_"
                    )
                )
            ),
            None
        )

        # Falls der Dateiname anders aufgebaut ist,
        # alternativ die erste TXT-Datei verwenden.
        if entry is None:

            entry = next(
                (
                    e
                    for e in archive.infolist()
                    if e.filename
                    .lower()
                    .endswith(".txt")
                ),
                None
            )

        if entry is None:

            raise RuntimeError(
                "Keine TXT-Datei im Solar-ZIP gefunden."
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

                if line.startswith(
                    "STATIONS_ID"
                ):

                    continue

                raw_fields = (
                    line.split(";")
                )

                if len(raw_fields) < 6:

                    continue

                if (
                    raw_fields[-1]
                    .strip()
                    .lower()
                    == "eor"
                ):

                    raw_fields = (
                        raw_fields[:-1]
                    )

                fields = [
                    field.strip()
                    for field in raw_fields
                ]

                if len(fields) < 6:

                    continue

                # ------------------------------------------------
                # Zeitstempel
                # ------------------------------------------------

                date_string = (
                    fields[1]
                )

                mess_datum = None

                for date_format in (
                    "%Y%m%d%H%M",
                    "%Y%m%d%H"
                ):

                    try:

                        mess_datum = (
                            pd.to_datetime(
                                date_string,
                                format=date_format,
                                utc=True
                            )
                        )

                        break

                    except ValueError:

                        pass

                if mess_datum is None:

                    continue

                # ------------------------------------------------
                # UTC -> Europe/Berlin
                # ------------------------------------------------

                mess_datum = (
                    mess_datum
                    .tz_convert(
                        "Europe/Berlin"
                    )
                )

                if (
                    mess_datum.date()
                    != target_date
                ):

                    continue

                # ------------------------------------------------
                # SD_10
                #
                # fields[5] = Sonnenscheindauer
                # der vorherigen 10 Minuten in Stunden.
                # ------------------------------------------------

                sd10 = (
                    parse_nullable_decimal(
                        fields[5]
                    )
                )

                if sd10 is None:

                    raise RuntimeError(
                        "Messlücke bei SD_10"
                    )

                rows.append(
                    (
                        mess_datum,
                        sd10
                    )
                )

    if not rows:

        raise RuntimeError(
            f"Keine Sonnenscheindaten für "
            f"{target_date}."
        )

    # ========================================================
    # CHRONOLOGISCH SORTIEREN
    # ========================================================

    rows.sort(
        key=lambda row: row[0]
    )

    timestamps = [
        row[0]
        for row in rows
    ]

    # ========================================================
    # 10-MINUTEN-RASTER PRÜFEN
    # ========================================================

    for previous, current in zip(
        timestamps,
        timestamps[1:]
    ):

        difference = (
            current
            - previous
        )

        if difference != pd.Timedelta(
            minutes=10
        ):

            raise RuntimeError(
                "Messlücke im "
                "10-Minuten-Raster"
            )

    # ========================================================
    # SONNENSCHEIN SUMMIEREN
    #
    # SD_10 ist bereits in Stunden.
    # ========================================================

    sunshine_values = [
        sd
        for _, sd in rows
    ]

    if not sunshine_values:

        raise RuntimeError(
            "Keine gültigen SD_10-Werte."
        )

    sunshine_hours = sum(
        sunshine_values
    )

    # ========================================================
    # TATSÄCHLICH LETZTER MESSZEITPUNKT
    # ========================================================

    data_until = (
        timestamps[-1]
    )

    return {
        "station_id": station_id,
        "date": target_date,
        "sunshine_hours": sunshine_hours,
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
        "[4/8] Verarbeite aktuelle DWD-Sonnenscheindaten ..."
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

                result = (
                    future.result()
                )

                if (
                    result[
                        "sunshine_hours"
                    ] is not None
                    and result[
                        "data_until"
                    ] is not None
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
        key=lambda x:
            x["station_id"]
    )

    # ========================================================
    # GLOBALER DATENSTAND
    # ========================================================

    data_until_values = [
        result["data_until"]
        for result in results
        if result["data_until"]
        is not None
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
        "      Stationen mit diesem Datenstand: "
        f"{matching_count}/{len(results)}"
    )

    return (
        results,
        data_until
    )


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
        .set_index(
            "station_id"
        )
        .to_dict(
            "index"
        )
    )

    for result in results:

        station_id = (
            result["station_id"]
        )

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

            "station_id":
                station_id,

            "name":
                info["name"],

            "bundesland":
                info["bundesland"],

            "sunshine_hours":
                result[
                    "sunshine_hours"
                ],

            "lat":
                meta["lat"],

            "lon":
                meta["lon"]
        })

    if not rows:

        raise RuntimeError(
            "Keine Stationen mit Koordinaten "
            "und CSV-Zuordnung."
        )

    df = pd.DataFrame(
        rows
    )

    geometry = (
        gpd.points_from_xy(
            df["lon"],
            df["lat"]
        )
    )

    return gpd.GeoDataFrame(
        df,
        geometry=geometry,
        crs="EPSG:4326"
    )


# ============================================================
# SONNENSCHEIN FORMATIEREN
# ============================================================

def format_sunshine(
    value
):

    return (
        f"{value:.1f}"
        .replace(
            ".",
            ","
        )
    )


# ============================================================
# TEXTFARBE
# ============================================================

def sunshine_text_color(
    value
):

    if value >= 12:

        return "#b35806"

    if value >= 10:

        return "#d6604d"

    if value >= 8:

        return "#e08214"

    if value >= 6:

        return "#8073ac"

    if value >= 4:

        return "#542788"

    return "#333333"


# ============================================================
# BUNDESLAND-EXTREME
#
# Nur MIN und MAX.
# KEIN Bundesland-Mittel.
# ============================================================

def calculate_state_extremes(
    gdf
):

    valid = gdf[
        gdf["sunshine_hours"]
        .notna()
    ].copy()

    states = []

    bundeslaender = sorted(
        gdf[
            "bundesland"
        ]
        .dropna()
        .unique()
    )

    for bundesland in bundeslaender:

        state = valid[
            valid["bundesland"]
            == bundesland
        ]

        states.append({

            "bundesland":
                bundesland,

            "sunshine_min": (
                state[
                    "sunshine_hours"
                ].min()
                if not state.empty
                else None
            ),

            "sunshine_max": (
                state[
                    "sunshine_hours"
                ].max()
                if not state.empty
                else None
            )
        })

    return pd.DataFrame(
        states
    )


# ============================================================
# DEUTSCHLAND-GESAMTWERTE
#
# Zusätzlich zum Minimum/Maximum:
#
# - Reines Mittel
# - Gerastertes Mittel
#
# Gerastertes Mittel =
# Reines Mittel * 0.9897
# ============================================================

def calculate_germany_extremes(
    gdf
):

    valid = gdf[
        gdf["sunshine_hours"]
        .notna()
    ]

    if valid.empty:

        return {

            "sunshine_min":
                None,

            "sunshine_max":
                None,

            "sunshine_mean":
                None,

            "sunshine_grid_mean":
                None
        }

    sunshine_values = (
        valid[
            "sunshine_hours"
        ]
    )

    pure_mean = (
        sunshine_values.mean()
    )

    grid_mean = (
        pure_mean
        * GRID_FACTOR
    )

    return {

        "sunshine_min":
            sunshine_values.min(),

        "sunshine_max":
            sunshine_values.max(),

        "sunshine_mean":
            pure_mean,

        "sunshine_grid_mean":
            grid_mean
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
    created_at,
    data_until
):

    ax.axis(
        "off"
    )

    # ========================================================
    # INFORMATIONSBLOCK OBEN
    # ========================================================

    ax.text(
        0.0,
        0.995,
        "Datenstand",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        0.0,
        0.963,
        "Daten bis",
        transform=ax.transAxes,
        fontsize=10.0,
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
        fontsize=10.0,
        ha="right",
        va="top",
        color="#333333"
    )

    ax.text(
        0.0,
        0.925,
        "Erstellt am",
        transform=ax.transAxes,
        fontsize=10.0,
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
        fontsize=10.0,
        ha="right",
        va="top",
        color="#333333"
    )

    # ========================================================
    # TRENNLINIE
    # ========================================================

    ax.plot(
        [0.0, 1.0],
        [0.875, 0.875],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    # ========================================================
    # HEADER
    # ========================================================

    ax.text(
        0.0,
        0.845,
        "Bundesland",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        va="top",
        color="#333333"
    )

    ax.text(
        0.68,
        0.845,
        "max.",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        ha="center",
        va="top",
        color="#a50026"
    )

    ax.text(
        0.91,
        0.845,
        "min.",
        transform=ax.transAxes,
        fontsize=10.0,
        fontweight="bold",
        ha="center",
        va="top",
        color="#542788"
    )

    ax.plot(
        [0.0, 1.0],
        [0.805, 0.805],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    # ========================================================
    # BUNDESLÄNDER
    # ========================================================

    y = 0.775

    line_height = 0.0415

    for _, row in state_df.iterrows():

        ax.text(
            0.0,
            y,
            row["bundesland"],
            transform=ax.transAxes,
            fontsize=7.9,
            fontweight="normal",
            va="center",
            color="#333333"
        )

        max_value = row[
            "sunshine_max"
        ]

        min_value = row[
            "sunshine_min"
        ]

        max_text = (
            format_sunshine(
                max_value
            )
            if pd.notna(
                max_value
            )
            else "–"
        )

        min_text = (
            format_sunshine(
                min_value
            )
            if pd.notna(
                min_value
            )
            else "–"
        )

        ax.text(
            0.68,
            y,
            max_text,
            transform=ax.transAxes,
            fontsize=7.9,
            ha="center",
            va="center",
            color="#333333"
        )

        ax.text(
            0.91,
            y,
            min_text,
            transform=ax.transAxes,
            fontsize=7.9,
            ha="center",
            va="center",
            color="#333333"
        )

        y -= line_height

    # ========================================================
    # DEUTSCHLAND
    # ========================================================

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
        fontsize=8.2,
        fontweight="bold",
        va="center",
        color="#222222"
    )

    # --------------------------------------------------------
    # Deutschland: Maximum
    # --------------------------------------------------------

    germany_max = (
        germany_extremes[
            "sunshine_max"
        ]
    )

    ax.text(
        0.68,
        y,
        (
            format_sunshine(
                germany_max
            )
            if pd.notna(
                germany_max
            )
            else "–"
        ),
        transform=ax.transAxes,
        fontsize=8.2,
        fontweight="bold",
        ha="center",
        va="center",
        color="#a50026"
    )

    # --------------------------------------------------------
    # Deutschland: Minimum
    # --------------------------------------------------------

    germany_min = (
        germany_extremes[
            "sunshine_min"
        ]
    )

    ax.text(
        0.91,
        y,
        (
            format_sunshine(
                germany_min
            )
            if pd.notna(
                germany_min
            )
            else "–"
        ),
        transform=ax.transAxes,
        fontsize=8.2,
        fontweight="bold",
        ha="center",
        va="center",
        color="#542788"
    )

    # ========================================================
    # DEUTSCHLAND-MITTEL
    # ========================================================

    y -= 0.055

    ax.text(
        0.0,
        y,
        "Reines Mittel",
        transform=ax.transAxes,
        fontsize=8.0,
        fontweight="bold",
        va="center",
        color="#333333"
    )

    pure_mean = (
        germany_extremes[
            "sunshine_mean"
        ]
    )

    ax.text(
        0.91,
        y,
        (
            format_sunshine(
                pure_mean
            )
            if pd.notna(
                pure_mean
            )
            else "–"
        ),
        transform=ax.transAxes,
        fontsize=8.0,
        fontweight="bold",
        ha="center",
        va="center",
        color="#333333"
    )

    y -= 0.0415

    ax.text(
        0.0,
        y,
        "Gerastertes Mittel",
        transform=ax.transAxes,
        fontsize=8.0,
        fontweight="bold",
        va="center",
        color="#333333"
    )

    grid_mean = (
        germany_extremes[
            "sunshine_grid_mean"
        ]
    )

    ax.text(
        0.91,
        y,
        (
            format_sunshine(
                grid_mean
            )
            if pd.notna(
                grid_mean
            )
            else "–"
        ),
        transform=ax.transAxes,
        fontsize=8.0,
        fontweight="bold",
        ha="center",
        va="center",
        color="#333333"
    )


# ============================================================
# KARTE
# ============================================================

def plot_map(
    germany,
    gdf,
    state_df,
    germany_extremes,
    target_date,
    title,
    output_file,
    created_at,
    data_until
):

    log(
        f"      Erstelle {output_file} ..."
    )

    column = (
        "sunshine_hours"
    )

    # ========================================================
    # FIGURE
    # ========================================================

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

    # ========================================================
    # DEUTSCHLAND
    # ========================================================

    germany.plot(
        ax=ax,
        color="#eeeeee",
        edgecolor="#555555",
        linewidth=0.55
    )

    # ========================================================
    # ACHSENBEREICH
    # ========================================================

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

    # ========================================================
    # STATIONEN
    # ========================================================

    valid = gdf[
        gdf[column].notna()
    ].copy()

    # Durch die deutlich geringere Anzahl an
    # Sonnenscheinstationen können die Labels
    # größer dargestellt werden.
    label_positions = (
        calculate_label_positions(
            ax,
            valid,
            column,
            min_distance=34,
            iterations=8
        )
    )

    # ========================================================
    # BESCHRIFTUNGEN
    #
    # KEINE weiße Box.
    # Die Zahlen werden direkt auf die Karte gesetzt.
    # ========================================================

    for index, row in valid.iterrows():

        value = row[
            column
        ]

        if index in label_positions:

            text_x, text_y = (
                label_positions[
                    index
                ]
            )

        else:

            text_x = row.geometry.x
            text_y = row.geometry.y

        ax.text(
            text_x,
            text_y,
            format_sunshine(
                value
            ),
            fontsize=16.0,
            fontweight="bold",
            ha="center",
            va="center",
            color=sunshine_text_color(
                value
            ),
            zorder=10
        )

    # ========================================================
    # TITEL
    # ========================================================

    date_string = (
        target_date.strftime(
            "%d.%m.%Y"
        )
    )

    ax.set_title(
        f"{title}\n{date_string}",
        fontsize=20,
        fontweight="bold",
        pad=14
    )

    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis(
        "off"
    )

    # ========================================================
    # ZUSAMMENFASSUNG
    # ========================================================

    draw_state_summary(
        summary_ax,
        state_df,
        germany_extremes,
        created_at,
        data_until
    )

    # ========================================================
    # SPEICHERN
    # ========================================================

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

    plt.close(
        fig
    )

    log(
        f"      Fertig: {output_file}"
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("DWD SONNENSCHEINDAUER – NOW")
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
            tz="Europe/Berlin"
        ).date()
    )

    log(
        "Auswertungstag: "
        + target_date.strftime(
            "%d.%m.%Y"
        )
    )

    # ========================================================
    # 3. SOLAR-NOW-DATEIEN
    # ========================================================

    files = (
        get_now_files()
    )

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

    results, data_until = (
        process_all(
            files,
            target_date
        )
    )

    # ========================================================
    # ZEITPUNKT DER KARTENERSTELLUNG
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
    # BUNDESLAND-WERTE
    # ========================================================

    state_df = (
        calculate_state_extremes(
            gdf
        )
    )

    # ========================================================
    # DEUTSCHLAND-GESAMTWERTE
    # ========================================================

    germany_extremes = (
        calculate_germany_extremes(
            gdf
        )
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
    # 7. KARTE
    # ========================================================

    log(
        "[7/8] Erstelle Karte ..."
    )

    plot_map(
        germany=germany,
        gdf=gdf,
        state_df=state_df,
        germany_extremes=germany_extremes,
        target_date=target_date,
        title="Sonnenscheindauer (h)",
        output_file=SUNSHINE_OUTPUT,
        created_at=created_at,
        data_until=data_until
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
        f"Sonnenschein-Karte: "
        f"{SUNSHINE_OUTPUT}"
    )

    log("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
