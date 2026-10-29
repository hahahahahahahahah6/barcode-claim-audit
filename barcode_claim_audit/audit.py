"""Documentation matching and provider-resolved AST inspection."""
import ast
import fnmatch
import re
from pathlib import Path
from .phrases import BARCODE, NOBARCODE

DIRECT = {'pyzbar.pyzbar.decode', 'pylibdmtx.pylibdmtx.decode', 'zxingcpp.read_barcode', 'zxingcpp.read_barcodes'}
CONSTRUCTORS = {'cv2.QRCodeDetector', 'cv2.barcode_BarcodeDetector'}
MODULES = {'pyzbar.pyzbar', 'pylibdmtx.pylibdmtx', 'zxingcpp', 'cv2'}


def claims(text):
    """Match exact templates outside fenced code blocks."""
    lines = []
    fence = None
    for line in text.splitlines():
        match = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if fence:
            if match and match[1][0] == fence[0] and len(match[1]) >= len(fence) and not match[2].strip():
                fence = None
            lines.append('')
        elif match:
            fence = match[1]
            lines.append('')
        else:
            lines.append(line)
    positive = negative = False
    def pattern(items):
        return r'\b(?:' + '|'.join(re.escape(p) for p in sorted(items, key=len, reverse=True)) + r')\b'
    for paragraph in re.split(r'\n\s*\n', '\n'.join(lines)):
        normalized = re.sub(r'\s+', ' ', paragraph.lower().replace("n't", ' not').replace('-', ' '))
        negative |= bool(re.search(pattern(NOBARCODE), normalized))
        normalized = re.sub(pattern(NOBARCODE), ' ', normalized)
        positive |= bool(re.search(pattern(BARCODE), normalized))
    return positive, negative


def source_evidence(text):
    """Resolve imports; local function and class definitions shadow them."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    aliases = {}
    shadows = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            shadows.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in MODULES:
                    aliases[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module in MODULES:
            for alias in node.names:
                aliases[alias.asname or alias.name] = node.module + '.' + alias.name
    def resolve(node):
        if isinstance(node, ast.Name):
            return '' if node.id in shadows else aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''
    # Every bound/chained detector route contains a constructor call,
    # which is independently sufficient evidence under this audit's rules.
    return any(isinstance(n, ast.Call) and resolve(n.func) in DIRECT | CONSTRUCTORS for n in ast.walk(tree))


def audit(root, ignore=(), fail_on='HIGH'):
    """Inspect docs and source without executing code or opening environment files."""
    root = Path(root)
    if not root.is_dir():
        raise ValueError('root must be a readable directory')
    positive = negative = prod = test = False
    scanned = []
    excluded = {'fixtures', 'docs', 'examples'}
    def walk(directory):
        for path in sorted(directory.iterdir()):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or any(fnmatch.fnmatchcase(rel, g) for g in ignore):
                continue
            if path.is_dir():
                yield from walk(path)
            else:
                yield path
    for path in walk(root):
        rel = path.relative_to(root)
        parts = rel.parts
        if (rel.as_posix() == 'README.md' or 'docs' in parts) and path.suffix.lower() == '.md':
            p, n = claims(path.read_text(encoding='utf-8', errors='replace'))
            positive |= p
            negative |= n
            scanned.append(rel.as_posix())
        elif path.suffix == '.py' and not excluded.intersection(parts[:-1]):
            is_test = 'tests' in parts[:-1] or path.name.startswith('test_') or path.name.endswith('_test.py')
            evidence = source_evidence(path.read_text(encoding='utf-8', errors='replace'))
            if is_test:
                test |= evidence
            else:
                prod |= evidence
            scanned.append(rel.as_posix())
    findings = []
    if positive and not prod:
        findings.append({'rule': 'documented-barcode-claim-false', 'severity': 'MEDIUM' if test else 'HIGH', 'message': 'Documented capability has only test evidence.' if test else 'Documented capability lacks production evidence.'})
    if negative and prod:
        findings.append({'rule': 'documented-no-barcode-claim-false', 'severity': 'HIGH', 'message': 'Documented absence conflicts with production evidence.'})
    failed = any(f['severity'] == 'HIGH' or fail_on == 'MEDIUM' for f in findings)
    return {'verdict': 'FAIL' if failed else 'PASS', 'findings': findings, 'evidence': {'production': prod, 'tests': test}, 'files': scanned}
