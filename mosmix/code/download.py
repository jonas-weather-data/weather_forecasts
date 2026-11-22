
import os
import requests

from config import (
    DATA_DIR,
    MOSMIX_URL,
    REQUEST_TIMEOUT
)


def download_mosmix():

    os.makedirs(DATA_DIR, exist_ok=True)

    file_path = os.path.join(
        DATA_DIR,
        "mosmix.kmz"
    )

    print("Lade aktuelle DWD-MOSMIX-Daten herunter ...")

    response = requests.get(
        MOSMIX_URL,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    with open(file_path, "wb") as file:
        file.write(response.content)

    print("Download abgeschlossen.")

    return file_path
