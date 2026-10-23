"""Discover, rank, draft and review jobs; only Telegram-approved forms may submit."""
import argparse
from contextlib import contextmanager
from datetime import date
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

import config
import db
from sources.base import Job
from matcher import evaluate_job, load_profile, append_learned_answer
from safety import sanitize_job, UnsafePosting
from ats import detect_ats, is_open_ats
from llm import get_llm_client
from form_filler import fill_form, verify_form, form_screenshot_bytes
from approval import request_approval, ask_user_field
from notifier import notify, send_telegram_document

LOCK_PATH = config.PROJECT_ROOT / 'run.lock'
CONFIRMATION = re.compile(
    r'(?:your application (?:has been |was )?(?:successfully )?(?:submitted|received)|'
    r'thank you for (?:your application|applying)|application submitted successfully)', re.I)


def parse_deadline(text: str) -> str | None:
    """Legacy SALTO deadline helper (new sources provide normalized ISO dates)."""
    months = {m:i+1 for i,m in enumerate(('January','February','March','April','May','June',
                                         'July','August','September','October','November','December'))}
    match = re.search(r'Application deadline[^:]*:\s*(\d{1,2})\s+(\w+)\s+(\d{4})', text, re.I)
    if not match:
        return None
    try:
        day, month, year = match.groups()
        return date(int(year), months[month.capitalize()], int(day)).isoformat()
    except (ValueError,KeyError):
        return None


@contextmanager
def _database_for_run(dry_run):
    """Dry runs use a temporary snapshot, never migrate or mark the real queue."""
    original = db.DB_PATH
    if not dry_run:
        db.init_db()
        yield
        return
    with tempfile.TemporaryDirectory(prefix='job-dry-run-') as directory:
        snapshot = str(Path(directory) / 'state.db')
        if Path(original).exists():
            with sqlite3.connect(Path(original).resolve().as_uri()+'?mode=ro', uri=True) as source:
                with sqlite3.connect(snapshot) as dest:
                    source.backup(dest)
        db.DB_PATH = snapshot
        try:
            db.init_db()
            yield
        finally:
            db.DB_PATH = original


def _match_one(job, profile_text, dry_run):
    key = db.resolve_job_id(job)
    if db.already_seen(key):
        return None
    if job.deadline and job.deadline < date.today().isoformat():
        db.record_job(job,key,{'reason':'Application deadline has passed'},'skipped')
        return None
    if not job.description.strip():
        db.record_job(job,key,{'reason':'Source did not provide a job description'},'needs_review')
        return None
    try:
        job = sanitize_job(job)
        result = evaluate_job(job, profile_text)
    except (UnsafePosting,ValueError) as exc:
        db.record_job(job,key,{'reason':str(exc)},'needs_review')
        print(f'REVIEW — {job.title}: {exc}')
        if not dry_run:
            notify('Job needs review', f'{job.title}\n{job.url}\n{exc}')
        return None
    status = 'suitable' if result['suitable'] else 'not_suitable'
    hard_fail = any(g['status']=='FAIL' for g in result['gates'].values())
    if not result['suitable'] and not hard_fail and (result['verdict']=='Moderate Fit' or any(g['status']=='FLAG' for g in result['gates'].values())):
        status = 'needs_review'
    db.record_job(job,key,result,status)
    print(f"{status.upper()} — {result['score']:.1f} {result['verdict']} — {job.title}")
    print('  Gates: ' + json.dumps(result['gates'], ensure_ascii=False))
    if status == 'needs_review' and not dry_run:
        notify('Job fit needs review', f'{job.title}\n{job.url}\n{result["reason"]}')
    return result


def _deliver_package(package, title):
    delivered = True
    for path in (package.cv, package.cover_letter, package.answers):
        delivered = bool(send_telegram_document(str(path), f'{title}: {Path(path).name}')) and delivered
    return delivered


def _manual(entry, package, reason):
    db.set_status(entry['id'], 'ready_manual', reason, str(package.directory))
    try:
        _deliver_package(package, entry['title'])
        notify('Apply manually', f"{entry['title']}\n{entry.get('apply_url') or entry['url']}\n"
               f"{reason}\nDocuments: {package.directory}\nUse 'manual' then 'applied <n>' after submitting.")
    except Exception:
        # Files remain available locally; failed delivery must not cause regeneration/reapplication.
        print(f"Manual package ready at {package.directory}; Telegram delivery failed.")
    return 'ready_manual'


