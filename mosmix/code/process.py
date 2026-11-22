
import zipfile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd

from config import PARAMETERS, STATION_FILE


def process_mosmix(file_path):

    print("Verarbeite MOSMIX-Prognosedaten ...")

    with zipfile.ZipFile(file_path) as archive:

        kml_name = next(
            name for name in archive.namelist()
            if name.lower().endswith(".kml")
        )

        with archive.open(kml_name) as file:
            root = ET.parse(file).getroot()

    ns = {
        "kml": "http://www.opengis.net/kml/2.2"
    }

    timestamps = [
        element.text
        for element in root.findall(
            ".//kml:ForecastTimeSteps/kml:TimeStep",
            ns
        )
        if element.text
    ]

    if not timestamps:
        raise ValueError("Keine Prognosezeitpunkte gefunden.")

    records = []

    for placemark in root.findall(
        ".//kml:Placemark",
        ns
    ):

        extended = placemark.find(
            "kml:ExtendedData/kml:SchemaData",
            ns
        )

        if extended is None:
            continue

        values = {
            element.attrib.get("name"): element.text
            for element in extended.findall(
                "kml:SimpleData",
                ns
            )
        }

        station = values.get("Station_id") or values.get("station_id")

        if not station:
            continue

        coordinates = placemark.find(
            ".//kml:Point/kml:coordinates",
            ns
        )

        if coordinates is None or not coordinates.text:
            continue

        longitude, latitude, *_ = map(
            float,
            coordinates.text.strip().split(",")
        )

        record = {
            "station_id": station,
            "latitude": latitude,
            "longitude": longitude
        }

        for parameter, settings in PARAMETERS.items():

            raw = values.get(parameter)

            if not raw:
                continue

            try:
                numbers = np.array(
                    [float(value) for value in raw.split()],
                    dtype=float
                )

                numbers[numbers >= 999] = np.nan

                conversion = settings["conversion"]

                if conversion == "kelvin":
                    numbers -= 273.15

                elif conversion == "seconds_to_hours":
                    numbers /= 3600

                elif conversion == "ms_to_kmh":
                    numbers *= 3.6

                record[parameter] = numbers

            except (ValueError, TypeError):
                continue

        records.append(record)

    if not records:
        raise ValueError("Keine Stationsdaten gefunden.")

    forecast = pd.DataFrame(records)

    stations = pd.read_csv(
        STATION_FILE,
        dtype={"station_id": str}
    )

    forecast["station_id"] = forecast["station_id"].astype(str)
    stations["station_id"] = stations["station_id"].astype(str)

    forecast = forecast.drop(
        columns=["latitude", "longitude"],
        errors="ignore"
    ).merge(
        stations[["station_id", "latitude", "longitude"]],
        on="station_id",
        how="inner"
    )

    if forecast.empty:
        raise ValueError("Keine passenden DWD-Stationen gefunden.")

    time_index = pd.to_datetime(
        timestamps,
        utc=True
    )

    reference_day = time_index[0].normalize()

    for parameter, settings in PARAMETERS.items():

        if parameter not in forecast.columns:
            continue

        for day in range(1, 11):

            start = reference_day + pd.Timedelta(days=day - 1)
            end = start + pd.Timedelta(days=1)

            results = []

            for values in forecast[parameter]:

                values = np.asarray(values, dtype=float)

                if len(values) != len(time_index):
                    results.append(np.nan)
                    continue

                mask = (
                    (time_index >= start)
                    & (time_index < end)
                )

                selected = values[mask]

                if not np.isfinite(selected).any():
                    results.append(np.nan)
                    continue

                aggregation = settings["aggregation"]

                if aggregation == "max":
                    result = np.nanmax(selected)

                elif aggregation == "min":
                    result = np.nanmin(selected)

                elif aggregation == "mean":
                    result = np.nanmean(selected)

                else:
                    result = np.nansum(selected)

                results.append(result)

            forecast[f"{parameter}_tag{day}"] = results

    for parameter in ("RR1c", "SunD1"):

        for day in range(1, 11):

            columns = [
                f"{parameter}_tag{number}"
                for number in range(1, day + 1)
            ]

            forecast[
                f"{parameter}_bis_tag{day}"
            ] = forecast[columns].sum(
                axis=1,
                min_count=1
            )

    print(f"{len(forecast)} Stationen verarbeitet.")

    return forecast
