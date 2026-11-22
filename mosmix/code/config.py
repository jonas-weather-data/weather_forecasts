
import os
import math

import matplotlib.colors as mcolors

from matplotlib.colors import (
    LinearSegmentedColormap,
    Normalize
)


# ============================================================
# VERZEICHNISSE UND DATEIPFADE
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

DATA_DIR = os.path.join(
    BASE_DIR,
    "data"
)

OUTPUT_DIR = os.path.abspath(
    os.path.join(
        BASE_DIR,
        "..",
        "output",
        "germany"
    )
)

STATION_FILE = os.path.join(
    DATA_DIR,
    "stationsdaten.csv"
)

SHAPEFILE = os.path.join(
    DATA_DIR,
    "gadm41_DEU_1.json"
)


# ============================================================
# DWD MOSMIX
# ============================================================

MOSMIX_URL = (
    "https://opendata.dwd.de/weather/local_forecasts/"
    "mos/MOSMIX_S/all_stations/kml/"
    "MOSMIX_S_LATEST_240.kmz"
)

REQUEST_TIMEOUT = 180


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

PLOT_STYLES = {

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

    "TTT": {
        "vmin": -20,
        "vmax": 35,
        "colors": [
            (0.000, "#08306b"),
            (0.255, "#6baed6"),
            (0.405, "#31a354"),
            (0.520, "#ffff66"),
            (0.655, "#fdae61"),
            (0.735, "#e31a1c"),
            (0.815, "#99000d"),
            (0.880, "#6a3d9a"),
            (0.945, "#c51b8a"),
            (1.000, "#f768a1")
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
            (0.0000, "#e2e2e2"),
            (0.0071, "#d9d9d9"),

            (0.0357, "#b8d8e8"),
            (0.0429, "#8fc5df"),

            (0.0786, "#70b5d8"),
            (0.0857, "#4299c8"),

            (0.1357, "#55b96b"),
            (0.1429, "#238b45"),

            (0.2000, "#c6df42"),
            (0.2071, "#e4df35"),

            (0.2714, "#ffff66"),
            (0.2786, "#ffca45"),

            (0.3500, "#ffad32"),
            (0.3571, "#ff8225"),

            (0.4357, "#ff641e"),
            (0.4429, "#ed351c"),

            (0.5286, "#e51d25"),
            (0.5357, "#bd0026"),

            (0.6286, "#a50026"),
            (0.6357, "#800026"),

            (0.7286, "#702080"),
            (0.7357, "#54278f"),

            (0.8357, "#a32ca5"),
            (0.8429, "#c51b8a"),

            (0.8500, "#e45ca8"),
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
# SUMMENKARTEN – FARBSKALIERUNG
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
# SCHRIFTFARBEN
# ============================================================

def get_readable_text_color(rgba):

    r, g, b = rgba[:3]

    h, s, v = mcolors.rgb_to_hsv(
        [r, g, b]
    )

    s = min(1.0, s * 1.35)

    if v > 0.75:
        v = 0.75 + (v - 0.75) * 0.35

    v = max(0.35, v)

    return tuple(
        mcolors.hsv_to_rgb([h, s, v])
    )


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
# LEGENDE – SCHRITTWEITEN
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
