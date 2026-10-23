"""Browser-backed tests only visit in-memory pages; never real ATS forms."""
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
import form_filler
import main


@pytest.fixture
def page():
    if not os.environ.get('RUN_BROWSER_TESTS'):
        pytest.skip('Set RUN_BROWSER_TESTS=1 with Playwright Chromium installed')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        page=browser.new_page()
        yield page
        browser.close()


def test_hidden_file_input_upload_and_no_submit(page,tmp_path,monkeypatch):
    page.set_content('''<form onsubmit="window.submitted=true; return false">
        <label for="cv">Resume CV</label><input id="cv" type="file" style="display:none" required accept=".pdf">
        <label for="name">Name</label><input id="name" required>
        <button type="submit">Submit</button></form>''')
    cv=tmp_path/'cv.pdf'; cv.write_bytes(b'%PDF-fixture')
    monkeypatch.setattr(form_filler,'_plan_dom_fields',lambda fields,profile:[{'idx':fields[0]['idx'],'value':'Sample Person'}])
    failed,blocked,found,learned,planned=form_filler.fill_form(page,'Name: Sample Person',documents={'cv':cv})
    assert not failed and not blocked and found
    assert page.locator('#cv').evaluate('(e)=>e.files[0].name')=='cv.pdf'
    assert page.locator('#name').input_value()=='Sample Person'
    assert not page.evaluate('window.submitted || false')


def test_unknown_required_upload_is_manual(page):
    page.set_content('<label for="f">Passport document</label><input id="f" type="file" required>')
    failed,blocked,found,_,_=form_filler.fill_form(page,'Name: Sample Person',documents={})
    assert failed and found


def test_next_button_cannot_be_arbitrary_submit(page):
    page.set_content('<button onclick="window.submitted=true">Continue and submit</button>')
    assert not form_filler._click_next_dom(page)
    assert not page.evaluate('window.submitted || false')


def test_confirmation_detector_real_playwright_signature(page):
    page.set_content('<p>Your application has been submitted.</p>')
    assert main._confirmed(page,'Apply for this role')
    assert not main._confirmed(page,'Your application has been submitted.')


def test_final_click_is_exact_and_once(page):
    page.set_content('''<button onclick="window.wrong=true">Apply with LinkedIn</button>
        <button onclick="window.count=(window.count||0)+1">Submit application</button>''')
    assert main._submit_once(page)
    assert page.evaluate('window.count')==1
    assert not page.evaluate('window.wrong || false')
