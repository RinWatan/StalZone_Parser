"""Local resale filters and explanations; no network or account access."""
import hashlib
import json
import math

CATEGORIES = {'all':'Все категории','artefact':'Артефакты','weapon':'Оружие',
    'armor':'Броня','attachment':'Обвесы','containers':'Контейнеры','bullet':'Патроны',
    'grenade':'Гранаты','medicine':'Медицина','misc':'Разное','other':'Прочее',
    'supply':'Припасы','backpacks':'Рюкзаки','device':'Устройства',
    'weapon_modules':'Модули оружия','drink':'Напитки','food':'Еда'}
DEFAULT_FILTERS = {'min_profit':100000,'min_roi':10,'category':'all','quality':None,
    'refine_min':0,'refine_max':15,'explored':'all','include':'','exclude':'',
    'max_cost':0,'verified_only':False}


def number(value):
    if isinstance(value,bool):return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (TypeError,ValueError,OverflowError):return None


def filters(settings):
    if not isinstance(settings,dict):raise ValueError('Некорректные фильтры')
    out=dict(DEFAULT_FILTERS,**{k:v for k,v in settings.items() if k in DEFAULT_FILTERS})
    for k in ('min_profit','min_roi','max_cost','refine_min','refine_max'):
        value=number(out[k])
        if value is None or value<0:raise ValueError('Нужны неотрицательные числа')
        out[k]=value
    for k in ('refine_min','refine_max'):
        if out[k]!=int(out[k]) or out[k]>15:raise ValueError('Заточка: целое от 0 до 15')
        out[k]=int(out[k])
    if out['refine_min']>out['refine_max']:raise ValueError('Минимальная заточка больше максимальной')
    if out['category'] not in CATEGORIES:raise ValueError('Неизвестная категория')
    if out['quality'] in ('',None):out['quality']=None
    else:
        q=number(out['quality'])
        if q is None or q!=int(q) or not 0<=q<=6:raise ValueError('Неизвестная редкость')
        out['quality']=int(q)
    if out['explored'] not in ('all','explored','unexplored'):raise ValueError('Неизвестный статус изученности')
    if not isinstance(out['verified_only'],bool):raise ValueError('Некорректный флаг проверки EXBO')
    for k in ('include','exclude'):
        if not isinstance(out[k],str) or len(out[k])>500:raise ValueError('Список названий: не более 500 символов')
        out[k]=out[k].strip()
    return out


def matches(row, f, now, ttl=45):
    if f['category']!='all' and row.get('category','other')!=f['category']:return False
    if f['quality'] is not None and row.get('qlt')!=f['quality']:return False
    if (f['refine_min'],f['refine_max'])!=(0,15):
        if row.get('qlt') is None and row.get('ptn') is None:return False
        if not f['refine_min']<=int(row.get('ptn') or 0)<=f['refine_max']:return False
    if f['explored']!='all':
        desired=f['explored']=='explored'
        if row.get('explored') is not desired:return False
    if f['max_cost']>0 and row['cost']>f['max_cost']:return False
    if f['verified_only'] and not (row.get('available') is True and
            0<=now-(row.get('availability_at') or 0)<=ttl):return False
    name=row['name'].casefold().replace('ё','е')
    def terms(text):return [s.strip().casefold().replace('ё','е') for s in text.replace('\n',',').split(',') if s.strip()]
    included,excluded=terms(f['include']),terms(f['exclude'])
    return (not included or any(s in name for s in included)) and not any(s in name for s in excluded)


def metadata(row, period):
    category=row.get('category')
    if category not in CATEGORIES or category=='all':category='other'
    studied=row.get('explored')
    charge=number(row.get('charge'))
    if charge is not None and not 0<=charge<=100:charge=None
    info=row.get('defaultBonusInfo')
    base=[]
    for b in (info.get('defaultBonuses') or [])[:20] if isinstance(info,dict) and isinstance(info.get('defaultBonuses'),list) else []:
        if not isinstance(b,dict):continue
        label=str(b.get('bonusName') or '').strip()[:120]
        value=str(b.get('textMinAndMax') or 'значение неизвестно').strip()[:160]
        if label:base.append(f'{label}: {value}')
    extra=row.get('bonusInfo')
    bonuses=[s[:180] for s in extra[:20] if isinstance(s,str)] if isinstance(extra,list) else []
    stats=row.get('metrics')
    stats=stats if isinstance(stats,dict) else {}
    periods=stats.get('periods')
    selected=periods.get(period.replace('д','d')) if isinstance(periods,dict) else None
    selected=selected if isinstance(selected,dict) else stats
    values={k:number(selected.get(k)) for k in ('median','mean','weightedMean')}
    return {'category':category,'explored':studied if isinstance(studied,bool) else None,
            'charge':charge,'base_bonuses':base,'bonuses':bonuses,'statistics':values}


