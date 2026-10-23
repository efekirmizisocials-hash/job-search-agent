"""Full coordinator flow with synthetic discovery and no external services."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import db
import documents
import main
import sources
from sources.base import Job


def test_discovery_to_manual_package_and_repeat_dedup(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'state.db'))
    monkeypatch.setattr(main,'load_profile',lambda:'Synthetic candidate')
    monkeypatch.setattr(main,'get_llm_client',lambda:object())
    monkeypatch.setattr(main.config,'TELEGRAM_BOT_TOKEN','')
    monkeypatch.setattr(main.config,'TELEGRAM_CHAT_ID','')
    job=Job(id='one',source='fixture',title='Python Engineer',company='Example',
            url='https://example.test/job/1',apply_url='https://example.test/job/1',description='Build Python services')
    source=SimpleNamespace(name='fixture',search=lambda queries:[job,replace(job,source='mirror')],detail=lambda j:j)
    monkeypatch.setattr(sources,'load_sources',lambda path:([source],['Python']))
    evaluate=Mock(return_value={'suitable':True,'score':80,'verdict':'Strong Fit','reason':'Relevant experience',
        'gates':{key:{'status':'PASS','reason':'Supported'} for key in ('eligibility','language','location')}})
    monkeypatch.setattr(main,'evaluate_job',evaluate)
    package=SimpleNamespace(directory=tmp_path/'package',cv=tmp_path/'cv.pdf',
        cover_letter=tmp_path/'cover_letter.pdf',answers=tmp_path/'answers.txt',posting=tmp_path/'posting.md')
    generate=Mock(return_value=package)
    monkeypatch.setattr(documents,'generate_documents',generate)
    deliver=Mock(return_value=True); notify=Mock()
    monkeypatch.setattr(main,'_deliver_package',deliver)
    monkeypatch.setattr(main,'notify',notify)
    main._run(dry_run=True)
    assert not Path(db.DB_PATH).exists()
    generate.assert_not_called(); deliver.assert_not_called(); notify.assert_not_called()
    main._run()
    assert len(db.get_manual())==1
    assert db.get_manual()[0]['docs_path']==str(package.directory)
    generate.assert_called_once(); deliver.assert_called_once()
    calls=evaluate.call_count
    main._run()
    assert evaluate.call_count==calls
    generate.assert_called_once(); deliver.assert_called_once()
