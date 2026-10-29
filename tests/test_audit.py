"""Behavior, CLI, scope and packaging contracts."""
import builtins
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from barcode_claim_audit import __version__
from barcode_claim_audit.audit import audit, claims, source_evidence
from barcode_claim_audit.phrases import BARCODE, NOBARCODE
from tests.cases import CASES

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / 'tests/fixtures'
POS = 'documented-barcode-claim-false'
NEG = 'documented-no-barcode-claim-false'


class AuditTests(unittest.TestCase):
    def tree(self, text, source=None, location='app.py'):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        (root / 'README.md').write_text(text)
        if source is not None:
            path = root / location
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        return root

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'barcode_claim_audit', *map(str, args)], text=True, capture_output=True)

    def test_testonly(self):
        for threshold, verdict in [('HIGH', 'PASS'), ('MEDIUM', 'FAIL')]:
            result = audit(FIX / 'testonly', fail_on=threshold)
            self.assertEqual(result['verdict'], verdict)
            self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [(POS, 'MEDIUM')])

    def test_negative(self):
        result = audit(FIX / 'no-barcode')
        self.assertEqual(result['verdict'], 'FAIL')
        self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [(NEG, 'HIGH')])

    def test_self_audit(self):
        self.assertEqual(claims((ROOT / 'README.md').read_text()), (False, False))
        self.assertEqual(audit(ROOT)['findings'], [])
        self.assertEqual(audit(ROOT)['verdict'], 'PASS')

    def test_normalization(self):
        for text, expected in [("DOESN'T scan\nQR-codes", (False, True)), ('scans\nQR-codes', (True, False)), ('scans\n\nqr codes', (False, False)), ('prescans barcodesuffix', (False, False)), ('`scans qr codes`', (True, False)), ('```text\nscans qr codes\n```', (False, False)), ('~~~~\nscans qr codes\n~~~~', (False, False))]:
            self.assertEqual(claims(text), expected)

    def test_docs_ignore(self):
        root = self.tree('Neutral')
        path = root / 'nested/docs/guide.md'
        path.parent.mkdir(parents=True)
        path.write_text('scans qr codes')
        self.assertEqual(audit(root)['verdict'], 'FAIL')
        self.assertEqual(audit(root, ['nested/docs/*'])['verdict'], 'PASS')
        self.assertEqual(self.cli(root, '--ignore', 'nested/docs/*', '--json').returncode, 0)
        (root / 'OTHER.md').write_text('scans qr codes')
        self.assertEqual(audit(root, ['nested'])['findings'], [])

    def test_scope(self):
        for location, severity in [('tests/reader.py', 'MEDIUM'), ('test_reader.py', 'MEDIUM'), ('reader_test.py', 'MEDIUM'), ('fixtures/reader.py', 'HIGH'), ('docs/reader.py', 'HIGH'), ('examples/reader.py', 'HIGH')]:
            with self.subTest(location=location):
                self.assertEqual(audit(self.tree('scans qr codes', CASES['good'][0], location))['findings'][0]['severity'], severity)

    def test_symlinks(self):
        root = self.tree('scans qr codes')
        outside = self.tree('Neutral', CASES['good'][0])
        (root / 'link.py').symlink_to(outside / 'app.py')
        (root / 'linked').symlink_to(outside, target_is_directory=True)
        self.assertEqual(audit(root)['findings'][0]['severity'], 'HIGH')

    def test_env_never_opened(self):
        def guard(delegate):
            def checked(file, *args, **kwargs):
                if not isinstance(file, int) and Path(file).name == '.env':
                    raise AssertionError('environment file opened')
                return delegate(file, *args, **kwargs)
            return checked
        with patch('builtins.open', guard(builtins.open)), patch('io.open', guard(io.open)):
            audit(ROOT)
            audit(FIX)

    def test_cli(self):
        self.assertEqual(self.cli('--version').stdout.strip(), '0.1.0')
        self.assertEqual(self.cli('/nonexistent-barcode-root').returncode, 1)
        self.assertEqual(self.cli('--unknown').returncode, 1)
        self.assertEqual(self.cli(FIX / 'good', '--verbose').returncode, 0)
        for name, code, findings in [('good', 0, []), ('bad', 2, [(POS, 'HIGH')]), ('testonly', 0, [(POS, 'MEDIUM')]), ('no-barcode', 2, [(NEG, 'HIGH')])]:
            result = self.cli(FIX / name, '--json')
            self.assertEqual(result.returncode, code)
            data = json.loads(result.stdout)
            self.assertEqual([(f['rule'], f['severity']) for f in data['findings']], findings)
        self.assertEqual(self.cli(FIX / 'testonly', '--fail-on', 'MEDIUM').returncode, 2)

    def test_packaging(self):
        metadata = (ROOT / 'pyproject.toml').read_text()
        self.assertIn('barcode_claim_audit.__main__:main', metadata)
        self.assertIn('requires-python = ">=3.9"', metadata)
        self.assertIn('version = "0.1.0"', metadata)
        self.assertEqual(__version__, '0.1.0')
        self.assertIn('MIT License', (ROOT / 'LICENSE').read_text())
        self.assertIn('recursive-include tests *.py *.md .env', (ROOT / 'MANIFEST.in').read_text())
        self.assertTrue((FIX / '.env').is_file())
        paths = list((ROOT / 'barcode_claim_audit').rglob('*.py')) + list((ROOT / 'tests').rglob('*.py')) + [ROOT / 'README.md']
        for path in paths:
            text = path.read_text()
            self.assertIsNone(re.search(r'\bpython\s+(?:-m|-c|\w+\.py)', text), str(path))
            self.assertIsNone(re.search(r'(?:AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|' + '-----BEGIN ' + 'PRIVATE KEY-----)', text), str(path))

    def test_invalid_syntax(self):
        self.assertFalse(source_evidence('def broken('))

    def test_duplicate_findings(self):
        result = audit(self.tree('scans qr codes and scans barcodes\n\ndoes not scan qr codes'))
        self.assertEqual(len(result['findings']), 1)
        self.assertEqual(result['findings'][0]['rule'], POS)


