#a next button that something on the page covers - a sticky header, a banner - refuses a plain click and only
#takes a script click. which way works does not change from one page to the next, so once it is known it is
#tried first: going through the refusals again cost ten seconds a page on a comic of thousands.
import selenium.common.exceptions as se

from comiclib import elements

BUTTON = '//*[@class="covered-next"]'


class Covered:
    #a button under something else: shown, but a plain click lands on whatever covers it
    def __init__(self):
        self.clicks = 0

    def is_displayed(self):
        return True

    def click(self):
        self.clicks += 1
        raise se.ElementClickInterceptedException("another element would receive the click")


class Page:
    def __init__(self, button):
        self.button = button
        self.scripted = 0
        self.waited = 0

    def find_element(self, by, xpath):
        return self.button

    def find_elements(self, by, xpath):
        return [self.button]

    def execute_script(self, script, *args):
        if "click" in script:
            self.scripted += 1


def test_the_way_that_pressed_a_button_is_tried_first_after(monkeypatch):
    button = Covered()
    page = Page(button)
    waits = []

    class Wait:
        #the scrolled click waits for the button to be clickable, which a covered one never is
        def __init__(self, driver, seconds):
            waits.append(seconds)

        def until(self, condition):
            raise se.TimeoutException("never clickable")

    monkeypatch.setattr(elements, "WebDriverWait", Wait)
    monkeypatch.setattr(elements, "next_element", lambda driver, xpath: button)
    monkeypatch.setattr(elements, "pressed_by", {})
    assert elements.next_ele_get(page, BUTTON)
    assert (button.clicks, len(waits), page.scripted) == (1, 1, 1)
    #every page after: straight to the script click, with no refusal and no wait
    for _ in range(3):
        assert elements.next_ele_get(page, BUTTON)
    assert (button.clicks, len(waits), page.scripted) == (1, 1, 4)


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
    monkeypatch.setattr(elements, "next_element", lambda driver, xpath: button)
    monkeypatch.setattr(elements, "pressed_by", {})
    monkeypatch.setattr(elements, "WebDriverWait", lambda driver, seconds: type(
        "Never", (), {"until": lambda self, condition: (_ for _ in ()).throw(se.TimeoutException())})())
    assert elements.next_ele_get(page, BUTTON) and page.scripted == 0
    button.covered = True
    assert elements.next_ele_get(page, BUTTON) and page.scripted == 1
    assert elements.pressed_by[BUTTON] == "a script click"
