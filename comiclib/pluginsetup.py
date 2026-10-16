#a plugin's own settings: the ones that are the setup's rather than any one comic's - an account on the site,
#its key, how the program should introduce itself - set once in the Plugins dialog and used by every comic
#of the plugin. plugin.json lists them as "setup", in the shape its comic fields take, with one more kind,
#a secret: text the page shows masked until asked, and that is never put on a command line. whoever can
#reach the page is trusted with the setup, so a secret is shown and edited there like any other setting.
#
#they are kept in the config folder's plugin-setup/, a file a plugin, rather than in the plugin's own folder:
#that is a clone of its repository, which an update pulls into and a removal deletes. readable by the
#updater's own user alone, since a secret is in it in the clear - there is nothing on the machine to lock
#it with that the updater would not also need the key to.
#
#a plugin's program is handed them in its environment, never on its command line, which the log and the
#comic's run record both keep; a plugin.py's functions find them as settings["setup"].
import json
import os
import re
import tempfile

from comiclib.paths import config_folder

FOLDER = "plugin-setup"
SECRET = "secret"
#an environment variable a setting is handed to the program as
ENV = re.compile(r'^[A-Z_][A-Z0-9_]*$')


class SetupError(Exception):
    #a plugin's settings that cannot be kept as given, saying which and why
    pass


def setup_folder():
    return os.path.join(config_folder(), FOLDER)


def fields(manifest):
    return manifest.get("setup") or []


def env_name(field):
    #named by the plugin, or ZCM_ and its key, so a program that reads its environment can always find it
    return field.get("env") or "ZCM_" + field["key"].upper()


def check(name, manifest, kinds, key_pattern):
    #what check_manifest asks of "setup", with what it already asks of fields: refused as plugin.json is read
    setup = manifest.get("setup")
    if setup is None:
        return []
    if not isinstance(setup, list):
        return ["{0}'s setup has to list its settings, [{{\"key\": ..., \"type\": ...}}, ...]".format(name)]
    problems, seen, envs = [], {field.get("key") for field in manifest.get("fields") or [] if isinstance(field, dict)}, set()
    for field in setup:
        if not isinstance(field, dict) or not key_pattern.match(str(field.get("key") or "")):
            problems.append("{0}'s setup has a setting with no usable key (letters, digits and _): {1!r}".format(
                name, field))
            continue
        key = field["key"]
        if field.get("type") not in kinds + (SECRET,):
            problems.append("{0}'s setup setting {1} is of type {2!r}; it has to be one of {3}".format(
                name, key, field.get("type"), ", ".join(kinds + (SECRET,))))
        if key in seen:
            #one name for one thing: a command's {key} and a hook's settings would not say which was meant
            problems.append("{0} names {1} twice, among its fields and its setup".format(name, key))
        seen.add(key)
        env = env_name(field)
        if not ENV.match(env):
            problems.append("{0}'s setup setting {1} would be handed over as {2!r}; an environment variable's "
                            "name is capitals, digits and _".format(name, key, env))
        if env in envs:
            problems.append("{0}'s setup hands two settings over as {1}".format(name, env))
        envs.add(env)
    return problems


def path(name):
    return os.path.join(setup_folder(), name + ".json")


def stored(name):
    #what has been saved for it, or nothing. a file that cannot be read is said, and taken as nothing set,
    #so a broken file costs a plugin its settings rather than every comic of it its run
    try:
        with open(path(name), encoding="utf-8") as f:
            kept = json.load(f)
        return kept if isinstance(kept, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        print("WARNING: {0}'s settings in {1} cannot be read ({2}); it runs as if none were set. Set them "
              "again in the Plugins dialog".format(name, path(name), error), flush=True)
        return {}


def values(plugin):
    #every setting, set or its default: what a plugin.py is handed as settings["setup"]
    kept = stored(plugin.name)
    return dict((field["key"], kept.get(field["key"], field.get("default"))) for field in fields(plugin.manifest))


def environment(plugin):
    #what the program finds in its environment: each setting that has a value, a flag as 1 when ticked
    out = {}
    for key, value in values(plugin).items():
        field = next(field for field in fields(plugin.manifest) if field["key"] == key)
        if value in (None, "", False):
            continue
        out[env_name(field)] = "1" if value is True else str(value)
    return out


def view(plugin):
    #what the page is told: each setting as plugin.json describes it, with its value, a secret's included
    kept = stored(plugin.name)
    return [dict(field, env=env_name(field), value=kept.get(field["key"], field.get("default")))
            for field in fields(plugin.manifest)]


def save(plugin, given):
    #the settings as sent from the page, checked against what plugin.json says each is, laid over what was
    #kept: a setting not sent is left as it was, and one sent empty is cleared, back to its default. one sent
    #as its default is not kept either - the form shows the default to edit, and saving it unchanged must
    #not pin it, or a plugin that improves its default would never reach anyone who once pressed Save
    from comiclib.plugins import field_value
    kept = stored(plugin.name)
    problems = []
    for field in fields(plugin.manifest):
        key, kind = field["key"], field["type"]
        if key not in given:
            continue
        value = given[key]
        if kind == SECRET:
            kind = "text"
        if value in (None, "") and kind != "flag":
            kept.pop(key, None)
            continue
        try:
            value = field_value(kind, value)
        except ValueError:
            problems.append({"url": "{0} must be a full http(s) address",
                             "count": "{0} must be a whole number, 0 or more"}.get(kind, "{0} is not usable")
                            .format(field.get("label") or key))
            continue
        if value == default_of(field, kind, field_value):
            kept.pop(key, None)
        else:
            kept[key] = value
    if problems:
        raise SetupError("; ".join(problems))
    write(plugin.name, kept)
    return view(plugin)


def default_of(field, kind, field_value):
    #a setting's default as its value would be kept, or a stand-in that nothing equals when it has none, or
    #when the plugin's own default is not one its type could hold
    try:
        return field_value(kind, field["default"]) if "default" in field else object()
    except ValueError:
        return object()


def write(name, kept):
    #written aside and moved into place, private to this user from the moment it exists
    os.makedirs(setup_folder(), exist_ok=True)
    handle, aside = tempfile.mkstemp(dir=setup_folder(), prefix="." + name, suffix=".writing")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(kept, f, indent=2, sort_keys=True)
        os.replace(aside, path(name))
    except BaseException:
        try:
            os.remove(aside)
        except OSError:
            pass
        raise
