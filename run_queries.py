"""Експорт результатів SPARQL про стадіони Італії."""
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
import requests

DIRECTORY = Path(__file__).resolve().parent
SERVICE = 'https://query.wikidata.org/sparql'
COLUMNS = {
    'q1': ('item', 'itemLabel', 'value', 'website'),
    'q2': ('region', 'regionLabel', 'cnt'),
    'q3': ('item', 'itemLabel', 'region', 'regionLabel', 'population'),
}


def fetch(client, query):
    for attempt in range(4):
        response = client.get(SERVICE, params={'query': query, 'format': 'json'}, timeout=120)
        if response.status_code not in {429, 502, 503, 504} or attempt == 3:
            response.raise_for_status()
            return response.json()['results']['bindings']
        try:
            pause = int(response.headers.get('Retry-After', '5'))
        except ValueError:
            pause = 5
        time.sleep(max(0, min(pause, 30)))


def save_table(name, bindings):
    records = []
    for binding in bindings:
        records.append({column: binding.get(column, {}).get('value', '') for column in COLUMNS[name]})
    with (DIRECTORY / (name + '.csv')).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=COLUMNS[name])
        writer.writeheader()
        writer.writerows(records)
    return records


def lower_threshold(query):
    match = re.search(r'FILTER\s*\(\s*\?value\s*>\s*(\d+(?:\.\d+)?)\s*\)', query)
    if match is None:
        raise ValueError('У Q1 відсутній числовий поріг місткості')
    threshold = float(match[1]) / 2
    return query[:match.start(1)] + f'{threshold:g}' + query[match.end(1):], threshold


def write_answers(tables, note=None):
    templates = {
        'q1': 'Q1: Першим у таблиці є {itemLabel}, місткість — {value} місць.',
        'q2': 'Q2: Найбільше стадіонів у результаті має регіон {regionLabel}: {cnt} об’єктів.',
        'q3': 'Q3: Населення регіону в першому записі становить {population} осіб.',
    }
    lines = []
    for name, template in templates.items():
        rows = tables[name]
        lines.append(template.format(**rows[0]) if rows else f'{name.upper()}: за заданими умовами записів не знайдено.')
    if note:
        lines.append(note)
    (DIRECTORY / 'ANSWERS.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main():
    tables = {}
    note = None
    with requests.Session() as client:
        client.headers.update({'User-Agent': 'mkr1/1.0', 'Accept': 'application/sparql-results+json'})
        for name in COLUMNS:
            source = DIRECTORY / (name + '.rq')
            query = source.read_text(encoding='utf-8')
            bindings = fetch(client, query)
            if name == 'q1' and len(bindings) < 5:
                query, threshold = lower_threshold(query)
                bindings = fetch(client, query)
                source.write_text(query, encoding='utf-8')
                note = f'Примітка: через недостатню кількість результатів Q1 застосовано половину початкового порогу — {threshold:g} місць.'
            tables[name] = save_table(name, bindings)
            print(f'Таблиця {name}: збережено {len(bindings)} записів', flush=True)
    metadata = {'retrieved_at': datetime.now(timezone.utc).isoformat()}
    (DIRECTORY / 'meta.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    write_answers(tables, note)


if __name__ == '__main__':
    main()
