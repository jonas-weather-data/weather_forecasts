import os
import math
import zipfile
from io import BytesIO
from datetime import timedelta

import numpy as np

from scipy.spatial import cKDTree

from pyproj import Transformer

from shapely.ops import unary_union

from shapely import vectorized

import requests
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

from matplotlib.colors import (
    LinearSegmentedColormap,
    Normalize
)

from xml.etree import ElementTree as ET


# ============================================================
# KONFIGURATION
# ============================================================

MOSMIX_URL = (
    "https://opendata.dwd.de/weather/local_forecasts/"
    "mos/MOSMIX_S/all_stations/kml/"
    "MOSMIX_S_LATEST_240.kmz"
)

# Verzeichnis dieser Python-Datei:
BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

# Hauptverzeichnis des GitHub-Repositories:
REPO_DIR = os.path.dirname(
    os.path.dirname(BASE_DIR)
)

# Eingabedateien bleiben neben main_germany.py:
STATION_FILE = os.path.join(
    BASE_DIR,
    "stationsdaten.csv"
)

SHAPEFILE = os.path.join(
    BASE_DIR,
    "gadm41_DEU_1.json"
)

# Ausgabe direkt im vorgesehenen Repository-Verzeichnis:
OUTPUT_DIR = os.path.join(
    REPO_DIR,
    "mosmix",
    "output",
    "germany"
)

REQUEST_TIMEOUT = 180
FIRST_RUN_MARKER = os.path.join(
    OUTPUT_DIR,
    ".first_run_date"
)


# ============================================================
# PARAMETER-KONFIGURATION
# ============================================================

PARAMETERS = {

    "TX": {
        "name": "Höchsttemperatur (°C)",
        "unit": "",
        "aggregation": "max",
        "window_hours": 12,
        "conversion": "kelvin"
    },

    "TN": {
        "name": "Tiefsttemperatur (°C)",
        "unit": "",
        "aggregation": "min",
        "window_hours": 12,
        "conversion": "kelvin"
    },

    "TTT": {
        "name": "Tagesmitteltemperatur (°C)",
        "unit": "",
        "aggregation": "mean",
        "window_hours": 0,
        "conversion": "kelvin"
    },

    "SunD1": {
        "name": "Sonnenscheindauer (h)",
        "unit": "",
        "aggregation": "sum",
        "window_hours": 1,
        "conversion": "seconds_to_hours"
    },

    "RR1c": {
        "name": "Niederschlagsmenge (mm)",
        "unit": "",
        "aggregation": "sum",
        "window_hours": 1,
        "conversion": "identity"
    },

    "FX1": {
        "name": "Stärkste Windböe (km/h)",
        "unit": "",
        "aggregation": "max",
        "window_hours": 1,
        "conversion": "ms_to_kmh"
    }

}


# ============================================================
# FARBSCHEMATA
# ============================================================

# ============================================================
# SCHRIFTFARBEN – KONTRASTKORREKTUR OHNE KONTUR
# ============================================================

# ============================================================
# SCHRIFTFARBEN – MODERATE KONTRASTKORREKTUR
# ============================================================

# ============================================================
# SCHRIFTFARBEN – KRÄFTIG UND GUT UNTERSCHEIDBAR
# ============================================================

def get_readable_text_color(rgba):

    r, g, b = rgba[:3]

    # RGB in HSV umwandeln
    h, s, v = mcolors.rgb_to_hsv(
        [r, g, b]
    )

    # Farben kräftiger machen
    s = min(1.0, s * 1.35)

    # Helle Farben stärker abdunkeln
    if v > 0.75:
        v = 0.75 + (v - 0.75) * 0.35

    # Sehr blasse Farben vermeiden
    v = max(0.35, v)

    # Zurück in RGB
    return tuple(
        mcolors.hsv_to_rgb([h, s, v])
    )

# ============================================================
# FARBSCHEMATA ALLER PARAMETER
# ============================================================

