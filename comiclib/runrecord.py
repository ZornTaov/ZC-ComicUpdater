#what a scrape writes into mirror_metadata.json about itself: the settings a later run is rebuilt from,
#where it is up to, and a record of the run. handed everything the run knows, rather than reaching into
#the scrape for it.
import os
import sys

from comiclib.exits import INTERRUPTED as EXIT_INTERRUPTED, OK as EXIT_OK
from comiclib.metadata import METADATA_FILE as metadata_file, load, now_stamp, write_json

#how many run records to keep. a monthly updater would otherwise grow this file forever; the first run is
#always kept, since it is the one that says how the comic was originally scraped
max_runs = 20


def resume_point(scrape_state):
    #where a follow-up run should pick up: the page after the last saved one, if we already moved on.
    #
    #what counts as "moved on" is a page this run walked to meaning to save it - not wherever the browser
    #happens to be standing. a comic whose last page's next button goes back to the front page leaves the
    #browser on the front page, and a comic that wraps round leaves it on page one; writing either of
    #those down as the place to carry on from is how a finished comic starts itself again from the top.
    url = scrape_state["last_page_url"]
    increment = scrape_state["last_increment"]
    walked = scrape_state["walked_to"]
    if walked and walked != url:
        #a page walked to but never saved: carry on there, counting it as the page after the last saved one
        return walked, increment + 1 if increment is not None else increment
    return url, increment


def failure_noted(args, folder, *, scrape_state, run_id, run_start, stop_reason, exit_code):
    #a run that saved nothing because it failed on the page it started from. it used to write nothing at
    #all, so a comic whose resume address had gone bad - the front page a last next link led to, before
    #anything knew better - failed the same way every day for weeks while its metadata still showed the
    #last run that worked. the run is written down so the library shows the fault; the settings and state
    #are left exactly as they were, since a run that got nowhere has learned nothing about where to resume.
    #
    #only for a comic that already has a file: a new comic that fails at once has nothing to add to. and
    #not for being stopped, which is someone's decision rather than the comic's fault
    path = os.path.join(folder, metadata_file)
    if exit_code in (None, EXIT_OK, EXIT_INTERRUPTED) or not os.path.exists(path):
        return None
    try:
        metadata = load(path)
        history = metadata.setdefault("history", {})
        runs = list(history.get("runs") or [])
    except (ValueError, OSError, TypeError, AttributeError):
        return None
    stamp = now_stamp()
    run = {
        "run_id": run_id,
        "started": run_start,
        "updated": stamp,
        "argv": sys.argv[1:],
        "start_url": args.URL,
        "start_page_number": args.increment,
        "last_url": scrape_state["walked_to"] or args.URL,
        "last_page_number": None,
        "pages_saved": 0,
        "completed": False,
        "stop_reason": stop_reason,
        "exit_code": exit_code,
    }
    #the same failure from the same place, day after day, is one fault that has gone on a while rather
    #than a new one each day - and twenty copies of it would push every run that worked out of the record
    last = runs[-1] if runs else {}
    if (last.get("pages_saved") == 0 and last.get("exit_code") == exit_code
            and last.get("start_url") == args.URL):
        run["since"] = last.get("since") or last.get("started")
        run["times"] = (last.get("times") or 1) + 1
        runs = runs[:-1]
    runs.append(run)
    if len(runs) > max_runs:
        runs = runs[:1] + runs[-(max_runs - 1):]
    history["runs"] = runs
    metadata["updated"] = stamp
    write_json(path, metadata)
    return path


def settings_from_args(args, folder, url, increment, ended=False):
    #everything about this comic that a later run has to be told, and nothing that can be worked out
    #from it. this block is the only place any of it is written down: the command is rebuilt from here
    #when a run starts, so editing one value here is the whole of changing how a comic is scraped.
    #every key is always written, even at its default, so there is somewhere obvious to change it.
    return {
        "url": url,
        "output": folder,
        "cbz_path": args.cbz_path,
        "increment": increment,
        "prefix": bool(args.prefix),
        "javascript": bool(args.enable_javascript),
        "firefox": bool(args.firefox),
        "waittime": args.waittime,
        "cbz": bool(args.cbz),
        "direction_check": bool(args.direction_check),
        "multi_page": bool(getattr(args, "multi_page", True)),
        #not a scraping option: update_comics.py reads it and leaves a finished comic alone
        "ended": bool(ended),
    }


