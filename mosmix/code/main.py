
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from download import download_mosmix
from process import process_mosmix
from maps import create_all_maps


def main():
    print("=== DWD MOSMIX Kartenproduktion ===")

    kmz_file = download_mosmix()

    forecast_data = process_mosmix(kmz_file)

    create_all_maps(forecast_data)

    print("=== Fertig ===")


if __name__ == "__main__":
    main()