PLOT_STYLES = {

    # --------------------------------------------------------
    # TAGESHÖCHSTTEMPERATUR – TX
    # Exakt deine bisherige Farbskala
    # --------------------------------------------------------

    "TX": {
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
    # --------------------------------------------------------

    "TN": {
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

    # --------------------------------------------------------
    # SONNENSCHEINDAUER – SunD1
    # Grau -> Gelb -> Orange -> Rot
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NIEDERSCHLAG – RR1c
    # Hellblau -> Dunkelblau -> Violett -> Rosa
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # STÄRKSTE WINDBÖE – FX1
    # Farbverlauf entsprechend der Beaufort-Skala
    # --------------------------------------------------------

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
    }

}


# ============================================================
# PARAMETER-FARBEN
# ============================================================

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

# ============================================================
# SUMMENKARTEN – FARBskalierung
# ============================================================

def get_precipitation_period_max(number_of_days):

    return (
        50.0
        + 50.0 * math.log(number_of_days)
    )


def get_period_norm(parameter, number_of_days):

    if parameter == "SunD1":

        return Normalize(
            vmin=0,
            vmax=16 * number_of_days,
            clip=True
        )

    elif parameter == "RR1c":

        return Normalize(
            vmin=0,
            vmax=get_precipitation_period_max(
                number_of_days
            ),
            clip=True
        )

    raise ValueError(
        f"Keine Summenskalierung für {parameter}"
    )


# ============================================================
# RÄUMLICHE NIEDERSCHLAGSINTERPOLATION
# ============================================================

def interpolate(
    germany,
    gdf,
    parameter,
    norm,
    resolution_x=400,
    resolution_y=500,
    neighbors=8,
    power=2.0
):

    """
    Erzeugt ein flächendeckendes, weich interpoliertes
    Niederschlagsfeld anhand der Stationswerte.

    IDW-Interpolation:
    - 8 nächste Stationen
    - Gewichtung nach Entfernung
    - Exakte Stationswerte an den Stationspositionen
    - Maskierung außerhalb Deutschlands
    """

    # --------------------------------------------------------
    # GÜLTIGE STATIONEN
    # --------------------------------------------------------

    valid = gdf[
        gdf[parameter].notna()
    ].copy()

    if len(valid) < 3:
        return None

    # --------------------------------------------------------
    # PROJEKTION FÜR DISTANZBERECHNUNG
    # --------------------------------------------------------

    source_crs = gdf.crs

    if source_crs is None:
        raise ValueError(
            "Stationsdaten besitzen kein Koordinatenreferenzsystem."
        )

    transformer = Transformer.from_crs(
        source_crs,
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

    # --------------------------------------------------------
    # DEUTSCHLAND-GRENZEN
    # --------------------------------------------------------

    xmin, ymin, xmax, ymax = germany.total_bounds

    # Raster in geografischen Koordinaten
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

    # --------------------------------------------------------
    # RASTERKOORDINATEN IN METRISCHES SYSTEM UMWANDELN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # NÄCHSTE STATIONEN FINDEN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # IDW-GEWICHTUNG
    # --------------------------------------------------------

    weights = 1.0 / np.maximum(
        distances,
        0.001
    ) ** power

    # Exakte Stationswerte übernehmen
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

    # --------------------------------------------------------
    # AUF DEUTSCHLAND BEGRENZEN
    # --------------------------------------------------------

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


# ============================================================
# SCHWARZE ODER WEISSE SCHRIFT JE NACH HINTERGRUND
# ============================================================

def get_contrast_text_color(rgba):

    r, g, b = rgba[:3]

    luminance = (
        0.2126 * r
        + 0.7152 * g
        + 0.0722 * b
    )

    if luminance > 0.48:
        return "#000000"

    return "#ffffff"



# ============================================================
# GEEIGNETE LEGENDE-SCHRITTWEITE
# ============================================================

def get_legend_step(maximum):

    if maximum <= 50:
        return 5

    elif maximum <= 120:
        return 10

    elif maximum <= 200:
        return 15

    elif maximum <= 300:
        return 25

    elif maximum <= 500:
        return 50

    else:
        return 100


def get_period_legend_ticks(maximum):

    step = get_legend_step(maximum)

    ticks = list(
        range(
            0,
            int(maximum) + 1,
            step
        )
    )

    if not ticks or ticks[-1] < maximum:

        ticks.append(
            math.ceil(maximum / step) * step
        )

    return ticks


# ============================================================
# XML-NAMESPACES
# ============================================================

NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "dwd": (
        "https://opendata.dwd.de/weather/lib/"
        "pointforecast_dwd_extension_V1_0.xsd"
    )
}


# ============================================================
# HTTP
# ============================================================

HTTP = requests.Session()

HTTP.headers.update({
    "User-Agent": "DWD-MOSMIX-Deutschlandkarte/1.0"
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
# ERSTEN LAUF DES TAGES ERKENNEN
# ============================================================

def is_first_run_of_day():

    today = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).strftime("%Y-%m-%d")

    if not os.path.exists(FIRST_RUN_MARKER):
        return True

    with open(
        FIRST_RUN_MARKER,
        "r",
        encoding="utf-8"
    ) as file:

        previous_date = file.read().strip()

    return previous_date != today


# ============================================================
# WERTE FORMATIEREN
# ============================================================

def format_value(value, parameter):

    if pd.isna(value):
        return "–"

    return f"{value:.1f}".replace(".", ",")


# ============================================================
# ZAHLEN AUS MOSMIX PARSEN
# ============================================================

def parse_forecast_values(value_text):

    if not value_text:

        return []

    result = []

    for token in value_text.split():

        try:

            value = float(
                token.replace(",", ".")
            )

        except ValueError:

            result.append(None)
            continue

        if not math.isfinite(value) or value <= -900:

            result.append(None)
            continue

        result.append(value)

    return result


# ============================================================
# MOSMIX-ZEITSTEMPEL
# ============================================================

def parse_time_steps(root):

    time_steps = []

    for node in root.findall(
        ".//dwd:TimeStep",
        NS
    ):

        try:

            timestamp = pd.to_datetime(
                node.text.strip(),
                utc=True
            )

            time_steps.append(timestamp)

        except Exception:

            continue

    if not time_steps:

        raise RuntimeError(
            "Keine MOSMIX-Zeitstempel gefunden."
        )

    return time_steps

def get_forecast_dates(kmz_bytes):

    with zipfile.ZipFile(
        BytesIO(kmz_bytes)
    ) as archive:

        kml_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".kml")
        ]

        if not kml_files:

            raise RuntimeError(
                "Keine KML-Datei in KMZ gefunden."
            )

        with archive.open(kml_files[0]) as stream:
            root = ET.parse(stream).getroot()

    time_steps = parse_time_steps(root)

    today = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).date()

    last_day = today + timedelta(days=9)

    dates = sorted({
        timestamp.date()
        for timestamp in time_steps
        if today <= timestamp.date() <= last_day
    })

    if not dates:

        raise RuntimeError(
            "Keine zukünftigen Prognosetage gefunden."
        )

    return dates

