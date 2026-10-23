from sources.ats_boards import Lever
from sources.base import Job, location_matches
from sources.http import HttpSource
from sources.salto import Salto


def test_location_preferences_preserve_remote_and_unknown():
    assert location_matches(Job(location='Berlin',remote=True),['Remote'])
    assert location_matches(Job(location='Worldwide',remote=True),['Istanbul'])
    assert location_matches(Job(location=''),['Istanbul'])
    assert not location_matches(Job(location='London',remote=False),['Istanbul'])
    assert not HttpSource().accepts(Job(id='x',title='',url='https://example.test'))


def test_lever_searches_later_pages_before_applying_result_limit(monkeypatch):
    source=Lever(boards=['example'],limit=1,max_pages=2,max_age_days=None)
    calls=[]
    def fetch(method,url,params):
        calls.append(params)
        if params['skip']==0:
            return [{'id':str(i),'text':'Sales','hostedUrl':f'https://jobs.lever.co/example/{i}'} for i in range(100)]
        return [{'id':'engineer','text':'Python Engineer','hostedUrl':'https://jobs.lever.co/example/engineer'}]
    monkeypatch.setattr(source,'_json',fetch)
    assert source.search(['Python'])[0].id=='engineer'
    assert [call['skip'] for call in calls]==[0,100]


def test_salto_original_deadline_format():
    assert Salto._deadline('Application deadline (24h UTC): 12 July 2026')=='2026-07-12'
    assert Salto._deadline('Application deadline: 31 February 2026') is None
