"""
Playwright access to salto-youth.net: listing index, listing detail pages,
login with a persisted session, and following the Apply link to the
(usually external) application form.

Selectors verified against the live site on 2026-07-11:
- Listings: European Training Calendar /browse/ — cards are
  `li.result-container`, title link is `h2.tool-item-name a`, and the card
  body `.tool-item-description` carries dates, venue, deadline, and blurb.
- Login: https://www.salto-youth.net/mysalto/login/ with `#_username`,
  `#_password`, submit `input[name='login']`.
- Detail page content: `.tool-item-detail-wrapper`.
- Apply flow: detail page -> "Apply now!" (href contains
  `application-procedure`) -> procedure page -> "Proceed to the external
  online application" (Google/MS Forms etc.), or a native SALTO form.
If the scraper starts returning zero listings, SALTO changed its markup —
re-inspect with `playwright codegen <SALTO_LISTINGS_URL>`.
"""
import os
import re
from dataclasses import dataclass

from playwright.sync_api import sync_playwright

from config import (
    SALTO_LISTINGS_URL, SALTO_LOGIN_URL, SALTO_EMAIL, SALTO_PASSWORD,
    STORAGE_STATE_PATH, MAX_LISTING_PAGES,
)

# How much detail-page text to hand the matcher (keeps Haiku calls cheap).
DETAILS_MAX_CHARS = 4000


@dataclass
class Listing:
    id: str
    title: str
    url: str
    summary: str


def _new_context(browser):
    """Reuses the saved SALTO session when one exists."""
    if os.path.exists(STORAGE_STATE_PATH):
        return browser.new_context(storage_state=STORAGE_STATE_PATH)
    return browser.new_context()


def _goto(page, url):
    """Some SALTO pages hold connections open forever (analytics), so a
    plain networkidle wait can time out. Load DOM first, then give the
    network a bounded chance to settle."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    _settle(page)


def _settle(page):
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass


def _is_logged_in(page) -> bool:
    return page.locator("a[href*='logout']").count() > 0


def ensure_logged_in(page) -> bool:
    """Logs into MySALTO if credentials are configured and the current
    session is anonymous. Persists the session to STORAGE_STATE_PATH so
    subsequent runs skip this. Returns True when a logged-in session is
    active."""
    if not (SALTO_EMAIL and SALTO_PASSWORD):
        return False

    if _is_logged_in(page):
        return True

    _goto(page, SALTO_LOGIN_URL)
    page.fill("input[name='_username']", SALTO_EMAIL)
    page.fill("input[name='_password']", SALTO_PASSWORD)
    page.locator("input[name='login']").click()
    _settle(page)

    if not _is_logged_in(page):
        print("SALTO login appears to have failed — continuing anonymously.")
        return False

    page.context.storage_state(path=STORAGE_STATE_PATH)
    print("SALTO login OK, session saved.")
    return True


def fetch_open_listings(headless: bool = True) -> list[Listing]:
    listings = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = _new_context(browser)
        page = context.new_page()
        _goto(page, SALTO_LISTINGS_URL)
        ensure_logged_in(page)
        _goto(page, SALTO_LISTINGS_URL)

        for page_num in range(1, MAX_LISTING_PAGES + 1):
            cards = page.locator("li.result-container").all()
            for card in cards:
                try:
                    title_link = card.locator("h2.tool-item-name a").first
                    title = title_link.inner_text().strip()
                    link = title_link.get_attribute("href")
                    # card body: type, dates, venue, deadline, blurb, eligible countries
                    summary = card.locator(".tool-item").first.inner_text().strip()
                    full_url = link if link.startswith("http") else f"https://www.salto-youth.net{link}"
                    listings.append(
                        Listing(id=full_url, title=title, url=full_url, summary=summary)
                    )
                except Exception as e:
                    print(f"Skipped a card due to parse error: {e}")
                    continue

            next_link = page.locator("ol.pagination a.next-page")
            if next_link.count() == 0:
                break
            next_link.first.click()
            _settle(page)

        browser.close()
    return listings


def open_listing(listing_url: str, headless: bool = True):
    """Opens the listing detail page with the saved session and returns the
    live Playwright handles. Caller is responsible for browser.close() and
    p.stop()."""
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=headless)
    context = _new_context(browser)
    page = context.new_page()
    _goto(page, listing_url)
    return p, browser, page


def extract_listing_details(page) -> str:
    """Returns the detail-page text (dates, host country, age limits,
    eligible countries, description) so the matcher can enforce the
    profile's hard constraints."""
    container = page.locator(".tool-item-detail-wrapper")
    if container.count() == 0:
        container = page.locator("body")
    text = container.first.inner_text().strip()[:DETAILS_MAX_CHARS]

    # The expanded eligible-country lists ("Erasmus+ Youth Programme
    # countries" -> Austria, ..., Türkiye) live in tooltip title attributes,
    # invisible to inner_text — without them the matcher wrongly rejects
    # eligible listings. Appended after truncation so they never get cut off.
    titles = [t.get_attribute("title") or ""
              for t in page.locator("img.info-tooltip-icon").all()]
    titles = [t for t in titles if t.strip()]
    if titles:
        text += ("\n\nEligible countries in full (expanded from tooltips): "
                 + " | ".join(titles)[:1500])

    return text


