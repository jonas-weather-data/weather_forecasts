from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import BytesIO
import zipfile
import requests
import pandas as pd
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import re
import os
import threading


# ============================================================
# MATPLOTLIB: GitHub Actions
# ============================================================

if os.environ.get('GITHUB_ACTIONS') == 'true':
    matplotlib.use('Agg')


# ============================================================
# MANUELL ZU PFLEGEN
#
# record       = bisheriger Stationsrekord
# record_year  = Jahr des Stationsrekords
# current_2026 = bisherige Sonnenscheindauer im laufenden Jahr
#
# current_2026 wird manuell gepflegt.
# Der DWD liefert ausschließlich die Werte des laufenden Monats.
# ============================================================

STATIONS = {
    '00183': {'record': 2187.4, 'record_year': 2018, 'current_2026': 1915.5},
    '00232': {'record': 2175.2, 'record_year': 1949, 'current_2026': 1897.1},
    '00403': {'record': 2188.0, 'record_year': 2022, 'current_2026': 1868.1},
    '00460': {'record': 2153.1, 'record_year': 1959, 'current_2026': 1840.0},
    '00596': {'record': 2105.7, 'record_year': 1947, 'current_2026': 1677.9},
    '00662': {'record': 2128.2, 'record_year': 2018, 'current_2026': 1753.5},
    '00691': {'record': 2062.6, 'record_year': 2018, 'current_2026': 1669.1},
    '00701': {'record': 1973.0, 'record_year': 2003, 'current_2026': 999.7},
    '00853': {'record': 2119.0, 'record_year': 2011, 'current_2026': 1588.8},
    '00856': {'record': 2090.1, 'record_year': 2011, 'current_2026': 1872.8},
    '00867': {'record': 2058.9, 'record_year': 2022, 'current_2026': 1863.7},
    '00963': {'record': 1968.7, 'record_year': 2022, 'current_2026': 1371.4},
    '01048': {'record': 2119.5, 'record_year': 2018, 'current_2026': 1796.8},
    '01303': {'record': 2058.8, 'record_year': 2022, 'current_2026': 1674.9},
    '01346': {'record': 2103.5, 'record_year': 2003, 'current_2026': 1874.7},
    '01358': {'record': 1968.9, 'record_year': 2003, 'current_2026': 1691.9},
    '01420': {'record': 2241.9, 'record_year': 2022, 'current_2026': 1894.0},
    '01443': {'record': 2073.9, 'record_year': 2020, 'current_2026': 1960.9},
    '01639': {'record': 2169.8, 'record_year': 2003, 'current_2026': 1644.7},
    '01684': {'record': 2162.5, 'record_year': 2011, 'current_2026': 1839.7},
    '01832': {'record': 1960.5, 'record_year': 2025, 'current_2026': 1331.4},
    '01975': {'record': 2040.7, 'record_year': 1947, 'current_2026': 1602.3},
    '02115': {'record': 2078.0, 'record_year': 1959, 'current_2026': 1669.7},
    '02290': {'record': 2266.4, 'record_year': 2022, 'current_2026': 2044.6},
    '02483': {'record': 2051.3, 'record_year': 1959, 'current_2026': 1671.6},
    '02601': {'record': 2199.7, 'record_year': 1959, 'current_2026': 1647.6},
    '02638': {'record': 2329.2, 'record_year': 1959, 'current_2026': 1885.8},
    '02667': {'record': 2063.5, 'record_year': 2003, 'current_2026': 1654.1},
    '02712': {'record': 2256.1, 'record_year': 2022, 'current_2026': 2001.1},
    '02925': {'record': 2050.1, 'record_year': 1959, 'current_2026': 1698.8},
    '02932': {'record': 2085.6, 'record_year': 2003, 'current_2026': 1858.6},
    '03015': {'record': 2200.0, 'record_year': 2018, 'current_2026': 1788.0},
    '03098': {'record': 1853.1, 'record_year': 2022, 'current_2026': 1603.7},
    '03287': {'record': 2180.8, 'record_year': 2003, 'current_2026': 1775.1},
    '03366': {'record': 2177.2, 'record_year': 2003, 'current_2026': 1883.3},
    '03379': {'record': 2281.8, 'record_year': 2022, 'current_2026': 2041.1},
    '03631': {'record': 2071.6, 'record_year': 2022, 'current_2026': 1433.2},
    '03660': {'record': 2067.9, 'record_year': 2003, 'current_2026': 1495.5},
    '03668': {'record': 2181.5, 'record_year': 2018, 'current_2026': 1992.4},
    '03987': {'record': 2246.7, 'record_year': 2018, 'current_2026': 1523.4},
    '04271': {'record': 2190.0, 'record_year': 2018, 'current_2026': 1786.3},
    '04336': {'record': 2269.9, 'record_year': 2003, 'current_2026': 1924.6},
    '04393': {'record': 2119.8, 'record_year': 1959, 'current_2026': 1718.2},
    '04466': {'record': 2135.8, 'record_year': 1959, 'current_2026': 1405.4},
    '04642': {'record': 2195.7, 'record_year': 2018, 'current_2026': 1769.2},
    '04887': {'record': 2079.7, 'record_year': 2022, 'current_2026': 1656.6},
    '04928': {'record': 2272.4, 'record_year': 2022, 'current_2026': 1433.2},
    '05100': {'record': 2143.2, 'record_year': 2003, 'current_2026': 1842.8},
    '05142': {'record': 2171.8, 'record_year': 2018, 'current_2026': 1801.8},
    '05397': {'record': 2124.3, 'record_year': 2003, 'current_2026': 1172.4},
    '05404': {'record': 2252.2, 'record_year': 1949, 'current_2026': 1491.4},
    '05426': {'record': 2256.5, 'record_year': 2003, 'current_2026': 1841.7},
    '05480': {'record': 2021.7, 'record_year': 2018, 'current_2026': 1707.8},
    '05705': {'record': 2188.5, 'record_year': 2003, 'current_2026': 1607.8},
    '05779': {'record': 1895.3, 'record_year': 2003, 'current_2026': 1664.8},
    '05792': {'record': 2242.8, 'record_year': 2011, 'current_2026': 1808.6},
    '05856': {'record': 2206.3, 'record_year': 2003, 'current_2026': 1731.2},
    '05906': {'record': 2252.1, 'record_year': 2003, 'current_2026': 1889.9},
    '06105': {'record': 1911.0, 'record_year': 2022, 'current_2026': 1609.8},
    '06163': {'record': 1938.4, 'record_year': 2018, 'current_2026': 1431.8},
    '06197': {'record': 1719.6, 'record_year': 2020, 'current_2026': 1656.5},
    '07370': {'record': 1933.5, 'record_year': 2025, 'current_2026': 1631.2},
    '15000': {'record': 2056.5, 'record_year': 2025, 'current_2026': 1822.1},
    '15444': {'record': 2213.6, 'record_year': 2022, 'current_2026': 1946.5}
}

