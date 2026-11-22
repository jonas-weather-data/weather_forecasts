
import os

import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.cm import ScalarMappable

from config import (
    OUTPUT_DIR,
    SHAPEFILE,
    PARAMETERS,
    get_parameter_cmap,
    get_parameter_norm,
    get_period_norm
)


NAMES = {
    "TTT": "mittel",
    "RR1c": "niederschlag",
    "FX1": "wind",
    "TX": "tmax",
    "TN": "tmin",
    "SunD1": "sonne"
}


def create_map(data, parameter, day, column, filename, cumulative=False):

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    germany = gpd.read_file(SHAPEFILE)

    fig, ax = plt.subplots(figsize=(12, 14))

    germany.plot(
        ax=ax,
        color="#eeeeee",
        edgecolor="#777777",
        linewidth=0.5
    )

    values = data.dropna(
        subset=["latitude", "longitude", column]
    )

    cmap = get_parameter_cmap(parameter)

    if cumulative:
        norm = get_period_norm(parameter, day)
    else:
        norm = get_parameter_norm(parameter)

    ax.scatter(
        values["longitude"],
        values["latitude"],
        c=values[column],
        cmap=cmap,
        norm=norm,
        s=16,
        edgecolors="none"
    )

    unit = PARAMETERS[parameter]["name"]

    ax.set_title(
        f"{NAMES[parameter].capitalize()} – Tag {day}"
        + (" (kumuliert)" if cumulative else ""),
        fontsize=17,
        pad=15
    )

    colorbar = fig.colorbar(
        ScalarMappable(norm=norm, cmap=cmap),
        ax=ax,
        shrink=0.75,
        pad=0.02
    )

    colorbar.set_label(unit)

    ax.set_axis_off()

    fig.tight_layout()

    output_path = os.path.join(
        OUTPUT_DIR,
        filename + ".png"
    )

    fig.savefig(
        output_path,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(fig)

    print(f"Erstellt: {output_path}")


def create_all_maps(data):

    print("Erstelle Deutschlandkarten ...")

    if isinstance(data, tuple):
        data = data[0]

    if data.empty:
        raise ValueError(
            "Keine Prognosedaten für die Kartenerstellung vorhanden."
        )

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    required_columns = {
        "latitude",
        "longitude"
    }

    missing = required_columns - set(data.columns)

    if missing:
        raise ValueError(
            "Fehlende Stationskoordinaten: "
            + ", ".join(sorted(missing))
        )

    created = 0

    for parameter, name in NAMES.items():

        if parameter not in data.columns:
            continue

        if data[parameter].notna().sum() == 0:
            continue

        create_map(
            data=data,
            parameter=parameter,
            day=1,
            column=parameter,
            filename=f"{name}_tag1"
        )

        created += 1

    if created == 0:
        raise RuntimeError(
            "Keine Karten erstellt. "
            "Keine gültigen Parameterwerte vorhanden."
        )

    print(f"{created} Karten erfolgreich erstellt.")
    print(f"Ausgabeordner: {OUTPUT_DIR}")
    print("Alle Karten wurden erstellt.")
