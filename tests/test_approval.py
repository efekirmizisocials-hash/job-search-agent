from types import SimpleNamespace
from unittest.mock import Mock

import approval


def test_only_matching_chat_message_and_token_can_approve(monkeypatch):
    monkeypatch.setattr(approval,'TELEGRAM_CHAT_ID','7')
    monkeypatch.setattr(approval,'TELEGRAM_BOT_TOKEN','test')
    monkeypatch.setattr(approval.uuid,'uuid4',lambda:SimpleNamespace(hex='a'*32))
    monkeypatch.setattr(approval,'send_telegram_message',lambda *a,**k:{'message_id':9})
    def cb(data='approve:'+'a'*12,chat=7,message=9):
        return {'id':'callback','data':data,'message':{'chat':{'id':chat},'message_id':message}}
    updates=[{'update_id':i,'callback_query':value} for i,value in enumerate([
        cb(chat=88), cb(message=88), cb(data='evil:approve:'+'a'*12),
        cb(data='decline:'+'a'*12),
    ])]
    monkeypatch.setattr(approval.requests,'get',lambda *a,**k:SimpleNamespace(json=lambda:{'result':updates}))
    ack=Mock(); monkeypatch.setattr(approval.requests,'post',ack)
    assert approval._telegram_approval('Role','https://example.test','screenshot.png') is False
    ack.assert_called_once()
    assert ack.call_args.kwargs['data']['text']=='Skipped.'


def test_jobs_cannot_fall_back_to_console(monkeypatch):
    monkeypatch.setattr(approval,'TELEGRAM_BOT_TOKEN','')
    monkeypatch.setattr(approval,'TELEGRAM_CHAT_ID','')
    console=Mock(return_value=True)
    monkeypatch.setattr(approval,'_console_approval',console)
    monkeypatch.setattr(approval.sys.stdin,'isatty',lambda:True)
    assert approval.request_approval('Role','url','image',require_telegram=True) is False
    console.assert_not_called()
