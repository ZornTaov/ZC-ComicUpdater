#scraper plugins: another program doing the scraping for a comic, so a site some other tool already handles
#well is kept like any comic here - its pages loose, its archives on the shelf, its chapters, its place in
#the reader. a plugin is a folder in the config folder's plugins/, each one its own repository: a
#plugin.json saying how to run the program and what it leaves behind, and as much as it needs of a plugin.py
#whose functions replace the defaults, a dialog.js for the web page, and the program itself in tool/.
import importlib.util
import json
import os
import re
import sys

from comiclib import pluginenv
from comiclib.metadata import METADATA_FILE, now_stamp, write as write_metadata
from comiclib.paths import config_folder

MANIFEST = "plugin.json"
HOOKS = "plugin.py"
DIALOG = "dialog.js"
STYLE = "dialog.css"
#what a plugin's program may leave behind: pages, a folder of pages per chapter, or an archive per chapter
SHAPES = ("pages", "chapter-folders", "chapter-cbz")
#what a plugin's setting can be, the same few the web page already edits a comic's settings as
KINDS = ("url", "text", "count", "flag")
#the functions a plugin.py may define, each replacing the default of the same name
HOOK_NAMES = ("build_command", "chapter_order", "remember", "ended")
#a plugin is named by its folder, which ends up in a comic's settings and in an address the page asks for
NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
KEY = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
#where a plugin's program got to, as the default remember() keeps it
REMEMBERED = ("last_chapter", "last_page")
#a placeholder in a command: {url}, {staging}, a field's key
PLACEHOLDER = re.compile(r'\{([A-Za-z_][A-Za-z0-9_]*)\}')


class PluginError(Exception):
    #a plugin that cannot be used as it is, saying what to do about it
    pass


def plugins_folder():
    return os.path.join(config_folder(), "plugins")


class Plugin:
    def __init__(self, name, folder, manifest, hooks=None):
        self.name = name
        self.folder = folder
        self.manifest = manifest
        self.hooks = hooks
        self.title = str(manifest.get("name") or name)
        self.version = manifest.get("version")
        self.output = manifest.get("output") or "pages"
        self.fields = manifest.get("fields") or []
        self.command = manifest.get("command")
        #the python its program runs with: the updater's own, until ready() finds it has a venv of its own
        self.python = sys.executable

    def ready(self, say=print):
        #what its program needs, there before it is run: the programs it names found, and its packages
        #installed. PluginError says what is missing and what to do about it
        missing = pluginenv.missing_programs(self.manifest)
        if missing:
            raise PluginError("{0} needs {1}, which this image does not have. Ask for it to be added to the "
                              "image, or run the plugin somewhere that has it".format(self.name, ", ".join(missing)))
        try:
            self.python = pluginenv.ensure(self.folder, self.manifest, say)
        except pluginenv.EnvError as error:
            raise PluginError("{0}: {1}".format(self.name, error))
        return self

    @property
    def is_repository(self):
        return os.path.isdir(os.path.join(self.folder, ".git")) or os.path.isfile(os.path.join(self.folder, ".git"))

    @property
    def has_dialog(self):
        return os.path.isfile(os.path.join(self.folder, DIALOG))

    def hook(self, name):
        return getattr(self.hooks, name, None) if self.hooks is not None else None

    def field(self, key):
        return next((field for field in self.fields if field["key"] == key), None)

    def view(self):
        #what the web page is told about it
        return {"name": self.name, "title": self.title, "output": self.output, "fields": self.fields,
                "about": self.manifest.get("about"), "dialog": self.has_dialog,
                "style": os.path.isfile(os.path.join(self.folder, STYLE)), "version": self.version,
                "repository": self.is_repository, "env": pluginenv.state(self.folder, self.manifest),
                "missing": pluginenv.missing_programs(self.manifest)}


