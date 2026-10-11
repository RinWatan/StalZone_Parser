"""Evidence labels for auction price estimates."""
import math
import time


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
