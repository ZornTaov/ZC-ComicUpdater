"""Dump the reader's OpenAPI spec to docs/reader-openapi.json.

Run from the repo root with the reader's dependencies installed:
    python docs/generate_reader_spec.py
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "reader"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from comicreader.app import create_app
from comicreader.config import Config

with tempfile.TemporaryDirectory() as tmp:
    config = Config(library=tmp, data=tmp, web=tmp)
    app = create_app(config, scan_in_background=False)
    spec = app.openapi()

out = os.path.join(os.path.dirname(__file__), "reader-openapi.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(spec, f, indent=2)
    f.write("\n")
print("wrote {0}".format(out))
