#the page itself, served over http: who may ask, and which of the other modules answers each address.
#standard library only, so the container needs nothing new.
import base64
import hmac
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from comiclib.paths import PROJECT
from comiclib.web.adding import parse_entries
from comiclib.web.edits import discard_walk, fix_chapter, insert_page, save_config, save_settings, try_chapter_list
from comiclib.web.elementpaths import element_settings, save_elements
from comiclib.web.jobs import LogTee, Runner
from comiclib.web.views import chapters_label, comic_detail, config_view, find_comic, is_running, job_view
from comiclib.web.views import walk_needed
from comiclib.web.views import library_view, walked_pages

#the page, read afresh on every request so editing it needs no restart. it stays beside the scripts, where
#it is edited, rather than in here
page_folder = os.path.join(PROJECT, "web_page")

#named here rather than asked of mimetypes, which on windows reads the registry, where .js can be text/plain:
#a browser will not run a script served as that. anything else in the folder is not served at all
page_kinds = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
              ".js": "text/javascript; charset=utf-8"}


def page_part(address):
    #the file in the page's folder an address names, or None. resolved and then checked to still be inside
    #the folder, so a request for /../config/ComicScraper.json reads nothing
    name = unquote(address).lstrip("/") or "index.html"
    full = os.path.normpath(os.path.join(page_folder, name))
    try:
        if os.path.commonpath([page_folder, full]) != page_folder:
            return None
    except ValueError:
        #on windows, an address naming another drive, /C:/x, which join takes as absolute
        return None
    if os.path.splitext(full)[1] not in page_kinds or not os.path.isfile(full):
        return None
    return full


