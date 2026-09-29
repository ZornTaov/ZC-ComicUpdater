#what every test here stands on: a fake comic served from this machine, a library and a config folder of
#its own in a temporary folder, and ways to run the real scripts against them. nothing reaches the
#internet and nothing touches a real library - the scripts are driven the way the container drives them,
#as subprocesses, against comics that exist only for the length of a test.
import argparse
import base64
import importlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

#the scripts under test sit one folder up, and are imported from there as well as run
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT not in sys.path:
    sys.path.insert(0, PROJECT)

#a 1x1 png, for a page whose size does not matter
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489'
                    '0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082')
#a 240x240 png. the browser lays an image out at the size it really is, and a check that looks for the
#comic among a page's images passes over anything smaller than 200x200 as a button
PNG_240 = bytes.fromhex('89504e470d0a1a0a0000000d494844520000010000000100010300000066bc3a'
                        '2500000003504c5445b5d0d0630416ea0000001f494441546881edc1010d000000'
                        'c2a0f74f6d0e37a00000000000000000be0d210000019a60e1d50000000049454e'
                        '44ae426082')


def pytest_configure(config):
    config.addinivalue_line("markers", "browser: drives a real browser, directly or through a scrape")
    config.addinivalue_line("markers", "slow: takes more than a few seconds")


def pytest_collection_modifyitems(config, items):
    #a machine with no chrome still runs everything that does not need one, rather than failing it all
    if browser_available():
        return
    skip = pytest.mark.skip(reason="no chrome on this machine")
    for item in items:
        if "browser" in item.keywords:
            item.add_marker(skip)


_browser = None


def browser_available():
    global _browser
    if _browser is None:
        _browser = bool(os.environ.get("MIRROR_BROWSER_BINARY") or shutil.which("chrome")
                        or shutil.which("chromium") or shutil.which("google-chrome")
                        or os.path.exists(r"C:\Program Files\Google\Chrome\Application\chrome.exe"))
    return _browser


# ---------------- a fake comic ----------------
class Site(BaseHTTPRequestHandler):
    #the plumbing every fake site shares. a test subclasses this and writes do_GET with send()
    def send(self, body, ctype="text/html", status=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *ignored):
        pass

    def handle_error(self, *ignored):
        #a browser closing a connection early is not worth a traceback across the results
        pass


def comic_page(image, onward=None, title="Comic", size=240, image_id="comic-image", next_class="cc-next"):
    #the markup most comics come down to: one image with an id the shipped element paths know, and a next
    #link with a class they know. a page with no onward address is the newest one
    link = '<a class="{0}" href="{1}">Next</a>'.format(next_class, onward) if onward else ''
    return ('<html><head><title>{0}</title></head><body><div id="wrap">'
            '<img id="{1}" width="{2}" height="{2}" src="{3}"></div>{4}</body></html>'.format(
                title, image_id, size, image, link))


class Comic(Site):
    #a comic of `pages` pages at /p/1 .. /p/N, each image /img/NNNN.png. a test changes the shape by
    #subclassing with different class attributes, or by overriding page() or image()
    pages = 5
    png = PNG_240

    def page(self, number):
        onward = "/p/{0}".format(number + 1) if number < self.pages else None
        return comic_page("/img/{0:04d}.png".format(number), onward, "Comic {0}".format(number))

    def image(self, name):
        return self.png

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/img/"):
            self.send(self.image(path[len("/img/"):]), "image/png")
            return
        number = path.rsplit("/", 1)[-1]
        if path.startswith("/p/") and number.isdigit() and 1 <= int(number) <= self.pages:
            self.send(self.page(int(number)))
            return
        self.send_error(404)


@pytest.fixture
def serve():
    #starts a fake site on a port of its own and hands back its address. any number can be started in one
    #test; all of them are shut down after it
    started = []

    def start(handler=Comic):
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        started.append(server)
        return "http://127.0.0.1:{0}".format(server.server_port)

    yield start
    for server in started:
        server.shutdown()
        server.server_close()


@pytest.fixture
def stalling():
    #a server that promises a page and never finishes sending it, which is how a site that hangs looks to
    #a browser: loading, forever
    stop = threading.Event()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(8)

    def hold():
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except OSError:
                return
            try:
                conn.recv(4096)
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n"
                             b"Content-Length: 100000\r\n\r\n<html><body>loading")
                stop.wait(180)
            except OSError:
                pass
            finally:
                conn.close()

    threading.Thread(target=hold, daemon=True).start()
    yield "http://127.0.0.1:{0}".format(sock.getsockname()[1])
    stop.set()
    sock.close()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------- a library and its settings ----------------
@pytest.fixture
def config(tmp_path, monkeypatch):
    #a config folder of the test's own, named in the environment so that every script this test runs -
    #and every module it imports afresh - reads its settings and its index from here and nowhere else
    folder = tmp_path / "config"
    (folder / "index").mkdir(parents=True)
    monkeypatch.setenv("MIRROR_CONFIG", str(folder))
    monkeypatch.delenv("MIRROR_ELEMENTS", raising=False)
    return folder


@pytest.fixture
def library(tmp_path, config):
    #laid out the way a real one is: loose pages under Uncompressed, archives on the CBZs shelf
    root = tmp_path / "lib"
    (root / "Uncompressed").mkdir(parents=True)
    (root / "CBZs").mkdir()
    return root


