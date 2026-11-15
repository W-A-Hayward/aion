"""Local extraction. Source text is not automatically a verified evidence passage."""
import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET

PDF_HELPER = Path(__file__).resolve().parents[1] / 'source_documents' / 'pdf_metadata.js'
SERIES = {'DCOILBRENTEU': ('USD/barrel', 'Daily'), 'DCOILWTICO': ('USD/barrel', 'Daily'),
          'T10YIE': ('percent', 'Daily'), 'DGS10': ('percent', 'Daily'), 'DGS2': ('percent', 'Daily')}


def cover_report_year(text):
    compact = re.sub(r'[^a-z0-9]', '', text.lower())
    years = {y for pair in re.findall(r'(20\d\d)(?:annualreport|rapportannuel)|(?:annualreport|rapportannuel)(20\d\d)', compact) for y in pair if y}
    return next(iter(years)) if len(years) == 1 else None


class HTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.parts = []; self.links = []; self.anchor = None
        self.title = ''; self.in_title = False; self.tables = []; self.table = None; self.row = None; self.cell = None
        self.dates = []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ('script', 'style', 'noscript'): self.skip += 1
        if tag == 'title': self.in_title = True
        if tag == 'a' and a.get('href'): self.anchor = [a['href'], []]
        if tag == 'meta' and a.get('property', a.get('name')) in ('article:published_time', 'date', 'datePublished', 'dcterms.issued'):
            self.dates.append(a.get('content', ''))
        if tag in ('p', 'div', 'h1', 'h2', 'h3', 'li', 'br', 'tr'): self.parts.append('\n')
        if tag == 'table': self.table = []
        if tag == 'tr' and self.table is not None: self.row = []
        if tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript') and self.skip: self.skip -= 1
        if tag == 'title': self.in_title = False
        if tag == 'a' and self.anchor:
            self.links.append({'href': self.anchor[0], 'text': ' '.join(self.anchor[1])}); self.anchor = None
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(' '.join(self.cell)); self.cell = None
        if tag == 'tr' and self.row is not None:
            self.table.append(self.row); self.row = None
        if tag == 'table' and self.table is not None:
            self.tables.append(self.table); self.table = None
    def handle_data(self, value):
        if self.skip: return
        if self.in_title: self.title += value
        if value.strip(): self.parts.append(value.strip() + ' ')
        if self.anchor: self.anchor[1].append(value.strip())
        if self.cell is not None: self.cell.append(value.strip())
    @property
    def text(self):
        return '\n'.join(s.strip() for s in ''.join(self.parts).splitlines() if s.strip())


def numeric(value):
    if str(value).strip() in ('', '-', '.', '..', '...', 'F', 'x', 'N/A'): return None
    try:
        d = Decimal(str(value).replace(',', ''))
    except InvalidOperation: raise ValueError('Invalid numeric cell')
    if not d.is_finite(): raise ValueError('Nonfinite value')
    return str(d)


def csv_extract(raw, series=None):
    text = raw.decode('utf-8-sig')
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows) > 500_000: raise ValueError('CSV empty or exceeds row limit')
    hi = next((i for i, r in enumerate(rows[:30]) if r and r[0] == 'Ticker'), None)
    if hi is not None:
        header = rows[hi]
        weight_column = 'Weight (%)' if 'Weight (%)' in header else 'Market Weight' if 'Market Weight' in header else None
        if not {'Name', 'Sector', 'Asset Class'} <= set(header) or weight_column is None: raise ValueError('Holdings columns missing')
        dated = next((r[1] for r in rows[:hi] if len(r) > 1 and 'holdings as of' in r[0].lower()), None)
        if not dated: raise ValueError('Official holdings date missing')
        try: as_of = datetime.strptime(dated, '%b %d, %Y').date().isoformat()
        except ValueError: as_of = date.fromisoformat(dated).isoformat()
        positions = []
        for r in rows[hi + 1:]:
            if len(r) != len(header): continue  # disclosure/footer prose, never interpreted as a holding
            v = dict(zip(header, r)); weight = numeric(v[weight_column])
            if not v['Ticker']: continue
            positions.append({'as_of': as_of, 'ticker_original': v['Ticker'], 'name': v['Name'],
                              'sector': v['Sector'], 'asset_class': v['Asset Class'], 'weight_pct': weight,
                              'currency': v.get('Currency'), 'raw': v})
        if not positions: raise ValueError('No positions parsed')
        missing = sum(p['weight_pct'] is None for p in positions)
        total = str(sum(Decimal(p['weight_pct']) for p in positions if p['weight_pct'] is not None))
        return {'kind': 'holdings', 'as_of': as_of, 'unit': 'percent of fund', 'positions': positions,
                'row_count': len(positions), 'total_displayed_weight_pct': total if not missing else None,
                'missing_weight_count': missing, 'sum_known_weight_pct': total,
                'weights_renormalized': False, 'source_weight_column': weight_column,
                'weight_unit_basis': 'Explicit percent column' if weight_column == 'Weight (%)' else 'iShares Market Weight percentage convention; review before modeling',
                'source_columns': header, 'date_min': as_of, 'date_max': as_of}
    header = rows[0]
    if series in SERIES and len(header) == 2 and header[0] in ('DATE', 'observation_date') and header[1] == series:
        values = []
        for r in rows[1:]:
            if not r: continue
            if len(r) != 2: raise ValueError('Series row has wrong shape')
            d = date.fromisoformat(r[0]).isoformat()
            values.append({'date': d, 'series_id': series, 'value': numeric(r[1]), 'unit': SERIES[series][0], 'frequency': SERIES[series][1]})
        if len({v['date'] for v in values}) != len(values): raise ValueError('Duplicate observation dates')
        return describe_series(values, header)
    if {'REF_DATE', 'VALUE', 'UOM', 'SCALAR_FACTOR'} <= set(header):
        records = [dict(zip(header, r)) for r in rows[1:] if len(r) == len(header)]
        for r in records: numeric(r['VALUE'])  # don't interpolate suppression codes or multiply scalars
        return {'kind': 'statcan_table', 'records': records, 'row_count': len(records), 'source_columns': header,
                'date_min': min((r['REF_DATE'] for r in records), default=None),
                'date_max': max((r['REF_DATE'] for r in records), default=None),
                'units': sorted({r['UOM'] for r in records}), 'scalar_factors': sorted({r['SCALAR_FACTOR'] for r in records}),
                'note': 'Dimensions, geographic labels, suppression flags and scalar factors retained; not aggregated.'}
    return {'kind': 'csv_unmapped', 'source_columns': header, 'row_count': max(0, len(rows) - 1),
            'rows': rows[1:], 'status': 'pending_unit_and_date_mapping'}