# ============================================================
# DEUTSCHLANDMITTEL – MANUELL ZU PFLEGEN
#
# germany_record       = bisheriger Rekord des Deutschlandmittels
# germany_record_year  = Jahr dieses Rekords
# germany_current_2026 = bisherige Menge 2026 vor dem laufenden
#                        Monat
#
# HIER DEINE DREI WERTE EINTRAGEN.
# ============================================================

GERMANY_RECORD = 2024.1
GERMANY_RECORD_YEAR = 2022
GERMANY_CURRENT_2026 = 1783.0

GERMANY_MONTH_FACTOR = 0.9897


# ============================================================
# KONFIGURATION
# ============================================================

MAX_WORKERS = 16

STATIONS_URL = (
    'https://opendata.dwd.de/climate_environment/CDC/'
    'observations_germany/climate/daily/kl/historical/'
    'KL_Tageswerte_Beschreibung_Stationen.txt'
)

RECENT_URL = (
    'https://opendata.dwd.de/climate_environment/CDC/'
    'observations_germany/climate/daily/kl/recent/'
)

SHAPEFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'gadm41_DEU_1.json'
)

TARGET_STATIONS = set(STATIONS.keys())


# ============================================================
# AKTUELLES DATUM
#
# Auswertung immer nur bis einschließlich VORTAG.
# Der heutige Tag wird nicht berücksichtigt, da dessen
# Sonnenscheindauer noch nicht vollständig feststeht.
# ============================================================

