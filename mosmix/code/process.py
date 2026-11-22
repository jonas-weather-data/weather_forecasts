
import zipfile
import xml.etree.ElementTree as ET

import pandas as pd


def process_mosmix(file_path):

    print("Verarbeite MOSMIX-Daten ...")

    with zipfile.ZipFile(file_path, "r") as archive:

        kml_file = next(
            name for name in archive.namelist()
            if name.endswith(".kml")
        )

        with archive.open(kml_file) as file:
            root = ET.parse(file).getroot()

    ns = {
        "kml": "http://www.opengis.net/kml/2.2"
    }

    data = {}

    for placemark in root.findall(
        ".//kml:Placemark",
        ns
    ):

        station = placemark.findtext(
            "kml:ExtendedData/kml:SchemaData/"
            "kml:SimpleData[@name='station_id']",
            namespaces=ns
        )

        if not station:
            continue

        values = {}

        for element in placemark.findall(
            ".//kml:SimpleData",
            ns
        ):

            name = element.attrib.get("name")

            if name:
                values[name] = element.text

        data[station] = values

    print(f"{len(data)} Stationen verarbeitet.")

    return pd.DataFrame.from_dict(
        data,
        orient="index"
    )
