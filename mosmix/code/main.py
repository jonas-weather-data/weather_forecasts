
import pandas as pd
import geopandas as gpd

from config import (
    OUTPUT_DIR,
    STATION_FILE,
    SHAPEFILE,
    PARAMETERS,
)

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
    "SunD1",
    "RR1c",
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

            station_values.append(float(match.iloc[0]))

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

    state_df = calculate_state_extremes(
        gdf,
        parameter
    )

    germany_extremes = calculate_germany_extremes(
        gdf,
        parameter
    )

    parameter_name = PARAMETER_FILENAMES[parameter]

    if number_of_days is None:

        filename = f"{parameter_name}_tag{day_number}.png"

    else:

        filename = f"{parameter_name}_bis_tag{day_number}.png"

    output_file = OUTPUT_DIR / filename

    print(f"Erstelle {filename} ...")

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

    print("=" * 65)
    print("MOSMIX – DEUTSCHLAND PROGNOSEKARTEN")
    print("=" * 65)

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    ) if hasattr(OUTPUT_DIR, "mkdir") else __import__("pathlib").Path(OUTPUT_DIR).mkdir(
        parents=True,
        exist_ok=True
    )

    # --------------------------------------------------------
    # STATIONSDATEN
    # --------------------------------------------------------

    station_data = load_station_data(STATION_FILE)

    # --------------------------------------------------------
    # MOSMIX DOWNLOAD
    # --------------------------------------------------------

    kmz_bytes = download_mosmix()

    # --------------------------------------------------------
    # PROGNOSETAGE
    # --------------------------------------------------------

    forecast_dates = get_forecast_dates(kmz_bytes)[:10]

    print(f"{len(forecast_dates)} Prognosetage gefunden.")

    # --------------------------------------------------------
    # DEUTSCHLAND-GEOMETRIE
    # --------------------------------------------------------

    germany = gpd.read_file(SHAPEFILE)

    # --------------------------------------------------------
    # ERSTELLUNGSZEITPUNKT
    # --------------------------------------------------------

    created_at = pd.Timestamp.now(
        tz="Europe/Berlin"
    ).to_pydatetime()

    daily_data = []

    # ========================================================
    # TAGESKARTEN
    # ========================================================

    for day_number, target_date in enumerate(
        forecast_dates,
        start=1
    ):

        print()
        print(
            f"PROGNOSETAG {day_number}: "
            f"{target_date.strftime('%d.%m.%Y')}"
        )

        results, issue_time = process_mosmix(
            kmz_bytes,
            station_data,
            target_date
        )

        gdf = create_geodata(results)

        if germany.crs is not None:
            gdf = gdf.to_crs(germany.crs)

        daily_data.append({
            "date": target_date,
            "gdf": gdf.copy(),
            "issue_time": issue_time,
        })

        # ----------------------------------------------------
        # SECHS INTERPOLIERTE TAGESKARTEN
        # ----------------------------------------------------

        for parameter in PARAMETERS:

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
    print("ERSTELLE SUMMENKARTEN")

    for end_index in range(2, len(daily_data) + 1):

        period = daily_data[:end_index]

        number_of_days = len(period)

        end_date = period[-1]["date"]
        issue_time = period[-1]["issue_time"]

        for parameter in PERIOD_PARAMETERS:

            gdf = calculate_period_sum(
                [item["gdf"] for item in period],
                parameter
            )

            if gdf is None:
                continue

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

    daily_count = len(forecast_dates) * len(PARAMETERS)

    sum_count = max(0, len(daily_data) - 1) * len(PERIOD_PARAMETERS)

    print()
    print("=" * 65)
    print("ALLE PROGNOSEKARTEN FERTIG")
    print(f"Tageskarten: {daily_count}")
    print(f"Summenkarten: {sum_count}")
    print(f"Gesamt: {daily_count + sum_count}")
    print(f"Ausgabeordner: {OUTPUT_DIR}")
    print("=" * 65)


if __name__ == "__main__":
    main()