def check_manifest(name, manifest, has_hooks):
    #a plugin.json that does not say what it needs to is refused when it is read, with what is wrong with
    #it, rather than at three in the morning when a comic that uses it is due
    if not isinstance(manifest, dict):
        raise PluginError("{0}'s {1} has to be one object, {{...}}".format(name, MANIFEST))
    output = manifest.get("output") or "pages"
    if output not in SHAPES:
        raise PluginError("{0}'s {1} says output is {2!r}; it has to be one of {3}".format(
            name, MANIFEST, output, ", ".join(SHAPES)))
    fields = manifest.get("fields") or []
    if not isinstance(fields, list):
        raise PluginError("{0}'s {1} has to list its fields, [{{\"key\": ..., \"type\": ...}}, ...]".format(
            name, MANIFEST))
    seen = set()
    for field in fields:
        if not isinstance(field, dict) or not KEY.match(str(field.get("key") or "")):
            raise PluginError("{0}'s {1} has a field with no usable key (letters, digits and _): {2!r}".format(
                name, MANIFEST, field))
        if field.get("type") not in KINDS:
            raise PluginError("{0}'s field {1} is of type {2!r}; it has to be one of {3}".format(
                name, field["key"], field.get("type"), ", ".join(KINDS)))
        if field["key"] in seen:
            raise PluginError("{0}'s {1} names the field {2} twice".format(name, MANIFEST, field["key"]))
        seen.add(field["key"])
    #what names its folder, and so the comics that use it: a folder of another name was put there by hand,
    #and installing it again from its repository would put it beside itself
    own = manifest.get("id")
    if own is not None and (not isinstance(own, str) or not NAME.match(own)):
        raise PluginError("{0}'s {1} has an id of {2!r}; it has to be letters, digits, '.', '_' and '-'".format(
            name, MANIFEST, own))
    if own is not None and own != name:
        raise PluginError("{0}'s {1} says its id is {2}, so its folder has to be named {2} too. Rename the "
                          "folder, and the scraper in the settings of any comic that uses it".format(
                              name, MANIFEST, own))
    install = manifest.get("install")
    if install is not None and not (isinstance(install, dict)
                                    and isinstance(install.get("pip", []), list)
                                    and all(isinstance(bit, str) for bit in install.get("pip", []))
                                    and isinstance(install.get("requirements", ""), str)):
        raise PluginError("{0}'s install has to be {{\"pip\": [\"package\", ...], \"requirements\": "
                          "\"tool/requirements.txt\"}}, either or both".format(name))
    needs = manifest.get("needs")
    if needs is not None and not (isinstance(needs, list) and all(isinstance(bit, str) for bit in needs)):
        raise PluginError("{0}'s needs has to list the programs it runs, [\"ffmpeg\", ...]".format(name))
    command = manifest.get("command")
    if command is None and not has_hooks:
        raise PluginError("{0}'s {1} has no command, and it has no {2} to build one. Add "
                          "\"command\": [\"{{python}}\", \"{{tool}}/scraper.py\", \"{{url}}\"] or the like.".format(
                              name, MANIFEST, HOOKS))
    if command is not None and not (isinstance(command, list) and command and all(
            isinstance(part, str) or (isinstance(part, list) and all(isinstance(bit, str) for bit in part))
            for part in command)):
        raise PluginError("{0}'s command has to be a list of words, each a string or a list of strings "
                          "that go in together".format(name))


def load(name, with_hooks=True):
    #a plugin by its folder's name. with_hooks False reads only what it says about itself, which is all the
    #web page needs - a plugin's own code runs in the process that runs its comic, and nowhere else
    if not name or not NAME.match(str(name)):
        raise PluginError("{0!r} is not a plugin's name: it is the name of its folder in {1}".format(
            name, plugins_folder()))
    folder = os.path.join(plugins_folder(), name)
    path = os.path.join(folder, MANIFEST)
    if not os.path.isfile(path):
        raise PluginError("there is no plugin named {0}: put its folder in {1}, with a {2} in it".format(
            name, plugins_folder(), MANIFEST))
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except (OSError, ValueError) as error:
        raise PluginError("{0}'s {1} cannot be read: {2}".format(name, MANIFEST, error))
    hooks_path = os.path.join(folder, HOOKS)
    check_manifest(name, manifest, os.path.isfile(hooks_path))
    hooks = None
    if with_hooks and os.path.isfile(hooks_path):
        try:
            spec = importlib.util.spec_from_file_location("comic_plugin_" + re.sub(r'\W', '_', name), hooks_path)
            hooks = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hooks)
        except Exception as error:  # noqa: BLE001 - whatever a plugin's own code raises, it is the plugin's fault
            raise PluginError("{0}'s {1} failed as it was loaded: {2}: {3}".format(
                name, HOOKS, type(error).__name__, error))
    return Plugin(name, folder, manifest, hooks)


def installed():
    #every plugin in the config folder, and what is wrong with any that cannot be used. read fresh each time
    #it is asked, so a plugin put in place shows up without the updater being restarted
    plugins, problems = [], []
    folder = plugins_folder()
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return plugins, problems
    for name in names:
        if name.startswith('.') or not os.path.isfile(os.path.join(folder, name, MANIFEST)):
            continue
        try:
            plugins.append(load(name, with_hooks=False))
        except PluginError as error:
            problems.append(str(error))
    return plugins, problems


def field_value(kind, value):
    #one setting as it is kept, or ValueError when it cannot be. the same rules the page has always edited
    #a comic's settings by, so a plugin's settings mean what anyone would expect them to
    if kind == "flag":
        return bool(value)
    if kind == "count":
        number = int(str(value).strip() or 0)
        if number < 0:
            raise ValueError("a count cannot be below 0")
        return number
    text = str(value if value is not None else "").strip()
    if kind == "url":
        if not re.match(r"^https?://\S+$", text):
            raise ValueError("not a full http(s) address")
        return text
    return text or None


