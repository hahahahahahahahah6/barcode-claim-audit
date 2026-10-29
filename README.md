# barcode-claim-audit 0.1.0

An offline static audit of documented code-reading claims against Python source.
Requires Python >=3.9, with no runtime dependencies. Source is parsed with AST
and never executed. Environment files are never opened.

## Usage

```sh
python3 -m pip install .
barcode-claim-audit /path/to/project
python3 -m barcode_claim_audit /path/to/project --json
python3 -m barcode_claim_audit /path/to/project --verbose --ignore 'vendor/*'
python3 -m barcode_claim_audit /path/to/project --fail-on MEDIUM
python3 -m barcode_claim_audit --version
```

JSON stdout contains verdict, findings (rule, severity, message), evidence flags,
and inspected file paths. Human output shows the verdict and all findings.
Repeat --ignore to exclude relative paths using glob patterns; matching directories
are pruned. --verbose adds a file count in human output. Default threshold is HIGH;
MEDIUM reports remain visible but exit successfully. Exit codes: 0 for PASS,
2 for findings meeting the threshold, 1 for usage or filesystem errors.

## Matching and rules

Only root README.md and Markdown files with a docs path component contribute
claims. Fenced code is excluded; inline code counts. Matching lowercases text,
expands n't to not, replaces hyphens with spaces and joins whitespace within
blank-line-separated paragraphs. Exact templates use word boundaries, longest
first. Negative spans are removed before positive matching. The full template
sets are in barcode_claim_audit/phrases.py. Examples:

```text
scans qr codes
supports barcode scanning
does not scan qr codes
no barcode support
```

One finding per family, at most two: documented-barcode-claim-false is HIGH
when a positive template has no production evidence, or MEDIUM when evidence
exists only in tests. documented-no-barcode-claim-false is HIGH when a negative
template conflicts with production evidence. Without claims the result is PASS.
With no source, a positive template yields HIGH and a negative one yields PASS.

Production evidence excludes tests/, test_*.py, *_test.py, fixtures/, docs/,
examples/, and symlinks. Test evidence is limited to tests/ and test-named files
outside the other excluded directories. Imports are resolved per module, including
aliases; local functions and classes shadow imported names.

Supported calls: pyzbar.pyzbar.decode, pylibdmtx.pylibdmtx.decode,
zxingcpp.read_barcode/read_barcodes, cv2.QRCodeDetector and
cv2.barcode_BarcodeDetector. Construction alone counts for cv2. Bound detector
methods detect, detectAndDecode and detectAndDecodeMulti (including self
attributes, with targets and chained construction) consequently qualify too.

## Limitations

Only the exact templates count. A bare QR or barcode word is insufficient.
Generation, camera capture, image opening, file export and setup instructions
about a user holding a code up to a camera are outside the claim vocabulary.
Comments, docstrings and strings alone are never evidence. Imports without calls,
image creation, camera access and unbound lookalike methods do not qualify.
System code reader helpers invoked through subprocess are not counted; command
names inside strings are never evidence. Other scan stacks, including phone-camera
SDKs and hardware scanner wedges that type keystrokes, are out of scope; only
the Python decode routes listed above are counted.

This checks syntax rather than runtime success, reachability, dependency availability,
image quality or actual hardware. Dynamic imports and reassignment are not modeled.
Local definitions conservatively shadow imports throughout a module. Syntax-invalid
source contributes no evidence. Filesystem errors produce a usage error.

## Development

```sh
python3 -m unittest discover
python3 -m build
```

The sdist includes the test suite and fixtures. License: MIT.