def _maybe_popup_click(page, locator):
    """Clicks a link that may open a new tab or navigate in place; returns
    the page that ends up showing the destination."""
    try:
        with page.expect_popup(timeout=5000) as popup_info:
            locator.click()
        new_page = popup_info.value
    except Exception:
        new_page = page
    _settle(new_page)
    return new_page


def _abs_url(href: str) -> str:
    return href if href.startswith("http") else f"https://www.salto-youth.net{href}"


def open_application_form(page):
    """From an open training detail page, follows 'Apply now!' to the SALTO
    application-procedure page, then on to the external form if the
    organiser uses one (Google Forms, MS Forms, Typeform...). Returns the
    page showing the actual application form.

    Navigates by href instead of clicking: SALTO renders invisible
    duplicate links that swallow clicks.

    Returns None when the listing no longer accepts applications (SALTO
    removes the Apply link once the organiser closes the call)."""
    apply_links = page.locator("a[href*='application-procedure']")
    if apply_links.count() == 0:
        return None
    apply_href = apply_links.first.get_attribute("href")
    if apply_href:
        _goto(page, _abs_url(apply_href))

    proceed = page.locator("a:has-text('Proceed to the external')")
    if proceed.count() > 0:
        href = proceed.first.get_attribute("href")
        if href and not href.startswith(("#", "javascript")):
            _goto(page, _abs_url(href))
            return page
        return _maybe_popup_click(page, proceed.first)

    # some procedure pages only announce the external URL in prose:
    # "(Notice: You will be forwarded to https://...)"
    m = re.search(r"forwarded to (https?://[^\s)]+)",
                  page.locator("body").inner_text())
    if m:
        _goto(page, m.group(1).rstrip("."))
        return page

    # last resort: trigger SALTO's jQuery modal — the Apply link loads the
    # procedure content into an in-page dialog instead of navigating
    dialog_href = _proceed_href_via_dialog(page)
    if dialog_href:
        _goto(page, dialog_href)
        return page

    # no external link — the application is handled natively on SALTO and
    # the procedure page (after login) is the form itself
    return page


def _proceed_href_via_dialog(page) -> str | None:
    """Clicks the first *visible* fx-dialog Apply link and waits for the
    'Proceed to the external online application' anchor to appear in the
    jQuery dialog. Returns its href, or None."""
    apply_links = page.locator("a.fx-dialog[href*='application-procedure']")
    try:
        for i in range(min(apply_links.count(), 5)):
            el = apply_links.nth(i)
            if not el.is_visible():
                continue
            el.click(timeout=10000)
            proceed = page.locator("a:has-text('Proceed to the external')")
            proceed.first.wait_for(state="visible", timeout=15000)
            href = proceed.first.get_attribute("href")
            if href and href.startswith("http"):
                return href
    except Exception as e:
        print(f"Dialog fallback failed: {e}")
    return None
