"""Real WebView2: local presets, artifact details, escaping and fresh contexts."""
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
import stalzone_tracker as tracker

root=Path(__file__).resolve().parents[1]
temp=tempfile.TemporaryDirectory();agent.DIR=Path(temp.name)
bridge=gui.Bridge();mode=['full'];actions=[]
bridge._hud=SimpleNamespace(snapshot=lambda:{'mode':mode[0],'hotkey':True})
engine=tracker.TrackerFeed(agent,6400000,lambda _:None,lambda state:setattr(bridge,'_tracker_state',state))
engine.connected=True
engine.ingest({'type':'snapshot','data':[{
    'uniqueId':101,'itemId':'zyrm','name':'Зеркало','category':'artefact','qlt':3,'ptn':10,
    'amount':1,'cost':1600000,'targetPrice':2600000,'explored':True,'charge':87,
    'qltInfo':{'labelPercentQlt':'132,1%'},'bonusInfo':['<img src=x onerror="window.__bad=1">'],
    'defaultBonusInfo':{'defaultBonuses':[{'bonusName':'Переносимый вес','textMinAndMax':'+10,5'}]},
    'metrics':{'median':2600000,'sampleSize':6}}]})
engine.report()
identity=engine.pool.active['zyrm'][0].identity
window=webview.create_window('Resale tools check',html=gui.PAGE,js_api=bridge,width=1250,height=900)

def wait(expr):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        value=window.evaluate_js(expr)
        if value:return value
        time.sleep(.1)
    raise AssertionError(expr)

def js(code):window.evaluate_js(code+'; null')

def check():
    report={}
    try:
        assert window.events.loaded.wait(20)
        wait("Boolean(document.getElementById('szsave').onclick)")
        wait("state.tables.resale && state.tables.resale.length === 1")
        js("show('resale'); document.querySelector('[data-resale]').click()")
        wait("document.getElementById('resaledialog').open")
        assert window.evaluate_js("document.getElementById('resalebody').textContent.includes('Переносимый вес')")
        assert window.evaluate_js("document.getElementById('resalebody').textContent.replace(/\\s/g,'').includes('2470000')")
        assert window.evaluate_js("document.getElementById('resalebody').textContent.includes('<img') && !document.querySelector('#resalebody img') && !window.__bad")
        engine.contexts[identity]={'checked_at':time.time(),'cheapest_unit':1400000,'cheaper_lots':1,'variant_lots':3,'limited':False}
        engine.report()
        wait("document.getElementById('resalebody').textContent.includes('дешевле за штуку: 1')")
        engine.contexts[identity]['checked_at']=time.time()-60;engine.report()
        wait("document.getElementById('resalebody').textContent.includes('конкурентах устарели')")
        js("document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}))")
        wait("!document.getElementById('resaledialog').open")
        assert not actions
        report['details_calculation_escaping_and_expiry']=True
        js("document.getElementById('szadvanced').open=true; document.getElementById('szcategory').value='weapon'; document.getElementById('szapply').click()")
        wait("state.tables.resale.length === 0")
        js("document.getElementById('szpresetname').value='Оружие'; document.getElementById('szsave').click()")
        wait("document.getElementById('szpresets').value === 'Оружие'")
        js("document.getElementById('szcategory').value='artefact'; document.getElementById('szquality').value='3'; document.getElementById('szrefmin').value='10'; document.getElementById('szexplored').value='explored'; document.getElementById('szinclude').value='зеркало'; document.getElementById('szapply').click()")
        wait("state.tables.resale.length === 1")
        js("document.getElementById('szpresetname').value='<Мои арты>'; document.getElementById('szsave').click()")
        wait("document.getElementById('szpresets').value === '<Мои арты>'")
        js("document.getElementById('szpresets').value='Оружие'; document.getElementById('szload').click()")
        wait("state.tables.resale.length === 0 && document.getElementById('szcategory').value === 'weapon'")
        js("document.getElementById('szpresets').value='<Мои арты>'; document.getElementById('szload').click()")
        wait("state.tables.resale.length === 1 && document.getElementById('szquality').value === '3'")
        js("document.getElementById('szdelete').click()")
        wait("document.getElementById('szpresets').options.length === 2")
        assert gui.Bridge().boot()['tracker_filters']['quality']==3
        mode[0]='compact'
        wait("!document.body.classList.contains('full') && document.getElementById('deals').textContent.includes('Зеркало')")
        report['advanced_filters_presets_reload_delete_compact']=True
        report['ok']=True
    except Exception as error:report['error']=str(error)
    finally:
        (root/'build/resale_tools_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        window.destroy()

with patch.object(bridge,'hud_action',side_effect=lambda action:actions.append(action)),patch.object(agent,'auction_listing',return_value=[]):
    webview.start(check,gui='edgechromium')
temp.cleanup()
report=json.loads((root/'build/resale_tools_ui.json').read_text(encoding='utf-8'))
print(json.dumps(report,ensure_ascii=True))
sys.exit(0 if report.get('ok') else 1)