TODAY = date.today()
DATA_DATE = TODAY - timedelta(days=1)

CURRENT_YEAR = DATA_DATE.year
CURRENT_MONTH = DATA_DATE.month
CURRENT_DAY = DATA_DATE.day

MONTH_NAMES = {
    1: 'Januar',
    2: 'Februar',
    3: 'März',
    4: 'April',
    5: 'Mai',
    6: 'Juni',
    7: 'Juli',
    8: 'August',
    9: 'September',
    10: 'Oktober',
    11: 'November',
    12: 'Dezember'
}

CURRENT_MONTH_NAME = MONTH_NAMES[CURRENT_MONTH]


# ============================================================
# FORTSCHRITTSANZEIGE
# ============================================================

progress_lock = threading.Lock()
completed = 0


def log(message):
    print(message, flush=True)


# ============================================================
# STATIONSMETADATEN LADEN
# ============================================================

def load_station_meta():
    log('[1/5] Lade Stationsmetadaten vom DWD ...')

    response = requests.get(
        STATIONS_URL,
        timeout=120
    )
    response.raise_for_status()

    txt = response.content.decode('cp1252')
    lines = txt.replace('\r\n', '\n').split('\n')

    header = next(
        i for i, line in enumerate(lines)
        if line.startswith('Stations_id')
    )

    result = {}

    for line in lines[header + 1:]:
        try:
            sid = line[0:5].strip()

            if sid not in TARGET_STATIONS:
                continue

            result[sid] = {
                'lat': float(
                    line[43:50].strip().replace(',', '.')
                ),
                'lon': float(
                    line[53:60].strip().replace(',', '.')
                ),
                'name': line[61:101].strip()
            }

        except (ValueError, IndexError):
            continue

    log(
        f'      {len(result)} von '
        f'{len(TARGET_STATIONS)} Stationen gefunden.'
    )

    missing = TARGET_STATIONS - set(result)

    if missing:
        log(
            '      WARNUNG: Nicht gefundene Stationen: '
            + ', '.join(sorted(missing))
        )

    return result


# ============================================================
# DWD-DATEIEN ERMITTELN
# ============================================================

def get_zip_files():
    log('[2/5] Ermittle DWD-Stationsdateien ...')

    response = requests.get(
        RECENT_URL,
        timeout=120
    )
    response.raise_for_status()

    files = re.findall(
        r'href="(tageswerte_KL_\d+_.*?\.zip)"',
        response.text
    )

    station_files = [
        filename
        for filename in files
        if filename.split('_')[2] in TARGET_STATIONS
    ]

    log(
        f'      {len(station_files)} passende Stationsdateien gefunden.'
    )

    return station_files


# ============================================================
# EINZELNE STATION VERARBEITEN
# ============================================================

