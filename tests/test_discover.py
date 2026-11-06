import hashlib
import tempfile
import unittest
from pathlib import Path
from discover import validate_evidence, BASE


class EvidenceTests(unittest.TestCase):
    def fixture(self, folder, total_pages=1):
        raw = (folder / 'raw'); raw.mkdir()
        html = f'<p>Page 1 of {total_pages} · 1 communities listed</p><div class="card"><h3><a href="/communities/test">Test</a></h3></div>'
        evidence = []
        for path, content in [('/communities', html), ('/communities/test', '<h1>Test</h1>')]:
            digest = hashlib.sha256(content.encode()).hexdigest()
            (raw / (digest + '.html')).write_text(content)
            evidence.append({'url': BASE + path, 'sha256': digest})
        return [{'source_url': BASE + '/communities/test', 'source_sha256': evidence[-1]['sha256']}], evidence

    def test_complete_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cs, evidence = self.fixture(folder)
            validate_evidence(folder, cs, evidence)

    def test_missing_pagination_fails(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cs, evidence = self.fixture(folder, total_pages=2)
            with self.assertRaises(ValueError):
                validate_evidence(folder, cs, evidence)

    def test_tampered_html_fails(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            cs, evidence = self.fixture(folder)
            (folder / 'raw' / (evidence[0]['sha256'] + '.html')).write_text('Changed')
            with self.assertRaises(ValueError):
                validate_evidence(folder, cs, evidence)