def describe_series(values, columns):
    if not values: raise ValueError('Empty time series')
    return {'kind': 'time_series', 'records': values, 'source_columns': columns, 'row_count': len(values),
            'date_min': min(v['date'] for v in values), 'date_max': max(v['date'] for v in values),
            'units': sorted({v['unit'] for v in values}),
            'missing_count': sum(v['value'] is None for v in values)}


def extract(path, series=None):
    raw = Path(path).read_bytes()
    if raw.startswith(b'%PDF'):
        r = subprocess.run(['/usr/bin/osascript', '-l', 'JavaScript', str(PDF_HELPER), str(path)],
                           capture_output=True, timeout=70, text=True)
        if r.returncode: raise ValueError('PDFKit extraction failed; manual/OCR review needed')
        pdf = json.loads(r.stdout)
        if not any(p['text'].strip() for p in pdf['pages']): raise ValueError('Scanned PDF needs OCR')
        return {'kind': 'pdf', **pdf, 'printed_pages': 'not_inferred', 'extraction_method': 'PDFKit original text layer'}
    if raw.startswith(b'PK'):
        members = []
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if sum(i.file_size for i in z.infolist()) > 100_000_000 or len(z.infolist()) > 30: raise ValueError('Archive limit exceeded')
            if 'xl/workbook.xml' in z.namelist():
                ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                strings = []
                if 'xl/sharedStrings.xml' in z.namelist():
                    strings = [''.join(s.itertext()) for s in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', ns)]
                sheets = []
                for name in z.namelist():
                    if not re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name): continue
                    rows = []
                    for row in ET.fromstring(z.read(name)).findall('.//s:row', ns):
                        cells = []
                        for c in row.findall('s:c', ns):
                            if c.find('s:f', ns) is not None: raise ValueError('Workbook formula: no execution or trusted cached values')
                            value = ''.join(c.itertext())
                            if c.get('t') == 's': value = strings[int(value)]
                            cells.append({'cell': c.get('r'), 'value': value, 'type': c.get('t'), 'style': c.get('s')})
                        rows.append(cells)
                    sheets.append({'sheet': name, 'rows': rows})
                return {'kind': 'xlsx_cells', 'sheets': sheets, 'status': 'pending_date_unit_mapping',
                        'note': 'Values and original cells preserved. Excel date serials and percentages not guessed.'}
            for name in z.namelist():
                if name.lower().endswith('.csv') and not any(w in name.lower() for w in ('metadata', 'readme')):
                    members.append({'member': name, 'data': csv_extract(z.read(name), series)})
        return {'kind': 'zip_csv', 'members': members}
    text = raw.decode('utf-8-sig', errors='replace')
    if text.lstrip().startswith(('{', '[')):
        j = json.loads(text)
        if isinstance(j, dict) and 'observations' in j and 'seriesDetail' in j:
            values = []
            for o in j['observations']:
                d = date.fromisoformat(o['d']).isoformat()
                for sid, v in o.items():
                    if sid == 'd': continue
                    description = j['seriesDetail'].get(sid, {}).get('description', '')
                    unit = 'CAD per USD' if sid == 'FXUSDCAD' else 'percent' if sid.startswith('BD.CDN.') else 'UNVERIFIED'
                    values.append({'date': d, 'series_id': sid, 'value': numeric(v['v']), 'unit': unit,
                                   'frequency': 'Daily', 'label': description})
            return {**describe_series(values, ['d', *j['seriesDetail']]), 'series_metadata': j['seriesDetail']}
        return {'kind': 'json_metadata', 'data': j}
    if re.search(r'<(?:!doctype\s+html|html|head|body)\b', text[:3000], re.I):
        p = HTML(); p.feed(text)
        if len(p.text) < 100: raise ValueError('HTML contains no substantive text; script-only/manual review')
        return {'kind': 'html', 'title': p.title.strip(), 'text': p.text, 'links': p.links,
                'publication_date_candidates': p.dates, 'tables': p.tables,
                'extraction_method': 'visible HTML text; source line/character references, not PDF pages'}
    return csv_extract(raw, series)