# ============================================================
# MOSMIX-LAUFZEIT AUSLESEN
# ============================================================

def parse_issue_time(root):

    node = root.find(
        ".//dwd:ProductDefinition/dwd:IssueTime",
        NS
    )

    if node is None or not node.text:

        raise RuntimeError(
            "MOSMIX IssueTime nicht gefunden."
        )

    return pd.to_datetime(
        node.text.strip(),
        utc=True
    )

# ============================================================
# STATIONSDATEN LADEN
# ============================================================

def load_station_data():

    log("[1/6] Lade Stationsdaten ...")

    if not os.path.exists(STATION_FILE):

        raise FileNotFoundError(
            f"Datei nicht gefunden: {STATION_FILE}"
        )

    df = pd.read_csv(
        STATION_FILE,
        sep=",",
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False
    )

    df.columns = [
        str(column).strip().lower()
        for column in df.columns
    ]

    required = {
        "mosmix_code",
        "mosmix_name",
        "station_id",
        "name",
        "bundesland",
        "latitude",
        "longitude",
        "stationshoehe"
    }

    missing = required - set(df.columns)

    if missing:

        raise ValueError(
            "Fehlende Spalten: "
            + ", ".join(sorted(missing))
        )

    df = df[
        [
            "mosmix_code",
            "mosmix_name",
            "station_id",
            "name",
            "bundesland",
            "latitude",
            "longitude",
            "stationshoehe"
        ]
    ].copy()

    for column in [
        "mosmix_code",
        "mosmix_name",
        "station_id",
        "name",
        "bundesland"
    ]:

        df[column] = df[column].str.strip()

    for column in [
        "latitude",
        "longitude",
        "stationshoehe"
    ]:

        df[column] = pd.to_numeric(
            df[column].str.replace(
                ",",
                ".",
                regex=False
            ),
            errors="coerce"
        )

    df = df[
        (df["mosmix_code"] != "")
        & (df["bundesland"] != "")
        & df["latitude"].notna()
        & df["longitude"].notna()
    ].copy()

    df = df.drop_duplicates(
        subset="mosmix_code",
        keep="first"
    )

    log(
        f"      {len(df)} Stationen geladen."
    )

    return df


# ============================================================
# MOSMIX-KMZ LADEN
# ============================================================

def download_mosmix():

    log("[2/6] Lade aktuelle MOSMIX-Datei ...")

    response = get(MOSMIX_URL)

    log(
        f"      Download: "
        f"{len(response.content) / 1024 / 1024:.1f} MB"
    )

    return response.content


# ============================================================
# EINZELNE STATION AUSWERTEN
# ============================================================