def _open_job_page(url):
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    browser = None
    try:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(service_workers='block')
        # DOM submission remains blocked until our approved final click.
        context.add_init_script('''(() => {
            window.__jobApproved = false;
            document.addEventListener('submit', e => {
                if (!window.__jobApproved) { e.preventDefault(); e.stopImmediatePropagation(); }
            }, true);
            const original = HTMLFormElement.prototype.submit;
            HTMLFormElement.prototype.submit = function() {
                if (window.__jobApproved) return original.call(this);
            };
        })();''')
        page = context.new_page()
        # Block pre-approval mutation requests, including JS fetch submissions.
        # Upload endpoints are the sole exception; unknown POST-based forms fall back to manual.
        approved = {'value':False}
        def route_request(route):
            request = route.request
            mutation = request.method.upper() not in {'GET','HEAD','OPTIONS'}
            upload = bool(re.search(r'/(?:uploads?|attachments?)(?:[/?._-]|$)', request.url, re.I))
            same_ats = detect_ats(request.url) == detect_ats(url)
            if mutation and not approved['value'] and not (upload and same_ats):
                route.abort()
            else:
                route.continue_()
        context.route('**/*', route_request)
        page.goto(url, wait_until='domcontentloaded', timeout=45000)
        return p,browser,page,approved
    except BaseException:
        if browser:
            browser.close()
        p.stop()
        raise


def _submit_once(page):
    """One chosen submit control, one click. A timeout is uncertain, never a retry."""
    for label in ('Submit application', 'Submit', 'Send application', 'Apply', 'Gönder'):
        candidates = page.get_by_role('button', name=label, exact=True)
        for index in range(min(candidates.count(),20)):
            button = candidates.nth(index)
            if button.is_visible() and button.is_enabled():
                button.click(timeout=15000)
                return True
    return False


def _confirmed(page, before_text):
    try:
        page.wait_for_function('''pattern => new RegExp(pattern, 'i').test(document.body.innerText)''',
                               arg=CONFIRMATION.pattern, timeout=15000)
    except Exception:
        return False
    text = page.locator('body').inner_text()
    return not CONFIRMATION.search(before_text) and bool(CONFIRMATION.search(text))


def apply_to(entry: dict, profile_text: str) -> str:
    from documents import generate_documents
    with db.get_conn() as conn:
        current = conn.execute('SELECT status FROM listings WHERE id=?', (entry['id'],)).fetchone()
    if not current or current['status'] != 'suitable':
        return current['status'] if current else 'failed'
    job = sanitize_job(db.entry_job(entry))
    package = generate_documents(job, profile_text, entry['id'])
    db.set_status(entry['id'],'suitable',entry.get('match_reason') or '', str(package.directory))
    if not is_open_ats(job.apply_url):
        return _manual(entry,package,'This application site requires manual submission.')
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        return _manual(entry,package,'Telegram approval is not configured.')
    p = browser = None
    claimed = False
    try:
        p,browser,page,approved = _open_job_page(job.apply_url)
        if not is_open_ats(page.url) or detect_ats(page.url) != detect_ats(job.apply_url):
            return _manual(entry,package,'Application redirected to an unsupported site.')
        failed,blocked,any_fields,learned,planned = fill_form(
            page,profile_text,
            ask_user=lambda label,question: ask_user_field(job.title,label,question),
            documents={'cv':package.cv,'cover_letter':package.cover_letter})
        for answer in learned:
            append_learned_answer(answer['label'],answer['question'],answer['answer'])
        if planned:
            with Path(package.answers).open('a',encoding='utf-8') as handle:
                handle.write('\n\nForm answers prepared:\n')
                for answer in planned:
                    handle.write(f"\n{answer['label']}\n{answer['value']}\n")
        if blocked and blocked.startswith('pending: '):
            db.set_status(entry['id'],'pending',blocked,str(package.directory))
            notify('Application waiting for your answer', f"{job.title}\n{blocked}\nUse 'pending' and 'answer <n> <text>'.")
            return 'pending'
        if blocked or failed or not any_fields:
            return _manual(entry,package,blocked or f'Form needs manual completion: {failed or "no fields detected"}')
        invalid = page.locator('input:invalid, select:invalid, textarea:invalid').count()
        if invalid:
            return _manual(entry,package,f'{invalid} form fields fail browser validation.')
        verification = verify_form(page)
        if verification.get('ready') is not True:
            return _manual(entry,package,'Form verification failed: '+str(verification.get('issue','')))
        screenshot = Path(package.directory)/'review.png'
        screenshot.write_bytes(form_screenshot_bytes(page))
        if not _deliver_package(package,job.title):
            return _manual(entry,package,'Could not deliver all documents for approval.')
        gates = json.loads(entry.get('gates') or '{}')
        caveats = '; '.join(f'{k}: {v.get("reason", "")}' for k,v in gates.items() if v.get('status')=='FLAG')
        approval_title = job.title + ('\nReview caveats: '+caveats if caveats else '')
        if not request_approval(approval_title,job.apply_url,str(screenshot), require_telegram=True):
            db.mark_skipped(entry['id'],'Declined or approval timed out')
            return 'declined'
        before_text = page.locator('body').inner_text()
        if not db.claim_submission(entry['id']):
            return 'submission_unknown'
        claimed = True
        approved['value'] = True
        page.evaluate('window.__jobApproved = true')
        if not _submit_once(page):
            claimed = False
            return _manual(entry,package,'No final submit button found.')
        if not _confirmed(page,before_text):
            db.set_status(entry['id'],'submission_unknown','Submit clicked but confirmation was not observed; check manually before retrying.')
            return 'submission_unknown'
        db.mark_applied(entry['id'])
        try:
            notify('Application submitted',f'{job.title}\n{job.apply_url}')
        except Exception:
            pass
        return 'applied'
    except Exception as exc:
        if claimed:
            db.set_status(entry['id'],'submission_unknown','Submission may have occurred; check manually before retrying.')
            print(f'Submission uncertain ({type(exc).__name__}); no automatic retry.')
            return 'submission_unknown'
        return _manual(entry,package,f'Automation could not finish ({type(exc).__name__}).')
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if p:
            try:
                p.stop()
            except Exception:
                pass


