import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import webview
import stalzone_gui as gui
import stalzone_agent as agent
from stalzone_overlay import HudController

root = Path(__file__).resolve().parents[1]
(root / 'build').mkdir(exist_ok=True)
temp = tempfile.TemporaryDirectory()
agent.DIR = Path(temp.name)
bridge = gui.Bridge()
webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
window = webview.create_window('STALZONE integration check', html=gui.PAGE, js_api=bridge,
    width=520, height=380, min_size=(440,340), frameless=True, easy_drag=False,
    hidden=True, on_top=True, background_color='#12100e')
hud = HudController(window, agent.DIR / 'settings.json')
bridge._hud = hud
window.events.loaded += hud.start
window.events.closing += hud.closing
window.events.closed += hud.stop
report = {}

def wait_js(expr, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = window.evaluate_js(expr)
        if value: return value
        time.sleep(.2)
    raise AssertionError('Timeout: ' + expr)

def check():
    try:
        assert window.events.loaded.wait(25), 'WebView2 page not loaded'
        wait_js("Boolean(document.getElementById('quickmap').onclick)")
        deadline = time.monotonic() + 10
        while not hud.native and time.monotonic() < deadline: time.sleep(.1)
        # Deterministic controller foreground during DOM tests; style/place calls
        # still use the actual native WebView2 HWND.
        hud.native.foreground = lambda: hud.native.hwnd
        window.evaluate_js("window.testErrors=[]; window.addEventListener('unhandledrejection', e => window.testErrors.push(String(e.reason))); window.addEventListener('error', e => window.testErrors.push(e.message))")
        report['compact'] = window.evaluate_js("({full:document.body.classList.contains('full'),height:innerHeight,leaflet:typeof L})")
        assert report['compact']['full'] is False
        hud.command('full')
        wait_js("document.body.classList.contains('full')")
        report['native'] = hud.snapshot()
        window.evaluate_js("show('map')")
        wait_js("Boolean(state.wiki && state.pack)", 55)
        report['map'] = window.evaluate_js("({slug:state.mapSlug,tiles:document.querySelectorAll('.leaflet-tile').length,height:document.getElementById('wikimap').clientHeight,layers:Object.keys(state.wiki._layers).length})")
        assert report['map']['height'] > 200, report['map']
        wait_js("Boolean(document.querySelector('.leaflet-tile-loaded'))", 30)
        time.sleep(.4)
        from System.Drawing import Bitmap, Graphics
        x, y, width, height = hud.native.window_bounds()
        bitmap = Bitmap(width, height)
        graphics = Graphics.FromImage(bitmap)
        graphics.CopyFromScreen(x, y, 0, 0, bitmap.Size)
        bitmap.Save(str(root / 'build/map_hud_full.png'))
        graphics.Dispose()
        bitmap.Dispose()
        window.evaluate_js("window.savedMap = state.wiki; state.wiki.setZoom(state.wiki.getZoom()+1, {animate:false}); window.savedZoom=state.wiki.getZoom()")
        hud.command('compact')
        wait_js("!document.body.classList.contains('full')")
        hud.command('full')
        wait_js("document.body.classList.contains('full')")
        report['preserved'] = window.evaluate_js("({identity:state.wiki===window.savedMap,zoom:state.wiki.getZoom(),saved:window.savedZoom,tab:document.getElementById('v-map').classList.contains('on'),mode:document.body.className})")
        assert report['preserved']['identity'] and report['preserved']['tab'] and report['preserved']['zoom'] == report['preserved']['saved']
        window.evaluate_js('''window.mapRace = null; (async () => {
          const original = pywebview.api.wiki_map;
          const pack = state.pack;
          const pending = {};
          pywebview.api.wiki_map = slug => new Promise(resolve => pending[slug] = resolve);
          const first = openWiki('south-zone'), second = openWiki('north-zone');
          pending['north-zone']({...pack, slug:'north-zone'});
          await second;
          pending['south-zone']({...pack, slug:'south-zone'});
          await first;
          pywebview.api.wiki_map = original;
          window.mapRace = {ok:state.pack.slug === state.mapSlug, pack:state.pack.slug, selected:state.mapSlug};
        })(); null''')
        report['map_race'] = wait_js('window.mapRace')
        assert report['map_race']['ok'], 'Older request overwrote the selected map'
        window.evaluate_js("state.placing=true; document.getElementById('markname').value='HUD check'; state.wiki.fire('click', {latlng:state.wiki.getCenter()}); null")
        wait_js("state.mine.some(m => m.title==='HUD check')")
        report['personal_mark'] = gui.Bridge()._marks_of('north-zone')[0]['title']
        assert report['personal_mark'] == 'HUD check'
        report['native_style'] = int(hud.native.u.GetWindowLongPtrW(hud.native.hwnd, -20))
        hud.command('passive')
        time.sleep(.5)
        report['passive_style'] = int(hud.native.u.GetWindowLongPtrW(hud.native.hwnd, -20))
        assert report['passive_style'] & 0x08000020 == 0x08000020
        report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
        report['ui_errors'] = window.evaluate_js('window.testErrors')
        report['mark_state'] = window.evaluate_js("({placing:state.placing,slug:state.mapSlug,pack:state.pack?.slug,mine:state.mine})")
        report['mark_file'] = bridge._load_marks()
    finally:
        (root / 'build/map_hud_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        hud.stop()
        window.destroy()

webview.start(check, gui='edgechromium')
temp.cleanup()
print(json.dumps(report,ensure_ascii=True))
sys.exit(0 if report.get('ok') else 1)
