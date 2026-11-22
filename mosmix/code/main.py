
import os
from pathlib import Path

import geopandas as gpd
import pandas as pd

from mosmix_data import (
    load_station_data,
    download_mosmix,
    get_forecast_dates,
    process_mosmix,
    create_geodata,
)

from map_generator import (
    plot_map,
    calculate_state_extremes,
    calculate_germany_extremes,
)


# ============================================================
# PFADE
# ============================================================

CODE_DIR = Path(__file__).resolve().parent

MOSMIX_DIR = CODE_DIR.parent

STATION_FILE = MOSMIX_DIR / "stationsdaten.csv"

SHAPEFILE = MOSMIX_DIR / "gadm41_DEU_1.json"

OUTPUT_DIR = MOSMIX_DIR / "output" / "germany"


# ============================================================
# DATEINAMEN
# ============================================================

PARAMETER_FILENAMES = {
    "TTT": "mittel",
    "RR1c": "niederschlag",
    "FX1": "wind",
    "TX": "tmax",
    "TN": "tmin",
    "SunD1": "sonne",
}

PERIOD_PARAMETERS = [
    "RR1c",
    "SunD1",
]


# ============================================================
# SUMMENWERTE MEHRERER PROGNOSETAGE
# ============================================================

def calculate_period_sum(daily_gdfs, parameter):

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

            if match.empty or pd.isna(match.iloc[0]):

                station_values = []
                break

            station_values.append(
                float(match.iloc[0])
            )

        if len(station_values) == len(daily_gdfs):

            values.append(sum(station_values))

        else:

            values.append(None)

    base[parameter] = values

    return base


# ============================================================
# KARTE ERSTELLEN
# ============================================================

def create_forecast_map(
    germany,
    gdf,
    parameter,
    target_date,
    day_number,
    created_at,
    issue_time,
    number_of_days=None,
):

    # --------------------------------------------------------
    # STATISTIKEN
    # --------------------------------------------------------

    state_df = calculate_state_extremes(
        gdf,
        parameter
    )

    germany_extremes = calculate_germany_extremes(
        gdf,
        parameter
    )

    # --------------------------------------------------------
    # DATEINAME
    # --------------------------------------------------------

    parameter_name = PARAMETER_FILENAMES[parameter]

    if number_of_days is None:

        filename = (
            f"{parameter_name}_tag{day_number}.png"
        )

    else:

        filename = (
            f"{parameter_name}_bis_tag{day_number}.png"
        )

    output_file = OUTPUT_DIR / filename

    # --------------------------------------------------------
    # INTERPOLIERTE KARTE ERSTELLEN
    # --------------------------------------------------------

    plot_map(
        germany=germany,
        gdf=gdf,
        state_df=state_df,
        germany_extremes=germany_extremes,
        parameter=parameter,
        target_date=target_date,
        created_at=created_at,
        issue_time=issue_time,
        output_file=str(output_file),
        number_of_days=number_of_days,
        interpolated=True,
    )


# ============================================================
# HAUPTPROGRAMM
# ============================================================

