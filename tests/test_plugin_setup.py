#a plugin's own settings: its plugin.json's "setup", set once in the Plugins dialog for every comic of it,
#kept in the config folder rather than in the plugin's clone, handed to its program in its environment and
#to its plugin.py as settings["setup"], and never put on a command line, which the log and the run record keep.
import json
import os
import stat

import pytest

from comiclib import plugins, pluginsetup
from conftest import open_page, read_meta, wait_until
from test_plugins import add, comic, install, with_ended

SETUP = [{"key": "account", "type": "text", "label": "Account", "env": "EXAMPLE_ACCOUNT"},
         {"key": "token", "type": "secret", "label": "Token"},
         {"key": "agent", "type": "text", "default": "Example/1.0"},
         {"key": "loud", "type": "flag"}]
#a program that says whether it was handed the settings, without saying them
SAYS = ("import os; print('account', os.environ.get('EXAMPLE_ACCOUNT')); "
        "print('token', 'right' if (os.environ.get('ZCM_TOKEN') or '')[::-1] == 'terc3s' else 'wrong'); "
        "print('agent', os.environ.get('ZCM_AGENT')); print('loud', os.environ.get('ZCM_LOUD'))")


def loaded(config, **manifest):
    install(config, **dict({"setup": SETUP}, **manifest))
    return plugins.load("example")


def test_settings_are_kept_apart_from_the_plugin_privately_and_shown_with_their_secrets(config):
    plugin = loaded(config)
    shown = pluginsetup.save(plugin, {"account": "someone", "token": "s3cret", "loud": True})
    assert {field["key"]: field["value"] for field in shown} == {
        "account": "someone", "token": "s3cret", "agent": "Example/1.0", "loud": True}
    #whoever can reach the page is trusted with the setup, so the page is told the secret to edit it
    assert next(field for field in shown if field["key"] == "token")["env"] == "ZCM_TOKEN"
    path = os.path.join(str(config), "plugin-setup", "example.json")
    assert not os.path.exists(os.path.join(plugin.folder, "setup.json")), "never in the plugin's own clone"
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"account": "someone", "token": "s3cret", "loud": True}


def test_a_setting_not_sent_is_kept_and_one_sent_empty_is_cleared(config):
    plugin = loaded(config)
    pluginsetup.save(plugin, {"account": "someone", "token": "s3cret", "agent": "Mine/2.0"})
    pluginsetup.save(plugin, {"account": "else"})
    assert pluginsetup.values(plugin) == {"account": "else", "token": "s3cret", "agent": "Mine/2.0", "loud": None}
    pluginsetup.save(plugin, {"token": "", "agent": ""})
    #back to nothing, and to its default
    assert pluginsetup.values(plugin)["token"] is None and pluginsetup.values(plugin)["agent"] == "Example/1.0"


def test_the_program_is_handed_them_in_its_environment_and_the_log_never_sees_a_secret(library, config):
    pluginsetup.save(loaded(config, command=["{python}", "-c", SAYS, "{agent}"]),
                     {"account": "someone", "token": "s3cret", "loud": True})
    done = add(library)
    assert done.returncode == 0, done.stdout + done.stderr
    said = done.stdout.splitlines()
    assert "account someone" in said and "token right" in said and "loud 1" in said
    #a setting with nothing saved is handed over as its default
    assert "agent Example/1.0" in said
    assert "s3cret" not in done.stdout
    assert "s3cret" not in json.dumps(read_meta(comic(library))), "nor in the run record, nor the settings"


def test_a_plugin_py_finds_them_as_settings_setup(library, config):
    with_ended(install(config, setup=SETUP), "return settings['setup']['token'] == 's3cret'")
    pluginsetup.save(plugins.load("example"), {"token": "s3cret"})
    add(library, "chapters=1")
    assert read_meta(comic(library))["settings"]["ended"] is True
    assert "setup" not in read_meta(comic(library))["settings"], "never written into the comic"


@pytest.mark.parametrize("setup, command, said", [
    ([{"key": "token", "type": "secret"}], ["{python}", "x.py", ["--token", "{token}"]], "names the secret {token}"),
    ([{"key": "url", "type": "text"}], None, "names url twice"),
    ([{"key": "a", "type": "password"}], None, "has to be one of"),
    ([{"key": "a", "type": "text", "env": "lower"}], None, "capitals, digits and _"),
    ([{"key": "a", "type": "text", "env": "SAME"}, {"key": "b", "type": "text", "env": "SAME"}], None, "two settings"),
])
def test_a_setup_that_cannot_work_says_what_is_wrong(config, setup, command, said):
    install(config, setup=setup, **({"command": command} if command else {}))
    with pytest.raises(plugins.PluginError, match=said.replace("{", "\\{").replace("}", "\\}")):
        plugins.load("example")


