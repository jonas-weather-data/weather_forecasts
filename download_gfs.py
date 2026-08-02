from datetime import datetime
from pathlib import Path
import argparse
import numpy as np
import pandas as pd
from utils.grib import open_grib
import requests
import time
from processing.normalise_forecast import normalize_forecast
from processing.elevation import build_model_elevation
from config import (
    FORECAST_DIR,
    NORMALIZED_DIR,
    LAT_MIN,
    LAT_MAX,
    LON_MIN,
    LON_MAX,
)

BASE_URL = (
    "https://nomads.ncep.noaa.gov/"
    "pub/data/nccf/com/gfs/prod"
)

def build_url(
    run_date,
    run_hour,
    forecast_hour,
    member="GFS"
):
    """
    Build the download URL for either the deterministic GFS
    or a GEFS ensemble member.

    Parameters
    ----------
    run_date : datetime
    run_hour : str
        "00", "06", "12" or "18"
    forecast_hour : int
    member : str
        "GFS", "C00", "P01" ... "P30"

    Returns
    -------
    str
    """

    date_string = run_date.strftime("%Y%m%d")
    # ----------------------------------------------------------
    # Deterministic GFS
    # ----------------------------------------------------------
    if member == "GFS":
        filename = (
            f"gfs.t{run_hour}z.pgrb2.0p25."
            f"f{forecast_hour:03d}"
        )
        directory = (
            f"/gfs.{date_string}/{run_hour}/atmos"
        )
        return (
            "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?"
            f"file={filename}"
            "&lev_2_m_above_ground=on"
            "&var_TMP=on"
            "&subregion="
            f"&leftlon={LON_MIN}"
            f"&rightlon={LON_MAX}"
            f"&toplat={LAT_MAX}"
            f"&bottomlat={LAT_MIN}"
            f"&dir={directory.replace('/', '%2F')}"
        )
    # ----------------------------------------------------------
    # GEFS Control
    # ----------------------------------------------------------
    if member == "C00":
        prefix = "gec00"
    # ----------------------------------------------------------
    # GEFS Perturbed Members P01-P30
    # ----------------------------------------------------------
    elif member.startswith("P"):
        prefix = f"gep{member[1:]}"
    else:
        raise ValueError(
            f"Unknown member '{member}'"
        )
    filename = (
        f"{prefix}.t{run_hour}z."
        f"pgrb2a.0p50.f{forecast_hour:03d}"
    )
    directory = (
        f"/gefs.{date_string}/"
        f"{run_hour}/"
        "atmos/pgrb2ap5"
    )
    return (
        "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl?"
        f"file={filename}"
        "&lev_2_m_above_ground=on"
        "&var_TMP=on"
        "&subregion="
        f"&leftlon={LON_MIN}"
        f"&rightlon={LON_MAX}"
        f"&toplat={LAT_MAX}"
        f"&bottomlat={LAT_MIN}"
        f"&dir={directory.replace('/', '%2F')}"
    )

def download_file(
    url,
    outfile,
    retries=5
):
    """
    Download a file with retries and streaming.
    """

    headers = {
        "User-Agent": "Mozilla/5.0"
    }
    for attempt in range(1, retries + 1):
        try:
            print(
                f"Download attempt {attempt}/{retries}"
            )
            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=(30, 600) #first value is connection timeout (30 s), second is download/read timeout (10 minutes)
            ) as r:
                print(
                    "HTTP status:",
                    r.status_code
                )
                print(
                    "Content length:",
                    r.headers.get("Content-Length")
                )
                r.raise_for_status()

                with open(outfile, "wb") as f:

                    for chunk in r.iter_content(
                        chunk_size=1024*1024
                    ):
                        if chunk:
                            f.write(chunk)
            return

        except Exception as e:
            print(
                f"Attempt {attempt} failed:",
                e
            )
            if attempt < retries:
                time.sleep(5)
            else:
                raise
        time.sleep(2)

def read_gfs_grib(
    filename
):
    """
    Extract 2 m temperature from GFS GRIB.
    Returns
    -------
    temperature : ndarray
        °C
    latitude : ndarray
        2D latitude grid
    longitude : ndarray
        2D longitude grid
    valid_time : Timestamp
    """

    ds = open_grib(
        filename,
        filter_by_keys={
            "typeOfLevel": "heightAboveGround",
            "level": 2
        }
    )
    temperature = (
        ds["t2m"].values
        - 273.15
    )
    latitude = ds.latitude.values
    longitude = ds.longitude.values
    valid_time = pd.Timestamp(
        ds.valid_time.values
    )
    return (
        temperature,
        latitude,
        longitude,
        valid_time
    )

