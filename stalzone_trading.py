"""Evidence labels and local, opt-in auction price alerts."""
import hashlib
import json
import math
import statistics
import threading
import time
import uuid
from datetime import datetime


def confidence(samples, now=None):
    now = time.time() if now is None else now
    recent = [(float(p), float(ts)) for p, ts in samples
              if math.isfinite(p) and math.isfinite(ts) and p > 0 and 0 <= now-ts <= 12*3600]
    values = sorted(p for p, _ in recent)
    count = len(values)
    age = (now-max(ts for _, ts in recent))/60 if recent else None
    spread = (values[math.ceil((count-1)*.9)] / values[math.floor((count-1)*.1)]) if count else None
    level = 'low'
    if count >= 12 and age <= 30 and spread <= 1.35:
        level = 'high'
    elif count >= 6 and age <= 120 and spread <= 2:
        level = 'medium'
    label = {'high':'Высокая', 'medium':'Средняя', 'low':'Недостаточно данных'}[level]
    detail = f'{label} · {count} продаж в выборке за 12ч'
    if count:
        detail += f' · разброс P90/P10 ×{spread:.2f} · последняя {age:.0f} мин назад'
    return {'level':level,'label':label,'count':count,'spread':spread,'age_minutes':age,'detail':detail}


class HuntStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._seen = {}
        try:
            raw = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raw = []
        self._rules = []
        for row in raw if isinstance(raw,list) else []:
            try:
                rule = self._validate(row['slug'],row['name'],row.get('qlt'),row['lo'],row['hi'],row['max_unit'])
                rule['id'] = str(row['id'])
                self._rules.append(rule)
            except (KeyError, TypeError, ValueError):
                continue
        self._rules = self._rules[:10]

    @staticmethod
    def _validate(slug,name,qlt,lo,hi,max_unit):
        lo,hi,max_unit=int(lo),int(hi),float(max_unit)
        qlt = None if qlt is None else int(qlt)
        if not slug or not math.isfinite(max_unit) or max_unit <= 0 or not 0 <= lo <= hi <= 15:
            raise ValueError('Проверь цену и диапазон заточки 0–15')
        if qlt is not None and not 0 <= qlt <= 6:
            raise ValueError('Неверная редкость')
        return {'slug':str(slug),'name':str(name),'qlt':qlt,'lo':lo,'hi':hi,'max_unit':max_unit}

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self._rules,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.path)

    def rules(self):
        with self.lock:
            return [dict(rule) for rule in self._rules]

    def add(self,slug,name,qlt,lo,hi,max_unit):
        rule=self._validate(slug,name,qlt,lo,hi,max_unit)
        with self.lock:
            if len(self._rules)>=10:
                raise ValueError('Можно следить максимум за 10 условиями')
            for saved in self._rules:
                if all(saved[k]==v for k,v in rule.items()):
                    return dict(saved)
            rule['id']=uuid.uuid4().hex
            previous=list(self._rules)
            self._rules.append(rule)
            try:
                self._save()
            except OSError:
                self._rules=previous
                raise
        return dict(rule)

    def remove(self,rule_id):
        with self.lock:
            previous=list(self._rules)
            self._rules=[r for r in self._rules if r['id']!=rule_id]
            try:
                self._save()
            except OSError:
                self._rules=previous
                raise
            self._seen.pop(rule_id,None)

    def evaluate(self,slug,lots,now=None):
        now=time.time() if now is None else now
        alerts=[]
        with self.lock:
            for rule in self._rules:
                if rule['slug']!=slug:
                    continue
                matches={}
                for lot in lots:
                    try:
                        buy,amount=int(lot.get('buyoutPrice') or 0),int(lot.get('amount') or 0)
                        add=lot.get('additional') or {}
                        quality=add.get('qlt')
                        point=int(add.get('ptn') or 0)
                        if buy<=0 or amount<=0 or add.get('personal_on_get'):
                            continue
                        if lot.get('endTime'):
                            end=datetime.fromisoformat(str(lot['endTime']).replace('Z','+00:00'))
                            if end.tzinfo is None or end.timestamp()<=now:
                                continue
                        if rule['qlt'] is not None and quality!=rule['qlt']:
                            continue
                        if quality is not None and not rule['lo']<=point<=rule['hi']:
                            continue
                        if buy/amount>rule['max_unit']:
                            continue
                        identity={k:lot.get(k) for k in ('id','lotId','itemId','startTime','endTime','amount','buyoutPrice','additional')}
                        fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
                        matches[fingerprint]={'name':rule['name'],'slug':slug,'unit':buy/amount,
                                              'buyout':buy,'amount':amount,'qlt':quality,'ptn':point,
                                              'rule_id':rule['id'],'time':now}
                    except (ValueError, TypeError, OverflowError):
                        continue
                seen=self._seen.get(rule['id'],set())
                alerts.extend(v for key,v in matches.items() if key not in seen)
                self._seen[rule['id']]=set(matches)
        return sorted(alerts,key=lambda r:r['unit'])
