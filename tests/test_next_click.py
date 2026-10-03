#a next button that something on the page covers - a sticky header, a banner - refuses a plain click and only
#takes a script click. which way works does not change from one page to the next, so once it is known it is
#tried first; and a scrolled click, which can wait out a whole timeout, is only ever tried last. a script
#click the site ignores is not taken for a press, since that would end the run as if it were caught up.
import selenium.common.exceptions as se

from comiclib import elements

BUTTON = '//*[@class="covered-next"]'


class Covered:
    #a button under something else: shown, but a plain click lands on whatever covers it
    def __init__(self):
        self.clicks = 0

    def is_displayed(self):
        return True

    def is_enabled(self):
        return True

    def click(self):
        self.clicks += 1
        raise se.ElementClickInterceptedException("another element would receive the click")


class Page:
    #moves on a script click, unless it only answers a reader's own click
    def __init__(self, button, trusts_scripts=True):
        self.button = button
        self.trusts_scripts = trusts_scripts
        self.scripted = 0
        self.current_url = "https://example.com/comic/1"

    def execute_script(self, script, *args):
        if "click" in script:
            self.scripted += 1
            if self.trusts_scripts:
                self.current_url = "https://example.com/comic/{0}".format(self.scripted + 1)


def never_clickable(waits):
    class Wait:
        #the scrolled click waits for the button to be clickable, which a covered one never is
        def __init__(self, driver, seconds):
            waits.append(seconds)

        def until(self, condition):
            raise se.TimeoutException("never clickable")
    return Wait


def press(monkeypatch, button):
    waits = []
    monkeypatch.setattr(elements, "WebDriverWait", never_clickable(waits))
    monkeypatch.setattr(elements, "next_element", lambda driver, xpath: button)
    monkeypatch.setattr(elements, "pressed_by", {})
    return waits


def test_a_covered_button_takes_a_script_click_without_waiting(monkeypatch):
    button = Covered()
    page = Page(button)
    waits = press(monkeypatch, button)
    assert elements.next_ele_get(page, BUTTON)
    #refused once, then the script click: the scrolled click and its wait never come into it
    assert (button.clicks, waits, page.scripted) == (1, [], 1)
    #and every page after goes straight to the script click
    for _ in range(3):
        assert elements.next_ele_get(page, BUTTON)
    assert (button.clicks, waits, page.scripted) == (1, [], 4)
    assert elements.pressed_by[BUTTON] == "a script click"


def test_a_script_click_the_site_ignores_falls_through_to_a_real_one(monkeypatch):
    class Scrollable(Covered):
        #covered until it is scrolled to, when a real click goes through
        pass

    button = Scrollable()
    page = Page(button, trusts_scripts=False)
    monkeypatch.setattr(elements, "next_element", lambda driver, xpath: button)
    monkeypatch.setattr(elements, "pressed_by", {})
    clicked = []

    class Ready:
        def __init__(self, driver, seconds):
            pass

        def until(self, condition):
            return type("Clickable", (), {"click": lambda self: clicked.append(True)})()

    monkeypatch.setattr(elements, "WebDriverWait", Ready)
    monkeypatch.setattr(elements, "page_moved", lambda driver, pressed, before, wait=2.0: False)
    assert elements.next_ele_get(page, BUTTON)
    assert page.scripted == 1 and clicked == [True]
    assert elements.pressed_by[BUTTON] == "a click after scrolling to it"


def test_a_script_click_that_is_all_there_is_still_counts(monkeypatch):
    #a comic that redraws its page in place moves in a way that cannot be seen from here; with nothing
    #else able to press it, the script click is taken, as it always was
    button = Covered()
    page = Page(button, trusts_scripts=False)
    waits = press(monkeypatch, button)
    monkeypatch.setattr(elements, "page_moved", lambda driver, pressed, before, wait=2.0: False)
    assert elements.next_ele_get(page, BUTTON)
    assert page.scripted == 1 and waits == [10]
    #not remembered, since it was never seen to work
    assert BUTTON not in elements.pressed_by


def test_a_button_that_stops_taking_the_remembered_way_falls_back(monkeypatch):
    class Plain(Covered):
        #takes a plain click, until it is covered part way through the comic
        covered = False

        def click(self):
            self.clicks += 1
            if self.covered:
                raise se.ElementClickInterceptedException("covered now")

    button = Plain()
    page = Page(button)
    press(monkeypatch, button)
    assert elements.next_ele_get(page, BUTTON) and page.scripted == 0
    button.covered = True
    assert elements.next_ele_get(page, BUTTON) and page.scripted == 1
    assert elements.pressed_by[BUTTON] == "a script click"


def test_a_page_has_moved_once_its_address_changes_or_it_is_replaced():
    class Gone(Covered):
        def is_enabled(self):
            raise se.StaleElementReferenceException("replaced")

    page = Page(Covered())
    assert not elements.page_moved(page, Covered(), page.current_url, wait=0.1)
    assert elements.page_moved(page, Covered(), "https://example.com/comic/0", wait=0.1)
    assert elements.page_moved(page, Gone(), page.current_url, wait=0.1)