def make_handler(runner, args, uc, tee):
    password = os.environ.get("MIRROR_WEB_PASSWORD") or ""

    class Handler(BaseHTTPRequestHandler):
        server_version = "update_comics"

        def log_message(self, *ignored):
            pass

        def allowed(self):
            if not password:
                return True
            given = self.headers.get("Authorization", "")
            if given.startswith("Basic "):
                try:
                    _, _, secret = base64.b64decode(given[6:]).decode("utf-8").partition(":")
                    if hmac.compare_digest(secret, password):
                        return True
                except (ValueError, UnicodeDecodeError):
                    pass
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="update_comics"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False

        def reply(self, body, status=200, kind="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return
            where = urlsplit(self.path)
            if not where.path.startswith("/api/"):
                #read on every request, so editing the page needs no restart
                part = page_part(where.path)
                if part is None:
                    if where.path == "/":
                        self.reply("the page is missing: {0} should hold index.html. Copy the web_page folder "
                                   "there beside the scripts.".format(page_folder).encode(), 500, "text/plain")
                    else:
                        self.reply({"error": "not found"}, 404)
                    return
                try:
                    with open(part, "rb") as f:
                        self.reply(f.read(), kind=page_kinds[os.path.splitext(part)[1]])
                except OSError as error:
                    self.reply("could not read {0}: {1}".format(part, error).encode(), 500, "text/plain")
            elif where.path == "/api/state":
                since = int((parse_qs(where.query).get("since") or ["0"])[0] or 0)
                lines, seq = tee.since(since)
                with runner.changed:
                    current, waiting, history = runner.current, list(runner.waiting), list(runner.recent)
                self.reply({
                    "now": time.time(),
                    "root": args.root,
                    "jobs_at_once": args.jobs,
                    "next_run": runner.next_run.timestamp() if runner.next_run else None,
                    "current": job_view(current, uc, live=True) if current else None,
                    "waiting": [job_view(job, uc) for job in waiting],
                    #summarised as each finished, so a job from before a restart reads the same as one since
                    "history": history,
                    "log": [{"seq": s, "at": at, "text": text} for s, at, text in lines],
                    "seq": seq,
                })
            elif where.path == "/api/config":
                self.reply(config_view(args, uc))
            elif where.path == "/api/elements":
                self.reply(element_settings(args, uc))
            elif where.path == "/api/comics":
                self.reply(library_view(args, uc))
            elif where.path == "/api/comic":
                name = (parse_qs(where.query).get("name") or [""])[0]
                detail, problem = comic_detail(args, uc, runner, name)
                self.reply(detail if detail else {"error": problem}, 200 if detail else 404)
            else:
                self.reply({"error": "not found"}, 404)

        def do_POST(self):
            if not self.allowed():
                return
            #json only: a page on another site cannot send that without the browser asking first, which is
            #what keeps a stray link from starting scrapes
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                self.reply({"error": "send json"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self.reply({"error": "that was not json"}, 400)
                return
            path = urlsplit(self.path).path

            if path == "/api/update":
                names = [str(name) for name in body.get("names") or []]
                job = runner.submit_update(names, "Started from the web page")
                self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/add":
                entries, problems = parse_entries(body.get("rows") or body.get("entries") or [],
                                                  uc.with_config(args))
                #whatever the request did not say is taken from the settings file, so adding a comic
                #through the page and adding one any other way start from the same options
                fallback = uc.load_config().get("add_defaults", {})
                try:
                    options = {}
                    for key in ("prime", "prefix", "javascript", "cbz", "direction_check"):
                        options[key] = bool(body[key]) if key in body else bool(fallback.get(key))
                    for key, floor in (("increment", 1), ("waittime", 0)):
                        given = body.get(key, fallback.get(key, floor))
                        options[key] = int(given if given not in ("", None) else floor)
                except (TypeError, ValueError):
                    problems.append("the starting number and wait time must be whole numbers")
                #a comic the adder already knows is long, cut into parts from the start rather than walked
                #for it afterwards. not a default from the settings file: it is about these comics only
                every = str(body.get("every") or "").strip()
                if every and (not every.isdigit() or int(every) < 1):
                    problems.append("pages per part has to be a whole number, or blank for none")
                options["every"] = int(every) if every.isdigit() and int(every) > 0 else None
                if problems:
                    self.reply({"error": "; ".join(problems)}, 400)
                elif not entries:
                    self.reply({"error": "no comics given"}, 400)
                else:
                    job = runner.submit_add(entries, options)
                    self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/settings":
                name = str(body.get("name") or "")
                status, result = save_settings(args, uc, runner, name, body.get("settings") or {},
                                               body.get("updated"))
                if status == 200 and body.get("update_after"):
                    job = runner.submit_update([name], "Edited on the web page")
                    result["queued"] = job.label
                self.reply(result, status)
            elif path == "/api/config":
                status, result = save_config(args, uc, body.get("settings") or {})
                self.reply(result, status)
            elif path == "/api/elements":
                status, result = save_elements(args, uc, body)
                self.reply(result, status)
            elif path == "/api/check":
                url = str(body.get("url") or "").strip()
                if not re.match(r"^https?://\S+$", url):
                    self.reply({"error": "that is not a full http(s) address"}, 400)
                else:
                    job = runner.submit_check(url)
                    self.reply({"queued": job.id, "label": job.label})
            elif path == "/api/chapterize":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name)
                if comic is None:
                    self.reply({"error": "no comic named {0}".format(name)}, 404)
                elif is_running(runner, name):
                    self.reply({"error": "that comic is being scraped right now"}, 409)
                else:
                    #no chapter list means the comic's own addresses, which is the right source for one
                    #that counts /comic/issue-4-page-7 and has no archive page worth reading
                    listing = (str(body.get("url") or "").strip()
                               or (comic.metadata.get("chapters") or {}).get("source_url"))
                    every = str(body.get("every") or "").strip()
                    every = int(every) if every.isdigit() and int(every) > 0 else None
                    #taking the existence of the record to mean the comic was walked once stopped the
                    #chaptering of a 3,500 page comic with nothing to align against, so it is asked
                    #whether it reaches the comic's newest page. a comic cut by size may not need walking
                    #at all, which the job finds out from its filenames, since listing a folder of
                    #thousands on a network share is no thing to make a request wait for
                    walk = walk_needed(args, uc, comic)
                    numbers_first = bool(every) and walk == "start"
                    #what the reader chose after this last stopped to ask. only names of files in the
                    #comic's own folder are passed on, and the job checks each again before moving it
                    aside = body.get("set_aside") if isinstance(body.get("set_aside"), list) else []
                    choices = {"set_aside": [str(name) for name in aside
                                             if str(name) == os.path.basename(str(name)) and str(name) not in ("", ".", "..")],
                               "discard_walk": body.get("discard_walk") is True, "walk": body.get("walk") is True}
                    job = runner.submit_chapterize(comic, listing, walk, every, choices)
                    self.reply({"queued": job.id, "label": job.label, "walking": bool(walk) and not numbers_first,
                                "carrying_on": walk == "carry on", "numbers_first": numbers_first,
                                "from": "every" if every else "archive" if listing else "addresses"})
            elif path == "/api/trylist":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name) if name else None
                status, result = try_chapter_list(uc.with_config(args), comic, body)
                self.reply(result, status)
            elif path == "/api/pages":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name)
                if comic is None:
                    self.reply({"error": "no comic named {0}".format(name)}, 404)
                else:
                    status, result = walked_pages(uc.with_config(args), comic)
                    self.reply(result, status)
            elif path == "/api/insert":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name)
                if comic is None:
                    self.reply({"error": "no comic named {0}".format(name)}, 404)
                elif is_running(runner, name):
                    self.reply({"error": "that comic is being scraped right now"}, 409)
                else:
                    status, result = insert_page(uc.with_config(args), comic, body)
                    self.reply(result, status)
            elif path == "/api/chapterfix":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name)
                if comic is None:
                    self.reply({"error": "no comic named {0}".format(name)}, 404)
                elif is_running(runner, name):
                    self.reply({"error": "that comic is being scraped right now"}, 409)
                else:
                    status, result = fix_chapter(uc.with_config(args), comic, body)
                    self.reply(result, status)
            elif path == "/api/discardwalk":
                name = str(body.get("name") or "")
                comic = find_comic(args, uc, name)
                if comic is None:
                    self.reply({"error": "no comic named {0}".format(name)}, 404)
                elif runner.current is not None and runner.current.label == chapters_label(name):
                    self.reply({"error": "that comic's chapters are being worked out right now"}, 409)
                else:
                    status, result = discard_walk(uc.with_config(args), uc, comic)
                    self.reply(result, status)
            elif path == "/api/stop":
                self.reply({"stopping": runner.stop()})
            elif path == "/api/drop":
                self.reply({"dropped": runner.drop(int(body.get("id") or 0))})
            else:
                self.reply({"error": "not found"}, 404)

    return Handler


def start(args, uc):
    tee = LogTee(sys.stdout)
    sys.stdout = tee
    runner = Runner(args, uc)
    server = ThreadingHTTPServer((args.web_host, args.web), make_handler(runner, args, uc, tee))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    shown = "localhost" if args.web_host in ("0.0.0.0", "", "::") else args.web_host
    print("Web page on http://{0}:{1}/{2}".format(
        shown, args.web, "" if os.environ.get("MIRROR_WEB_PASSWORD") else
        " (no password set; anyone who can reach this port can start scrapes)"), flush=True)
    return runner
