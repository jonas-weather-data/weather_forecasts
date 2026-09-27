# dwd_monatskarten_parallel_fertig.py
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from io import BytesIO
import threading
import zipfile
import requests
import pandas as pd
import geopandas as gpd
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import re
import os
import time
import webbrowser

# ============================================================
# STATIONSLISTE HIER EINFÜGEN
# ============================================================
TARGET_STATIONS = {
    '00044',
    '00073',
    '00320',
    '00330',
    '00342',
    '00368',
    '00656',
    '00662',
    '01297',
    '01300',
    '01303',
    '01327',
    '01587',
    '01590',
    '01602',
    '01605',
    '02014',
    '02023',
    '02039',
    '02044',
    '02290',
    '02575',
    '02578',
    '02597',
    '02600',
    '03028',
    '03031',
    '03032',
    '03034',
    '03042',
    '03226',
    '03231',
    '03234',
    '03244',
    '03571',
    '03591',
    '03603',
    '04024',
    '04032',
    '04036',
    '04039',
    '04480',
    '04501',
    '04748',
    '04763',
    '04813',
    '05146',
    '05149',
    '05158',
    '05629',
    '05640',
    '05643',
    '07106',
    '07187',
    '07298',
    '07319',
    '07321',
    '07329',
    '07330',
    '00257',
    '00259',
    '00282',
    '00603',
    '00617',
    '00953',
    '00963',
    '01332',
    '01339',
    '01346',
    '01357',
    '01612',
    '01639',
    '01645',
    '02074',
    '02303',
    '02306',
    '02315',
    '02319',
    '02323',
    '02601',
    '02627',
    '02629',
    '02985',
    '03015',
    '03257',
    '03268',
    '03271',
    '03278',
    '03621',
    '03623',
    '03631',
    '03639',
    '04063',
    '04094',
    '04104',
    '04393',
    '04411',
    '04841',
    '04857',
    '04878',
    '04887',
    '05229',
    '05275',
    '05279',
    '05280',
    '05538',
    '05541',
    '05546',
    '05562',
    '06265',
    '06266',
    '06272',
    '06273',
    '06275',
    '06305',
    '06310',
    '06314',
    '06336',
    '06337',
    '00222',
    '00232',
    '00460',
    '00880',
    '00891',
    '00896',
    '00917',
    '01224',
    '01246',
    '01255',
    '01262',
    '01411',
    '01420',
    '01424',
    '01975',
    '01981',
    '02362',
    '02385',
    '02410',
    '02638',
    '02641',
    '02667',
    '02947',
    '02951',
    '02953',
    '03284',
    '03287',
    '03289',
    '03307',
    '03319',
    '03321',
    '03660',
    '03667',
    '03668',
    '03975',
    '03987',
    '04445',
    '04464',
    '04466',
    '04911',
    '04928',
    '04931',
    '05300',
    '05335',
    '05664',
    '05688',
    '05692',
    '06158',
    '06159',
    '06163',
    '06170',
    '06197',
    '06217',
    '06258',
    '06259',
    '06260',
    '06262',
    '06263',
    '06264',
    '00183',
    '00403',
    '00420',
    '00427',
    '00853',
    '00856',
    '00860',
    '00867',
    '01107',
    '01161',
    '01503',
    '01504',
    '01526',
    '01964',
    '02115',
    '02559',
    '02564',
    '02856',
    '02878',
    '02886',
    '02905',
    '03147',
    '03155',
    '03158',
    '03164',
    '03166',
    '03426',
    '03442',
    '03484',
    '03485',
    '03761',
    '04175',
    '04177',
    '04189',
    '04703',
    '04704',
    '04706',
    '04745',
    '05014',
    '05017',
    '05029',
    '05046',
    '05480',
    '05490',
    '05516',
    '05825',
    '05839',
    '05856',
    '05871',
    '07331',
    '07341',
    '07343',
    '07351',
    '07364',
    '07367',
    '07368',
    '00191',
    '00198',
    '00217',
    '00433',
    '00445',
    '00817',
    '00840',
    '00850',
    '01197',
    '01200',
    '01207',
    '01214',
    '01468',
    '01757',
    '01759',
    '01766',
    '01792',
    '01803',
    '01832',
    '02211',
    '02486',
    '02497',
    '02907',
    '02925',
    '02928',
    '02932',
    '03167',
    '03181',
    '03196',
    '03204',
    '03527',
    '03540',
    '03545',
    '03927',
    '03939',
    '03946',
    '04300',
    '04301',
    '04323',
    '04336',
    '04651',
    '05097',
    '05099',
    '05100',
    '05397',
    '05404',
    '05906',
    '05930',
    '06093',
    '06105',
    '06109',
    '06129',
    '06157',
    '00078',
    '00091',
    '00096',
    '00102',
    '00125',
    '00131',
    '00142',
    '00377',
    '00379',
    '00390',
    '00400',
    '00722',
    '01048',
    '01050',
    '01052',
    '01072',
    '01358',
    '01684',
    '02429',
    '02437',
    '02444',
    '02712',
    '02750',
    '02773',
    '03086',
    '03093',
    '03098',
    '03490',
    '03513',
    '03875',
    '03897',
    '03904',
    '03925',
    '04349',
    '04354',
    '04371',
    '04377',
    '04592',
    '04978',
    '04997',
    '05009',
    '05347',
    '05349',
    '05371',
    '05792',
    '05797',
    '05800',
    '07369',
    '07370',
    '07373',
    '07374',
    '07389',
    '07393',
    '07394',
    '07395',
    '07396',
    '07403',
    '07410',
    '07412',
    '07419',
    '07420',
    '07424',
    '07427',
    '07428',
    '07431',
    '00150',
    '00151',
    '00154',
    '00161',
    '00164',
    '00167',
    '00535',
    '00555',
    '00591',
    '00596',
    '00755',
    '00757',
    '00760',
    '00766',
    '00769',
    '01078',
    '01103',
    '01443',
    '01451',
    '01691',
    '01694',
    '01721',
    '01735',
    '01736',
    '02261',
    '02480',
    '02483',
    '02485',
    '02794',
    '02796',
    '02812',
    '03126',
    '03137',
    '03402',
    '03679',
    '03730',
    '03734',
    '03739',
    '04127',
    '04160',
    '04169',
    '04508',
    '04548',
    '04559',
    '05064',
    '05440',
    '05745',
    '05750',
    '05779',
    '07432',
    '13670',
    '13674',
    '13675',
    '13696',
    '13700',
    '13711',
    '13713',
    '13777',
    '13965',
    '06344',
    '06346',
    '06347',
    '07075',
    '07105',
    '19856',
    '20098',
    '15000',
    '15207',
    '15444',
    '00294',
    '00298',
    '00303',
    '00314',
    '00691',
    '00701',
    '00704',
    '00983',
    '00991',
    '01001',
    '01266',
    '01270',
    '01279',
    '01544',
    '01550',
    '01572',
    '01580',
    '01863',
    '01869',
    '01886',
    '02171',
    '02174',
    '02201',
    '02680',
    '02700',
    '02704',
    '02708',
    '03083',
    '03348',
    '03362',
    '03366',
    '03376',
    '03379',
    '03811',
    '03821',
    '03836',
    '03857',
    '04271',
    '04275',
    '04280',
    '04287',
    '04605',
    '04642',
    '05109',
    '05111',
    '05133',
    '05142',
    '05424',
    '05426',
    '05433',
    '05705',
    '05715',
    '05717',
    '05731',
    '15555',
    '15813',
    '19171',
    '19172',
    '19207'
}