def row_id(row):
    key=[row.get(k) for k in ('slug','source_id','name','cost','amount','qlt','ptn','received_at')]
    return hashlib.sha256(json.dumps(key,ensure_ascii=False).encode('utf-8')).hexdigest()[:24]


def detail(row, now, ttl=45):
    target=row['target_price'];net=math.floor(target*.95);profit=net-row['cost']
    studied=row.get('explored')
    attrs=[f"Категория: {CATEGORIES.get(row.get('category'),'неизвестна')}",
           'Изученность: '+('изучен' if studied is True else 'не изучен' if studied is False else 'неизвестна'),
           f"Качество: {row.get('quality_label') or 'неизвестно'}",
           'Заряд: '+(f"{row['charge']:g}%" if row.get('charge') is not None else 'неизвестен')]
    attrs+=row.get('base_bonuses') or ['Базовые характеристики: данные не переданы']
    attrs+=['Доп. характеристика: '+s for s in row.get('bonuses') or []]
    if not row.get('bonuses'):attrs.append('Доп. характеристики: данные не переданы')
    period=row.get('estimate_period') or 'период не указан';count=row.get('estimate_samples') or 0
    basis=[f'Цена продажи — оценка SZ: {period}, сделок в выборке: {count}.',
           'Расчёт для всей пачки: цена продажи × 95% (округление вниз) − цена покупки.',
           'Плюс и рентабельность — расчётный сценарий, не обещание продажи.']
    for k,label in (('median','Медиана'),('mean','Среднее'),('weightedMean','Взвешенное среднее')):
        value=(row.get('statistics') or {}).get(k)
        if value is not None:basis.append(f'{label} SZ за штуку: {value:,.0f}'.replace(',',' '))
    warnings=[]
    if count<3:warnings.append('Мало данных: оценка опирается менее чем на 3 сделки либо число сделок неизвестно.')
    elif count<10:warnings.append('Небольшая выборка: отдельные сделки заметно влияют на оценку.')
    if period!='7д':warnings.append('Период шире 7 дней либо неизвестен: старые цены могут отличаться от текущих.')
    sales=row.get('sales_per_day')
    basis.append(f'Продаж в сутки SZ: {sales:g}.' if sales is not None else 'Скорость продаж SZ не передана — она неизвестна.')
    if sales is not None and sales<1:warnings.append('Редкие продажи: перепродажа может потребовать длительного ожидания.')
    if row.get('qlt') is not None:
        warnings.append('EXBO сравнивает редкость, заточку, количество и цену; случайные характеристики артефакта могут различаться.')
    if studied is False and row.get('category')=='artefact':warnings.append('Артефакт не изучен: часть характеристик неизвестна.')
    if now-row['received_at']>1800:warnings.append('Наблюдение старше 30 минут: оценка SZ могла измениться.')
    context=row.get('exbo_context') or {}
    checked=context.get('checked_at') or 0
    competition=[]
    if checked and 0<=now-checked<=ttl:
        minimum=context.get('cheapest_unit')
        competition.append(f"Проверено предложений того же варианта: {context.get('variant_lots',0)}.")
        if minimum is not None:competition.append(f'Минимум в выборке: {minimum:,.0f} за штуку.'.replace(',',' '))
        cheaper=context.get('cheaper_lots',0)
        competition.append(f'Предложений дешевле за штуку: {cheaper}.')
        if cheaper:warnings.append('В проверенной выборке есть предложения дешевле; учтите различия характеристик и размеров пачек.')
        if context.get('limited'):competition.append('Выборка ограничена первыми 800 лотами; остальной рынок не проверен.')
        competition.append('Это сравнение по редкости и заточке, без подтверждения одинаковых случайных свойств.')
    else:competition.append('Данные EXBO о конкурентах устарели.' if checked else 'Конкуренты EXBO ещё не проверены.')
    availability=row.get('availability') or 'Не проверено'
    availability_at=row.get('availability_at') or 0
    if availability_at and not 0<=now-availability_at<=ttl:availability='Проверка наличия EXBO устарела'
    return {'ok':True,'id':row_id(row),'name':row['name'],'attributes':attrs,'basis':basis,
        'warnings':warnings,'competition':competition,'availability':availability,
        'received_at':row['received_at'],'checked_at':checked,
        'calculation':{'cost':row['cost'],'target':target,'net':net,'fee':target-net,
                       'profit':profit,'roi':profit/row['cost']*100,'amount':row['amount']}}
