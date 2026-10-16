#the public install assets must work even when the library is behind a password: a phone's home screen
#fetches its icons without the browser's credentials. none of the library becomes public with them.
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
from PIL import IcoImagePlugin, Image
import pytest

from comicreader.app import create_app
from comicreader.config import Config

WEB = Path(__file__).resolve().parents[1] / "web"


class Head(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.meta = {}
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link":
            self.links.append(attrs)
        elif tag == "meta":
            self.meta[attrs.get("name")] = attrs.get("content")


@pytest.fixture
def installed(tmp_path, library):
    web = tmp_path / "web"
    shutil.copytree(WEB / "public", web)
    shutil.copyfile(WEB / "index.html", web / "index.html")
    app = create_app(Config(library=str(library), data=str(tmp_path / "data"), web=str(web),
                            password="test-password"), scan_in_background=False)
    with TestClient(app) as client:
        yield client


def public_asset(client, path, media):
    response = client.get(path)
    assert response.status_code == 200, path
    assert response.headers["content-type"].split(";")[0] == media
    assert response.headers["cache-control"] == "no-cache"
    return response


def test_the_manifest_meets_the_install_requirements(installed):
    manifest = public_asset(installed, "/manifest.webmanifest", "application/manifest+json").json()
    assert manifest["name"] == "Comic Reader" and manifest["short_name"] == "Comics"
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "fullscreen"
    assert manifest["background_color"] == manifest["theme_color"] == "#111111"
    assert manifest["description"] and manifest["lang"] == "en"
    assert manifest.get("prefer_related_applications", False) is False
    for purpose in ("any", "maskable"):
        for size in (192, 512):
            icon = next(icon for icon in manifest["icons"] if icon["sizes"] == f"{size}x{size}"
                        and icon["purpose"] == purpose)
            response = public_asset(installed, icon["src"], "image/png")
            assert icon["type"] == "image/png"
            with Image.open(BytesIO(response.content)) as image:
                assert image.size == (size, size)
                if purpose == "maskable":
                    assert image.convert("RGBA").getchannel("A").getextrema() == (255, 255)
                    #the drawing fits inside the circle platforms promise not to cut away
                    pixels = image.convert("RGB").load()
                    assert pixels is not None
                    for y in range(size):
                        for x in range(size):
                            if (x - size / 2) ** 2 + (y - size / 2) ** 2 > (size * 0.4) ** 2:
                                assert pixels[x, y] == (17, 17, 17)


def test_apple_and_desktop_install_metadata_points_to_real_assets(installed):
    response = installed.get("/", auth=("reader", "test-password"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    head = Head(response.text)
    assert head.meta["application-name"] == head.meta["apple-mobile-web-app-title"] == "Comic Reader"
    assert head.meta["mobile-web-app-capable"] == head.meta["apple-mobile-web-app-capable"] == "yes"
    assert head.meta["apple-mobile-web-app-status-bar-style"] == "black"
    assert "viewport-fit=cover" in head.meta["viewport"]
    assert any(link["rel"] == "manifest" and link["href"] == "/manifest.webmanifest" for link in head.links)
    apple = [link for link in head.links if link["rel"] == "apple-touch-icon"]
    assert {link["sizes"] for link in apple} == {"152x152", "167x167", "180x180"}
    for link in apple:
        response = public_asset(installed, link["href"], "image/png")
        with Image.open(BytesIO(response.content)) as image:
            assert f"{image.width}x{image.height}" == link["sizes"]
            assert image.convert("RGBA").getchannel("A").getextrema() == (255, 255)
    for link in head.links:
        if link["rel"] == "icon":
            response = installed.get(link["href"])
            assert response.status_code == 200
            if link.get("type") == "image/png":
                with Image.open(BytesIO(response.content)) as image:
                    assert f"{image.width}x{image.height}" == link["sizes"]
    pinned = next(link for link in head.links if link["rel"] == "mask-icon")
    public_asset(installed, pinned["href"], "image/svg+xml")
    with Image.open(BytesIO(installed.get("/favicon.ico").content)) as image:
        assert isinstance(image, IcoImagePlugin.IcoImageFile)
        assert image.ico.sizes() == {(16, 16), (32, 32), (48, 48)}
    tiles = ET.fromstring(public_asset(installed, head.meta["msapplication-config"], "application/xml").content)
    assert tiles.findtext("./msapplication/tile/TileColor") == head.meta["msapplication-TileColor"] == "#111111"
    tile = tiles.find("./msapplication/tile/square150x150logo")
    assert tile is not None
    with Image.open(BytesIO(public_asset(installed, tile.attrib["src"], "image/png").content)) as image:
        assert image.size == (150, 150)


@pytest.mark.parametrize("path", ["/", "/index.html", "/api/library", "/api/settings", "/api/health",
                                  "/missing.png", "/assets/private.js", "/apple-touch-icon-secret.png"])
def test_only_the_named_install_assets_skip_the_password(installed, path):
    response = installed.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="reader"'