def process_placemark(
    placemark,
    time_steps,
    station_lookup,
    target_date
):

    name_node = placemark.find(
        "kml:name",
        NS
    )

    if name_node is None or not name_node.text:

        return None

    mosmix_code = name_node.text.strip()

    station_info = station_lookup.get(
        mosmix_code
    )

    if station_info is None:

        return None

    forecasts = {}

    # --------------------------------------------------------
    # ALLE BENÖTIGTEN PROGNosePARAMETER EINLESEN
    # --------------------------------------------------------

    for forecast in placemark.findall(
        ".//dwd:Forecast",
        NS
    ):

        element_name = forecast.get(
            "{"
            + NS["dwd"]
            + "}elementName"
        )

        if element_name not in PARAMETERS:
            continue

        value_node = forecast.find(
            "dwd:value",
            NS
        )

        if value_node is None:
            continue

        values = parse_forecast_values(
            value_node.text
        )

        if len(values) != len(time_steps):
            continue

        forecasts[element_name] = values

        # --------------------------------------------------------
    # TAGESGRENZEN – AUSSCHLIESSLICH UTC
    # --------------------------------------------------------

    day_start = pd.Timestamp(
        target_date,
        tz="UTC"
    )

    day_end = day_start + pd.Timedelta(days=1)

    # --------------------------------------------------------
    # GRUNDDATEN
    # --------------------------------------------------------

    result = {

        "mosmix_code": mosmix_code,

        "station_id": station_info["station_id"],

        "name": station_info["name"],

        "bundesland": station_info["bundesland"],

        "latitude": station_info["latitude"],

        "longitude": station_info["longitude"]

    }

    
    # --------------------------------------------------------
    # SECHS PARAMETER BERECHNEN
    # --------------------------------------------------------

    for parameter, config in PARAMETERS.items():

        values = forecasts.get(parameter)

        if values is None:

            result[parameter] = None
            continue

        selected = []

        window_hours = config["window_hours"]

        for timestamp, value in zip(
            time_steps,
            values
        ):

            if value is None:
                continue

            # --------------------------------------------
            # TX UND TN:
            # AUSSCHLIESSLICH DAS 12-STUNDEN-INTERVALL
            # 06:00 BIS 18:00 UTC
            # --------------------------------------------

            if window_hours == 12:

                target_timestamp = (
                    day_start
                    + pd.Timedelta(hours=18)
                )

                if timestamp == target_timestamp:

                    selected.append(value)

            # --------------------------------------------
            # TTT:
            # STUNDENWERTE VON 00:00 BIS EXKLUSIV 24:00
            # --------------------------------------------

            elif window_hours == 0:

                if (
                    timestamp >= day_start
                    and timestamp < day_end
                ):

                    selected.append(value)

            # --------------------------------------------
            # STUNDENINTERVALLE:
            # 01:00 BIS EINSCHLIESSLICH 24:00 UTC
            # --------------------------------------------

            else:

                if (
                    timestamp > day_start
                    and timestamp <= day_end
                ):

                    selected.append(value)

        # ------------------------------------------------
        # FEHLENDE WERTE
        # ------------------------------------------------

        if not selected:

            result[parameter] = None
            continue

        if window_hours == 1:

            if (
                len(selected) < 24
                and target_date != pd.Timestamp.now(
                    tz="UTC"
                ).date()
            ):

                result[parameter] = None
                continue

        # ------------------------------------------------
        # EINHEITENUMRECHNUNG
        # ------------------------------------------------

        conversion = config["conversion"]

        if conversion == "kelvin":

            selected = [
                value - 273.15
                for value in selected
            ]

        elif conversion == "seconds_to_hours":

            selected = [
                value / 3600.0
                for value in selected
            ]

        elif conversion == "ms_to_kmh":

            selected = [
                value * 3.6
                for value in selected
            ]

        # ------------------------------------------------
        # TX UND TN:
        # 12-STUNDEN-EXTREM MIT TTT-STUNDENEXTREM
        # DES GESAMTEN KALENDERTAGES KOMBINIEREN
        # ------------------------------------------------

        if parameter in ("TX", "TN"):

            ttt_values = forecasts.get("TTT")

            if ttt_values is None:

                result[parameter] = None
                continue

            ttt_selected = []

            for timestamp, value in zip(
                time_steps,
                ttt_values
            ):

                if (
                    value is not None
                    and timestamp >= day_start
                    and timestamp < day_end
                ):

                    ttt_selected.append(
                        value - 273.15
                    )

            if not ttt_selected:

                result[parameter] = None
                continue

            candidates = (
                selected + ttt_selected
            )

            if parameter == "TX":

                result[parameter] = max(
                    candidates
                )

            else:

                result[parameter] = min(
                    candidates
                )

            continue

        # ------------------------------------------------
        # AGGREGATION ALLER ÜBRIGEN PARAMETER
        # ------------------------------------------------

        aggregation = config["aggregation"]

        if aggregation == "max":

            final_value = max(selected)

        elif aggregation == "min":

            final_value = min(selected)

        elif aggregation == "mean":

            final_value = sum(selected) / len(selected)

        elif aggregation == "sum":

            final_value = sum(selected)

        else:

            final_value = None

        result[parameter] = final_value

    return result


# ============================================================
# ALLE MOSMIX-STATIONEN VERARBEITEN
# ============================================================

def process_mosmix(
    kmz_bytes,
    station_data,
    target_date
):

    log("[3/6] Verarbeite MOSMIX-Prognosen ...")

    station_lookup = (
        station_data
        .set_index("mosmix_code")
        .to_dict("index")
    )

    with zipfile.ZipFile(
        BytesIO(kmz_bytes)
    ) as archive:

        kml_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".kml")
        ]

        if not kml_files:

            raise RuntimeError(
                "Keine KML-Datei in KMZ gefunden."
            )

        with archive.open(kml_files[0]) as stream:

            root = ET.parse(stream).getroot()

    # --------------------------------------------------------
    # MOSMIX-LAUF
    # --------------------------------------------------------

    issue_time = parse_issue_time(root)

    log(
        "      MOSMIX-Lauf: "
        + issue_time.strftime("%d.%m.%Y %Hz")
    )

    # --------------------------------------------------------
    # ZEITSTEMPEL
    # --------------------------------------------------------

    time_steps = parse_time_steps(root)

    log(
        f"      {len(time_steps)} Prognosezeitpunkte."
    )

    # --------------------------------------------------------
    # PLACEMARKS
    # --------------------------------------------------------

    placemarks = root.findall(
        ".//kml:Placemark",
        NS
    )

    log(
        f"      {len(placemarks)} MOSMIX-Placemarks."
    )

    results = []

    for placemark in placemarks:

        result = process_placemark(
            placemark,
            time_steps,
            station_lookup,
            target_date
        )

        if result is not None:

            results.append(result)

    if not results:

        raise RuntimeError(
            "Keine Stationen konnten verarbeitet werden."
        )

    # --------------------------------------------------------
    # AUSWERTUNG
    # --------------------------------------------------------

    log(
        f"      {len(results)} Stationen verarbeitet."
    )

    for parameter in PARAMETERS:

        valid_count = sum(
            1
            for result in results
            if result[parameter] is not None
        )

        log(
            f"      {parameter}: "
            f"{valid_count} gültige Stationen"
        )

    results.sort(
        key=lambda x: x["station_id"]
    )

    return results, issue_time