MAX_WORKERS = 64
SHAPEFILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'gadm41_DEU_1.json'
)

if os.environ.get('GITHUB_ACTIONS') == 'true':
    matplotlib.use('Agg')

STATIONS_URL = 'https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/historical/KL_Tageswerte_Beschreibung_Stationen.txt'
RECENT_URL = 'https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/daily/kl/recent/'

heute = date.today()
gestern = heute - timedelta(days=1)
monat_start = date(gestern.year, gestern.month, 1)

lock = threading.Lock()
fertig = 0


def log(msg):
    print(f'[{time.strftime("%H:%M:%S")}] {msg}', flush=True)


def load_stations():
    log('Stationsliste laden ...')
    txt = requests.get(STATIONS_URL, timeout=120).content.decode('cp1252')
    lines = txt.replace('\r\n', '\n').split('\n')
    header = next(i for i, l in enumerate(lines) if l.startswith('Stations_id'))

    result = {}

    for line in lines[header + 1:]:
        try:
            sid = line[0:5].strip()
            if sid not in TARGET_STATIONS:
                continue

            result[sid] = {
                'lat': float(line[43:50].strip().replace(',', '.')),
                'lon': float(line[53:60].strip().replace(',', '.')),
                'name': line[61:101].strip()
            }
        except Exception:
            pass

    log(f'{len(result)} Zielstationen gefunden')
    return result


def get_zip_files():
    log('Verzeichnis vom DWD laden ...')
    html = requests.get(RECENT_URL, timeout=120).text

    files = re.findall(r'href="(tageswerte_KL_\d+_.*?\.zip)"', html)

    files = [f for f in files if f.split('_')[2] in TARGET_STATIONS]

    log(f'{len(files)} relevante ZIP-Dateien gefunden')
    return files


