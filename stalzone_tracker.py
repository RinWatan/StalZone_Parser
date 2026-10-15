"""Public Free feed supplies candidates; only EXBO supplies verified deals."""
import json
import math
import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

FEED_URL = 'wss://sztracker.ru/ws/lots?lang=ru&region=RU'
CANDIDATE_TTL = 180
RESULT_TTL = 45
REFRESH_AFTER = 20


@dataclass(frozen=True)
class Candidate:
    slug: str
    name: str
    amount: int
    cost: int
    qlt: int | None
    ptn: int | None
    source_id: str
    received_at: float
    priority: float
    target_price: float = 0
    unsupported: bool = False

    @property
    def variant(self):
        return None if self.qlt is None and self.ptn is None else (self.qlt or 0, self.ptn or 0)

    @property
    def identity(self):
        return (self.slug, self.source_id, self.cost, self.amount, self.qlt, self.ptn)


def candidate(row, budget, now, display_only=False):
    if not isinstance(row, dict):
        return None
    unsupported = bool(row.get('module') or row.get('contents'))
    if unsupported and not display_only:
        return None
    try:
        name = str(row.get('name') or '').strip()[:180]
        slug = str(row.get('itemId') or '')
        if not re.fullmatch(r'[a-z0-9]{3,12}', slug):
            slug = {'протоартефакт': 'dm6l2'}.get(name.casefold(), '')
        if not slug or row.get('uniqueId') is None or not name:
            return None
        price = float(row.get('cost') or 0)
        amount = int(row.get('amount') or 0)
        quality, point = row.get('qlt'), row.get('ptn')
        quality = None if quality is None else int(quality)
        point = None if point is None else int(point)
        if quality is not None and not 0 <= quality <= 6:
            return None
        if point is not None and not 0 <= point <= 15:
            return None
        if not math.isfinite(price) or price <= 0 or price != int(price) or amount <= 0:
            return None
        if budget > 0 and price > budget:
            return None
        target = float(row.get('targetPrice') or 0)
        # targetPrice is the resale estimate for the WHOLE lot (including stacks).
        target = target if math.isfinite(target) and target > 0 else 0
        expected = max(0, target * .95 - price)
        return Candidate(slug, name, amount, int(price), quality, point,
                         str(row['uniqueId']), now, expected, target, unsupported)
    except (ValueError, TypeError, OverflowError):
        return None


class Candidates:
    """Called under the engine lock; bounded by items and identities."""
    def __init__(self, budget, max_items=128):
        self.budget, self.max_items = budget, max_items
        self.active = OrderedDict()
        self.pending = set()
        self.seen = OrderedDict()
        self.received = self.skipped = self.duplicates = 0

    def ingest(self, message, now):
        if not isinstance(message, dict) or message.get('type') not in ('snapshot', 'lots_update'):
            return
        rows = message.get('data')
        if not isinstance(rows, list):
            raise ValueError('Изменился формат ленты')
        self.prune(now)
        for row in rows[:5000]:
            self.received += 1
            # Display valid source observations even when our verifier cannot use them.
            item = candidate(row, 0, now, display_only=True)
            if item is None:
                self.skipped += 1
                continue
            if item.identity in self.seen:
                self.duplicates += 1
                continue
            self.seen[item.identity] = now
            group = [c for c in self.active.get(item.slug, []) if c.identity != item.identity]
            self.active[item.slug] = (group + [item])[-32:]
            self.active.move_to_end(item.slug)
            if self.eligible(item):
                self.pending.add(item.slug)
            while len(self.active) > self.max_items:
                slug, _ = self.active.popitem(last=False)
                self.pending.discard(slug)
                self.skipped += 1
            while len(self.seen) > 10000:
                self.seen.popitem(last=False)

    def prune(self, now):
        for slug, rows in list(self.active.items()):
            rows = [c for c in rows if 0 <= now-c.received_at <= CANDIDATE_TTL]
            if rows:
                self.active[slug] = rows
            else:
                self.active.pop(slug, None)
                self.pending.discard(slug)
        while self.seen and now-next(iter(self.seen.values())) > 300:
            self.seen.popitem(last=False)

    def queued(self):
        return len(self.pending)

    def eligible(self, item):
        return not item.unsupported and (self.budget <= 0 or item.cost <= self.budget)

    def take(self, now, cooldowns=None):
        self.prune(now)
        cooldowns = cooldowns or {}
        slugs = [s for s in self.pending if cooldowns.get(s, 0) <= now
                 and any(self.eligible(c) for c in self.active[s])]
        if not slugs:
            return []
        slug = max(slugs, key=lambda s: max(c.priority for c in self.active[s] if self.eligible(c)))
        self.pending.discard(slug)
        return [c for c in self.active[slug] if self.eligible(c)]

