#runs mirror_base.py over every comic in a library folder, resuming each one from its saved metadata.
#meant to be driven by a timer, so it isolates failures, caps how long any one comic can run, and finishes
#with a summary of what moved. #V 1.4
#
#this is the command, and the long-running process the container starts; the work is in comiclib - config,
#library, batch and schedule. everything this held is still reachable here under its old name, which is
#how the web page, handed this module, reaches it.
import argparse
import copy
import os
import signal
import sys
from datetime import datetime, timedelta

from comiclib.batch import (describe, ended_reason, exit_reasons, kill_tree, lock_file,  # noqa: F401
                            pack_chapters, print_lock, read_chapters, report_skipped, run_batch, run_comic,
                            run_once, say, select_comics, still_running, stopped_code, take_lock,
                            with_config)
from comiclib.config import config_defaults, config_file, config_path, load_config, warned_about  # noqa: F401
from comiclib.library import Comic, find_comics, page_count, resume_argv  # noqa: F401
from comiclib.metadata import METADATA_FILE, argv_to_settings, saved_command, settings_to_argv  # noqa: F401
from comiclib.pages import count as folder_pages  # noqa: F401
from comiclib.paths import config_folder
from comiclib.schedule import (ignored_triggers, local_zone, next_run, parse_schedule,  # noqa: F401
                               take_trigger, trigger_files, trigger_poll, wait_until)

metadata_file = METADATA_FILE


def setup():
    params = argparse.ArgumentParser(
        description="Updates every comic in a library folder by resuming it from its mirror_metadata.json.")
    params.add_argument("root", nargs='?', default=".",
                        help="Library folder holding one directory per comic. Defaults to the working directory.")
    params.add_argument("-j", "--jobs", type=int, default=None,
                        help="How many comics to update at once. Each one runs its own browser, so raise this only as far as memory allows. Defaults to 1.")
    params.add_argument("-t", "--timeout", type=int, default=None,
                        help="Seconds any one comic may run before it is killed. Defaults to 1800.")
    params.add_argument("-o", "--only", action='append', default=None,
                        help="Update only the named comic folder. May be repeated, and takes wildcards: \"Group/*\" is every comic under Group, however deep.")
    params.add_argument("-n", "--dry-run", action='store_true', default=False,
                        help="List what would run, and the command each comic would use, without running anything.")
    params.add_argument("--script", default=None,
                        help="Path to mirror_base.py. Defaults to the copy beside this script.")
    params.add_argument("--max-depth", type=int, default=None,
                        help="How many folders deep to look for comics. Lets a library group comics by author or site. Defaults to 5.")
    params.add_argument("--schedule", default=None, metavar="HH:MM",
                        help="Stay running and start an update at this local time every day. Without it the update runs once and exits.")
    params.add_argument("--progress", type=int, default=None, metavar="SECONDS",
                        help="While a run is going, say every so often which comics are still going "
                             "and how far they have got. Defaults to 60 seconds; 0 turns it off.")
    params.add_argument("--now", action='store_true', default=False,
                        help="Update once straight away, then settle into --schedule. Without --schedule "
                             "this is what happens anyway. Useful for a container that should not sit "
                             "idle until the small hours the first time it starts.")
    params.add_argument("--web", type=int, default=None, metavar="PORT",
                        help="Serve a page on this port for watching runs, starting updates and adding new "
                             "comics. Keeps running even without --schedule. Set MIRROR_WEB_PASSWORD to "
                             "require a password.")
    params.add_argument("--refresh-chapters", action=argparse.BooleanOptionalAction, default=None,
                        help="Before writing a chaptered comic's archives again, read the archive page it "
                             "remembers, in case the new pages started a chapter. On by default. A change "
                             "that would move existing chapters is reported rather than taken.")
    params.add_argument("--pack-chapters", action=argparse.BooleanOptionalAction, default=None,
                        help="After a comic that is split into chapters gains pages, line them up and "
                             "write its chapter archives again. On unless the settings file says otherwise.")
    params.add_argument("--config", default=None, metavar="FOLDER",
                        help="Folder holding {0} and element_paths.json. Defaults to a config folder beside "
                             "this script.".format(config_file))
    params.add_argument("--web-host", default="0.0.0.0", metavar="ADDRESS",
                        help="Address the page listens on. Defaults to every interface; 127.0.0.1 keeps it "
                             "to this machine.")
    args = params.parse_args()

    #which options were actually typed, so a later re-read of the settings file leaves those alone
    args.from_command_line = {action.dest for action in params._actions
                              if any(flag in sys.argv[1:] for flag in action.option_strings)}

    #passed on to every mirror_base this starts, so the scrapes read their element paths from the same place
    if args.config:
        os.environ["MIRROR_CONFIG"] = os.path.abspath(args.config)
    args.config = config_folder()
    saved = load_config()
    #anything not given on the command line comes from the settings file, and anything missing there from
    #the built-in defaults. the command line wins because it is the more deliberate of the two.
    for key in ("jobs", "timeout", "progress", "max_depth", "schedule", "pack_chapters",
                "refresh_chapters"):
        if getattr(args, key) is None:
            setattr(args, key, saved[key])
    args.pages_folder = saved["pages_folder"]
    args.cbz_folder = saved["cbz_folder"]

    args.root = os.path.abspath(args.root)
    if args.script is None:
        args.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mirror_base.py")
    return args