# ============================================================
# GEODATEN ERSTELLEN
# ============================================================

def create_geodata(results):

    rows = []

    for result in results:

        rows.append({

            "mosmix_code": result["mosmix_code"],

            "station_id": result["station_id"],

            "name": result["name"],

            "bundesland": result["bundesland"],

            "lat": result["latitude"],

            "lon": result["longitude"],

            **{
                parameter: result[parameter]
                for parameter in PARAMETERS
            }

        })

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
# SUMMENWERTE MEHRERER PROGNOSETAGE
# ============================================================

def calculate_period_sum(
    daily_gdfs,
    parameter
):

    if not daily_gdfs:
        return None

    base = daily_gdfs[0].copy()

    values = []

    for station_code in base["mosmix_code"]:

        station_values = []

        for daily_gdf in daily_gdfs:

            match = daily_gdf.loc[
                daily_gdf["mosmix_code"] == station_code,
                parameter
            ]

            if (
                match.empty
                or pd.isna(match.iloc[0])
            ):

                station_values = []
                break

            station_values.append(
                float(match.iloc[0])
            )

        if len(station_values) == len(daily_gdfs):

            values.append(
                sum(station_values)
            )

        else:

            values.append(None)

    base[parameter] = values

    return base


# ============================================================
# BUNDESLAND-STATISTIK
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

        subset = gdf.loc[
            gdf["bundesland"] == bundesland,
            parameter
        ].dropna()

        states.append({

            "bundesland": bundesland,

            "min": (
                subset.min()
                if not subset.empty
                else None
            ),

            "mean": (
                subset.mean()
                if not subset.empty
                else None
            ),

            "max": (
                subset.max()
                if not subset.empty
                else None
            )

        })

    return pd.DataFrame(states)


# ============================================================
# DEUTSCHLAND-STATISTIK
# ============================================================

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
# BESCHRIFTUNGSPOSITIONEN
# ============================================================

def calculate_label_positions(
    ax,
    gdf,
    min_distance=25,
    iterations=8
):

    if gdf.empty:

        return {}

    xy = ax.transData.transform(
        gdf.geometry.apply(
            lambda p: (p.x, p.y)
        ).tolist()
    )

    positions = xy.copy()

    count = len(positions)

    for _ in range(iterations):

        moved = False

        for i in range(count):

            for j in range(i + 1, count):

                dx = (
                    positions[i][0]
                    - positions[j][0]
                )

                dy = (
                    positions[i][1]
                    - positions[j][1]
                )

                distance_sq = (
                    dx * dx + dy * dy
                )

                if distance_sq >= min_distance ** 2:
                    continue

                if distance_sq < 0.01:

                    dx = 1.0
                    dy = 0.0
                    distance_sq = 1.0

                distance = math.sqrt(distance_sq)

                push = (
                    min_distance - distance
                ) * 0.55

                nx = dx / distance
                ny = dy / distance

                positions[i][0] += nx * push
                positions[i][1] += ny * push

                positions[j][0] -= nx * push
                positions[j][1] -= ny * push

                moved = True

        if not moved:
            break

    inverse = ax.transData.inverted()

    return {
        index: inverse.transform(position)
        for index, position in zip(
            gdf.index,
            positions
        )
    }


# ============================================================
# BUNDESLAND- UND DEUTSCHLANDÜBERSICHT
# ============================================================



def draw_state_summary(
    ax,
    state_df,
    germany_extremes,
    parameter,
    created_at,
    issue_time
):

    ax.axis("off")

    accent = "#a50026"

    # --------------------------------------------------------
    # DATENSTAND
    # --------------------------------------------------------

    ax.text(
        0.0, 0.995,
        "MOSMIX-Prognose",
        transform=ax.transAxes,
        fontsize=11,
        fontweight="bold",
        va="top",
        color="#555555"
    )

    ax.text(
        0.0, 0.963,
        "Lauf",
        transform=ax.transAxes,
        fontsize=10.5,
        va="top",
        color="#777777"
    )

    ax.text(
        1.0, 0.963,
        issue_time.strftime("%d.%m.%Y %Hz"),
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

    # --------------------------------------------------------
    # TRENNLINIE
    # --------------------------------------------------------

    ax.plot(
        [0.0, 1.0],
        [0.875, 0.875],
        transform=ax.transAxes,
        color="#bdbdbd",
        linewidth=0.8,
        clip_on=False
    )

    # --------------------------------------------------------
    # TABELLENKOPF
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # BUNDESLÄNDER
    # --------------------------------------------------------

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

        for (x, _), value in zip(
            columns,
            values
        ):

            ax.text(
                x,
                y,
                format_value(value, parameter),
                transform=ax.transAxes,
                fontsize=10.5,
                ha="center",
                va="center",
                color="#333333"
            )

        y -= line_height

    # --------------------------------------------------------
    # DEUTSCHLAND
    # --------------------------------------------------------

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
        fontsize=11,
        fontweight="bold",
        va="center",
        color="#222222"
    )

    values = [
        germany_extremes["max"],
        germany_extremes["mean"],
        germany_extremes["min"]
    ]

    for (x, _), value in zip(
        columns,
        values
    ):

        ax.text(
            x,
            y,
            format_value(value, parameter),
            transform=ax.transAxes,
            fontsize=11,
            fontweight="bold",
            ha="center",
            va="center",
            color=accent
        )

