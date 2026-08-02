import pandas as pd
import xarray as xr
from pathlib import Path
from ecmwf.opendata import Client
from config import FORECAST_DIR
from config import NORMALIZED_DIR
from processing.normalise_forecast import normalize_forecast

def download_ecmwf_member(
    system,
    member,
    date,
    run
):
    # ---------------------------------------------------------
    # Create output folder
    # ---------------------------------------------------------
    model_dir = (
        FORECAST_DIR
        / system
        / member
    )
    model_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    outfile = (
        model_dir
        /
        f"{member}_{date}_{run}Z.grib"
    )
    # ---------------------------------------------------------
    # Create client
    # ---------------------------------------------------------
    if system == "IFS":
        client = Client(
            source="ecmwf",
            model="ifs"
        )
    elif system == "AIFS":
        if member == "AIFS":
            client = Client(
                source="ecmwf",
                model="aifs-single"
            )
        else:
            client = Client(
                source="ecmwf",
                model="aifs-ens"
            )
    else:
        raise ValueError(f"Unknown system: {system}")
    # ---------------------------------------------------------
    # Build request
    # ---------------------------------------------------------
    if system == "IFS":
        max_step = 240
    elif system == "AIFS":
        max_step = 360
    else:
        raise ValueError(f"Unknown system: {system}")
    if member in ("HRES", "AIFS"):
        request = {
            "date": date,
            "time": run,
            "step": f"0/to/{max_step}/by/6",
            "type": "fc",
            "param": "2t",
            "levtype": "sfc",
        }
    else:
        request = {
            "date": date,
            "time": run,
            "step": f"0/to/{max_step}/by/6",
            "type": "pf",
            "number": int(member.replace("P", "")),
            "param": "2t",
            "levtype": "sfc",
        }
    # ---------------------------------------------------------
    # Download GRIB
    # ---------------------------------------------------------
    print(
        "Downloading", system, member)
    client.retrieve(
        request,
        str(outfile)
    )
    print("[OK]", outfile)

    ds = xr.open_dataset(
        outfile,
        engine="cfgrib"
    )

    temperature = ds["t2m"].values - 273.15

    latitude = ds["latitude"].values
    longitude = ds["longitude"].values

    valid_times = ds["valid_time"].values
    init_time = pd.Timestamp(
        ds["time"].values
    )
    normalized = normalize_forecast(
        temperature=temperature,
        latitude=latitude,
        longitude=longitude,
        valid_times=valid_times,
        init_time=init_time,
        model_name=system,
    )
    normalised_dir = (
        NORMALIZED_DIR
        /
        system
        /
        member
    )
    normalised_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    normalised_file = (
        normalised_dir
        /
        f"{member}_{date}_{run}Z.nc"
    )
    normalized.to_netcdf(
        normalised_file
    )
    ds.close()
    print(
        "[OK] Saved",
        normalised_file
    )
    return normalised_file

def download_ecmwf(
    system,
    date,
    run
):
    if system == "IFS":
        members = [
            "HRES",
            *[f"P{i:02d}" for i in range(1, 51)]
        ]
    else:
        members = [
            "AIFS",
            *[f"P{i:02d}" for i in range(1, 51)]
        ]
    for member in members:
        download_ecmwf_member(
            system=system,
            member=member,
            date=date,
            run=run
        )

if __name__ == "__main__":

    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--member",
        default="HRES",
        help="HRES, C00 or P01-P50"
    )
    parser.add_argument(
        "--ensemble",
        action="store_true",
        help="Download the complete ensemble for the selected ECMWF system"
    )
    parser.add_argument(
        "--date",
        required=True,
        help="YYYYMMDD"
    )
    parser.add_argument(
        "--run",
        default="00",
        help="00 or 12"
    )
    parser.add_argument(
        "--system",
        default="IFS",
        choices=["IFS", "AIFS"]
    )
    args = parser.parse_args()

    if args.ensemble:
        download_ecmwf(
            system=args.system,
            date=args.date,
            run=args.run
        )
    else:
        download_ecmwf_member(
            system=args.system,
            member=args.member,
            date=args.date,
            run=args.run
        )