def process_station(file_name, meta, total_stations):
    global completed

    sid = file_name.split('_')[2]
    station_name = meta[sid]['name']

    log(
        f'      [{sid}] Download gestartet: {station_name}'
    )

    response = requests.get(
        RECENT_URL + file_name,
        timeout=120
    )
    response.raise_for_status()

    log(
        f'      [{sid}] Download fertig – lese Messdaten ...'
    )

    with zipfile.ZipFile(BytesIO(response.content)) as z:
        csv_file = next(
            filename
            for filename in z.namelist()
            if filename.startswith('produkt_klima_tag')
        )

        with z.open(csv_file) as f:
            df = pd.read_csv(
                f,
                sep=';',
                encoding='cp1252',
                dtype=str
            )

    df.columns = [
        column.strip()
        for column in df.columns
    ]

    df['MESS_DATUM'] = pd.to_datetime(
        df['MESS_DATUM'],
        format='%Y%m%d',
        errors='coerce'
    )

    # ========================================================
    # AUSSCHLIESSLICH:
    # - Jahr des Datenstichtags
    # - Monat des Datenstichtags
    # - bis einschließlich VORTAG
    #
    # Keine vorherigen Monate.
    # Kein heutiger Tag.
    # Keine späteren Tage.
    # ========================================================

    current_month = df[
        (df['MESS_DATUM'].dt.year == CURRENT_YEAR)
        & (df['MESS_DATUM'].dt.month == CURRENT_MONTH)
        & (df['MESS_DATUM'].dt.day <= CURRENT_DAY)
    ].copy()

    current_month['SDK'] = pd.to_numeric(
        current_month['SDK'],
        errors='coerce'
    )

    current_month['SDK'] = current_month['SDK'].replace(
        -999,
        np.nan
    )

    monthly_sum = float(
        current_month['SDK'].sum()
    )

    # Auf eine Nachkommastelle runden.
    monthly_sum = round(monthly_sum, 1)

    number_of_days = int(
        current_month['SDK'].notna().sum()
    )

    # ========================================================
    # STATIONS-JAHRESWERT
    #
    # Manuell gepflegte bisherige Menge 2026
    # +
    # automatisch ermittelte Menge des laufenden Monats
    # ========================================================

    current = round(
        STATIONS[sid]['current_2026'] + monthly_sum,
        1
    )

    record = round(
        STATIONS[sid]['record'],
        1
    )

    remaining = round(
        record - current,
        1
    )

    result = {
        'station_id': sid,
        'lat': meta[sid]['lat'],
        'lon': meta[sid]['lon'],
        'current': current,
        'monthly_sum': monthly_sum,
        'record': record,
        'record_year': STATIONS[sid]['record_year'],
        'remaining': remaining
    }

    with progress_lock:
        completed += 1

        log(
            f'      [{completed}/{total_stations}] '
            f'{sid} fertig: '
            f'{monthly_sum:.1f} h im {CURRENT_MONTH_NAME}, '
            f'{current:.1f} h 2026, '
            f'Rest zum Rekord: {remaining:.1f} h'
        )

    return result


# ============================================================
# DEUTSCHLANDMITTEL
# ============================================================

def calculate_germany_mean(results):
    """
    Separates Deutschlandmittel:

    bisherige Deutschlandmenge 2026
    +
    Mittelwert der Stations-Monatssummen * 0.9897
    """

    if GERMANY_CURRENT_2026 is None:
        raise ValueError(
            'GERMANY_CURRENT_2026 wurde noch nicht gesetzt.'
        )

    if not results:
        raise ValueError(
            'Keine Stationsdaten für Deutschlandmittel vorhanden.'
        )

    station_monthly_sums = [
        result['monthly_sum']
        for result in results.values()
    ]

    station_monthly_mean = round(
        float(np.mean(station_monthly_sums)),
        1
    )

    germany_month_increment = round(
        station_monthly_mean * GERMANY_MONTH_FACTOR,
        1
    )

    germany_current = round(
        GERMANY_CURRENT_2026
        + germany_month_increment,
        1
    )

    return {
        'previous': round(GERMANY_CURRENT_2026, 1),
        'station_monthly_mean': station_monthly_mean,
        'factor': GERMANY_MONTH_FACTOR,
        'month_increment': germany_month_increment,
        'current': germany_current,
        'record': (
            None
            if GERMANY_RECORD is None
            else round(GERMANY_RECORD, 1)
        ),
        'record_year': GERMANY_RECORD_YEAR
    }


# ============================================================
# KARTE ERSTELLEN
# ============================================================

