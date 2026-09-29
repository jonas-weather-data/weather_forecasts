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
    "extreme_temperature/now/"
)

STATIONS_URL = (
    "https://opendata.dwd.de/climate_environment/CDC/"
    "observations_germany/climate/daily/kl/historical/"
    "KL_Tageswerte_Beschreibung_Stationen.txt"
)

SHAPEFILE = "gadm41_DEU_1.json"

STATION_LIST = "stationen_extreme.csv"

OUTPUT_DIR = "output"

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

                # DWD liefert den Zeitstempel in UTC.
                # Für die Tagesauswertung in Deutschland
                # wird er zunächst in Europe/Berlin umgerechnet.

                mess_datum = (
                    mess_datum
                    .tz_convert("Europe/Berlin")
                )

                if (
                    mess_datum.date()
                    != target_date
                ):

                    continue

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
        + "°"
    )


# ============================================================
# TEXTFARBE
# ============================================================

def txk_text_color(value):

    if value >= 35:

        return "#7f0000"

    if value >= 30:

        return "#a50026"

    if value >= 25:

        return "#c63d17"

    if value >= 20:

        return "#8c2d04"

    return "#333333"


def tnk_text_color(value):

    if value <= -10:

        return "#08306b"

    if value <= -5:

        return "#08519c"

    if value <= 0:

        return "#2171b5"

    if value <= 5:

        return "#225ea8"

    return "#333333"


# ============================================================
# BUNDESLAND-EXTREME
# ============================================================

def calculate_state_extremes(
    gdf
):

    valid_tx = gdf[
        gdf["txk"].notna()
    ].copy()

    valid_tn = gdf[
        gdf["tnk"].notna()
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

        tx = valid_tx[
            valid_tx["bundesland"]
            == bundesland
        ]

        tn = valid_tn[
            valid_tn["bundesland"]
            == bundesland
        ]

        states.append({

            "bundesland":
                bundesland,

            "txk_min": (
                tx["txk"].min()
                if not tx.empty
                else None
            ),

            "txk_max": (
                tx["txk"].max()
                if not tx.empty
                else None
            ),

            "tnk_min": (
                tn["tnk"].min()
                if not tn.empty
                else None
            ),

            "tnk_max": (
                tn["tnk"].max()
                if not tn.empty
                else None
            )
        })

    return pd.DataFrame(
        states
    )


# ============================================================
# DEUTSCHLAND-GESAMTWERTE
# ============================================================

def calculate_germany_extremes(
    gdf
):

    valid_tx = gdf[
        gdf["txk"].notna()
    ]

    valid_tn = gdf[
        gdf["tnk"].notna()
    ]

    return {

        "txk_min": (
            valid_tx["txk"].min()
            if not valid_tx.empty
            else None
        ),

        "txk_max": (
            valid_tx["txk"].max()
            if not valid_tx.empty
            else None
        ),

        "tnk_min": (
            valid_tn["tnk"].min()
            if not valid_tn.empty
            else None
        ),

        "tnk_max": (
            valid_tn["tnk"].max()
            if not valid_tn.empty
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

    if parameter == "TXK":

        value_columns = [
            ("TXK ↑", "txk_max"),
            ("TXK ↓", "txk_min")
        ]

        accent = "#a50026"

        germany_values = (
            germany_extremes["txk_max"],
            germany_extremes["txk_min"]
        )

    else:

        value_columns = [
            ("TNK ↑", "tnk_max"),
            ("TNK ↓", "tnk_min")
        ]

        accent = "#225ea8"

        germany_values = (
            germany_extremes["tnk_max"],
            germany_extremes["tnk_min"]
        )

    # ========================================================
    # INFORMATIONSBLOCK OBEN
    # ========================================================

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
        fontsize=9.0,
        fontweight="bold",
        va="top",
        color="#333333"
    )

    ax.text(
        0.68,
        0.845,
        value_columns[0][0],
        transform=ax.transAxes,
        fontsize=9.0,
        fontweight="bold",
        ha="center",
        va="top",
        color=accent
    )

    ax.text(
        0.91,
        0.845,
        value_columns[1][0],
        transform=ax.transAxes,
        fontsize=9.0,
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

        for x, (_, column) in zip(
            (0.68, 0.91),
            value_columns
        ):

            value = row[column]

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

    for x, value in zip(
        (0.68, 0.91),
        germany_values
    ):

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
            fontsize=8.2,
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

    if parameter == "TXK":

        column = "txk"
        color_function = txk_text_color

    else:

        column = "tnk"
        color_function = tnk_text_color

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

    label_positions = (
        calculate_label_positions(
            ax,
            valid,
            column,
            min_distance=24,
            iterations=7
        )
    )

    # ========================================================
    # BESCHRIFTUNGEN
    # ========================================================

    for index, row in valid.iterrows():

        value = row[column]

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
            format_temperature(
                value
            ),
            fontsize=8.0,
            fontweight="bold",
            ha="center",
            va="center",
            color=color_function(
                value
            ),
            zorder=10,
            bbox={
                "boxstyle":
                    "round,pad=0.13",
                "facecolor":
                    "white",
                "edgecolor":
                    "none",
                "alpha":
                    0.78
            }
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
        fontsize=18,
        fontweight="bold",
        pad=14
    )

    ax.set_xticks([])
    ax.set_yticks([])
    ax.axis("off")

    # ========================================================
    # ZUSAMMENFASSUNG
    # ========================================================

    draw_state_summary(
        summary_ax,
        state_df,
        germany_extremes,
        parameter,
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
    # BUNDESLAND-EXTREME
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
    # 7. KARTEN
    # ========================================================

    log(
        "[7/8] Erstelle Karten ..."
    )

    plot_map(
        germany=germany,
        gdf=gdf,
        state_df=state_df,
        germany_extremes=germany_extremes,
        parameter="TXK",
        target_date=target_date,
        title="Höchste Temperatur (TXK)",
        output_file=TXK_OUTPUT,
        created_at=created_at,
        data_until=data_until
    )

    plot_map(
        germany=germany,
        gdf=gdf,
        state_df=state_df,
        germany_extremes=germany_extremes,
        parameter="TNK",
        target_date=target_date,
        title="Niedrigste Temperatur (TNK)",
        output_file=TNK_OUTPUT,
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
        f"TXK-Karte: {TXK_OUTPUT}"
    )

    log(
        f"TNK-Karte: {TNK_OUTPUT}"
    )

    log("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
