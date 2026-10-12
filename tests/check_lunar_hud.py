import json
import sys
import tempfile
import time
import traceback
from unittest.mock import patch
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
# Public map cache is reusable; personal marks remain in temporary storage.
import stalzone_lunar as lunar
lunar_load = lunar.load
lunar.load = lambda folder, slug: lunar_load(root / 'build/lunar_test_cache', slug)
bridge = gui.Bridge()
webview.settings['DRAG_REGION_DIRECT_TARGET_ONLY'] = True
window = webview.create_window('STALZONE integration check', html=gui.PAGE, js_api=bridge,
    width=520, height=380, min_size=(440,340), frameless=True, easy_drag=False,
    hidden=True, on_top=True, background_color='#12100e')
hud = HudController(window, agent.DIR / 'settings.json')
bridge._hud = hud
def start_hud():
    # DOM tests do not reserve the hotkey used by the user's running overlay.
    with patch('stalzone_overlay.GlobalHotkey') as hotkey:
        hotkey.return_value.registered = True
        hud.start()
window.events.loaded += start_hud
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
        window.evaluate_js("window.savedCatalog=pywebview.api.lunar_catalog; pywebview.api.lunar_catalog=()=>Promise.resolve([]); show('map'); null")
        wait_js("document.getElementById('mapstatus').textContent.includes('Лунар не отдал карты')")
        assert window.evaluate_js("!state.mapBooted"), 'Failed catalogue cannot be retried'
        window.evaluate_js("pywebview.api.lunar_catalog=window.savedCatalog; show('map'); null")
        wait_js("Boolean(state.wiki && state.pack && state.pack.lunar)", 180)
        report['map'] = window.evaluate_js("({slug:state.mapSlug,tiles:document.querySelectorAll('.leaflet-tile').length,height:document.getElementById('wikimap').clientHeight,layers:Object.keys(state.wiki._layers).length})")
        assert report['map']['height'] > 200, report['map']
        wait_js("Array.from(document.querySelectorAll('.leaflet-image-layer')).some(i => i.naturalWidth > 0 && i.src.includes('/z'))", 40)
        assert window.evaluate_js("state.marks.getLayers().length > 0")
        report['lunar'] = window.evaluate_js("({markers:state.pack.markers.length,categories:state.pack.categories.length,detailTiles:Object.keys(state.ground).length,shown:state.marks.getLayers().length})")
        window.evaluate_js("state.wiki.setZoom(0,{animate:false}); null")
        wait_js("state.groundLevel === 0")
        wait_js("Array.from(document.querySelectorAll('.leaflet-image-layer')).some(i => i.naturalWidth > 0 && i.src.includes('/z0/'))",40)
        report['zoom_detail'] = True
        window.evaluate_js("document.querySelector('#maplayers button[data-cat]').click(); null")
        assert window.evaluate_js("Object.values(state.hidden).some(Boolean)")
        window.evaluate_js("document.getElementById('mapq').value='impossible-search-token'; paintLunar(); null")
        assert window.evaluate_js("state.marks.getLayers().length === 0")
        window.evaluate_js("document.getElementById('mapq').value=''; paintLunar(); null")
        report['layers_search'] = True
        time.sleep(.4)
        from System.Drawing import Bitmap, Graphics
        x, y, width, height = hud.native.window_bounds()
        bitmap = Bitmap(width, height)
        graphics = Graphics.FromImage(bitmap)
        graphics.CopyFromScreen(x, y, 0, 0, bitmap.Size)
        bitmap.Save(str(root / 'build/lunar_hud_full.png'))
        graphics.Dispose()
        bitmap.Dispose()
        window.evaluate_js("window.savedMap = state.wiki; state.wiki.setZoom(state.wiki.getZoom()+1, {animate:false}); window.savedZoom=state.wiki.getZoom()")
        hud.command('compact')
        wait_js("!document.body.classList.contains('full')")
        hud.command('full')
        wait_js("document.body.classList.contains('full')")
        report['preserved'] = window.evaluate_js("({identity:state.wiki===window.savedMap,zoom:state.wiki.getZoom(),saved:window.savedZoom,tab:document.getElementById('v-map').classList.contains('on'),mode:document.body.className})")
        assert report['preserved']['identity'] and report['preserved']['tab'] and report['preserved']['zoom'] == report['preserved']['saved']
        hud.command('passive')
        wait_js("!document.body.classList.contains('full')")
        hud.command('toggle')
        wait_js("document.body.classList.contains('full')")
        report['mode_restored'] = window.evaluate_js("state.wiki === window.savedMap && state.wiki.getZoom() === window.savedZoom && document.getElementById('v-map').classList.contains('on')")
        assert report['mode_restored']
        window.evaluate_js('''window.mapRace = null; (async () => {
          const original = pywebview.api.lunar_map;
          const pack = state.pack;
          const pending = {};
          pywebview.api.lunar_map = slug => new Promise(resolve => pending[slug] = resolve);
          const first = openLunar('test-old'), second = openLunar('test-new');
          pending['test-new']({...pack, slug:'test-new'});
          await second;
          pending['test-old']({...pack, slug:'test-old'});
          await first;
          pywebview.api.lunar_map = original;
          window.mapRace = {ok:state.pack.slug === state.mapSlug, pack:state.pack.slug, selected:state.mapSlug};
        })(); null''')
        report['map_race'] = wait_js('window.mapRace')
        assert report['map_race']['ok'], 'Older request overwrote the selected map'
        window.evaluate_js("state.placing=true; document.getElementById('markname').value='HUD check'; state.wiki.fire('click', {latlng:state.wiki.getCenter()}); null")
        wait_js("state.mine.some(m => m.title==='HUD check')")
        report['personal_mark'] = gui.Bridge()._marks_of('test-new')[0]['title']
        assert report['personal_mark'] == 'HUD check'
        mine=bridge._marks_of('test-new')
        bridge.delete_mark('test-new',mine[0]['id'])
        assert not bridge._marks_of('test-new')
        report['personal_mark_deleted']=True
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
        (root / 'build/lunar_hud_check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        hud.stop()
        window.destroy()

webview.start(check, gui='edgechromium')
temp.cleanup()
print(json.dumps(report,ensure_ascii=True))
sys.exit(0 if report.get('ok') else 1)
