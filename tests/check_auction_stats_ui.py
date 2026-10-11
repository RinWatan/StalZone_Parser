"""Real WebView2 smoke test with deterministic public-style auction data."""
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import webview
import stalzone_agent as agent
import stalzone_gui as gui

root=Path(__file__).resolve().parents[1]
temp=tempfile.TemporaryDirectory()
agent.DIR=Path(temp.name)
bridge=gui.Bridge()
bridge._hud=SimpleNamespace(snapshot=lambda:{'mode':'full','hotkey':True})
now=datetime.now(timezone.utc).isoformat()
data={'slug':'test','total':1,
      'lots':[{'qname':agent._qname(4),'qlt':4,'ptn':0,'amount':1,'buyout':80,'unit':80,'start':0,'left':'2ч'}],
      'sales':[{'time':'01.10 12:00','qname':agent._qname(4),'qlt':4,'ptn':0,'amount':1,'price':100,'unit':100}],
      'history_pages':[[{'time':now,'price':p,'amount':1,'additional':{'qlt':4}} for p in [100,200,3000]]]}
window=webview.create_window('Auction statistics check',html=gui.PAGE,js_api=bridge,width=1250,height=800)

def wait(expression):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        value=window.evaluate_js(expression)
        if value: return value
        time.sleep(.1)
    raise AssertionError(expression)

def check():
    report={}
    try:
        assert window.events.loaded.wait(20)
        wait("Boolean(document.getElementById('open').onclick)")
        window.evaluate_js("document.body.classList.add('full'); show('auc'); null")
        wait("state.catalog.length")
        window.evaluate_js("selected='test'; openItem(); null")
        summary=wait("document.getElementById('lotstats').textContent.includes('Медиана:') && document.getElementById('lotstats').textContent")
        assert 'Медиана: 200' in summary,summary
        report['summary']=summary
        report['above_table']=window.evaluate_js("document.getElementById('lotstats').getBoundingClientRect().bottom <= document.getElementById('lotbox').getBoundingClientRect().top")
        assert report['above_table']
        assert 'Надёжность:' in summary
        window.evaluate_js("document.getElementById('hist').click(); null")
        assert window.evaluate_js("document.getElementById('lotstats').textContent") == summary
        window.evaluate_js("document.getElementById('lo').value='5'; document.getElementById('hi').value='5'; document.getElementById('lo').onchange(); null")
        report['empty']=wait("document.getElementById('lotstats').textContent.includes('Нет продаж за 7 дней')")
        report['ok']=True
    except Exception as error:
        report['error']=str(error)
    finally:
        bridge.stop_run()
        if bridge.worker:
            bridge.worker.join(2)
        (root/'build/auction_stats_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy()

with patch.object(agent,'auction_listing',return_value=[{'id':'test','name':'Тестовый предмет','cat':'artefact','color':'DEFAULT'}]),patch.object(agent,'item_view',return_value=data),patch.object(agent,'live_lots',return_value=[{'amount':1,'buyoutPrice':80,'additional':{'qlt':4}}]):
    webview.start(check,gui='edgechromium')
temp.cleanup()
report=json.loads((root/'build/auction_stats_ui.json').read_text(encoding='utf-8'))
print(json.dumps(report,ensure_ascii=True))
sys.exit(0 if report.get('ok') else 1)
