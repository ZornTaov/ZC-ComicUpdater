#the web page's own handling, in a real browser: a pasted list filling the add table, the settings dialog
#opening and closing, and the element path lists reordered by button and by drag without jumping about.
import time

import pytest

from conftest import console_errors, open_page, wait_until

pytestmark = [pytest.mark.browser, pytest.mark.slow]

#the shape a reader keeps their list in: folder | archive | address, one comic a line
PASTE = ("ComicName | ComicName/ComicName.cbz | https://example.com/comic\n"
         "ComicSeries/ComicA | ComicSeries/ComicA.cbz | https://example.com/series/comic_a\n"
         "ComicSeries/ComicB | ComicSeries/ComicB.cbz | https://example.com/series/comic_b")


@pytest.fixture
def page(web, browser):
    started = web()
    browser.set_window_size(1350, 1000)
    open_page(browser, started.base + "/")
    return started


def test_a_pasted_list_fills_the_add_table(page, browser):
    browser.execute_script("""
      const cell = document.querySelector('[data-add-field="folder"]');
      const data = new DataTransfer();
      data.setData('text/plain', arguments[0]);
      cell.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
    """, PASTE)
    time.sleep(0.6)
    rows = browser.execute_script("return addRows")
    assert len(rows) == 3, rows
    assert rows[0]["folder"] == "ComicName" and rows[0]["cbz"] == "ComicName/ComicName.cbz", rows[0]
    assert rows[2]["url"] == "https://example.com/series/comic_b", rows[2]


def test_the_element_lists_reorder_by_button_and_by_drag(page, browser):
    #the settings dialog opens and closes on the way, as it did when these were only looked at
    browser.execute_script("document.getElementById('open-config').click()")
    time.sleep(0.3)
    browser.execute_script("document.getElementById('cfg-cancel').click()")

    browser.execute_script("document.getElementById('open-elements').click()")
    #the lists arrive by fetch once the dialog opens
    wait_until(lambda: browser.execute_script("return typeof paths !== 'undefined' && paths.image "
                                              "&& paths.image.length && document.querySelectorAll("
                                              "'[data-list=\"image\"] [data-move=\"up\"]').length"),
               why="the element lists never arrived")
    #a row well down the list, so moving it happens somewhere a re-render could scroll away from
    at = browser.execute_script("return Math.min(8, paths.image.length - 1)")
    assert at >= 1, "the image list is too short to move a row up"
    browser.execute_script("document.querySelector('[data-list=\"image\"]').scrollTop = 200")
    time.sleep(0.4)
    before = browser.execute_script(
        "return [document.querySelector('[data-list=\"image\"]').scrollTop, paths.image[arguments[0]].xpath]", at)
    browser.execute_script(
        "document.querySelectorAll('[data-list=\"image\"] [data-move=\"up\"]')[arguments[0]].click()", at)
    time.sleep(0.4)
    after = browser.execute_script(
        "return [document.querySelector('[data-list=\"image\"]').scrollTop, paths.image[arguments[0] - 1].xpath]", at)
    assert before[1] == after[1], "moving a row up did not move it: {0} {1}".format(before, after)
    assert abs(before[0] - after[0]) < 5, "the list scrolled back ({0} -> {1})".format(before[0], after[0])

    #and a drag, from one row onto another
    dragged = browser.execute_script("""
      const list = document.querySelector('[data-list="next"]');
      const rows = list.querySelectorAll('.ep');
      const from = rows[0], onto = rows[3];
      const was = paths.next[0].xpath;
      const data = new DataTransfer();
      from.dispatchEvent(new DragEvent('dragstart', { dataTransfer: data, bubbles: true }));
      onto.dispatchEvent(new DragEvent('dragover', { dataTransfer: data, bubbles: true, cancelable: true }));
      onto.dispatchEvent(new DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true }));
      return [was, paths.next[3].xpath];
    """)
    assert dragged[0] == dragged[1], "the dragged row did not land where it was dropped: {0}".format(dragged)

    browser.set_window_size(430, 1200)
    open_page(browser, page.base + "/")
    time.sleep(1)
    errors = console_errors(browser)
    assert not errors, errors