class Verifier:
    def __init__(self, api, clock=time.time):
        self.api, self.clock = api, clock
        self.history = OrderedDict()
        self.outcomes = {}

    def check(self, candidates):
        api = self.api
        self.outcomes = {c.identity:'Проверка EXBO прервана' for c in candidates}
        if not candidates or api.HALT.is_set():
            return []
        slug, name = candidates[0].slug, candidates[0].name
        now = self.clock()
        fetched = api.live_lots(slug, pages=4)
        if api.HALT.is_set():
            return []
        lots = []
        wanted = {(c.variant, c.amount, c.cost) for c in candidates}
        matched = set()
        for lot in fetched:
            try:
                amount, price = int(lot.get('amount') or 0), int(lot.get('buyoutPrice') or 0)
                add = lot.get('additional') or {}
                if amount <= 0 or price <= 0 or add.get('personal_on_get'):
                    continue
                if lot.get('endTime') and api._epoch(lot['endTime']) <= now:
                    continue
                signature = (api.side_key(add), amount, price)
                lots.append(lot)
                if signature in wanted:
                    matched.add(signature)
            except (ValueError, TypeError):
                continue
        if not matched:
            self.outcomes = {c.identity:'EXBO: лот не найден среди первых 800 предложений'
                             for c in candidates}
            return []
        self.outcomes = {c.identity:('EXBO: не прошёл расчёт выгоды, конкуренции или ликвидности'
                         if (c.variant,c.amount,c.cost) in matched else 'EXBO: лот не найден среди первых 800 предложений')
                         for c in candidates}
        cached = self.history.get(slug)
        if cached is None or not 0 <= now-cached[0] < 120:
            if api.HALT.is_set():
                return []
            raw = api.get_json(f'{api.EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset=0')
            sales = {}
            for row in raw.get('prices') or []:
                try:
                    amount, price = int(row.get('amount') or 0), float(row.get('price') or 0)
                    ts = api._epoch(row.get('time'))
                    if amount <= 0 or not math.isfinite(price) or price <= 0 or not 0 < ts <= self.clock():
                        continue
                    sales.setdefault(api.side_key(row.get('additional')), []).append((amount, price/amount, ts))
                except (ValueError, TypeError, OverflowError):
                    continue
            self.history[slug] = (self.clock(), sales)
            self.history.move_to_end(slug)
            while len(self.history) > 128:
                self.history.popitem(last=False)
        else:
            sales = cached[1]
        if api.HALT.is_set():
            return []
        current = self.clock()
        if not 0 <= current-now <= RESULT_TTL:
            self.outcomes = {c.identity:'EXBO: проверка заняла более 45с, нужно обновление' for c in candidates}
            return []
        lots = [lot for lot in lots if not lot.get('endTime') or api._epoch(lot['endTime']) > current]
        matched = {(api.side_key(lot.get('additional')),int(lot['amount']),int(lot['buyoutPrice']))
                   for lot in lots} & wanted
        for c in candidates:
            if (c.variant,c.amount,c.cost) not in matched:
                self.outcomes[c.identity] = 'EXBO: лот не найден или истёк'
            elif not any(a == c.amount for a, _, _ in sales.get(c.variant, [])):
                self.outcomes[c.identity] = 'EXBO: нет истории продаж такой пачки и варианта'
        rows = api.find_flips({'sales': sales}, slug, name, allow_single=True, lots=lots, limit=None)
        confirmed = []
        for row in rows:
            variant = None if row['qlt_i'] is None else (row['qlt_i'], int(row['ptn'].lstrip('+')))
            if (variant, row['amount'], row['buyout']) not in matched:
                continue
            # A full last page may cut off equal-priced competing offers.
            if len(fetched) >= 800 and row['buyout'] >= int(fetched[-1].get('buyoutPrice') or 0):
                for c in candidates:
                    if (c.variant,c.amount,c.cost) == (variant,row['amount'],row['buyout']):
                        self.outcomes[c.identity] = 'EXBO: неполный ценовой уровень, выгода не подтверждена'
                continue
            for c in candidates:
                if (c.variant,c.amount,c.cost) == (variant,row['amount'],row['buyout']):
                    self.outcomes[c.identity] = ('EXBO: мало данных — проверь рынок'
                        if (row.get('confidence') or {}).get('level') == 'low' else 'EXBO: расчёт пройден; отбор по бюджету — Выкуп')
            confirmed.append(dict(row, source='SZ Tracker → EXBO', verified_at=now))
        return api._as_buys(confirmed)