def test_a_setting_saved_as_its_default_is_not_pinned(config):
    plugin = loaded(config)
    #the form shows the default to edit; pressing Save without touching it keeps nothing
    pluginsetup.save(plugin, {"agent": "Example/1.0", "account": "someone"})
    with open(os.path.join(str(config), "plugin-setup", "example.json"), encoding="utf-8") as f:
        assert json.load(f) == {"account": "someone"}
    #so a plugin that changes its default is followed
    plugin.manifest["setup"][2]["default"] = "Example/2.0"
    assert pluginsetup.values(plugin)["agent"] == "Example/2.0"


def test_a_setting_of_the_wrong_kind_is_refused_and_nothing_is_written(config):
    plugin = loaded(config, setup=[{"key": "tries", "type": "count", "label": "Tries"}])
    with pytest.raises(pluginsetup.SetupError, match="Tries must be a whole number"):
        pluginsetup.save(plugin, {"tries": "lots"})
    assert not os.path.exists(os.path.join(str(config), "plugin-setup", "example.json"))


def test_the_page_lists_them_and_saves_them(library, config, web):
    install(config, setup=SETUP)
    page = web()
    code, answer = page.call("/api/plugins")
    assert [field["key"] for field in answer["plugins"][0]["setup"]] == ["account", "token", "agent", "loud"]
    code, answer = page.call("/api/plugins/setup", {"name": "example", "values": {"token": "s3cret"}})
    assert code == 200, answer
    assert next(field for field in answer["setup"] if field["key"] == "token")["value"] == "s3cret"
    code, answer = page.call("/api/plugins")
    assert next(field for field in answer["plugins"][0]["setup"] if field["key"] == "token")["value"] == "s3cret"
    assert page.call("/api/plugins/setup", {"name": "missing", "values": {}})[0] == 404


@pytest.mark.browser
def test_an_open_settings_form_survives_the_list_being_read_again(library, config, web, browser):
    #the dialog reads the list again as it opens, and again whenever a job finishes: landing after a plugin's
    #settings were opened and typed in, it drew them afresh and threw the typing away. here the dialog's own
    #read is held back until then, which the test of the dialog below raced against by chance
    install(config, setup=SETUP)
    pluginsetup.save(plugins.load("example"), {"token": "old"})
    page = web()
    open_page(browser, page.base + "/")
    wait_until(lambda: browser.execute_script("return pluginList.length > 0"), why="the plugins were never listed")
    browser.execute_script("""
      const real = window.fetch;
      window.release = null;
      window.fetch = (url, init) => String(url).endsWith('/api/plugins') && !window.release
        ? new Promise((resolve) => { window.release = () => real(url, init).then(resolve); })
        : real(url, init);
      document.getElementById('open-plugins').click();""")
    wait_until(lambda: browser.execute_script("return !!window.release"), why="the dialog never read the list")
    browser.execute_script("document.querySelector('[data-plugin-settings=\"example\"]').click()")
    token = wait_until(lambda: browser.execute_script(
        "return document.querySelector('[data-setup-for=\"example\"] [data-plugin-field=\"token\"]')"))
    browser.execute_script("""
      const form = document.querySelector('[data-setup-for="example"]');
      form.querySelector('[data-plugin-field="account"]').value = 'half typed';
      form.querySelector('[data-show-secret]').click();
      //gone once the list is drawn again, which is how the test knows it has been
      document.getElementById('pl-list').insertAdjacentHTML('beforeend', '<i id="not-yet-drawn"></i>');
      window.release();""")
    wait_until(lambda: browser.execute_script("return !document.getElementById('not-yet-drawn')"),
               why="the list was never drawn again")
    assert token.get_attribute("type") == "text", "the secret was hidden again"
    assert browser.execute_script("return document.querySelector('[data-setup-for=\"example\"] "
                                  "[data-plugin-field=\"account\"]').value") == "half typed"


def test_the_plugins_dialog_edits_them_showing_a_secret_only_when_asked(library, config, web, browser):
    install(config, setup=SETUP)
    pluginsetup.save(plugins.load("example"), {"token": "old"})
    page = web()
    open_page(browser, page.base + "/")
    browser.execute_script("document.getElementById('open-plugins').click()")
    wait_until(lambda: browser.execute_script("return !!document.querySelector('[data-plugin-settings=\"example\"]')"))
    browser.execute_script("document.querySelector('[data-plugin-settings=\"example\"]').click()")
    token = wait_until(lambda: browser.execute_script(
        "return document.querySelector('[data-setup-for=\"example\"] [data-plugin-field=\"token\"]')"))
    assert token.get_attribute("type") == "password" and token.get_attribute("value") == "old"
    browser.execute_script("document.querySelector('[data-setup-for=\"example\"] [data-show-secret]').click()")
    assert token.get_attribute("type") == "text"
    browser.execute_script("""
      const form = document.querySelector('[data-setup-for="example"]');
      form.querySelector('[data-plugin-field="token"]').value = 'new';
      form.querySelector('[data-plugin-field="account"]').value = 'someone';
      form.querySelector('[data-plugin-setup-save]').click();""")
    wait_until(lambda: pluginsetup.values(plugins.load("example"))["token"] == "new")
    assert pluginsetup.values(plugins.load("example"))["account"] == "someone"
    assert "saved" in browser.execute_script("return document.getElementById('pl-msg').textContent")

