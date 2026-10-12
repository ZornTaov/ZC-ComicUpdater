#runs a comic that another program scrapes, through that program's plugin in the config folder's plugins/:
#the program pointed at the comic, and what it fetched taken in as the comic's pages and chapters, so the
#comic is kept and read like any other. update_comics runs this for every comic whose settings name a
#scraper, the way it runs mirror_base for the rest.
#
#this is the command; the work is in comiclib - plugins (finding one, its settings, its command), intake
#(taking in what it wrote) and pluginrun (one run).
import argparse
import os
import sys

from comiclib import exits, plugins
from comiclib.pluginrun import run


def setup():
    params = argparse.ArgumentParser(
        description="Runs a comic another program scrapes, through its plugin in the config folder's "
                    "plugins/, and takes in what it fetched as the comic's pages and chapters.")
    params.add_argument("folder", nargs='?', help="The comic's folder.")
    params.add_argument("values", nargs='*', metavar="KEY=VALUE",
                        help="With --add: the plugin's settings, as its plugin.json names them.")
    params.add_argument("--add", metavar="PLUGIN",
                        help="Start a new comic in FOLDER, scraped by this plugin, and run it.")
    params.add_argument("--cbz-path", help="With --add: where the comic's archive goes, if not on the "
                                           "CBZs shelf beside its pages.")
    params.add_argument("--cbz", action=argparse.BooleanOptionalAction, default=True,
                        help="With --add: keep archives of the comic (default on).")
    params.add_argument("--deadline", type=float, default=0,
                        help="Seconds the plugin's program may run before it is stopped and what it "
                             "fetched is taken in. 0, the default, is no limit.")
    params.add_argument("--list", action="store_true", help="List the plugins there are, and their settings.")
    return params


def list_plugins():
    found, problems = plugins.installed()
    if not found and not problems:
        print("No plugins in {0}. A plugin is a folder there holding a plugin.json.".format(
            plugins.plugins_folder()))
    for plugin in found:
        print("{0}  ({1}, {2})".format(plugin.name, plugin.title, plugin.output))
        for field in plugin.fields:
            print("    {0:<20} {1:<6} {2}".format(field["key"], field["type"], field.get("label") or ""))
    for problem in problems:
        print("CANNOT BE USED: {0}".format(problem))
    return exits.OK


def truthy(text):
    return str(text).strip().lower() in ("1", "true", "yes", "on")


def add(args):
    try:
        plugin = plugins.load(args.add)
    except plugins.PluginError as error:
        print("ERROR: {0}".format(error))
        return exits.USAGE
    given = {}
    for value in args.values:
        key, said, text = value.partition("=")
        if not said:
            print("ERROR: {0} is not a setting; give each as key=value, such as url=https://example.com/".format(
                value))
            return exits.USAGE
        field = plugin.field(key.strip())
        if field is None:
            print("ERROR: {0} has no setting called {1}. Its settings are: {2}".format(
                plugin.name, key, ", ".join(f["key"] for f in plugin.fields) or "none"))
            return exits.USAGE
        given[field["key"]] = truthy(text) if field["type"] == "flag" else text
    values, problems = plugins.check_values(plugin, given)
    if problems:
        print("ERROR: {0}".format("; ".join(problems)))
        return exits.USAGE
    #named as update_comics finds it: relative to where this runs, which for update_comics is the library
    output = os.path.relpath(args.folder).replace(os.sep, '/')
    try:
        plugins.start_comic(args.folder, plugin, values, output, args.cbz_path, args.cbz)
    except plugins.PluginError as error:
        print("ERROR: {0}".format(error))
        return exits.USAGE
    print("Started {0}, scraped by {1}.".format(output, plugin.title), flush=True)
    return run(args.folder, args.deadline)


def main(argv=None):
    params = setup()
    args = params.parse_args(argv)
    if args.list:
        return list_plugins()
    if not args.folder:
        params.print_usage()
        return exits.USAGE
    if args.add:
        return add(args)
    if args.values:
        print("ERROR: settings are only given with --add; change a comic's settings in its metadata, or on "
              "the web page.")
        return exits.USAGE
    return run(args.folder, args.deadline)


if __name__ == '__main__':
    sys.exit(main())