def read_meta(folder):
    with open(os.path.join(str(folder), "mirror_metadata.json"), encoding="utf-8") as f:
        return json.load(f)


def write_meta(folder, metadata):
    os.makedirs(str(folder), exist_ok=True)
    with open(os.path.join(str(folder), "mirror_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)


def pages_in(folder, suffix=".png"):
    return sorted(name for name in os.listdir(str(folder)) if name.endswith(suffix))


def write_index(path, lines):
    with open(str(path), "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def backdate(folder, names, start=1000000000, step=10):
    #gives files write times in the order listed, for lining up by when each was written
    for at, name in enumerate(names):
        stamp = start + at * step
        os.utime(os.path.join(str(folder), name), (stamp, stamp))


# ---------------- running the scripts ----------------
def run(script, *args, cwd=None, env=None, timeout=300):
    #one of the scripts, as its own process, the way update_comics and the web page start them
    return subprocess.run([sys.executable, os.path.join(PROJECT, script)] + [str(a) for a in args],
                          capture_output=True, text=True, errors="replace", cwd=cwd and str(cwd),
                          env=dict(os.environ, PYTHONUNBUFFERED="1", **(env or {})), timeout=timeout)


def fresh(module):
    #a module imported anew, so it reads the environment this test set up rather than whatever an earlier
    #test left behind: mirror_base keeps its whole run in module globals, and reads its element paths once,
    #when it is imported
    sys.modules.pop(module, None)
    return importlib.import_module(module)


@pytest.fixture
def mirror(config):
    return fresh("mirror_base")


@pytest.fixture
def chapters(config):
    return fresh("chapters")


def scrape_args(folder, **over):
    #what setup() would hand back for a scrape into this folder, for calling mirror_base's parts directly
    args = argparse.Namespace(
        URL="https://example.com/1", element_find_manual=False, element_find_next_manual=False,
        prefix=True, output=str(folder), cbz=False, cbz_path=None, increment=1, waittime=0,
        enable_javascript=False, firefox=False, chrome=True, headless=True, verbose=False,
        direction_check=True, multi_page=True, keep_index=False, index=None, index_first=False,
        index_limit=0, check=False, prime=False, page_source=False)
    for key, value in over.items():
        setattr(args, key, value)
    return args


# ---------------- a real browser ----------------
@pytest.fixture
def browser(mirror):
    #headless chrome with javascript on, the way the web page is looked at
    driver = mirror.build_driver(argparse.Namespace(
        firefox=False, chrome=False, headless=True, enable_javascript=True, waittime=0,
        element_find_next_manual=False, verbose=False))
    driver.set_window_size(1280, 900)
    yield driver
    mirror.quit_quietly(driver)


def console_errors(driver):
    try:
        return [entry for entry in driver.get_log("browser") if entry.get("level") == "SEVERE"]
    except Exception:
        return []


# ---------------- the web page ----------------
class WebUI:
    #update_comics serving its page over a library, and a client for its api
    def __init__(self, root, config, password=None, extra=()):
        self.port = free_port()
        self.base = "http://127.0.0.1:{0}".format(self.port)
        self.password = password
        env = {"MIRROR_WEB_PASSWORD": password} if password else {}
        self.process = subprocess.Popen(
            [sys.executable, os.path.join(PROJECT, "update_comics.py"), str(root), "--web", str(self.port),
             "--web-host", "127.0.0.1", "--progress", "0", "--config", str(config)] + list(extra),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
            env=dict(os.environ, PYTHONUNBUFFERED="1", **env))
        #what the container log would show, kept for a test to look through
        self.log = []
        threading.Thread(target=lambda: [self.log.append(line) for line in self.process.stdout],
                         daemon=True).start()
        for _ in range(120):
            try:
                self.call("/api/state")
                return
            except (OSError, urllib.error.URLError):
                if self.process.poll() is not None:
                    break
                time.sleep(0.25)
        raise RuntimeError("the web page never came up:\n" + "".join(self.log[-20:]))

    def call(self, path, body=None, auth=True, ctype="application/json"):
        #(status, answer), where the answer is json when the page said it was and bytes otherwise
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + path, data=data,
                                         method="POST" if body is not None else "GET")
        if auth and self.password:
            secret = base64.b64encode("me:{0}".format(self.password).encode()).decode()
            request.add_header("Authorization", "Basic " + secret)
        if body is not None:
            request.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:
                raw = answer.read()
                kind = answer.headers.get("Content-Type", "")
                return answer.status, (json.loads(raw) if "json" in kind else raw)
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw)
            except ValueError:
                return error.code, raw

    def wait_idle(self, limit=240):
        #until nothing is running or waiting; the last state seen, or None if it never settled
        end = time.time() + limit
        while time.time() < end:
            _, state = self.call("/api/state")
            if not state["current"] and not state["waiting"]:
                return state
            time.sleep(0.5)
        return None

    def said(self):
        return "".join(self.log)

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            self.process.kill()


@pytest.fixture
def web(library, config):
    #the page over this test's library. started on first use, so a test can set the library up first
    started = []

    def start(password=None, extra=()):
        page = WebUI(library, config, password, extra)
        started.append(page)
        return page

    yield start
    for page in started:
        page.stop()
