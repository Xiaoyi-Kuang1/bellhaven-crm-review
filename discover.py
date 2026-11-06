"""Read-only website crawler and paginated CRM snapshot. Never writes to CRM."""
import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BASE = 'https://analyst-assessment-production.up.railway.app'


def fetch(path, token=None):
    url = urljoin(BASE, path)
    if urlparse(url).netloc != urlparse(BASE).netloc:
        raise ValueError('Refusing cross-origin request')
    headers = {'User-Agent': 'BellhavenReconciliation/0.1'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                return response.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def scrape(output):
    pending = ['/', '/about', '/communities']
    visited, locations, evidence = set(), {}, []
    while pending:
        path = pending.pop(0)
        if path in visited:
            continue
        visited.add(path)
        raw = fetch(path)
        digest = hashlib.sha256(raw).hexdigest()
        (output / 'raw' / (digest + '.html')).write_bytes(raw)
        soup = BeautifulSoup(raw.decode('utf-8'), 'html.parser')
        evidence.append({'url': BASE + path, 'sha256': digest})
        for link in soup.select('a[href]'):
            url = urlparse(urljoin(BASE + path, link['href']))
            if url.netloc != urlparse(BASE).netloc:
                continue
            if url.path == '/communities' or url.path.startswith('/communities/'):
                target = url.path + ('?' + url.query if url.query and url.path == '/communities' else '')
                if target not in visited and target not in pending:
                    pending.append(target)
        if not urlparse(path).path.startswith('/communities/'):
            continue
        fields = {}
        for term in soup.select('dl.detail dt'):
            value = term.find_next_sibling('dd')
            if value:
                fields[term.get_text(' ', strip=True)] = value
        address = fields['Address'].get_text('\n', strip=True).splitlines()
        match = re.fullmatch(r'(.+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)', address[-1])
        if not match or len(address) < 2:
            raise ValueError(f'Unrecognized address at {path}: {address}')
        care = [badge.get_text(' ', strip=True) for badge in fields['Care Offerings'].select('.badge')]
        if not care:
            raise ValueError(f'Missing care offerings at {path}')
        locations[BASE + path] = {
            'name': soup.select_one('h1').get_text(' ', strip=True),
            'street': ', '.join(address[:-1]), 'city': match[1],
            'state': match[2], 'zip': match[3], 'care_offerings': care,
            'phone': fields['Phone'].get_text(' ', strip=True) if 'Phone' in fields else '',
            'source_url': BASE + path, 'source_sha256': digest,
            'page_text': soup.select_one('.wrap').get_text('\n', strip=True),
        }
    if not locations:
        raise ValueError('No communities found; snapshot aborted')
    rows = sorted(locations.values(), key=lambda row: row['name'])
    validate_evidence(output, rows, evidence)
    return rows, evidence


def validate_evidence(output, communities, evidence):
    """Fail closed if pagination, declared counts, or evidence files are incomplete."""
    pages, page_totals, directory_totals, homepage_totals, listed = set(), set(), set(), set(), set()
    sources = {}
    for item in evidence:
        raw = (output / 'raw' / (item['sha256'] + '.html')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Evidence hash mismatch')
        sources[item['url']] = item['sha256']
        soup = BeautifulSoup(raw.decode('utf-8'), 'html.parser')
        text = soup.get_text(' ', strip=True)
        path = urlparse(item['url']).path
        if path == '/':
            homepage_totals.update(int(n) for n in re.findall(r'serve (\d+) communities', text))
        if path == '/communities':
            match = re.search(r'Page (\d+) of (\d+) · (\d+) communities listed', text)
            if not match:
                raise ValueError('Missing directory completeness markers; verify site structure')
            pages.add(int(match[1])); page_totals.add(int(match[2])); directory_totals.add(int(match[3]))
            listed.update(urljoin(BASE, link['href']).split('?')[0] for link in soup.select('.card h3 a[href]'))
    if len(page_totals) != 1 or pages != set(range(1, next(iter(page_totals)) + 1)):
        raise ValueError('Directory pages incomplete or counts inconsistent')
    if directory_totals != {len(listed)}:
        raise ValueError('Directory community count mismatch')
    urls = {c['source_url'] for c in communities}
    if len(urls) != len(communities) or not listed.issubset(urls):
        raise ValueError('Missing or duplicated community detail pages')
    if homepage_totals and homepage_totals != {len(communities)}:
        raise ValueError('Homepage count disagrees with crawl; investigate before absence proposals')
    for c in communities:
        if sources.get(c['source_url']) != c['source_sha256']:
            raise ValueError('Community source evidence mismatch')


def accounts(token):
    rows, page, expected = [], 1, None
    while True:
        result = json.loads(fetch(f'/api/v1/accounts?page={page}&page_size=50', token))
        if expected is None:
            expected = result['total']
        if result['total'] != expected:
            raise ValueError('CRM count changed during pagination; rerun snapshot')
        rows.extend(result['data'])
        if len(rows) >= expected:
            break
        if not result['data']:
            raise ValueError('CRM pagination ended prematurely')
        page += 1
    if len(rows) != expected or len({r['account_id'] for r in rows}) != expected:
        raise ValueError('CRM snapshot has duplicate or missing IDs')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('data/snapshots'))
    args = parser.parse_args()
    token = os.environ.get('BELLHAVEN_API_TOKEN')
    if not token:
        parser.error('Set BELLHAVEN_API_TOKEN in the environment')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = args.output / stamp
    (output / 'raw').mkdir(parents=True)
    communities, evidence = scrape(output)
    crm = accounts(token)
    for name, value in [('communities', communities), ('accounts', crm), ('sources', evidence)]:
        (output / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    manifest = {'captured_at': stamp, 'communities': len(communities), 'accounts': len(crm),
                'website_pages': len(evidence), 'complete': True, 'crm_writes': 0}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'output': str(output.resolve()), **manifest}, indent=2))


if __name__ == '__main__':
    main()