class TrackerFeed:
    def __init__(self, api, budget, on_update, on_state, connect=None, clock=time.time):
        self.api, self.budget, self.clock = api, budget, clock
        self.on_update, self.on_state = on_update, on_state
        self.pool, self.verifier = Candidates(budget), Verifier(api, clock)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.socket = None
        self.connect = connect or self._connect
        self.connected = self.stale = False
        self.phase = 'Подключение'
        self.last_message = 0
        self.checked = 0
        self.cooldowns, self.last_check, self.results = {}, {}, {}
        self.outcomes = {}

    @staticmethod
    def _connect():
        import websocket
        ws = websocket.create_connection(FEED_URL, timeout=10)
        ws.settimeout(1)
        return ws

    def ingest(self, message):
        with self.lock:
            self.last_message = self.clock()
            if isinstance(message, dict) and message.get('type') == 'sourceStatus':
                self.stale = bool(message.get('stale'))
            else:
                self.pool.ingest(message, self.clock())

    def report(self):
        with self.lock:
            now = self.clock()
            self.pool.prune(now)
            active = [c for group in self.pool.active.values() for c in group]
            identities = {c.identity for c in active}
            self.outcomes = {k:v for k,v in self.outcomes.items() if k in identities}
            feed_rows = []
            for c in sorted(active, key=lambda c:c.received_at, reverse=True):
                status, checked_at = self.outcomes.get(c.identity, ('В очереди EXBO',0))
                if c.unsupported:
                    status = 'Только SZ: лот с модулями/содержимым, проверка не поддерживается'
                elif self.budget > 0 and c.cost > self.budget:
                    status = 'Выше бюджета — только просмотр SZ'
                elif not self.connected:
                    status = 'SZ отключён — дождитесь подключения'
                elif self.stale:
                    status = 'SZ: источник сообщает об устаревших данных'
                elif checked_at and now-checked_at > RESULT_TTL:
                    status = 'Проверка EXBO устарела — ожидает обновления'
                feed_rows.append({'name':c.name,'slug':c.slug,'amount':c.amount,'cost':c.cost,
                                  'qlt':c.qlt,'ptn':c.ptn,'target_price':c.target_price,
                                  'received_at':c.received_at,'status':status})
            state = {'phase': 'Источник сообщает об устаревших данных' if self.stale else self.phase,
                     'connected':self.connected,'stale':self.stale,'received':self.pool.received,
                     'checked':self.checked,'queue':self.pool.queued(),'skipped':self.pool.skipped,
                     'duplicates':self.pool.duplicates,'last_message':self.last_message,'running':True,
                     'feed_rows':feed_rows}
        if not self.stop.is_set():
            self.on_state(state)

    def _reader(self):
        import websocket
        delay = 5
        while not self.stop.is_set() and not self.api.HALT.is_set():
            ws = None
            started = self.clock()
            try:
                ws = self.connect()
                with self.lock:
                    self.socket = ws
                    self.connected = True
                    self.stale = False
                    self.phase = 'Подключена'
                self.report()
                while not self.stop.is_set() and not self.api.HALT.is_set():
                    try:
                        payload = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not payload:
                        raise ConnectionError('Лента закрыта')
                    if len(payload) > 4*1024*1024:
                        raise ValueError('Слишком большое сообщение')
                    self.ingest(json.loads(payload))
                    self.report()
            except Exception as error:
                with self.lock:
                    self.phase = f'Переподключение через {delay}с ({type(error).__name__})'
            finally:
                with self.lock:
                    self.connected = False
                    self.socket = None
                self.report()
                if ws is not None:
                    try:
                        ws.close(timeout=1)
                    except Exception:
                        pass
            if self.clock()-started > 30:
                delay = 5
            if self.stop.wait(delay):
                break
            delay = min(60, delay*2)

    def visible(self, now):
        with self.lock:
            usable = self.connected and not self.stale
            active = set(self.pool.active)
        rows = [r for slug, group in self.results.items() if slug in active for r in group
                if 0 <= now-r['verified_at'] <= RESULT_TTL] if usable else []
        return self.api.fit_budget(rows, self.budget)

    def run(self):
        reader = threading.Thread(target=self._reader, daemon=True)
        reader.start()
        last_state, previous = 0, None
        try:
            while not self.api.HALT.is_set():
                now = self.clock()
                with self.lock:
                    self.pool.prune(now)
                    for slug in list(self.results):
                        if slug in self.pool.active and now-self.last_check.get(slug, 0) >= REFRESH_AFTER:
                            self.pool.pending.add(slug)
                    ready = self.connected and not self.stale
                    batch = self.pool.take(now, self.cooldowns) if ready else []
                if batch:
                    slug = batch[0].slug
                    with self.lock:
                        for c in batch:
                            self.outcomes[c.identity] = ('Проверяется в EXBO',0)
                    self.report()
                    try:
                        rows = self.verifier.check(batch)
                        with self.lock:
                            for c in batch:
                                self.outcomes[c.identity] = (self.verifier.outcomes.get(c.identity,'EXBO: проверка завершена'),now)
                        self.checked += 1
                        self.last_check[slug] = self.clock()
                        self.results[slug] = rows
                    except Exception as error:
                        self.results.pop(slug, None)
                        code = getattr(getattr(error, 'response', None), 'status_code', None)
                        if code in (401, 403):
                            raise RuntimeError('EXBO отклонил API-ключ') from None
                        self.cooldowns[slug] = self.clock() + (300 if code in (400, 404) else 30)
                        with self.lock:
                            for c in batch:
                                self.outcomes[c.identity] = (f'EXBO: ошибка {code or type(error).__name__}, повтор позже',self.clock())
                            if slug in self.pool.active:
                                self.pool.pending.add(slug)
                    with self.lock:
                        active = set(self.pool.active)
                    self.cooldowns = {s:t for s,t in self.cooldowns.items() if s in active}
                    self.last_check = {s:t for s,t in self.last_check.items() if s in active}
                    self.results = {s:r for s,r in self.results.items() if s in active}
                shown = self.visible(self.clock())
                signature = repr(shown)
                if signature != previous:
                    self.on_update(shown)
                    previous = signature
                if self.clock()-last_state >= 1:
                    self.report()
                    last_state = self.clock()
                if not batch:
                    self.stop.wait(.2)
        finally:
            self.stop.set()
            with self.lock:
                ws = self.socket
            if ws is not None:
                try:
                    ws.close(timeout=1)
                except Exception:
                    pass
            reader.join(2)
            self.on_update([])
