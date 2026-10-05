"""Побудова RDF за нормалізованими записами рейсів."""
import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote
from rdflib import Graph, Literal, Namespace, RDF, RDFS, XSD

EX = Namespace('http://example.org/mkr/')


def iri(group, text):
    return EX[group + '/' + quote(text.strip().replace(' ', '_'), safe='-_')]


def load_records(filename):
    unique = {}
    with Path(filename).open(encoding='utf-8-sig', newline='') as source:
        for row in csv.DictReader(source):
            row = {key: value.strip() for key, value in row.items()}
            row['flight_id'] = row['flight_id'].upper()
            row['from_city'] = row['from_city'].title()
            row['to_city'] = row['to_city'].title()
            unique.setdefault(row['flight_id'], row)
    return list(unique.values())


def schema_graph():
    graph = Graph()
    graph.bind('ex', EX)
    for name in ('Flight', 'Airline', 'City', 'Country', 'BudgetFlight', 'LongFlight'):
        graph.add((EX[name], RDF.type, RDFS.Class))
    for name in ('BudgetFlight', 'LongFlight'):
        graph.add((EX[name], RDFS.subClassOf, EX.Flight))
    declarations = [
        ('operatedBy', EX.Flight, EX.Airline),
        ('departsFrom', EX.Flight, EX.City),
        ('arrivesAt', EX.Flight, EX.City),
        ('locatedIn', EX.City, EX.Country),
        ('departureDate', EX.Flight, XSD.date),
        ('durationMin', EX.Flight, XSD.integer),
        ('priceEur', EX.Flight, XSD.decimal),
        ('hasDelayMinutes', EX.Flight, XSD.integer),
        ('reportedBy', RDF.Statement, RDFS.Resource),
        ('fromBusyCountry', EX.Flight, XSD.boolean),
    ]
    for name, domain, range_ in declarations:
        graph.add((EX[name], RDF.type, RDF.Property))
        graph.add((EX[name], RDFS.domain, domain))
        graph.add((EX[name], RDFS.range, range_))
    return graph


def named_node(graph, group, label, category):
    subject = iri(group, label)
    graph.add((subject, RDF.type, category))
    graph.add((subject, RDFS.label, Literal(label, lang='en')))
    return subject


def city_node(graph, city_name, country_name):
    city = named_node(graph, 'city', city_name, EX.City)
    country = named_node(graph, 'country', country_name, EX.Country)
    graph.add((city, EX.locatedIn, country))
    return city


def add_delay(graph, flight, identifier, note):
    fields = {}
    for part in note.split(';'):
        key, separator, value = part.partition('=')
        if separator:
            fields[key.strip()] = value.strip()
    if 'delay' not in fields or 'by' not in fields:
        return
    statement = iri('stmt', identifier + '-delay')
    values = [
        (RDF.type, RDF.Statement), (RDF.subject, flight),
        (RDF.predicate, EX.hasDelayMinutes),
        (RDF.object, Literal(int(fields['delay']), datatype=XSD.integer)),
        (EX.reportedBy, iri('source', fields['by'])),
    ]
    for predicate, value in values:
        graph.add((statement, predicate, value))


def add_record(graph, row, limits, busy):
    flight = iri('flight', row['flight_id'])
    airline = named_node(graph, 'airline', row['airline'], EX.Airline)
    graph.add((flight, EX.operatedBy, airline))
    graph.add((flight, EX.departsFrom, city_node(graph, row['from_city'], row['from_country'])))
    graph.add((flight, EX.arrivesAt, city_node(graph, row['to_city'], row['to_country'])))
    pattern = '%d.%m.%Y' if '.' in row['dep_date'] else '%Y-%m-%d'
    departure = datetime.strptime(row['dep_date'], pattern).date()
    minutes = int(row['duration_min'])
    graph.add((flight, EX.departureDate, Literal(departure, datatype=XSD.date)))
    graph.add((flight, EX.durationMin, Literal(minutes, datatype=XSD.integer)))
    categories = set()
    if row['price_eur']:
        price = Decimal(row['price_eur'])
        graph.add((flight, EX.priceEur, Literal(price, datatype=XSD.decimal)))
        if price <= Decimal(str(limits['budget_threshold_eur'])):
            categories.add(EX.BudgetFlight)
    if minutes >= limits['long_flight_min']:
        categories.add(EX.LongFlight)
    for category in categories or {EX.Flight}:
        graph.add((flight, RDF.type, category))
    if row['from_country'] in busy:
        graph.add((flight, EX.fromBusyCountry, Literal(True, datatype=XSD.boolean)))
    add_delay(graph, flight, row['flight_id'], row['note'])


def build_graph(table, settings):
    records = load_records(table)
    limits = json.loads(Path(settings).read_text(encoding='utf-8'))
    counts = Counter(row['from_country'] for row in records)
    busy = {country for country, count in counts.items() if count >= 2}
    graph = schema_graph()
    for record in records:
        add_record(graph, record, limits, busy)
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('table', type=Path)
    parser.add_argument('settings', type=Path)
    parser.add_argument('destination', type=Path)
    options = parser.parse_args()
    graph = build_graph(options.table, options.settings)
    graph.serialize(options.destination, format='turtle')
    print(f'Записано {len(graph)} тріплів у {options.destination}')


if __name__ == '__main__':
    main()