def _run(dry_run=False, search_config=None, source_names=None):
    from sources import load_sources
    profile = load_profile()
    get_llm_client()  # Fail before touching the queue if the chosen SDK/key is unavailable.
    sources,queries = load_sources(search_config or config.SEARCH_CONFIG_PATH)
    if source_names:
        # Explicit override supports the preserved SALTO flow without rewriting config.
        from sources import load_sources as load
        import yaml
        with tempfile.TemporaryDirectory(prefix='job-sources-') as directory:
            path = Path(directory)/'search.yaml'
            original = Path(search_config or config.SEARCH_CONFIG_PATH)
            settings = yaml.safe_load(original.read_text()) if original.exists() else {}
            settings = settings or {}
            settings['sources'] = source_names
            path.write_text(yaml.safe_dump(settings))
            sources,queries = load(str(path))
    with _database_for_run(dry_run):
        for source in sources:
            try:
                jobs = source.search(queries)
            except Exception as exc:
                print(f'Source {source.name} unavailable ({type(exc).__name__}).')
                continue
            for job in jobs:
                try:
                    if db.already_seen(db.resolve_job_id(job)):
                        continue
                    detail = getattr(source,'detail',None)
                    if detail:
                        job = detail(job)
                    _match_one(job,profile,dry_run)
                except Exception as exc:
                    # Transient provider/source failure remains eligible for the next discovery run.
                    print(f'Could not process {job.title} ({type(exc).__name__}); will retry discovery later.')
        queue = db.get_application_queue(config.MAX_APPLICATIONS_PER_RUN)
        if dry_run:
            print(f'[dry-run] {len(queue)} queued applications (capped); no documents or forms generated.')
            for entry in queue:
                print(f"  {entry['score'] or 0:.1f} | {entry['deadline'] or '?'} | {entry['title']}")
            return
        for entry in queue:
            try:
                print(f"{apply_to(entry,profile)} — {entry['title']}")
            except Exception as exc:
                db.set_status(entry['id'],'needs_review',f'Document preparation or profile validation failed ({type(exc).__name__}): {exc}')
                print(f"REVIEW — {entry['title']}: {exc}")


def main(dry_run=False, search_config=None, source_names=None):
    try:
        fd = os.open(LOCK_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        raise RuntimeError('Another run holds run.lock. If a previous run crashed, verify it has stopped before removing the lock.')
    try:
        with os.fdopen(fd,'w') as handle:
            handle.write(str(os.getpid()))
        _run(dry_run,search_config,source_names)
    finally:
        LOCK_PATH.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run',action='store_true',help='Find and rank jobs without changing the queue or filling forms')
    parser.add_argument('--config',dest='search_config',help='Search YAML configuration')
    parser.add_argument('--sources',help='Comma-separated source override, e.g. salto or remotive,arbeitnow')
    args = parser.parse_args()
    try:
        main(args.dry_run,args.search_config,args.sources.split(',') if args.sources else None)
    except (RuntimeError,ValueError,FileNotFoundError) as exc:
        parser.exit(1,f'{exc}\n')