def create_map(
    results,
    mode,
    title,
    outfile,
    cmap,
    germany_mean=None
):
    log(f'      Erstelle {outfile} ...')

    gdf = gpd.read_file(SHAPEFILE)

    fig, ax = plt.subplots(
        figsize=(12, 14)
    )

    gdf.plot(
        color='white',
        edgecolor='black',
        linewidth=0.5,
        ax=ax
    )

    xs = []
    ys = []
    vals = []

    for result in results.values():
        xs.append(result['lon'])
        ys.append(result['lat'])
        vals.append(result[mode])

    sc = ax.scatter(
        xs,
        ys,
        c=vals,
        cmap=cmap,
        s=35,
        zorder=10
    )

    for result in results.values():

        if mode == 'record':
            txt = (
                f"{result['record']:.1f}\n"
                f"({result['record_year']})"
            )
        else:
            txt = f"{result[mode]:.1f}"

        ax.text(
            result['lon'] + 0.03,
            result['lat'] + 0.02,
            txt,
            fontsize=9
        )

    plt.colorbar(sc, ax=ax)

    # ========================================================
    # DEUTSCHLANDMITTEL
    #
    # Aktuelle Jahreskarte:
    # Deutschlandmittel aktuell + Rekord
    #
    # Restkarte:
    # Fehlende Stunden bis zum Deutschland-Rekord
    # ========================================================

    if mode == 'current' and germany_mean is not None:

        germany_text = (
            f"Deutschlandmittel: "
            f"{germany_mean['current']:.1f} h"
        )

        fig.text(
            0.5,
            0.035,
            germany_text,
            ha='center',
            fontsize=12,
            fontweight='bold'
        )

        if (
            germany_mean['record'] is not None
            and germany_mean['record_year'] is not None
        ):
            record_text = (
                f"Deutschland-Rekord: "
                f"{germany_mean['record']:.1f} h "
                f"({germany_mean['record_year']})"
            )

            fig.text(
                0.5,
                0.015,
                record_text,
                ha='center',
                fontsize=10
            )

    elif mode == 'remaining' and germany_mean is not None:

        if (
            germany_mean['record'] is not None
            and germany_mean['current'] is not None
        ):
            germany_remaining = round(
                germany_mean['record']
                - germany_mean['current'],
                1
            )

            germany_text = (
                f"Deutschlandmittel: noch "
                f"{germany_remaining:.1f} h bis zum Rekord"
            )

            fig.text(
                0.5,
                0.035,
                germany_text,
                ha='center',
                fontsize=12,
                fontweight='bold'
            )

            if germany_mean['record_year'] is not None:
                record_text = (
                    f"Deutschland-Rekord: "
                    f"{germany_mean['record']:.1f} h "
                    f"({germany_mean['record_year']})"
                )

                fig.text(
                    0.5,
                    0.015,
                    record_text,
                    ha='center',
                    fontsize=10
                )

    ax.set_title(title)
    ax.axis('off')

    plt.savefig(
        outfile,
        dpi=250,
        bbox_inches='tight'
    )

    plt.close()

    log(f'      Fertig: {outfile}')


# ============================================================
# HAUPTPROGRAMM
# ============================================================

log('')
log('=' * 70)
log('SONNENSCHEIN-AUSWERTUNG')
log('=' * 70)

log(
    f'Datum:              {TODAY.strftime("%d.%m.%Y")}'
)

log(
    f'Datenstand:         {DATA_DATE.strftime("%d.%m.%Y")}'
)

log(
    f'Laufender Monat:    '
    f'{CURRENT_MONTH_NAME} {CURRENT_YEAR}'
)

log(
    f'DWD-Auswertung:     '
    f'01.{CURRENT_MONTH:02d}.{CURRENT_YEAR} '
    f'bis '
    f'{CURRENT_DAY:02d}.{CURRENT_MONTH:02d}.{CURRENT_YEAR}'
)

log(
    f'Basis Stationswert: manuell gepflegte Menge 2026'
)

log(
    f'Stationen:          {len(TARGET_STATIONS)}'
)

log('=' * 70)
log('')


# ============================================================
# 1. STATIONSMETADATEN
# ============================================================

meta = load_station_meta()


# ============================================================
# 2. DWD-DATEIEN
# ============================================================

files = get_zip_files()

if not files:
    log('')
    log(
        'FEHLER: Keine passenden DWD-Stationsdateien gefunden.'
    )
    raise SystemExit(1)


# ============================================================
# 3. STATIONEN VERARBEITEN
# ============================================================

log('[3/5] Verarbeite Stationsdaten ...')
log(
    f'      Max. parallele Downloads: {MAX_WORKERS}'
)
log('')

files_to_process = [
    filename
    for filename in files
    if filename.split('_')[2] in meta
]

total_stations = len(files_to_process)

results = {}