def download_gfs(
    run_date,
    run_hour="00",
    max_fhr=384,
    member='GFS'
):
    """
    Download and normalize a GFS forecast run.

    Parameters
    ----------
    run_date : datetime
        Date of model initialization.

    run_hour : str
        Model cycle hour ("00", "06", "12", "18").

    max_fhr : int
        Maximum forecast hour.

    Returns
    -------
    Path
        Normalized NetCDF file.
    """
    # temporary storage for GRIB files
    forecast_dir = (
        FORECAST_DIR
        / "GFS"
        / member
    )
    forecast_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    temperature_fields = []
    valid_times = []

    latitude = None
    longitude = None
    # ---------------------------------------------------------------
    # Download all forecast hours
    # ---------------------------------------------------------------
    for fhr in range(0, max_fhr + 1, 6):
        url = build_url(
            run_date,
            run_hour,
            fhr,
            member
        )
        grib_file = (
            forecast_dir
            / f"{member}_{run_date:%Y%m%d}_{run_hour}Z_f{fhr:03d}.grib2"
        )
        print(
            f"Downloading GFS {run_hour}Z"
            f"forecast hour {fhr}"
        )
        try:
            print("Downloading...")
            download_file(
                url,
                grib_file
            )
        except Exception as e:
            print(
                "Download failed:",
                fhr,
                e
            )
            continue
        try:
            print("Reading GRIB...")
            (
                temperature,
                latitude,
                longitude,
                valid_time
            ) = read_gfs_grib(
                grib_file
            )
            temperature_fields.append(
                temperature
            )
            valid_times.append(
                valid_time
            )
        except Exception as e:
            print(
                "GRIB reading failed:",
                fhr,
                e
            )
            continue
    if len(temperature_fields) == 0:

        raise RuntimeError(
            "No GFS forecast fields downloaded."
        )
    # ---------------------------------------------------------------
    # Combine forecast times
    # ---------------------------------------------------------------
    temperature = np.stack(
        temperature_fields,
        axis=0
    )
    # ---------------------------------------------------------------
    # Normalize
    # ---------------------------------------------------------------
    init_time = pd.Timestamp(
        run_date
    ).replace(
        hour=int(run_hour)
    )
    normalized = normalize_forecast(
        temperature=temperature,
        latitude=latitude,
        longitude=longitude,
        valid_times=valid_times,
        init_time=init_time,
        model_name="GFS"
    )
    # ---------------------------------------------------------------
    # Save
    # ---------------------------------------------------------------
    member_dir = NORMALIZED_DIR / "GFS" / member

    member_dir.mkdir(
        parents=True,
        exist_ok=True
    )
    outfile = (
        member_dir
        /
        f"{member}_{run_date:%Y%m%d}_{run_hour}Z.nc"
    )
    normalized.to_netcdf(
        outfile
    )
    print(
        f"[OK] Saved {outfile}"
    )
    return outfile

def download_gefs(
    run_date,
    run_hour,
    max_fhr
):
    members = [
        "GFS",
        "C00",
        *[f"P{i:02d}" for i in range(1, 31)]
    ]
    files = {}

    for member in members:
        print(f"\n=====Downloading {member} =====")
        try:
            files[member] = download_gfs(
                run_date=run_date,
                run_hour=run_hour,
                max_fhr=max_fhr,
                member=member
            )
        except Exception as e:
            print(f"Failed {member}: {e}")
    return files

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--member",
        default="GFS"
    )
    parser.add_argument(
        "--ensemble",
        action="store_true",
        help="Download the full GEFS ensemble (GFS, C00 and P01-P30)"
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None
    )
    parser.add_argument(
        "--run",
        type=str,
        default="00"
    )
    parser.add_argument(
        "--max-fhr",
        type=int,
        default=384
    )
    args = parser.parse_args()

    if args.date is None:
        run_date = datetime.utcnow()
    else:
        run_date = datetime.strptime(
            args.date,
            "%Y%m%d"
        )
    if args.ensemble:
        download_gefs(
            run_date=run_date,
            run_hour=args.run,
            max_fhr=args.max_fhr
        )
    else:
        download_gfs(
            run_date=run_date,
            run_hour=args.run,
            max_fhr=args.max_fhr,
            member=args.member
        )