# ============================================================
# DEUTSCHLANDKARTE ERSTELLEN
# ============================================================

# ============================================================
# LEGENDE FÜR DIE PROGNOSEKARTEN
# ============================================================


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

    if parameter == "TX":

        ticks = list(range(-20, 51, 5))
        title = "Höchsttemperatur in °C"

    elif parameter == "TN":

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

        
def plot_map(
    germany,
    gdf,
    state_df,
    germany_extremes,
    parameter,
    target_date,
    created_at,
    issue_time,
    output_file,
    number_of_days=None,
    period_start=None,
    interpolated=True
):


    log(
        f"      Erstelle {output_file} ..."
    )

    config = PARAMETERS[parameter]

    cmap = get_parameter_cmap(parameter)

    if number_of_days is None:
    
        norm = get_parameter_norm(parameter)
    
    else:
    
        norm = get_period_norm(
            parameter,
            number_of_days
        )

    
    # --------------------------------------------------------
    # FIGURE MIT KARTE, ÜBERSICHT UND LEGENDE
    # --------------------------------------------------------

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

    legend_ax = fig.add_subplot(
        gs[1, :],
    )


    # --------------------------------------------------------
    # DEUTSCHLAND – GRUNDFLÄCHE
    # --------------------------------------------------------

    germany.plot(
        ax=ax,
        color="#e2e2e2",
        edgecolor="#555555",
        linewidth=0.55,
        zorder=1
    )

    # --------------------------------------------------------
    # ACHSENBEREICH
    # --------------------------------------------------------

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
    
    
    # --------------------------------------------------------
    # BESCHRIFTUNG DER GEOGRAFISCHEN KOORDINATEN
    # --------------------------------------------------------

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

    
    
    # --------------------------------------------------------
    # RÄUMLICHE IDW-INTERPOLATION
    # ALLE SECHS WETTERPARAMETER
    # --------------------------------------------------------

    if interpolated:

        interpolation = interpolate(
            germany=germany,
            gdf=gdf,
            parameter=parameter,
            norm=norm,
            resolution_x=400,
            resolution_y=500,
            neighbors=8,
            power=2.0
        )

        if interpolation is not None:

            grid_x, grid_y, interpolated_values = (
                interpolation
            )

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

            # Bundeslandgrenzen und Außenkontur
            # erneut über das interpolierte Raster zeichnen

            germany.boundary.plot(
                ax=ax,
                color="#555555",
                linewidth=0.55,
                zorder=4
            )


    # --------------------------------------------------------
    # STATIONEN
    # --------------------------------------------------------

    valid = gdf[
        gdf[parameter].notna()
    ].copy()

    label_positions = calculate_label_positions(
        ax,
        valid,
        min_distance=24,
        iterations=7
    )
    
    
    # --------------------------------------------------------
    # BESCHRIFTUNGEN
    # --------------------------------------------------------

    for index, row in valid.iterrows():

        value = row[parameter]

        if index in label_positions:

            text_x, text_y = label_positions[index]

        else:

            text_x = row.geometry.x
            text_y = row.geometry.y

        # ----------------------------------------------------
        # SCHRIFTFARBE
        # ----------------------------------------------------

        if interpolated:

            # SONNENSCHEIN:
            # Automatischer Schwarz-Weiß-Kontrast,
            # ausschließlich auf interpolierten Karten.

            if parameter == "SunD1":

                rgba = cmap(
                    norm(value)
                )

                text_color = get_contrast_text_color(
                    rgba
                )

            # ALLE ANDEREN INTERPOLIERTEN PARAMETER:
            # Immer schwarze Schrift.

            else:

                text_color = "#000000"

        ax.text(
            text_x,
            text_y,
            format_value(value, parameter),

            fontsize=10,
            fontfamily="DejaVu Sans",
            fontweight="bold",

            ha="center",
            va="center",

            color=text_color,

            zorder=10
        )

    # --------------------------------------------------------
    # TITEL
    # --------------------------------------------------------

    if number_of_days is None:
    
        map_title = (
            config["name"]
            + "\n"
            + target_date.strftime("%d.%m.%Y")
        )
    
    else:

        map_title = (
            config["name"]
            + "\n"
            + "bis "
            + target_date.strftime("%d.%m.%Y")
            + f" (Summe über {number_of_days} Tage)"
        )
    
    ax.set_title(
        map_title,
        fontsize=18,
        fontweight="bold",
        pad=4
    )

    # --------------------------------------------------------
    # RECHTE ÜBERSICHT
    # --------------------------------------------------------

    draw_state_summary(
        summary_ax,
        state_df,
        germany_extremes,
        parameter,
        created_at,
        issue_time
    )
    
    
    # --------------------------------------------------------
    # LEGENDE
    # --------------------------------------------------------

    draw_parameter_legend(
        legend_ax,
        parameter,
        number_of_days
    )


    # --------------------------------------------------------
    # SPEICHERN
    # --------------------------------------------------------

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


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    log("")
    log("=" * 70)
    log("MOSMIX – DEUTSCHLAND PROGNOSEKARTEN")
    log("=" * 70)
    log("")

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    # --------------------------------------------------------
    # ERSTEN TAGESLAUF ERKENNEN
    # --------------------------------------------------------

    first_run = is_first_run_of_day()

    if first_run:

        log("")
        log("ERSTER TAGESLAUF: Erstelle Stand A.")

    else:

        log("")
        log("REGULÄRER TAGESLAUF: Erstelle Stand B.")

    # --------------------------------------------------------
    # 1. STATIONSDATEN
    # --------------------------------------------------------

    station_data = load_station_data()

    # --------------------------------------------------------
    # 2. MOSMIX DOWNLOAD
    # --------------------------------------------------------

    kmz_bytes = download_mosmix()

    # --------------------------------------------------------
    # 3. VERFÜGBARE PROGNOSETAGE
    # --------------------------------------------------------

    forecast_dates = get_forecast_dates(
        kmz_bytes
    )

    log("")
    log(
        f"{len(forecast_dates)} Prognosetage gefunden:"
    )

    for date in forecast_dates:
        log(date.strftime("%d.%m.%Y"))

    # --------------------------------------------------------
    # 4. DEUTSCHLAND-GEOMETRIE
    # --------------------------------------------------------

    log("[4/6] Lade Deutschland-Geometrie ...")

    if not os.path.exists(SHAPEFILE):

        raise FileNotFoundError(
            f"Geodatei nicht gefunden: {SHAPEFILE}"
        )

    germany = gpd.read_file(SHAPEFILE)

    # --------------------------------------------------------
    # 5. ERSTELLUNGSZEITPUNKT
    # --------------------------------------------------------

    created_at = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).to_pydatetime()
    
    # ============================================================
    # VOLLSTÄNDIGE TAGESDATEN FÜR SUMMENKARTEN
    # ============================================================
    
    daily_full_gdfs = []
    
    today = pd.Timestamp.now(
        tz="UTC"
    ).date()

    # --------------------------------------------------------
    # 6. ALLE PROGNOSETAGE DURCHLAUFEN
    # --------------------------------------------------------

    for day_number, target_date in enumerate(
        forecast_dates,
        start=1
    ):

        log("")
        log("=" * 70)

        log(
            f"PROGNOSETAG {day_number}/{len(forecast_dates)}: "
            + target_date.strftime("%d.%m.%Y")
        )

        log("=" * 70)

        # --------------------------------------------
        # MOSMIX-PROGNOSEN VERARBEITEN
        # --------------------------------------------

        results, issue_time = process_mosmix(
            kmz_bytes,
            station_data,
            target_date
        )

        # --------------------------------------------
        # GEODATEN
        # --------------------------------------------

        log("[4/6] Erstelle Geodaten ...")

        gdf = create_geodata(results)

        log(
            f"      {len(gdf)} Stationen verarbeitet."
        )
        
        # --------------------------------------------------------
        # VOLLSTÄNDIGE ZUKÜNFTIGE TAGE SPEICHERN
        # --------------------------------------------------------
        
        if target_date >= today:
        
            daily_full_gdfs.append({
        
                "date": target_date,
        
                "gdf": gdf.copy(),
        
                "issue_time": issue_time
        
            })

        if germany.crs is not None:

            gdf = gdf.set_crs(
                germany.crs,
                allow_override=True
            )

        # --------------------------------------------
        # ALLE SECHS KARTEN ERSTELLEN
        # --------------------------------------------

        log("[6/6] Erstelle Prognosekarten ...")

        for parameter in PARAMETERS:

            log("")
            log("-" * 60)

            log(
                f"Parameter: {parameter} – "
                f"{PARAMETERS[parameter]['name']}"
            )

            # BUNDESLAND-STATISTIK

            state_df = calculate_state_extremes(
                gdf,
                parameter
            )

            # DEUTSCHLAND-STATISTIK

            germany_extremes = calculate_germany_extremes(
                gdf,
                parameter
            )

                        # ------------------------------------------------
            # INTERPOLIERTE TAGESKARTE ERSTELLEN
            # ------------------------------------------------

            parameter_names = {
                "SunD1": "sonne",
                "RR1c": "niederschlag",
                "FX1": "wind",
                "TX": "tx",
                "TN": "tn",
                "TTT": "tt"
            }

            map_name = parameter_names[parameter]

            # ------------------------------------------------
            # DATEINAME – STAND A ODER STAND B
            # ------------------------------------------------

            prefix = (
                "first_run_"
                if first_run
                else ""
            )

            output_file = os.path.join(
                OUTPUT_DIR,
                f"{prefix}{map_name}_tag{day_number}.png"
            )

            plot_map(
                germany=germany,
                gdf=gdf,
                state_df=state_df,
                germany_extremes=germany_extremes,
                parameter=parameter,
                target_date=target_date,
                created_at=created_at,
                issue_time=issue_time,
                output_file=output_file,
                interpolated=True
            )

    # ============================================================
    # SUMMENKARTEN ERSTELLEN
    # ============================================================
    
    log("")
    log("=" * 70)
    log("ERSTELLE SUMMENKARTEN")
    log("=" * 70)
    
    if len(daily_full_gdfs) >= 2:
    
        # --------------------------------------------------------
        # KUMULATIVE ZEITRÄUME ERZEUGEN
        # --------------------------------------------------------
    
        for end_index in range(
            2,
            len(daily_full_gdfs) + 1
        ):
    
            period = daily_full_gdfs[:end_index]
    
            number_of_days = len(period)
    
            start_date = period[0]["date"]
    
            end_date = period[-1]["date"]
    
            issue_time = period[-1]["issue_time"]
    
            log("")
            log("-" * 60)
    
            log(
                f"SUMMENZEITRAUM: "
                f"{start_date.strftime('%d.%m.%Y')} bis "
                f"{end_date.strftime('%d.%m.%Y')}"
            )
    
            # ----------------------------------------------------
            # SONNENSCHEIN UND NIEDERSCHLAG
            # ----------------------------------------------------
    
            for parameter in [
                "SunD1",
                "RR1c"
            ]:
    
                log(
                    f"      Erstelle {parameter}: "
                    f"{number_of_days} Tage"
                )
    
                # --------------------------------------------
                # SUMMEN BERECHNEN
                # --------------------------------------------
    
                gdf = calculate_period_sum(
                    [
                        item["gdf"]
                        for item in period
                    ],
                    parameter
                )
    
                if gdf is None:
                    continue
    
                # --------------------------------------------
                # BUNDESLAND-STATISTIK
                # --------------------------------------------
    
                state_df = calculate_state_extremes(
                    gdf,
                    parameter
                )
    
                # --------------------------------------------
                # DEUTSCHLAND-STATISTIK
                # --------------------------------------------
    
                germany_extremes = calculate_germany_extremes(
                    gdf,
                    parameter
                )
    
                # ------------------------------------------------
                # INTERPOLIERTE SUMMENKARTE ERSTELLEN
                # ------------------------------------------------

                parameter_names = {
                    "SunD1": "sonne",
                    "RR1c": "niederschlag"
                }

                map_name = parameter_names[parameter]

                # ------------------------------------------------
                # DATEINAME – STAND A ODER STAND B
                # ------------------------------------------------

                prefix = (
                    "first_run_"
                    if first_run
                    else ""
                )

                output_file = os.path.join(
                    OUTPUT_DIR,
                    f"{prefix}{map_name}_bis_tag{number_of_days}.png"
                )

                plot_map(
                    germany=germany,
                    gdf=gdf,
                    state_df=state_df,
                    germany_extremes=germany_extremes,
                    parameter=parameter,
                    target_date=end_date,
                    created_at=created_at,
                    issue_time=issue_time,
                    output_file=output_file,
                    number_of_days=number_of_days,
                    period_start=start_date,
                    interpolated=True
                )

    
    else:
    
        log(
            "Nicht genügend vollständige Tage "
            "für Summenkarten vorhanden."
        )
    # --------------------------------------------------------
    # FERTIG
    # --------------------------------------------------------

    log("")
    log("=" * 70)
    log("ALLE PROGNOSEKARTEN FERTIG")
    log("=" * 70)

    # --------------------------------------------------------
    # KARTENANZAHL
    # --------------------------------------------------------
    
    daily_map_count = (
        len(forecast_dates)
        * len(PARAMETERS)
    )
    
    number_of_periods = max(
        0,
        len(daily_full_gdfs) - 1
    )
    
    sum_map_count = (
        number_of_periods
        * 2
    )
    
    log(
        f"Prognosetage: {len(forecast_dates)}"
    )
    
    log(
        f"Parameter pro Tag: {len(PARAMETERS)}"
    )
    
    log(
        f"Tageskarten: {daily_map_count}"
    )
    
    log(
        f"Summenkarten: {sum_map_count}"
    )
    
    log(
        f"Erstellte Karten insgesamt: "
        f"{daily_map_count + sum_map_count}"
    )

    log(
        f"Ausgabeordner: {OUTPUT_DIR}"
    )

    # --------------------------------------------------------
    # ERSTEN TAGESLAUF REGISTRIEREN
    # ERST NACH ERFOLGREICHER ERSTELLUNG ALLER KARTEN
    # --------------------------------------------------------

    if first_run:

        with open(
            FIRST_RUN_MARKER,
            "w",
            encoding="utf-8"
        ) as file:

            file.write(
                pd.Timestamp.now(
                    tz="Europe/Berlin"
                ).strftime("%Y-%m-%d")
            )

        log(
            "Erster Tageslauf erfolgreich registriert."
        )

    log("=" * 70)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
