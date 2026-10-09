#a library of the reader's own for each test, laid out the way the scraper lays one out: loose pages under
#Uncompressed/, archives under CBZs/, made by the scraper's own packing so the reader is tested against
#exactly what it will be given. nothing here names a real comic.
import json
import os
import struct
import sys
import zlib

import pytest

READER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, READER)
sys.path.insert(0, os.path.dirname(READER))

from comicreader.app import create_app  # noqa: E402
from comicreader.config import Config  # noqa: E402


def png(width, height, shade=0):
    #a real png of that size, so a cover can be made of it and its size read back
    rows = b"".join(b"\x00" + bytes([shade]) * width for _ in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def comic_folder(library, name, pages, settings=None, extra=None):
    folder = library / "Uncompressed" / name
    folder.mkdir(parents=True)
    for n in range(1, pages + 1):
        (folder / "{0:04d}_page{0}.png".format(n)).write_bytes(png(40, 60, n))
    for file_name, body in (extra or {}).items():
        (folder / file_name).write_bytes(body)
    metadata = {"schema": 2, "settings": dict({"url": "https://example.com/{0}/1".format(name)}, **(settings or {}))}
    (folder / "mirror_metadata.json").write_text(json.dumps(metadata))
    return folder


def page_names(folder):
    return sorted(name for name in os.listdir(str(folder)) if name != "mirror_metadata.json")


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    (root / "CBZs").mkdir(parents=True)
    (root / "Uncompressed").mkdir()
    return root


@pytest.fixture
def make_app(tmp_path, library):
    made = []

    def make(**options):
        config = Config(library=str(library), data=str(tmp_path / "data"), web=str(tmp_path / "no-web"), **options)
        app = create_app(config, scan_in_background=False)
        app.state.library.scan()
        made.append(app)
        return app
    return make


@pytest.fixture
def client(make_app):
    from fastapi.testclient import TestClient

    def make(**options):
        app = make_app(**options)
        return TestClient(app), app
    return make