def main():
    args = setup()
    if not os.path.isdir(args.root):
        print("ERROR: {0} is not a folder.".format(args.root))
        return 2
    if not os.path.exists(args.script):
        print("ERROR: could not find {0}.".format(args.script))
        return 2
    if not args.schedule and args.web is None:
        return run_once(args)

    hour = minute = None
    if args.schedule:
        try:
            hour, minute = parse_schedule(args.schedule)
        except ValueError:
            print("ERROR: --schedule wants a 24 hour time like 03:30, not {0}.".format(args.schedule))
            return 2

    #python gets no default signal handling as pid 1, so without this a docker stop would sit through its
    #whole kill timeout instead of shutting down and releasing the lock
    signal.signal(signal.SIGTERM, lambda *ignored: sys.exit(0))

    web = None
    if args.web is not None:
        import web_ui
        try:
            web = web_ui.start(args, sys.modules[__name__])
        except OSError as error:
            print("ERROR: could not serve the web page on port {0}: {1}".format(args.web, error))
            return 2

    def update(names, why):
        #with the page running, every update goes through its queue, so one started there and one started
        #by the clock take turns instead of colliding over the lock
        if web is not None:
            web.submit_update(names, why)
            return
        chosen = copy.copy(args)
        if names:
            chosen.only = names
        print("{0}; updating {1}.".format(why, ", ".join(names) if names else "everything"), flush=True)
        run_once(chosen)

    zone = local_zone()
    if args.schedule:
        if not os.environ.get("TZ"):
            print("WARNING: TZ is not set, so this container is running on {0}. Set TZ to your own timezone "
                  "or the update will run at the wrong hour.".format(zone))
        print("Updating every day at {0:02d}:{1:02d} {2}.".format(hour, minute, zone), flush=True)
    print("To update sooner, put a file named {0} in {1}; list comic folders in it, one per line, to update "
          "only those.".format(trigger_files[0], args.root), flush=True)
    if args.now:
        #a fresh container would otherwise do nothing at all until the first scheduled hour came round,
        #which makes it hard to tell a working setup from a broken one
        update([], "Running once now before waiting for the schedule")
    while True:
        if args.schedule:
            target = next_run(hour, minute)
            wait = (target - datetime.now()).total_seconds()
            #the clock is printed rather than just the gap, so a wrong timezone is obvious at a glance
            print("It is now {0} {2}; next update at {1} ({3:.1f} hours away).".format(
                datetime.now().strftime("%Y-%m-%d %H:%M"), target.strftime("%Y-%m-%d %H:%M"),
                zone, wait / 3600), flush=True)
        else:
            #no schedule, so the page and the trigger file are the only things that start anything
            target = datetime.now() + timedelta(days=365)
        if web is not None:
            web.next_run = target if args.schedule else None
        wanted = wait_until(target, args.root)
        if wanted is None:
            update([], "Scheduled update")
        else:
            #a triggered run is limited to the comics the file names, or everything when it names none
            update(wanted, "Found an update-now file")


if __name__ == "__main__":
    sys.exit(main())