def main():

    print()
    print("=" * 65)
    print("MOSMIX – DEUTSCHLAND PROGNOSEKARTEN")
    print("=" * 65)

    # --------------------------------------------------------
    # AUSGABEORDNER
    # --------------------------------------------------------

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # STATIONSDATEN
    # --------------------------------------------------------

    station_data = load_station_data(
        str(STATION_FILE)
    )

    # --------------------------------------------------------
    # MOSMIX DOWNLOAD
    # --------------------------------------------------------

    kmz_bytes = download_mosmix()

    # --------------------------------------------------------
    # PROGNOSETAGE
    # --------------------------------------------------------

    forecast_dates = get_forecast_dates(
        kmz_bytes
    )

    forecast_dates = forecast_dates[:10]

    print()
    print(f"{len(forecast_dates)} Prognosetage gefunden.")

    # --------------------------------------------------------
    # DEUTSCHLAND-GEOMETRIE
    # --------------------------------------------------------

    print("Lade Deutschland-Geometrie ...")

    germany = gpd.read_file(
        SHAPEFILE
    )

    # --------------------------------------------------------
    # ERSTELLUNGSZEITPUNKT
    # --------------------------------------------------------

    created_at = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).to_pydatetime()

    # --------------------------------------------------------
    # TAGESDATEN SPEICHERN
    # --------------------------------------------------------

    daily_data = []

    # ========================================================
    # TAGESKARTEN
    # ========================================================

    for day_number, target_date in enumerate(
        forecast_dates,
        start=1
    ):

        print()
        print("=" * 65)
        print(
            f"PROGNOSETAG {day_number}: "
            f"{target_date.strftime('%d.%m.%Y')}"
        )
        print("=" * 65)

        # ----------------------------------------------------
        # MOSMIX VERARBEITEN
        # ----------------------------------------------------

        results, issue_time = process_mosmix(
            kmz_bytes,
            station_data,
            target_date
        )

        # ----------------------------------------------------
        # GEODATEN
        # ----------------------------------------------------

        gdf = create_geodata(results)

        if germany.crs is not None:

            gdf = gdf.to_crs(
                germany.crs
            )

        # ----------------------------------------------------
        # TAGESDATEN FÜR SUMMENKARTEN SPEICHERN
        # ----------------------------------------------------

        daily_data.append({

            "date": target_date,

            "gdf": gdf.copy(),

            "issue_time": issue_time,

        })

        # ----------------------------------------------------
        # ALLE SECHS INTERPOLIERTEN TAGESKARTEN
        # ----------------------------------------------------

        for parameter in PARAMETER_FILENAMES:

            print()
            print(
                f"Erstelle {PARAMETER_FILENAMES[parameter]}"
                f"_tag{day_number}.png"
            )

            create_forecast_map(
                germany=germany,
                gdf=gdf,
                parameter=parameter,
                target_date=target_date,
                day_number=day_number,
                created_at=created_at,
                issue_time=issue_time,
            )

    # ========================================================
    # SUMMENKARTEN
    # ========================================================

    print()
    print("=" * 65)
    print("ERSTELLE SUMMENKARTEN")
    print("=" * 65)

    for end_index in range(
        2,
        len(daily_data) + 1
    ):

        period = daily_data[:end_index]

        number_of_days = len(period)

        start_date = period[0]["date"]

        end_date = period[-1]["date"]

        issue_time = period[-1]["issue_time"]

        print()
        print(
            f"Summenzeitraum: "
            f"{start_date.strftime('%d.%m.%Y')} bis "
            f"{end_date.strftime('%d.%m.%Y')}"
        )

        for parameter in PERIOD_PARAMETERS:

            # ------------------------------------------------
            # SUMMEN BERECHNEN
            # ------------------------------------------------

            gdf = calculate_period_sum(
                [
                    item["gdf"]
                    for item in period
                ],
                parameter
            )

            if gdf is None:
                continue

            # ------------------------------------------------
            # SUMMENKARTE ERSTELLEN
            # ------------------------------------------------

            create_forecast_map(
                germany=germany,
                gdf=gdf,
                parameter=parameter,
                target_date=end_date,
                day_number=number_of_days,
                created_at=created_at,
                issue_time=issue_time,
                number_of_days=number_of_days,
            )

    # ========================================================
    # ABSCHLUSS
    # ========================================================

    daily_map_count = (
        len(forecast_dates)
        * len(PARAMETER_FILENAMES)
    )

    sum_map_count = (
        max(0, len(daily_data) - 1)
        * len(PERIOD_PARAMETERS)
    )

    print()
    print("=" * 65)
    print("ALLE PROGNOSEKARTEN FERTIG")
    print("=" * 65)

    print(f"Prognosetage: {len(forecast_dates)}")
    print(f"Tageskarten: {daily_map_count}")
    print(f"Summenkarten: {sum_map_count}")

    print(
        f"Gesamt: {daily_map_count + sum_map_count} Karten"
    )

    print(f"Ausgabeordner: {OUTPUT_DIR}")

    print("=" * 65)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