def check_values(plugin, given, partial=False):
    #a plugin's settings as sent, checked against what its plugin.json says each is. partial is an edit,
    #which may leave a setting as it was by not sending it; anything else has to give every one it needs
    cleaned, problems = {}, []
    for field in plugin.fields:
        key, kind = field["key"], field["type"]
        label = field.get("label") or key
        if key not in given or given[key] in (None, ""):
            if partial and key not in given:
                continue
            #an address is what a scraper is pointed at, so it is needed unless the plugin says otherwise
            if field.get("required", kind == "url"):
                problems.append("{0} is needed".format(label))
            elif kind == "flag":
                cleaned[key] = bool(field.get("default", False))
            else:
                cleaned[key] = field.get("default")
            continue
        try:
            cleaned[key] = field_value(kind, given[key])
        except ValueError:
            problems.append({"url": "{0} must be a full http(s) address",
                             "count": "{0} must be a whole number, 0 or more"}.get(kind, "{0} is not usable")
                            .format(label))
    return cleaned, problems


def split_values(values):
    #a plugin's address is the comic's address, kept where every comic's is, so the library shows it and
    #each archive's ComicInfo names the site; the rest are the plugin's own
    values = dict(values)
    return values.pop("url", None), values


def plugin_values(settings):
    #a plugin comic's settings as its plugin's fields: its own, and the address every comic keeps
    values = dict((settings or {}).get("plugin") or {})
    if (settings or {}).get("url"):
        values["url"] = settings["url"]
    return values


def is_plugin_comic(metadata):
    return bool(((metadata or {}).get("settings") or {}).get("scraper"))


def fill(template, values):
    #a command from its plugin.json: each {name} is put in from values. a word that is only a placeholder,
    #or a group of words given as a list, is left out whole when what it names is empty - a setting not
    #given, or a flag turned off - so `["--start", "{start}"]` asks for nothing rather than for ''. a flag
    #turned on is put in as the word its field gives as "option"
    out = []
    for part in template:
        group = part if isinstance(part, list) else [part]
        named = [name for bit in group for name in PLACEHOLDER.findall(bit)]
        unknown = [name for name in named if name not in values]
        if unknown:
            raise PluginError("the command names {{{0}}}, which is not a field of the plugin nor one of "
                              "{{python}}, {{plugin}}, {{tool}}, {{staging}}, {{last_chapter}}, {{last_page}}, "
                              "nor named in its \"remembers\"".format(unknown[0]))
        if any(values[name] in (None, "", False) for name in named):
            continue
        out.extend(PLACEHOLDER.sub(lambda found: str(values[found.group(1)]), bit) for bit in group)
    return out


def command_values(plugin, settings, state, staging):
    #what a command's placeholders stand for: where things are, where it last got to, and its settings.
    #where it got to is empty until a run has taken something in - the names the default remember() keeps,
    #and any a plugin.json lists as "remembers" for its own
    values = dict((name, None) for name in REMEMBERED + tuple(plugin.manifest.get("remembers") or ()))
    values.update(state or {})
    given = plugin_values(settings)
    for field in plugin.fields:
        key = field["key"]
        if field["type"] == "flag":
            on = given.get(key, field.get("default", False))
            values[key] = (field.get("option") or "--" + key.replace("_", "-")) if on else None
        else:
            values[key] = given.get(key)
    values.update(python=plugin.python, plugin=plugin.folder, tool=os.path.join(plugin.folder, "tool"),
                  staging=staging)
    return values


def build_command(plugin, settings, state, staging):
    #the program and its arguments for this comic's run. a plugin.py that builds its own is handed the
    #comic's settings, where it got to last time, and the folder the program is to write in
    own = plugin.hook("build_command")
    if own is not None:
        command = own(settings, state, staging)
        #a plugin.py written before plugins had packages of their own starts its program with the python
        #it was loaded by, which would not see them
        if command and command[0] == sys.executable:
            command = [plugin.python] + list(command[1:])
    else:
        command = fill(plugin.command, command_values(plugin, settings, state, staging))
    if not command or not all(isinstance(word, str) for word in command):
        raise PluginError("{0} built no command to run. Its plugin.json's command, or its plugin.py's "
                          "build_command, has to give a list of words".format(plugin.name))
    return list(command)


def comic_settings(plugin, values, output, cbz_path=None, cbz=True):
    #the settings a new plugin comic starts with. only cbz turned off is written, as for any comic
    url, own = split_values(values)
    settings = {"scraper": plugin.name, "url": url, "output": output, "cbz_path": cbz_path, "plugin": own}
    if cbz is False:
        settings["cbz"] = False
    return settings


def start_comic(folder, plugin, values, output, cbz_path=None, cbz=True):
    #a plugin comic's first metadata, written before its first run, since nothing else would write it: the
    #plugin's program knows nothing of this file. a folder that already holds a comic is never taken over
    path = os.path.join(folder, METADATA_FILE)
    if os.path.exists(path):
        raise PluginError("{0} already holds a comic".format(folder))
    stamp = now_stamp()
    metadata = {
        "schema": 2,
        "generator": "plugin:" + plugin.name,
        "generator_version": plugin.version,
        "created": stamp,
        "updated": stamp,
        "settings": comic_settings(plugin, values, output, cbz_path, cbz),
        "state": {"page_count": 0, "completed": False, "plugin": {}},
        "history": {"adopted": False, "runs": []},
    }
    os.makedirs(folder, exist_ok=True)
    write_metadata(folder, metadata)
    return metadata
