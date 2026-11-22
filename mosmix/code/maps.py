
import os
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd

from config import (
    OUTPUT_DIR,
    SHAPEFILE,
    get_parameter_cmap,
    get_parameter_norm,
    get_period_norm,
    get_contrast_text_color
)


def create_map(data, parameter, day, filename):

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    germany = gpd.read_file(SHAPEFILE)

    fig, ax = plt.subplots(
        figsize=(12, 14)
    )

    germany.plot(
        ax=ax,
        color="#eeeeee",
        edgecolor="#777777",
        linewidth=0.5
    )

    values = data.dropna(
        subset=["latitude", "longitude", parameter]
    )

    cmap = get_parameter_cmap(parameter)

    norm = get_parameter_norm(parameter)

    ax.scatter(
        values["longitude"],
        values["latitude"],
        c=values[parameter],
        cmap=cmap,
        norm=norm,
        s=12,
        edgecolors="none"
    )

    ax.set_title(
        f"{parameter} – Tag {day}",
        fontsize=16
    )

    ax.axis("off")

    output_path = os.path.join(
        OUTPUT_DIR,
        filename
    )

    plt.savefig(
        output_path,
        dpi=150,
        bbox_inches="tight"
    )

    plt.close(fig)

    print(f"Gespeichert: {output_path}")
