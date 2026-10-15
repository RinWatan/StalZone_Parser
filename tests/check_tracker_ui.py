"""Exercise the real WebView2 controls without contacting either data source."""
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import webview
import stalzone_agent as agent
import stalzone_gui as gui

root=Path(__file__).resolve().parents[1]
temp=tempfile.TemporaryDirectory();agent.DIR=Path(temp.name)
bridge=gui.Bridge(); mode=['full']; created=[]
bridge._hud=SimpleNamespace(snapshot=lambda:{'mode':mode[0],'hotkey':True})

class Feed:
    def __init__(self,api,budget,update,status):
        self.update,self.status=update,status
        created.append(budget)
    def run(self):
        self.status({'running':True,'connected':True,'phase':'Подключена','received':40,'checked':2,'queue':3})
        self.update(agent._as_buys([{'name':'Проверочный предмет','slug':'abc12','buyout':70,
            'amount':1,'unit':70,'med':100,'profit':25,'count':1,'required_copies':1,'per_h':2,
            'confidence':{'level':'high','detail':'Высокая · 12 продаж'},
            'source':'SZ Tracker → EXBO','verified_at':time.time()}]))
        agent.HALT.wait(15)
        self.update([])

window=webview.create_window('SZ Tracker mode check',html=gui.PAGE,js_api=bridge,width=1250,height=800)
def wait(expr):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        value=window.evaluate_js(expr)
        if value:return value
        time.sleep(.1)
    raise AssertionError(expr)

def check():
    report={}
    try:
        assert window.events.loaded.wait(20)
        wait("Boolean(document.getElementById('tracker').onclick)")
        window.evaluate_js("document.getElementById('budget').value='5000'; document.getElementById('tracker').click(); null")
        wait("document.getElementById('trackerinfo').textContent.includes('получено 40')")
        wait("document.getElementById('deals').textContent.includes('Проверочный предмет')")
        assert window.evaluate_js("state.tables.buys[0].cells[state.tables.buys[0].cells.length-1].includes('SZ Tracker → EXBO')")
        assert window.evaluate_js("document.getElementById('run').disabled && document.getElementById('tracker').disabled && !document.getElementById('stop').disabled")
        catalogue.assert_not_called()
        report['full_button_and_verified_source']=True
        window.evaluate_js("document.getElementById('stop').click(); null")
        bridge.worker.join(2)
        assert not bridge.worker.is_alive()
        wait("!document.getElementById('tracker').disabled")
        assert not bridge.poll()['compact']
        mode[0]='compact'
        wait("!document.body.classList.contains('full')")
        window.evaluate_js("document.getElementById('quicktracker').click(); null")
        wait("document.getElementById('deals').textContent.includes('Проверочный предмет')")
        assert len(created)==2 and created==[5000,5000]
        report['compact_button_and_stop']=True
        catalogue.assert_not_called()
        report['no_catalogue_download']=True
        report['ok']=True
    except Exception as error:
        report['error']=str(error)
    finally:
        bridge.stop_run()
        if bridge.worker:bridge.worker.join(2)
        (root/'build/tracker_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy()

with patch.object(gui.tracker,'TrackerFeed',Feed),patch.object(agent,'exbo_headers',return_value={}),patch.object(agent,'auction_listing',return_value=[]) as catalogue:
    webview.start(check,gui='edgechromium')
temp.cleanup()
report=json.loads((root/'build/tracker_ui.json').read_text(encoding='utf-8'))
print(json.dumps(report,ensure_ascii=True))
sys.exit(0 if report.get('ok') else 1)
