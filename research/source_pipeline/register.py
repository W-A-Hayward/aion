"""Read source records as data; never evaluate workbook formulas or cell instructions."""
import hashlib
import io
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET
import zipfile

NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
HEADERS = ['ID', 'Group', 'Priority', 'Publisher', 'Title', 'Period', 'Tickers',
           'What to extract / purpose', 'Official URL', 'Source / file validation',
           'Owner', 'Downloaded?', 'Verified in S3?']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_register(path):
    raw = Path(path).read_bytes()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if sum(i.file_size for i in z.infolist()) > 20_000_000:
            raise ValueError('Workbook exceeds limit')
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        sheets = [s for s in wb.findall('s:sheets/s:sheet', NS) if s.get('name') == 'OFFICIAL SOURCES']
        if len(sheets) != 1:
            raise ValueError('OFFICIAL SOURCES must exist exactly once')
        rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
        rel = next(r for r in rels if r.get('Id') == sheets[0].get(REL))
        target = rel.get('Target', '')
        if rel.get('TargetMode') == 'External' or '..' in PurePosixPath(target).parts:
            raise ValueError('External/traversing worksheet rejected')
        target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
        strings = []
        if 'xl/sharedStrings.xml' in z.namelist():
            strings = [''.join(x.itertext()) for x in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', NS)]
        rows = []
        for row in ET.fromstring(z.read(target)).findall('.//s:row', NS):
            values = [''] * len(HEADERS)
            for c in row.findall('s:c', NS):
                if c.find('s:f', NS) is not None:
                    raise ValueError('Workbook formulas are not trusted source metadata')
                index = 0
                for ch in c.get('r', ''):
                    if ch.isalpha(): index = index * 26 + ord(ch) - 64
                if not 1 <= index <= len(HEADERS): raise ValueError('Unexpected workbook column')
                v = ''.join(c.itertext())
                values[index - 1] = strings[int(v)] if c.get('t') == 's' else v
            if any(values): rows.append(values)
    if not rows or rows[0] != HEADERS: raise ValueError('Unexpected source register schema')
    sources = [dict(zip(HEADERS, row)) for row in rows[1:]]
    if len(sources) != 52 or {r['ID'] for r in sources} != {f'SRC-{i:03}' for i in range(1, 53)}:
        raise ValueError('Expected the exact 52 unique SRC records')
    return sources, sha(raw)