def process_station(file_name, stations, total):
    global fertig

    sid = file_name.split('_')[2]

    try:
        content = requests.get(RECENT_URL + file_name, timeout=120).content

        with zipfile.ZipFile(BytesIO(content)) as z:

            csv_file = next(
                x for x in z.namelist()
                if x.startswith('produkt_klima_tag')
            )

            with z.open(csv_file) as f:
                df = pd.read_csv(f, sep=';', encoding='cp1252', dtype=str)

        df.columns = [c.strip() for c in df.columns]

        df['MESS_DATUM'] = pd.to_datetime(
            df['MESS_DATUM'],
            format='%Y%m%d',
            errors='coerce'
        )

        df = df[
            (df['MESS_DATUM'].dt.date >= monat_start)
            &
            (df['MESS_DATUM'].dt.date <= gestern)
        ]

        if df.empty:
            return None

        for col in ['SDK', 'RSK', 'TMK']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').replace(-999, np.nan)

        with lock:
            fertig += 1
            print(f'[{fertig}/{total}] {fertig * 100 / total:.1f}%  {sid}', flush=True)

        def has_measurements(series):
            return series.notna().any()

        sdk = None
        rsk = None
        tmk = None

        if 'SDK' in df.columns and has_measurements(df['SDK']):
            sdk = float(df['SDK'].sum())

        if 'RSK' in df.columns and has_measurements(df['RSK']):
            rsk = float(df['RSK'].sum())

        if 'TMK' in df.columns and has_measurements(df['TMK']):
            tmk = float(df['TMK'].mean())

        return {
            'station_id': sid,
            'lat': stations[sid]['lat'],
            'lon': stations[sid]['lon'],
            'sdk': sdk,
            'rsk': rsk,
            'tmk': tmk
        }

    except Exception as ex:
        log(f'Fehler Station {sid}: {ex}')
        return None


def create_map(results, parameter, cmap, titel, outfile, faktor):

    log(f'Erzeuge {outfile}')

    gdf = gpd.read_file(SHAPEFILE)

    fig, ax = plt.subplots(figsize=(12, 14))

    gdf.plot(
        color='white',
        edgecolor='black',
        linewidth=0.5,
        ax=ax
    )

    xs = []
    ys = []
    vals = []

    for r in results.values():
        value = r[parameter]

        if value is None:
            continue

        xs.append(r['lon'])
        ys.append(r['lat'])
        vals.append(value)
        
    deutschlandmittel = None

    if vals:
        deutschlandmittel = np.mean(vals) * faktor

    sc = ax.scatter(
        xs,
        ys,
        c=vals,
        cmap=cmap,
        s=25,
        zorder=10
    )

    for r in results.values():

        value = r[parameter]

        if value is None:
            continue

        ax.text(
            r['lon'] + 0.03,
            r['lat'] + 0.02,
            f'{value:.1f}',
            fontsize=10,
            zorder=11
        )

    plt.colorbar(sc, ax=ax)

    ax.set_title(titel)
    ax.axis('off')
    
    if deutschlandmittel is not None:

        einheiten = {
            'sdk': 'h',
            'rsk': 'mm',
            'tmk': '°C'
        }

        einheit = einheiten.get(parameter, '')
        
        if parameter == 'tmk':
            mittel_format = f'{deutschlandmittel:.2f}'
        else:
            mittel_format = f'{deutschlandmittel:.1f}'

        fig.text(
            0.5,
            0.025,
            f'Deutschlandmittel: {mittel_format} {einheit}',
            ha='center',
            fontsize=12,
            fontweight='bold'
        )

    plt.savefig(outfile, dpi=250, bbox_inches='tight')
    plt.close()

    log(f'{outfile} gespeichert')


log(f'Zeitraum: {monat_start} bis {gestern}')

stations = load_stations()
files = get_zip_files()

results = {}

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

    futures = [
        executor.submit(process_station, f, stations, len(files))
        for f in files
    ]

    for future in as_completed(futures):
        r = future.result()
        if r:
            results[r['station_id']] = r

log(f'{len(results)} Stationen ausgewertet')

stichtag = gestern.strftime('%d.%m.%Y')

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'output'
)
os.makedirs(OUTPUT_DIR, exist_ok=True)

create_map(
    results,
    'sdk',
    'YlOrRd',
    f'Sonnenscheindauer bis {stichtag}',
    os.path.join(OUTPUT_DIR, 'sdk_monat.png'),
    0.9897
)

create_map(
    results,
    'rsk',
    'Blues',
    f'Niederschlag bis {stichtag}',
    os.path.join(OUTPUT_DIR, 'rsk_monat.png'),
    1.0648
)

create_map(
    results,
    'tmk',
    'coolwarm',
    f'Temperaturmittel bis {stichtag}',
    os.path.join(OUTPUT_DIR, 'tmk_monat.png'),
    1.0028
)

if os.environ.get('GITHUB_ACTIONS') != 'true':
    webbrowser.open(os.path.abspath(
        os.path.join(OUTPUT_DIR, 'sdk_monat.png')
    ))
    webbrowser.open(os.path.abspath(
        os.path.join(OUTPUT_DIR, 'rsk_monat.png')
    ))
    webbrowser.open(os.path.abspath(
        os.path.join(OUTPUT_DIR, 'tmk_monat.png')
    ))

log('Fertig')