def metadata_save(args, folder, *, scrape_state, run_id, run_start, stop_reason, image_xpath, next_xpath,
                  index_file, completed=False, exit_code=None):
    #writes the sidecar describing this scrape into the output folder, so it ends up inside the cbz
    if scrape_state["pages_saved"] == 0:
        return failure_noted(args, folder, scrape_state=scrape_state, run_id=run_id, run_start=run_start,
                             stop_reason=stop_reason, exit_code=exit_code)
    path = os.path.join(folder, metadata_file)

    #carry over what an earlier run recorded, so a resumed comic still knows where it originally started.
    #each lookup falls back to the flat key a schema 1 file used, so an old sidecar is read and then
    #quietly rewritten in the current shape rather than needing a separate conversion first
    created = run_start
    first_page_url = scrape_state["first_page_url"]
    first_increment = scrape_state["first_increment"]
    previous, was_ended = {}, False
    old_settings, old_state, old_history = {}, {}, {}
    runs = []
    if os.path.exists(path):
        try:
            previous = load(path)
            old_settings = previous.get("settings") or {}
            old_state = previous.get("state") or {}
            old_history = previous.get("history") or {}
            created = previous.get("created", created)
            first_page_url = old_history.get("first_page_url", previous.get("first_page_url")) or first_page_url
            saved_first = old_history.get("first_page_number", previous.get("first_page_number"))
            if saved_first is not None:
                first_increment = saved_first
            #a comic marked finished by hand stays finished, even if someone runs it once more directly
            was_ended = bool(old_settings.get("ended", previous.get("ended", False)))
            #drop this run's own entry so repeated writes update it instead of stacking up
            runs = [run for run in old_history.get("runs", previous.get("runs", []))
                    if run.get("run_id") != run_id]
        except (ValueError, OSError, TypeError, AttributeError):
            pass

    #a run that put no new page in the folder is a look, not an update: a comic that is up to date
    #re-saves the page it resumes on over itself and finds no next link. writing this down would add a
    #run saying a page was saved when the comic gained none - and summing those saves counts a comic's
    #pages many times over, which is what made one comic look as though it had lost pages. it would also
    #rewrite the sidecar, and with it the archive's copy, every single day for no reason.
    #
    #unless the run before it did not end well: then this one is the news that the comic is fine again,
    #and leaving it out would leave the library showing an error that has been over for weeks.
    was_well = not runs or runs[-1].get("exit_code") in (None, EXIT_OK)
    if scrape_state["fresh_pages"] == 0 and exit_code in (None, EXIT_OK) and was_well:
        return None

    #argv is the record of what this run was actually told to do. the rendered command and the full
    #option dump that used to sit beside it said the same thing twice more, and went stale the moment
    #anyone edited the settings by hand
    runs.append({
        "run_id": run_id,
        "started": run_start,
        "updated": now_stamp(),
        "argv": sys.argv[1:],
        "start_url": args.URL,
        "start_page_number": scrape_state["first_increment"],
        "last_url": scrape_state["last_page_url"],
        "last_page_number": scrape_state["last_increment"],
        "pages_saved": scrape_state["pages_saved"],
        "completed": completed,
        "stop_reason": stop_reason,
        "exit_code": exit_code,
    })

    if len(runs) > max_runs:
        runs = runs[:1] + runs[-(max_runs - 1):]

    resume_url, resume_increment = resume_point(scrape_state)
    metadata = {
        "schema": 2,
        "generator": "mirror_base.py",
        "generator_version": "3.5",
        "created": created,
        "updated": now_stamp(),
        #the one place to edit. everything a run needs is built from this and nowhere else
        "settings": settings_from_args(args, folder, resume_url, resume_increment, was_ended),
        "state": {
            "site": resume_url.split('/')[2] if resume_url and '//' in resume_url else None,
            #pages present in the folder, not saves made: a resume re-saves its starting page, so summing
            #the runs would count the overlap twice
            "page_count": len([f for f in os.listdir(folder) if f != metadata_file]),
            "completed": completed,
            #the xpaths that actually matched this site, handy if the automatic search ever stops finding
            #them. a run that found nothing keeps whatever an earlier run discovered
            "image_xpath": image_xpath or old_state.get("image_xpath", previous.get("image_xpath")),
            "next_xpath": next_xpath or old_state.get("next_xpath", previous.get("next_xpath")),
            "last_image_url": scrape_state["last_image_src"],
            "last_image_file": scrape_state["last_image_file"],
            #the most pages one address of this comic has been seen to hold, and the first address that
            #held more than one. a run that saw nothing keeps what an earlier one found, so the change
            #stays written down for a comic that has since gone quiet
            "pages_per_url": max(scrape_state["most_per_url"],
                                 old_state.get("pages_per_url") or previous.get("pages_per_url") or 0) or None,
            "multi_page_from": scrape_state["first_multi_url"] or old_state.get("multi_page_from"),
        },
        "history": {
            #the index this comic keeps, named here so another machine, where this folder has a different
            #path, still knows which one is its own
            "index_cache": os.path.basename(index_file) if index_file else None,
            "first_page_url": first_page_url,
            "first_page_number": first_increment,
            "adopted": bool(old_history.get("adopted", previous.get("adopted", False))),
            "runs": runs,
        },
    }
    kept_from = old_history.get("adopted_from", previous.get("adopted_from"))
    if kept_from:
        metadata["history"]["adopted_from"] = kept_from
    #changes made by hand through the web page, kept so a later look can tell a setting was edited
    if old_history.get("edits"):
        metadata["history"]["edits"] = old_history["edits"]
    #what this comic is known to be missing, and which of its files were made by hand. worked out by
    #chapters.py, which takes minutes to do, so a scrape must not throw it away
    for kept in ("gaps", "gaps_note", "hand_made", "gaps_checked", "index_cache"):
        if old_history.get(kept) is not None:
            metadata["history"][kept] = old_history[kept]
    if metadata["history"].get("index_cache") is None:
        #a comic with no index says nothing rather than saying nothing twice
        del metadata["history"]["index_cache"]

    #where the chapters are, worked out by chapters.py from an archive page or the addresses
    #themselves. it describes the comic rather than this run, so a scrape must leave it alone.
    if previous.get("chapters"):
        metadata["chapters"] = previous["chapters"]
    #what was said about the comic by hand - its title, who made it, a summary - read from the file as it is
    #now, so one said while this run was going is kept, not written over by what the run started with
    if previous.get("info"):
        metadata["info"] = previous["info"]

    #written aside and moved into place: this is rewritten after every page, and a run killed halfway
    #through writing it would otherwise leave a comic with no readable settings at all
    write_json(path, metadata)
    return path