with ThreadPoolExecutor(
    max_workers=MAX_WORKERS
) as pool:

    futures = {
        pool.submit(
            process_station,
            filename,
            meta,
            total_stations
        ): filename
        for filename in files_to_process
    }

    for future in as_completed(futures):

        filename = futures[future]
        sid = filename.split('_')[2]

        try:
            result = future.result()
            results[result['station_id']] = result

        except Exception as exc:
            log(
                f'      FEHLER bei Station {sid}: {exc}'
            )


# ============================================================
# 4. ERGEBNISSE + DEUTSCHLANDMITTEL
# ============================================================

log('')
log('[4/5] Berechne Ergebnisse ...')

if not results:
    log(
        '      FEHLER: Keine Station konnte verarbeitet werden.'
    )
    raise SystemExit(1)

log(
    f'      Erfolgreich verarbeitet: '
    f'{len(results)} / {len(TARGET_STATIONS)}'
)

missing_results = TARGET_STATIONS - set(results)

if missing_results:
    log(
        '      WARNUNG: Keine Ergebnisse für: '
        + ', '.join(sorted(missing_results))
    )


# ============================================================
# DEUTSCHLANDMITTEL SEPARAT BERECHNEN
# ============================================================

try:

    germany_mean = calculate_germany_mean(
        results
    )

except ValueError as exc:

    log(
        f'      FEHLER Deutschlandmittel: {exc}'
    )

    raise SystemExit(1)


log('')
log('      DEUTSCHLANDMITTEL')
log(
    f'      Bisher 2026:              '
    f'{germany_mean["previous"]:.1f} h'
)
log(
    f'      Stationsmittel laufender Monat: '
    f'{germany_mean["station_monthly_mean"]:.1f} h'
)
log(
    f'      Faktor:                    '
    f'{germany_mean["factor"]:.4f}'
)
log(
    f'      Zuwachs Deutschland:       '
    f'{germany_mean["month_increment"]:.1f} h'
)
log(
    f'      Deutschlandmittel aktuell: '
    f'{germany_mean["current"]:.1f} h'
)

if (
    germany_mean['record'] is not None
    and germany_mean['record_year'] is not None
):
    log(
        f'      Deutschland-Rekord:       '
        f'{germany_mean["record"]:.1f} h '
        f'({germany_mean["record_year"]})'
    )


# ============================================================
# 5. KARTEN
# ============================================================

log('')
log('[5/5] Erzeuge Karten ...')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')

os.makedirs(
    OUTPUT_DIR,
    exist_ok=True
)

stichtag = DATA_DATE.strftime(
    '%d.%m.%Y'
)

current_output = os.path.join(
    OUTPUT_DIR,
    f'sunshine_{CURRENT_YEAR}.png'
)

records_output = os.path.join(
    OUTPUT_DIR,
    'sunshine_records.png'
)

remaining_output = os.path.join(
    OUTPUT_DIR,
    'sunshine_remaining.png'
)

create_map(
    results,
    'current',
    f'Sonnenscheindauer {CURRENT_YEAR} '
    f'bis {stichtag}',
    current_output,
    'YlOrRd',
    germany_mean
)

create_map(
    results,
    'record',
    'Stationsrekorde Sonnenschein',
    records_output,
    'plasma'
)

create_map(
    results,
    'remaining',
    'Fehlend bis Stationsrekord',
    remaining_output,
    'RdYlGn_r',
    germany_mean
)


# ============================================================
# ABSCHLUSS
# ============================================================

log('')
log('=' * 70)
log('FERTIG')
log('=' * 70)

log(
    f'Datenstand:         {stichtag}'
)

log(
    f'Laufender Monat:    '
    f'{CURRENT_MONTH_NAME} {CURRENT_YEAR}'
)

log(
    f'Stationen:          '
    f'{len(results)} / {len(TARGET_STATIONS)}'
)

log(
    f'Deutschlandmittel:  '
    f'{germany_mean["current"]:.1f} h'
)

log('')
log('Ausgabedateien:')
log(
    f'  {current_output}'
)
log(
    f'  {records_output}'
)
log(
    f'  {remaining_output}'
)

log('=' * 70)