def add_cases():
    for name, (source, good) in CASES.items():
        def check(self, name=name, good=good):
            result = audit(FIX / name)
            self.assertEqual(result['verdict'], 'PASS' if good else 'FAIL')
            self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [] if good else [(POS, 'HIGH')])
        setattr(AuditTests, 'test_source_' + name, check)
    for family, phrases in [('positive', BARCODE), ('negative', NOBARCODE)]:
        for index, phrase in enumerate(phrases):
            def check(self, phrase=phrase, family=family):
                self.assertEqual(claims(phrase), (family == 'positive', family == 'negative'))
                result = audit(self.tree(phrase))
                self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [] if family == 'negative' else [(POS, 'HIGH')])
            setattr(AuditTests, 'test_phrase_{}_{}'.format(family, index), check)
    for index, text in enumerate(['Neutral tool.', 'generates qr codes', 'creates qr codes', 'renders a barcode', 'hold the code up to the camera first', 'barcode', 'camera capture and image opening', 'file export']):
        def check(self, text=text):
            self.assertEqual(audit(self.tree(text))['findings'], [])
        setattr(AuditTests, 'test_nonclaim_{}'.format(index), check)


add_cases()


def add_document_cases():
    for name in ['no-claim', 'generation-claim', 'user-instruction', 'bare-word', 'fenced-code', 'inline-code', 'negation', 'no-source-positive', 'no-source-negative']:
        def check(self, name=name):
            result = audit(FIX / name)
            failed = name in {'inline-code', 'no-source-positive'}
            self.assertEqual(result['verdict'], 'FAIL' if failed else 'PASS')
            self.assertEqual([(f['rule'], f['severity']) for f in result['findings']], [(POS, 'HIGH')] if failed else [])
        setattr(AuditTests, 'test_doc_fixture_' + name.replace('-', '_'), check)


add_document_cases()
