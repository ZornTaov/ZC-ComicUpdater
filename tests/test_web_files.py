#the page is a folder of files rather than one, so the server hands out whatever index.html names - and
#nothing outside that folder, however the address is spelled.
import base64
import http.client
import re

import comiclib.web.server as server

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
    assert any(p.endswith(".css") for p in parts) and any(p.endswith(".js") for p in parts), parts
    for part in parts:
        status, kind, body = fetch(page, "/" + part)
        wanted = "text/css" if part.endswith(".css") else "text/javascript"
        assert status == 200 and kind.startswith(wanted) and body.strip(), (part, status, kind)
        #the files are behind the password as much as the page and its api are
        assert fetch(page, "/" + part, auth=False)[0] == 401, part


def test_an_address_outside_the_folder_reads_nothing(web):
    page = web(password=PASSWORD)
    for path in ("/../update_comics.py", "/%2e%2e/README.md", "/js/../../comiclib/web/server.py",
                 "/nothing-here.js"):
        status, _, body = fetch(page, path)
        assert status == 404, (path, status, body[:80])


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
