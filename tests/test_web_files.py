#the page is a folder of files rather than one, so the server hands out whatever index.html names - and
#nothing outside that folder, however the address is spelled.
import base64
import http.client
import os
import re

import comiclib.web.server as server
from comiclib.paths import content_stamp

PASSWORD = "hunter2"


def fetch(page, path, auth=True):
    #(status, content type, body), with the path sent exactly as given: urllib would tidy a ../ away
    connection = http.client.HTTPConnection("127.0.0.1", page.port, timeout=30)
    headers = {}
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode("me:{0}".format(PASSWORD).encode()).decode()
    connection.request("GET", path, headers=headers)
    answer = connection.getresponse()
    try:
        return answer.status, answer.getheader("Content-Type", ""), answer.read()
    finally:
        connection.close()


def test_every_file_the_page_names_is_served_as_what_it_is(web):
    page = web(password=PASSWORD)
    status, kind, html = fetch(page, "/")
    assert status == 200 and kind.startswith("text/html"), (status, kind)
    parts = re.findall(r'(?:href|src)="((?:css|js)/[^"]+)"', html.decode())
    assert any(".css?" in p for p in parts) and any(".js?" in p for p in parts), parts
    for part in parts:
        file, _, stamp = part.partition("?v=")
        #each named by an address that changes with what the file holds, which a cache cannot have kept
        assert stamp == content_stamp(os.path.join(server.page_folder, file)), part
        status, kind, body = fetch(page, "/" + part)
        wanted = "text/css" if file.endswith(".css") else "text/javascript"
        assert status == 200 and kind.startswith(wanted) and body.strip(), (part, status, kind)
        #the files are behind the password as much as the page and its api are
        assert fetch(page, "/" + part, auth=False)[0] == 401, part


def test_a_changed_script_is_a_new_address_without_a_restart(tmp_path, monkeypatch):
    #read on every request like the files themselves, so an edit to the mounted folder is asked for afresh
    #at once. an address naming nothing in the folder, or something outside it, is left as it is
    folder = tmp_path / "web_page"
    (folder / "js").mkdir(parents=True)
    (folder / "css").mkdir()
    (folder / "js" / "main.js").write_text("one()")
    (folder / "css" / "base.css").write_text("body {}")
    monkeypatch.setattr(server, "page_folder", str(folder))
    html = (b'<link rel="stylesheet" href="css/base.css"><script src="js/main.js"></script>'
            b'<script src="js/gone.js"></script><script src="js/../../x.js"></script>'
            b'<a href="https://example.com/js/main.js">x</a>')
    first = server.stamped(html)
    stamps = re.findall(rb'\?v=(\w+)', first)
    assert len(stamps) == 2, first
    assert b'src="js/gone.js"' in first and b'src="js/../../x.js"' in first and b'"https://example.com/js/main.js"' in first
    (folder / "js" / "main.js").write_text("two()")
    again = re.findall(rb'\?v=(\w+)', server.stamped(html))
    assert again[0] == stamps[0] and again[1] != stamps[1], (stamps, again)


def test_an_address_outside_the_folder_reads_nothing(web):
    page = web(password=PASSWORD)
    for path in ("/../update_comics.py", "/%2e%2e/README.md", "/js/../../comiclib/web/server.py",
                 "/nothing-here.js"):
        status, _, body = fetch(page, path)
        assert status == 404, (path, status, body[:80])


def test_the_openapi_spec_is_served(web):
    page = web(password=PASSWORD)
    status, kind, body = fetch(page, "/api/openapi.yaml")
    assert status == 200 and kind.startswith("text/yaml"), (status, kind)
    assert b"openapi" in body and b"paths" in body
    assert fetch(page, "/api/openapi.yaml", auth=False)[0] == 401


def test_only_the_folders_own_pages_and_scripts_are_handed_out(tmp_path, monkeypatch):
    #a script beside the folder, which every spelling of the climb out to it has to miss
    folder = tmp_path / "web_page"
    (folder / "js").mkdir(parents=True)
    (folder / "index.html").write_text("<html></html>")
    (folder / "js" / "main.js").write_text("")
    (folder / "notes.txt").write_text("")
    (tmp_path / "secret.js").write_text("")
    monkeypatch.setattr(server, "page_folder", str(folder))
    assert server.page_part("/") == str(folder / "index.html")
    assert server.page_part("/js/main.js") == str(folder / "js" / "main.js")
    assert server.page_part("/js/../js/main.js") == str(folder / "js" / "main.js")
    for path in ("/../secret.js", "/js/../../secret.js", "/%2E%2E/secret.js", "/notes.txt",
                 "/" + str(tmp_path / "secret.js")):
        assert server.page_part(path) is None, path
