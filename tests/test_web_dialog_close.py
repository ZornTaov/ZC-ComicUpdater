#a comic's editor closed from the × in its head, or by a click beside it - but only a click pressed and let go
#both outside it: selecting a field's text by dragging, and letting go past the dialog's edge, keeps it open
import pytest
from selenium.webdriver.common.action_chains import ActionChains

from conftest import open_page, wait_until
from test_every import unwalked

pytestmark = [pytest.mark.browser]


def editor_open(browser):
    return browser.execute_script("return document.getElementById('editor').open")


def opened(browser, page):
    open_page(browser, page.base + "/")
    browser.execute_script("openEditor('Uncompressed/MyComic')")
    wait_until(lambda: editor_open(browser), why="the editor never opened")


def press(browser, start, end):
    #pressed at one point of the window and let go at another, as a hand does
    actions = ActionChains(browser)
    actions.w3c_actions.pointer_action.move_to_location(*start)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.move_to_location(*end)
    actions.w3c_actions.pointer_action.pointer_up()
    actions.perform()


def test_the_editor_closes_from_its_head_or_a_click_beside_it_but_not_a_drag_let_go_there(library, web, browser):
    unwalked(library, ["0001.png"], "MyComic")
    page = web()
    opened(browser, page)
    box = browser.execute_script("const b = document.getElementById('editor').getBoundingClientRect();"
                                 "return [b.left, b.top, b.right, b.bottom];")
    field = browser.execute_script("const b = document.getElementById('e-url').getBoundingClientRect();"
                                   "return [b.left + 20, b.top + b.height / 2];")
    beside = (int(box[0] / 2), int(field[1]))
    assert beside[0] > 2, "the dialog fills the window, so there is nowhere beside it to click"

    #a drag from the start page box out past the dialog's edge selects its text: chrome then clicks the
    #dialog itself, beside its box, which must not close it
    press(browser, (int(field[0]), int(field[1])), beside)
    assert editor_open(browser), "a drag let go beside the editor closed it"

    #pressed and let go beside it
    press(browser, beside, beside)
    wait_until(lambda: not editor_open(browser), limit=5, why="a click beside the editor did not close it")

    #and the × in its head
    opened(browser, page)
    browser.find_element("id", "edit-cancel").click()
    wait_until(lambda: not editor_open(browser), limit=5, why="the × did not close the editor")


def test_every_dialog_closes_the_same_way(web, browser):
    page = web()
    open_page(browser, page.base + "/")
    names = browser.execute_script("return [...document.querySelectorAll('dialog')].map((d) => d.id)")
    assert {"editor", "comicinfo", "bounds", "listcheck", "elements", "plugins", "config"} <= set(names), names
    for name in names:
        #one ×, last in the form so it is not what the dialog opens focused on, but shown in the head's
        #top right corner; and nothing in its foot that only closes it
        browser.execute_script("document.getElementById(arguments[0]).showModal()", name)
        found = browser.execute_script(
            "const d = document.getElementById(arguments[0]), x = d.querySelector('.dlg-x'),"
            " head = d.querySelector('.dlg-head').getBoundingClientRect(), at = x && x.getBoundingClientRect();"
            "return [d.querySelectorAll('.dlg-x').length,"
            " !!at && at.top >= head.top && at.bottom <= head.bottom && head.right - at.right < 30,"
            " document.activeElement === x,"
            " [...d.querySelectorAll('.dlg-foot button')].map((b) => b.textContent.trim())]", name)
        browser.execute_script("document.getElementById(arguments[0]).close()", name)
        assert found[:3] == [1, True, False], \
            "{0} should have one ×, in its head's corner, not focused as it opens: {1}".format(name, found)
        assert not {"Close", "Done", "Cancel"} & set(found[3]), "{0} still closes from its foot: {1}".format(name, found)

        def shown():
            browser.execute_script("document.getElementById(arguments[0]).showModal()", name)
            return browser.execute_script("const b = document.getElementById(arguments[0]).getBoundingClientRect();"
                                          "return [b.left, b.top + 30];", name)
        at = shown()
        press(browser, (int(at[0] / 2), int(at[1])), (int(at[0] / 2), int(at[1])))
        wait_until(lambda: not browser.execute_script("return document.getElementById(arguments[0]).open", name),
                   limit=5, why="a click beside {0} did not close it".format(name))
        shown()
        browser.execute_script("document.querySelector('#' + arguments[0] + ' .dlg-x').click()", name)
        wait_until(lambda: not browser.execute_script("return document.getElementById(arguments[0]).open", name),
                   limit=5, why="the × of {0} did not close it".format(name))
