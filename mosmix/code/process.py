
import zipfile
import math
from io import BytesIO

import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET

from config import PARAMETERS, STATION_FILE


# ============================================================
# XML-NAMESPACES – WIE IM ORIGINALCODE
# ============================================================

NS = {
    "kml": "http://www.opengis.net/kml/2.2",
    "dwd": (
        "https://opendata.dwd.de/weather/lib/"
        "pointforecast_dwd_extension_V1_0.xsd"
    )
}


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

            timestamp = timestamp.tz_convert(
                "Europe/Berlin"
            )

            time_steps.append(timestamp)

        except Exception:
            continue

    if not time_steps:

        raise RuntimeError(
            "Keine MOSMIX-Zeitstempel gefunden."
        )

    return time_steps


# ============================================================
# MOSMIX-WERTE PARSEN
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
# STATIONSDATEN LADEN
# ============================================================

def load_stations():

    stations = pd.read_csv(
        STATION_FILE,
        sep=",",
        dtype=str,
        encoding="utf-8-sig",
        keep_default_na=False
    )

    stations.columns = [
        str(column).strip().lower()
        for column in stations.columns
    ]

    required = {
        "mosmix_code",
        "station_id",
        "latitude",
        "longitude",
        "name",
        "bundesland"
    }

    missing = required - set(stations.columns)

    if missing:

        raise ValueError(
            "Fehlende Spalten in stationsdaten.csv: "
            + ", ".join(sorted(missing))
        )

    stations["mosmix_code"] = (
        stations["mosmix_code"].str.strip()
    )

    stations["station_id"] = (
        stations["station_id"].str.strip()
    )

    for column in ("latitude", "longitude"):

        stations[column] = pd.to_numeric(
            stations[column].str.replace(
                ",",
                ".",
                regex=False
            ),
            errors="coerce"
        )

    stations = stations.dropna(
        subset=["latitude", "longitude"]
    )

    stations = stations.drop_duplicates(
        subset="mosmix_code",
        keep="first"
    )

    return stations


# ============================================================
# EINZELNE MOSMIX-STATION VERARBEITEN
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

    for forecast in placemark.findall(
        ".//dwd:Forecast",
        NS
    ):

        element_name = forecast.get(
            "{" + NS["dwd"] + "}elementName"
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

    day_start = pd.Timestamp(
        target_date,
        tz="Europe/Berlin"
    )

    day_end = day_start + pd.DateOffset(days=1)

    result = {
        "mosmix_code": mosmix_code,
        "station_id": station_info["station_id"],
        "name": station_info["name"],
        "bundesland": station_info["bundesland"],
        "latitude": station_info["latitude"],
        "longitude": station_info["longitude"]
    }

    for parameter, settings in PARAMETERS.items():

        values = forecasts.get(parameter)

        if values is None:

            result[parameter] = None
            continue

        selected = []

        window_hours = settings["window_hours"]

        for timestamp, value in zip(
            time_steps,
            values
        ):

            if value is None:
                continue

            if window_hours == 12:

                interval_start = (
                    timestamp
                    - pd.Timedelta(hours=12)
                )

                if (
                    timestamp > day_start
                    and interval_start < day_end
                ):
                    selected.append(value)

            elif window_hours == 0:

                if (
                    timestamp >= day_start
                    and timestamp < day_end
                ):
                    selected.append(value)

            else:

                if (
                    timestamp > day_start
                    and timestamp <= day_end
                ):
                    selected.append(value)

        if not selected:

            result[parameter] = None
            continue

        if window_hours != 12:

            expected_hours = (
                24 if window_hours == 1 else 0
            )

            if (
                expected_hours > 0
                and len(selected) < expected_hours
                and target_date != pd.Timestamp.now(
                    tz="Europe/Berlin"
                ).date()
            ):

                result[parameter] = None
                continue

        conversion = settings["conversion"]

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

        aggregation = settings["aggregation"]

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
# MOSMIX VERARBEITEN
# ============================================================

def process_mosmix(file_path, target_date=None):

    print("Verarbeite MOSMIX-Prognosedaten ...")

    # --------------------------------------------------------
    # KMZ ÖFFNEN
    # --------------------------------------------------------

    with zipfile.ZipFile(file_path) as archive:

        kml_files = [
            name
            for name in archive.namelist()
            if name.lower().endswith(".kml")
        ]

        if not kml_files:

            raise RuntimeError(
                "Keine KML-Datei in KMZ gefunden."
            )

        with archive.open(kml_files[0]) as file:

            root = ET.parse(file).getroot()

    # --------------------------------------------------------
    # ZEITSTEMPEL
    # --------------------------------------------------------

    time_steps = parse_time_steps(root)

    print(
        f"{len(time_steps)} Prognosezeitpunkte gefunden."
    )

    # --------------------------------------------------------
    # PROGNOSETAGE
    # --------------------------------------------------------

    if target_date is None:

        today = pd.Timestamp.now(
            tz="Europe/Berlin"
        ).date()

        target_date = today

    # --------------------------------------------------------
    # STATIONSDATEN
    # --------------------------------------------------------

    stations = load_stations()

    station_lookup = (
        stations
        .set_index("mosmix_code")
        .to_dict("index")
    )

    # --------------------------------------------------------
    # MOSMIX-STATIONEN
    # --------------------------------------------------------

    placemarks = root.findall(
        ".//kml:Placemark",
        NS
    )

    print(
        f"{len(placemarks)} MOSMIX-Stationen gefunden."
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
            "Keine Stationen konnten verarbeitet werden. "
            "Bitte MOSMIX-Codes in stationsdaten.csv prüfen."
        )

    forecast = pd.DataFrame(results)

    print(
        f"{len(forecast)} Stationen verarbeitet."
    )

    return forecast
