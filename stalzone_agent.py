# -*- coding: utf-8 -*-
"""STALZONE агент. Цены и список предметов только из официальных данных EXBO."""
import argparse
import json
import statistics
import sys
import threading
import time
import traceback
import zipfile
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


DIR = app_dir()
EXBO = "https://eapi.stalzone.com"
DB_ZIP = "https://codeload.github.com/EXBO-Studio/stalzone-database/zip/refs/heads/main"
HTML = DIR / "stalzone_agent.html"
TXT = DIR / "stalzone_agent.txt"
LOG = DIR / "stalzone_agent.log"
BUY_HTML = DIR / "buy_now.html"
COMM = 0.95
UA = "stalzone-agent/1.0"
MSK = timezone(timedelta(hours=3))
HALT = threading.Event()
WORKERS = 4
AUCTION_WORKERS = 8
_LOG_LOCK = threading.Lock()
_HIST = {}
_HIST_LOCK = threading.Lock()
BUDGET = 5_000_000
BUY_AT = 0.85


# Дорогой бартер: фиолетовый (ветеран) и красный (мастер), север и Любеч.
BARTER_FARM = [
    ("7l127", "Аномальная пыль"),
    ("z301y", "Цветущий северный мох"),
    ("gn956", "Камень Жмых-Вжух-Плюх"),
    ("z30my", "Цветущий рыжий папоротник"),
    ("z3ogm", "Расцветший Горьколистник"),
    ("gnpr5", "Темный Лимб"),
    ("4k3qo", "Концентрированная лимбоплазма"),
    ("gn976", "Очищенное вещество 07270"),
    ("9dk7y", "Пси-маячок"),
    ("gn975", "Портативный квантовый генератор"),
    ("w3zj3", "Модифицированная аномальная батарея"),
    ("dr61j", "Блок данных «Бета»"),
    ("y409k", "Блок данных «Гамма»"),
    ("y4y33", "Блок данных «Лямбда»"),
]
FARM = [
    ("7l127", "Аномальная пыль", "пыль"),
    ("gn956", "Камень Жмых-Вжух-Плюх", "пачка"),
    ("9dk7y", "Пси-маячок", "пачка"),
    ("gn975", "Портативный квантовый генератор", "пачка"),
    ("55621", "Армейский аккумулятор", "пачка"),
    ("olz36", "Моток медной проволоки", "пачка"),
    ("z301y", "Цветущий северный мох", "пачка"),
    ("77oy6", "Остатки сигнального процессора", "пачка"),
    ("y40kk", "Крупный рассольник", "пачка"),
    ("009n9", "Полыхающий срачник", "пачка"),
    ("gn976", "Очищенное вещество 07270", "пачка"),
    ("4k5gr", "Блок данных «Альфа»", "пачка"),
    ("y409k", "Блок данных «Гамма»", "пачка"),
    ("dr61j", "Блок данных «Бета»", "пачка"),
    ("y4y33", "Блок данных «Лямбда»", "пачка"),
    ("gnpr5", "Темный Лимб", "пачка"),
    ("4k3qo", "Концентрированная лимбоплазма", "пачка"),
    ("w3zj3", "Модифицированная аномальная батарея", "пачка"),
    ("z30yy", "Камышовый грибок", "пачка"),
    ("kr53y", "Корень-липучка", "пачка"),
    ("34z1l", "Чернобыльская ромашка", "пачка"),
    ("z30my", "Цветущий рыжий папоротник", "пачка"),
    ("gn9y6", "Камень Водяного", "пачка"),
    ("z3ogm", "Расцветший Горьколистник", "пачка"),
]
FLIP = [
    ("y3nmw", "Продвинутые запчасти"),
    ("4q7pl", "Продвинутые инструменты"),
    ("40vn", "Аммиак"),
    ("3gqkg", "Нестабильная аномальная батарея"),
    ("3gq6k", "Набор компонентов оружия (Мастер)"),
    ("2d56", "Набор болтов"),
    ("npq3", "Аномальная плазма"),
]

# Арсенал и материалы убежища: сливать нафармленное или держать.
ARSENAL_ITEMS = [
    ("4q7pl", "Продвинутые инструменты"),
    ("y3nmw", "Продвинутые запчасти"),
    ("y7po", "Реагенты"),
    ("knydy", "Ящик гранат «Завеса»"),
    ("lyrdq", "Сумка СБП 9x39 мм"),
    ("n46d1", "Ящик гранат «Вонючка»"),
    ("lywdk", "Ящик гранат «Напалм»"),
    ("2d56", "Набор болтов"),
    ("1r0gg", "Сумка керамических пластин IV"),
    ("1dnq", "Тканевая сумка"),
    ("0ngy", "Керамическая пластина IV"),
    ("wodp", "Электросмесь"),
    ("m0wdy", "Ящик гранат «Подорожник»"),
    ("qjq69", "Сумка СБП 5.56 мм"),
    ("j5qd4", "Сумка СБП 7.62 мм"),
    ("wwod", "M18 Claymore"),
    ("9mmq", "Мякоть солевика"),
    ("4nkr", "Алюминиевый порошок"),
    ("6wmkp", "Ящик гранат «Кустарник-1»"),
    ("1d56", "Щепки"),
    ("knpd3", "Сумка СБП 5.45 мм"),
    ("4q7yl", "Сумка СБП 9 мм"),
    ("j5pd0", "Ящик гранат «Гром»"),
    ("y7dz", "Морозная смесь"),
    ("n4w7w", "Сумка зажигательных 7.62 мм"),
    ("jl44", "Серная кислота"),
    ("404p", "Термическая смесь"),
    ("j0w96", "Дешевые запчасти"),
    ("km9v", "Коагулянт"),
    ("p6kgw", "Сумка 12.7 мм Easy mode"),
    ("qvm9", "Азотная кислота"),
    ("q2yj", "Крепкая сталь"),
    ("z719", "Сталь"),
    ("wjlrd", "Дешевые инструменты"),
    ("96qll", "Ящик самодельных светошумов"),
    ("2o65l", "Сумка 5.56 мм «Прогрев»"),
    ("0rlzr", "Сумка зажигательных 12х76 мм"),
    ("r22z", "Ноотроп"),
    ("vj3zg", "Сумка бронебойных 5.56 мм"),
    ("m2lr", "Карбоноволокно"),
    ("5lqp1", "Сумка зажигательных 9x39 мм"),
    ("g4rd6", "Сумка керамических пластин V"),
    ("1731", "Кевлар"),
    ("rwl5v", "Сумка 5.56 «Курчатов»"),
    ("l2oo", "Зажигательное покрытие"),
    ("vrld", "Консервная банка"),
    ("wo2d", "Хлор"),
    ("qjl6j", "Ящик гранат «Искра»"),
    ("ovo4", "Абразив"),
    ("qjlzj", "Сумка СЭП 7.62 мм"),
    ("prm6", "Свинец"),
    ("999q", "Плитоноска"),
    ("96qjl", "Сумка керамических пластин III"),
    ("okq16", "Сумка 9 мм «Сосуля»"),
    ("wjn52", "Сумка композитных пластин IV"),
    ("nvpw", "СЗГ «Вспышка»"),
    ("kmmj", "Промышленный растворитель"),
    ("q224", "Нитроглицерин"),
    ("y31mk", "Сумка СЭП 9 мм"),
    ("0rwg9", "Сумка взрывных 10 мм"),
    ("y31lk", "Ящик самодельных мини-гранат"),
    ("z2om", "Дымный порох"),
    ("okp74", "Сумка зажигательных 5.56 мм"),
    ("kny0y", "Сумка СЭП 5.56 мм"),
    ("7l4q6", "Ящик кустарных гранат"),
    ("g325", "Стальная пластина III"),
    ("gm2p", "Нитрожелатин"),
    ("4qzpr", "Сумка СЭП 5.45 мм"),
    ("2o6zl", "Сумка стальных пластин IV"),
    ("zj9m", "Стальная пластина IV"),
    ("z7d2", "Кислота"),
    ("1r0zg", "Ящик кустарных ВОГ-25"),
    ("03zd", "Амортизирующее покрытие"),
    ("z29n", "Динамит"),
    ("rg5y", "Керамическая пластина III"),
    ("dmlwj", "Сумка дальнобойных 9x39 мм"),
    ("wjnq2", "Ящик кустарных осколочных гранат"),
    ("5n51", "Порох"),
    ("m0q7r", "Сумка зажигательных 5.45 мм"),
    ("z3oln", "Сумка снайперских 12.7 мм"),
    ("m0woy", "Сумка 7.62 мм «Динозавр»"),
    ("jon0", "Нашатырь"),
    ("j5pr0", "Сумка СЭП 9x39 мм"),
    ("7l1z6", "Сумка Баррикад"),
    ("vjqkr", "Сумка дальнобойных 9 мм"),
    ("okp24", "Сумка бронебойных 9 мм"),
    ("km6y", "Серная соль"),
    ("3g0yl", "Сумка патронов 12 калибра «Кислотный дракон»"),
    ("5np0", "Мутировавшие ферменты"),
    ("lywmk", "Сумка 5.45 «Ши-3»"),
    ("99n0", "Полиуретан"),
    ("dmyd9", "Сумка бронебойных 7.62 мм"),
    ("rwv7l", "Сумка зажигательных 9 мм"),
    ("g4r26", "Сумка бронебойных 10 мм"),
    ("zzg9y", "Сумка СБП 10 мм"),
    ("w732", "Селитра"),
    ("p6qd5", "Сумка бронебойных 5.45 мм"),
    ("n4wdw", "Сумка боевых пуль 12х76 мм"),
    ("dmldj", "Сумка стальных пластин III"),
    ("4nnj", "Гремучая ртуть"),
    ("2o0zm", "Сумка СП-6 9x39 мм"),
    ("zzgry", "Ящик самодельных M381"),
    ("z22k", "Пуля"),
    ("y31wk", "Сумка композитных пластин III"),
    ("wjnr2", "Сумка СЭП 10 мм"),
    ("n4691", "Сумка 9x39 мм «Электросвинг»"),
    ("knp93", "Особые инструменты"),
    ("gmmn", "Гильза"),
    ("g4rz0", "Самодельный светошум"),
    ("g4rq6", "Ящик кустарных ВОГ-25П"),
    ("5nno", "Крупнокалиберная пуля"),
    ("5lq41", "Ящик самодельных M397"),
    ("4qzyr", "Сумка композитных пластин V"),
    ("3g05l", "Сумка стальных пластин V"),
    ("2o0vl", "Сумка боевых пуль 23х75 мм"),
    ("1r0y6", "Ручная граната «Кустарник-1»"),
    ("1r03g", "Сумка зажигательных 10 мм"),
    ("194j1", "Сумка патронов 12.7 мм"),
]

SHELTER_ITEMS = [
    ("gn976", "Очищенное вещество 07270"),
    ("9dk7y", "Пси-маячок"),
    ("gn975", "Портативный квантовый генератор"),
    ("w39k3", "Огромный артефактный фрагмент"),
    ("z7pn", "Ткань"),
    ("55621", "Армейский аккумулятор"),
    ("g4lzg", "Водка «Гейзер»"),
    ("55ymq", "Обычный артефактный фрагмент"),
    ("wj2zp", "Чесночный суп"),
    ("009n9", "Полыхающий срачник"),
    ("pjkj2", "Экранированный схрон ветерана"),
    ("wogp", "Доски"),
    ("1r2l6", "«Астрикцин»"),
    ("gnpr5", "Темный Лимб"),
    ("40vn", "Аммиак"),
    ("p62q6", "Морфин"),
    ("2d76", "Мясо кабана"),
    ("9mr0", "Жгут"),
    ("1r2yq", "Силовой стимулятор"),
    ("y39yz", "Гороховый суп"),
    ("77oy6", "Остатки сигнального процессора"),
    ("5logg", "Странный артефакт"),
    ("6w59j", "«УДАР»"),
    ("qjmjk", "Боевой горох"),
    ("55olq", "Остатки приборов «Шепота»"),
    ("g4lz0", "«Биозаплатка»"),
    ("5lo3o", "Копыто сильного кабана"),
    ("mm4y", "Продвинутый электрод"),
    ("vjy3n", "Эпинефрин"),
    ("96zjw", "Подсумок с аптечками ученых"),
    ("dm1ln", "Красная икра"),
    ("7l9l7", "Холодец «Копытом по лицу»"),
    ("96z7y", "Катализатор"),
    ("964ow", "Энергетик «Батарейка»"),
    ("1r216", "«ТОПОТ»"),
    ("7lyo3", "«Алкобык»"),
    ("pry2", "Пластиковая бутылка"),
    ("y3knz", "«Убийца Боли»"),
    ("z3ozm", "«Светящийся сахар»"),
    ("7l127", "Аномальная пыль"),
    ("rr7g", "Медь"),
    ("vnqnd", "Экранированный схрон мастера"),
    ("7rp7", "Чеснок"),
    ("401j", "Батарея холодного синтеза"),
    ("zzqn9", "Коктейль «Незабываемый»"),
    ("2nw5", "Защитное покрытие"),
    ("l0ryo", "Черная селезенка"),
    ("prl2", "Кофе"),
    ("g060", "Набор для шитья"),
    ("6w5lj", "«Шизоерш»"),
    ("3g1zz", "«Субтропики»"),
    ("g4lp0", "Измененный сидр"),
    ("p3o4", "Роторная система"),
    ("ov50", "Сковорода"),
    ("5l23g", "Солянка"),
    ("jlll", "Алые минералы"),
    ("7l1kr", "Подсумок с аптечками проводника"),
    ("zzqn2", "Нейротоник"),
    ("mrwr7", "Схрон мастера"),
    ("prrd", "Янтарная полынь"),
    ("v25p", "Операционный усилитель"),
    ("drmwj", "Технический спирт"),
    ("m22k", "Водонос"),
    ("rrrz", "Бледнолист"),
    ("q2p3", "Полипропилен"),
    ("klwv", "Нефть"),
    ("4k3qo", "Концентрированная лимбоплазма"),
    ("dryl2", "Селезенка мутанта из Любеча"),
    ("rwow5", "Бутылка чистой воды"),
    ("zzwmm", "Сыворотка изменения"),
    ("m0pyj", "Аномальное шампанское"),
    ("npp9", "Чертоцвет"),
    ("jl77", "Железо"),
    ("kl9v", "Молоко"),
    ("1rlw2", "Эссенция сброса"),
    ("g4lk0", "Военная аптечка"),
    ("9d3gy", "Медная катушка"),
    ("m27j", "Аминокислота"),
    ("rr05", "Дрожжи"),
    ("p3vw", "Электродвигатель"),
    ("y7rw", "Детали электромотора"),
    ("y40kk", "Крупный рассольник"),
    ("1dk6", "Набор специй"),
    ("jl26", "Полимеры"),
    ("olz36", "Моток медной проволоки"),
    ("jl66", "Защитное снаряжение"),
    ("3rpg", "Полутухлая рыба"),
    ("dq2n", "Мультитул"),
    ("4qd3p", "Уха из сома «Дворянская»"),
    ("npq3", "Аномальная плазма"),
    ("033k", "Кислотная крапива"),
    ("m2g7", "Текстолит"),
    ("g0gp", "Гнилые доски"),
    ("wokd", "Смазочные материалы"),
    ("p6256", "«Панацея»"),
    ("40rl", "Разделочная доска"),
    ("rjvwy", "Сердце Лимб"),
    ("dm165", "Макароны по-флотски"),
    ("g00n", "Мякоть сластены"),
    ("5drg", "Брага"),
    ("3g12z", "Жаркое из мутантов"),
    ("kllj", "Лазурные минералы"),
    ("19on2", "Трансформатор"),
    ("w3923", "Сменный аккумулятор"),
    ("964k0", "Сильная мазь от ожогов"),
    ("lll2", "Золотые минералы"),
    ("ovv5", "Гнозис"),
    ("99dl", "Фреза"),
    ("5njq", "Алюминий"),
    ("6rpy", "Помидор"),
    ("lynkj", "Энергетик «Жидень EXTRA»"),
    ("ly6w1", "Бутерброд с колбасой"),
    ("dj92", "Набор кухонных ножей"),
    ("z3k1m", "Малый артефактный фрагмент"),
    ("96z2z", "Хронопыль"),
    ("z77k", "Мякоть спиртня"),
    ("rwol5", "Консервированная фасоль"),
    ("5lzyg", "«Гемостат»"),
    ("03p1", "Газовый баллон"),
    ("40lp", "Микроэлектроника"),
    ("y391o", "Колбасная нарезка"),
    ("qvwk", "Клей"),
    ("00w01", "Схрон ветерана"),
    ("03v1", "Колба с раствором"),
    ("qvv4", "Пурпурные минералы"),
    ("4qdqn", "Отечественный ИРП"),
    ("5ddo", "Мякоть куборбуза"),
    ("y770", "Мякоть лимонника"),
    ("wo6z", "Адронный конвертор"),
    ("5dm4", "Контрольная плата"),
    ("1rn01", "Кусок черного хлеба"),
    ("m2k7", "Глаз зомби"),
    ("1ddr", "Мякоть мятноплода"),
    ("1d31", "Банка с фасолью"),
    ("nmj1", "Листы сваренного металла"),
    ("j5mg7", "Игристое шампанское"),
    ("r2mv", "Вино с осадком"),
    ("77w9j", "Резонатор"),
    ("npz3", "Кастрюля"),
    ("dq0n", "Мясо хрюши"),
    ("7ly13", "Аптечка проводника"),
    ("99pz", "Полиэтиленовая основа"),
    ("5dp0", "Банка с пшеном"),
    ("j5456", "Отличная тушенка"),
    ("dqn9", "Аномальные материалы"),
    ("rwoj5", "Лимон"),
    ("gmy0", "Очищающий реагент"),
    ("qvrk", "Борная кислота"),
    ("y220", "Адреналин"),
]

ARSENAL = [
    ("4k5gr", "Блок данных «Альфа»"),
    ("dr61j", "Блок данных «Бета»"),
    ("y409k", "Блок данных «Гамма»"),
    ("y4y33", "Блок данных «Лямбда»"),
    ("8fg9w", "Большой ящик с продовольствием"),
    ("9d10q", "Военный радиопередатчик"),
    ("knpzj", "Глаз сильного бурелома"),
    ("qjqn4", "Голова сильной бестии"),
    ("egn0u", "Дорогие сигареты"),
    ("egh7l", "Драгоценности"),
    ("z3wgm", "Запчасти для ПДА"),
    ("gn1nn", "Комплект заводских инструментов"),
    ("j0q0l", "Компоненты редких сплавов"),
    ("4k3qo", "Концентрированная лимбоплазма"),
    ("007oy", "Кость мутанта"),
    ("y4gr3", "Крупный артефактный фрагмент"),
    ("krpnp", "Лоскут светящейся кожи"),
    ("z3k1m", "Малый артефактный фрагмент"),
    ("nb9wi", "Малый ящик с продовольствием"),
    ("y4n40", "Медицинские инструменты"),
    ("9d3gy", "Медная катушка"),
    ("w3zj3", "Модифицированная аномальная батарея"),
    ("olz36", "Моток медной проволоки"),
    ("9kpmj", "Набор компонентов брони (Мастер)"),
    ("3gq6k", "Набор компонентов оружия (Мастер)"),
    ("771lj", "Ноутбук"),
    ("55ymq", "Обычный артефактный фрагмент"),
    ("b80pf", "Обычный ящик с продовольствием"),
    ("w39k3", "Огромный артефактный фрагмент"),
    ("55olq", "Остатки приборов «Шепота»"),
    ("gn976", "Очищенное вещество 07270"),
    ("gn975", "Портативный квантовый генератор"),
    ("y3nmw", "Продвинутые запчасти"),
    ("4q7pl", "Продвинутые инструменты"),
    ("c4n76", "Промышленные запчасти"),
    ("dm6l2", "Протоартефакт"),
    ("vn3n7", "Прототипы «Шепота»"),
    ("9dk7y", "Пси-маячок"),
    ("z3ogm", "Расцветший Горьколистник"),
    ("wjlzz", "Рука сильного шныря"),
    ("rjvwy", "Сердце лимб"),
    ("s0xp7", "Системы наведения"),
    ("gnk55", "Соленоид"),
    ("l0og1", "Стандартные запчасти"),
    ("qjqw9", "Стандартные инструменты"),
    ("gnpr5", "Темный Лимб"),
    ("y4g93", "Фильтр"),
    ("1rl61", "Хроносфера"),
    ("z30my", "Цветущий рыжий папоротник"),
    ("l0ryo", "Черная селезенка"),
    ("nia64", "Ящик с деталями"),
    ("drym2", "Ящик с запчастями"),
    ("22odq", "Ящик с ресурсами (ветеран, украдены)"),
    ("pjn64", "Ящик с ресурсами (ветеран)"),
    ("n96ww", "Ящик с ресурсами (сталкер)"),
]
SHELTER = SHELTER_ITEMS

SHELTER_BUY = [
    ("z7pn", "Ткань"),
    ("2d76", "Мясо кабана"),
    ("9mr0", "Жгут"),
    ("5lo3o", "Копыто сильного кабана"),
    ("r22z", "Ноотроп"),
    ("g00n", "Мякоть сластены"),
    ("z3ozm", "Светящийся сахар"),
    ("7rp7", "Чеснок"),
    ("dq0n", "Мясо хрюши"),
    ("prrd", "Янтарная полынь"),
    ("drmwj", "Технический спирт"),
    ("m22k", "Водонос"),
    ("rrrz", "Бледнолист"),
    ("rwow5", "Бутылка чистой воды"),
    ("npp9", "Чертоцвет"),
    ("kl9v", "Молоко"),
    ("rr05", "Дрожжи"),
    ("1dk6", "Набор специй"),
    ("033k", "Кислотная крапива"),
    ("9mmq", "Мякоть солевика"),
    ("l2kk", "Глицерин"),
    ("5drg", "Брага"),
    ("mmn2", "Кровяная сыворотка"),
    ("y7dz", "Морозная смесь"),
    ("ovv5", "Гнозис"),
    ("404p", "Термическая смесь"),
    ("6rpy", "Помидор"),
    ("dm1ln", "Красная икра"),
    ("prl2", "Кофе"),
    ("km9v", "Коагулянт"),
    ("z77k", "Мякоть спиртня"),
    ("5ddo", "Мякоть куборбуза"),
    ("y770", "Мякоть лимонника"),
    ("1ddr", "Мякоть мятноплода"),
    ("1d31", "Банка с фасолью"),
    ("5dp0", "Банка с пшеном"),
    ("rwoj5", "Лимон"),
    ("y220", "Адреналин"),
]

SHELTER_SELL = [
    ("g4lzg", "Водка «Гейзер»"),
    ("wj2zp", "Чесночный суп"),
    ("y39yz", "Гороховый суп"),
    ("7l9l7", "Холодец «Копытом по лицу»"),
    ("7lyo3", "Алкобык"),
    ("zzqn9", "Коктейль «Незабываемый»"),
    ("3g1zz", "Субтропики"),
    ("g4lp0", "Измененный сидр"),
    ("5l23g", "Солянка"),
    ("m0pyj", "Аномальное шампанское"),
    ("qjmlk", "Бутерброд с икрой"),
    ("4qd3p", "Уха из сома «Дворянская»"),
    ("dm165", "Макароны по-флотски"),
    ("3g12z", "Жаркое из мутантов"),
    ("ly6w1", "Бутерброд с колбасой"),
    ("g0y0", "Соленья"),
    ("rwol5", "Консервированная фасоль"),
    ("y391o", "Колбасная нарезка"),
    ("4qdqn", "Отечественный ИРП"),
    ("j5mg7", "Игристое шампанское"),
    ("r2mv", "Вино с осадком"),
    ("j5456", "Отличная тушенка"),
    ("964z0", "Водка «Кривой Коготь»"),
    ("0row1", "Рыбные консервы"),
    ("qjmjk", "Боевой горох"),
    ("okdpo", "Веселый лимонад"),
    ("n4lg6", "Пшенка с мясом"),
    ("p62q6", "Морфин"),
    ("vjy3n", "Эпинефрин"),
    ("1r2l6", "Астрикцин"),
    ("g4lz0", "Биозаплатка"),
    ("6w59j", "УДАР"),
    ("1r216", "ТОПОТ"),
    ("y3knz", "Убийца Боли"),
    ("6w5lj", "Шизоерш"),
    ("zzqn2", "Нейротоник"),
    ("p6256", "Панацея"),
    ("964k0", "Сильная мазь от ожогов"),
    ("964ow", "Энергетик «Батарейка»"),
    ("1r2yq", "Силовой стимулятор"),
]


# Еда, хилки и бафы. Не только морфин.
CONSUMABLES = [
    ("vjy3n", "Эпинефрин"),
    ("p62q6", "Морфин"),
    ("g4lk0", "Военная аптечка"),
    ("96430", "Аптечка индивидуальная"),
    ("1r2o6", "Аптечка ученых"),
    ("7ly13", "Аптечка проводника"),
    ("zzqk2", "Бинт"),
    ("g4lz0", "Биозаплатка"),
    ("5lzyg", "Гемостат"),
    ("y3knz", "Убийца Боли"),
    ("p6256", "Панацея"),
    ("1r2l6", "Астрикцин"),
    ("2o9g0", "Озверин"),
    ("6w59j", "УДАР"),
    ("1r216", "ТОПОТ"),
    ("6w5lj", "Шизоерш"),
    ("1r2yq", "Силовой стимулятор"),
    ("g4l10", "Анаболик ATLAS"),
    ("zzqo2", "Анаболик SALT"),
    ("7lyd3", "Анаболик STARK"),
    ("zzqn2", "Нейротоник"),
    ("964ow", "Энергетик «Батарейка»"),
    ("lynkj", "Энергетик «Жидень EXTRA»"),
    ("rw1mg", "Тоник «Арни»"),
    ("j5mq7", "Антидот первого класса"),
    ("qj9y6", "Антидот второго класса"),
    ("lynrj", "Антидот третьего класса"),
    ("y3kgz", "Антирад Б-191"),
    ("wjw9p", "Антирад Б-292"),
    ("4qgop", "Антирад Б-393"),
    ("n4vw6", "Мазь от ожогов"),
    ("964k0", "Сильная мазь от ожогов"),
    ("4qdqn", "Отечественный ИРП"),
    ("wj2jo", "Американский ИРП"),
    ("j5456", "Отличная тушенка"),
    ("okrq0", "Мясные консервы"),
    ("rwow5", "Бутылка чистой воды"),
    ("z3o52", "Боевой набор"),
]
PROTO = ("dm6l2", "Протоартефакт")

ARTS = [
    ("gyq5", "Спираль"), ("1kv2", "Прима"), ("kqgy", "Браслет"),
    ("kqp0", "Жар-птица"), ("zy32", "Батарейка"), ("y54z", "Гиря"),
    ("qoq6", "Солнце"), ("zyqk", "Хрусталь"), ("5rpq", "Янтарник"),
    ("y5jk", "Жильник"), ("5rg1", "Проклятая роза"), ("wgvd", "Чернильница"),
    ("jkj4", "Ряска"), ("4l7p", "Гребешок"), ("5r5g", "Ледяной ежик"),
    ("qodk", "Бубльгум"), ("kqr0", "Гелий"), ("wg53", "Атом"),
    ("lj0j", "Катушка"), ("qo06", "Трансформатор"), ("rnvg", "Шишка"),
    ("g34p", "Юла"), ("jkq7", "Магма"), ("y5k0", "Вихрь"),
    ("wg62", "Белая роза"), ("zyly", "Цибуля"), ("9n1w", "Ягодка"),
    ("gypg", "Плод"), ("ljpq", "Многогранник"), ("4lml", "Змеиный глаз"),
    ("zyw2", "Огонек"), ("ljrj", "Радиатор"), ("zyrm", "Зеркало"),
    ("y5yw", "Гантель"), ("9nvy", "Вехотка"), ("kqoj", "Каблук"),
    ("gyg5", "Креветка"), ("qo94", "Куриный бог"), ("5rwq", "Осколок"),
    ("4l1r", "Протоцибуля"), ("wgwz", "Фаренгейт"), ("wg3p", "Дезинтегратор"),
    ("1kdg", "Липкий репях"), ("zy7y", "Ежик"), ("9nd0", "Призрачный кристалл"),
    ("1k96", "Трещотка"), ("qo59", "Жвачка"), ("kqj3", "Улитка"),
]
QLT = ["Обычный", "Необычный", "Особый", "Редкий", "Исключительный", "Легендарный"]
ART_MIN_SALES = 6
ART_MIN_NET = 8000
ART_MARGIN = 1.12


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with _LOG_LOCK:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def rub(n):
    try:
        n = float(n)
    except Exception:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}кк"
    if n >= 1000:
        return f"{n / 1000:.1f}к"
    return f"{n:.0f}"


def history_json(slug):
    with _HIST_LOCK:
        cached = _HIST.get(slug)
    if cached is not None:
        return cached
    data = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset=0")
    with _HIST_LOCK:
        _HIST[slug] = data
    return data


def parallel(items, fn):
    results = [None] * len(items)
    if not items or HALT.is_set():
        return results
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as e:
                results[i] = e
    return results


def hist(slug):
    data = history_json(slug)
    prices = []
    for p in data.get("prices") or []:
        amt = max(p.get("amount") or 1, 1)
        prices.append(p["price"] / amt)
    if not prices:
        return None
    top = prices[:30]
    return {
        "last": top[0],
        "med": statistics.median(top),
        "mn": min(top),
        "mx": max(top),
        "prices": prices,
    }


def farm_action(kind, last, med):
    if last < med * 0.9:
        return "ДЕРЖАТЬ", "last ниже медианы на 10%+"
    if kind == "пыль":
        return "СЛИТЬ 3000", f"на руки ~{rub(3000 * last * COMM)}"
    return "СЛИТЬ ПАЧКОЙ", f"цель {rub(med)}"


def flip_action(last, med):
    if last <= med * 0.85:
        return "БРАТЬ", "спред после 5% ок"
    return "НЕ ТРОГАТЬ", "тонкий спред"


def art_history(slug):
    """Последние выкупленные лоты напрямую с EXBO."""
    out = []
    for page in range(5):
        if HALT.is_set():
            break
        data = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset={page * 200}")
        batch = data.get("prices") or []
        out.extend(batch)
        if len(batch) < 200:
            break
    return out


def sale_points(prices):
    out = []
    for p in prices:
        amt = max(int(p.get("amount") or 1), 1)
        add = p.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        qlt = 0 if qlt is None else int(qlt)
        ptn = 0 if ptn is None else int(ptn)
        if ptn < 0 or ptn > 15:
            continue
        price = p.get("price")
        if not price:
            continue
        out.append((price / amt, qlt, ptn))
    return out


def qlabel(qlt, ptn):
    qname = QLT[qlt] if 0 <= qlt < len(QLT) else f"qlt {qlt}"
    return f"{qname} +{ptn}"


def _art_one(item):
    slug, name = item
    try:
        book = market_book(slug, 4)
    except Exception as e:
        return [{"name": name, "err": str(e)}]
    rows = []
    for key, prices in book["sales"].items():
        if not key:
            continue
        got = usual_sale(prices)
        bought = book["live"].get(key)
        if not got or not bought:
            continue
        last, sold, n = got
        net = sold * COMM - bought
        roi = net / bought if bought else 0
        samples = [(row[1], row[2]) for row in prices if len(row) > 2]
        alive = _fair_exit(samples, time.time(), 4)
        if bought and roi >= 0.06 and net >= ART_MIN_NET and alive and alive[1] >= 0.5:
            liq = "ВЫКУПИТЬ"
        elif bought >= sold * 1.15 and n >= 12:
            liq = "ДОРОГО"
        else:
            continue
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        qlt, ptn = key
        rows.append({
            "name": name, "qlt": QLT[qlt] if 0 <= qlt < len(QLT) else str(qlt), "ptn": f"+{ptn}", "qlt_i": qlt, "n": n,
            "cheap": bought, "med": sold,
            "hand": sold * COMM, "net": net, "liq": liq,
        })
    return rows


def art_deals():
    parts = parallel(ARTS, _art_one)
    rows, checked = [], 0
    for part in parts:
        if isinstance(part, Exception):
            continue
        if part:
            rows.extend(part)
            checked += 1
        elif part == []:
            checked += 1
    rows.sort(key=lambda r: (0 if r.get("liq") == "ВЫКУПИТЬ" else 1, -(r.get("net") or 0)))
    return rows[:80], checked


def hist_timed(slug, max_pages, enough=None):
    raw = []
    for page in range(max_pages):
        if HALT.is_set():
            break
        data = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset={page * 200}")
        batch = data.get("prices") or []
        if not batch:
            break
        raw.extend(batch)
        if enough is not None:
            probe = []
            for p in raw:
                t = datetime.fromisoformat(p["time"].replace("Z", "+00:00")).astimezone(MSK)
                probe.append(t)
            if enough(probe):
                break
        if len(batch) < 200:
            break
    out = []
    for p in raw:
        amt = max(p.get("amount") or 1, 1)
        t = datetime.fromisoformat(p["time"].replace("Z", "+00:00")).astimezone(MSK)
        out.append((t, p["price"] / amt))
    out.sort(key=lambda x: x[0])
    return out


def _clip(prices):
    if len(prices) < 20:
        return list(prices)
    s = sorted(prices)
    lo = s[int(len(s) * 0.05)]
    hi = s[min(len(s) - 1, int(len(s) * 0.95))]
    return [p for p in prices if lo <= p <= hi]


def buy_check(prices, hours=None, min_n=20):
    clean = _clip(prices)
    if len(clean) < min_n:
        return {
            "liq": "НЕ СКУПАТЬ",
            "low": min(prices) if prices else 0,
            "avg": 0,
            "per_h": 0,
            "n": len(clean),
            "note": "мало продаж, выкуп зависнет",
        }
    ordered = sorted(clean)
    low = ordered[max(0, int(len(ordered) * 0.1) - 1)]
    avg = statistics.mean(clean)
    per_h = len(clean) / hours if hours and hours > 0 else 0
    net = avg * COMM - low
    margin = net / low if low else 0
    if hours and per_h < 4:
        liq = "НЕ СКУПАТЬ"
        note = f"{per_h:.0f} продаж/час, сливать будет некуда"
    elif margin < 0.08:
        liq = "НЕ СКУПАТЬ"
        note = f"низ {rub(low)} и средняя {rub(avg)} слишком близко после 5%"
    else:
        liq = "СКУПАТЬ"
        note = f"низ {rub(low)} против средней {rub(avg)}, профит {rub(net)}"
    return {"liq": liq, "low": low, "avg": avg, "per_h": per_h, "n": len(clean), "net": net, "note": note}


def kit_signal(sales):
    prices = [p for _, p in sales]
    if len(prices) < 20:
        return {"name": "Боевой набор", "err": "мало сделок"}
    span = max((sales[-1][0] - sales[0][0]).total_seconds() / 3600, 0.5)
    chk = buy_check(prices, hours=span)
    last = sales[-1][1]
    snipes = [p for p in prices if 120000 <= p <= 145000]
    if chk["liq"] == "СКУПАТЬ" and last <= chk["low"] * 1.02:
        act = "СКУПАТЬ"
        why = chk["note"]
    else:
        act = "НЕ СКУПАТЬ"
        why = chk["note"]
        if snipes:
            why += f". разовых дешёвых лотов {len(snipes)}, это не полка для скупа"
    return {
        "name": "Боевой набор", "act": act, "why": why, "last": last,
        "med": chk["avg"], "low": chk["low"], "avg": chk["avg"],
        "per_h": chk["per_h"], "liq": chk["liq"], "extra": f"снайпов 120–145к: {len(snipes)}",
    }


def med_signal(name, sales, now):
    if not sales:
        return {"name": name, "err": "нет сделок"}
    morning = [p for t, p in sales if 7 <= t.hour < 11]
    evening = [p for t, p in sales if 16 <= t.hour < 21]
    span = max((sales[-1][0] - sales[0][0]).total_seconds() / 3600, 0.5)
    sell = _clip(morning) if len(morning) >= 20 else []
    buy = _clip(evening) if len(evening) >= 20 else []
    if len(sell) < 20 or len(buy) < 20:
        chk = buy_check([p for _, p in sales], hours=span)
        return {
            "name": name, "act": "НЕ СКУПАТЬ",
            "why": f"мало окна: утро {len(morning)}, вечер {len(evening)}",
            "last": sales[-1][1], "med": chk["avg"], "low": chk["low"], "avg": chk["avg"],
            "per_h": chk["per_h"], "liq": "НЕ СКУПАТЬ", "extra": "",
        }
    low = sorted(buy)[max(0, int(len(buy) * 0.1) - 1)]
    avg = statistics.mean(sell)
    per_h = len(sales) / span
    net = avg * COMM - low
    margin = net / low if low else 0
    extra = f"низ вечера {rub(low)} / средняя утра {rub(avg)} / {per_h:.0f} продаж/час"
    liquid = per_h >= 4 and margin >= 0.08
    if not liquid:
        act = "НЕ СКУПАТЬ"
        why = f"{per_h:.0f} продаж/час, сливать некуда" if per_h < 4 else "низ и средняя продажа слишком близко после 5%"
    elif 16 <= now.hour < 23:
        act = "СКУПАТЬ"
        why = f"окно закупа. профит к утру ~{rub(net)}"
    elif 7 <= now.hour < 12:
        act = "НЕ СКУПАТЬ"
        why = f"сейчас утро, это цена слива, не закупа. профит был бы ~{rub(net)}"
    else:
        act = "НЕ СКУПАТЬ"
        why = f"зазор есть, закуп с 16 до 21. профит ~{rub(net)}"
    return {
        "name": name, "act": act, "why": why, "last": sales[-1][1], "med": avg,
        "low": low, "avg": avg, "per_h": per_h,
        "liq": "СКУПАТЬ" if act == "СКУПАТЬ" else "НЕ СКУПАТЬ", "extra": extra,
    }


def session_deals():
    now = datetime.now(MSK)

    def both_windows(times):
        morning = sum(1 for t in times if 7 <= t.hour < 11)
        evening = sum(1 for t in times if 16 <= t.hour < 21)
        return morning >= 40 and evening >= 40

    def kit():
        return kit_signal(hist_timed("z3o52", 4))

    def med(item):
        slug, name = item
        return med_signal(name, hist_timed(slug, 30, both_windows), now)

    kit_row, epi, morph = parallel([("kit",), ("vjy3n", "Эпинефрин"), ("p62q6", "Морфин")], lambda item: kit() if item == ("kit",) else med(item))
    rows = []
    for row, fallback in ((kit_row, "Боевой набор"), (epi, "Эпинефрин"), (morph, "Морфин")):
        if isinstance(row, Exception):
            rows.append({"name": fallback, "err": str(row)})
        elif row:
            rows.append(row)
    return rows


def _farm_one(item):
    slug, name, kind = item
    h = hist(slug)
    if not h:
        return {"name": name, "err": "нет сделок"}
    act, why = farm_action(kind, h["last"], h["med"])
    extra = ""
    if kind == "пыль":
        extra = f" | 3000={rub(3000 * h['last'])} на руки={rub(3000 * h['last'] * COMM)}"
    return {**h, "name": name, "act": act, "why": why + extra, "kind": kind}


def _flip_one(item):
    slug, name = item
    h = hist(slug)
    if not h:
        return {"name": name, "err": "нет сделок"}
    chk = buy_check(h["prices"], min_n=25)
    return {
        **h, "name": name, "act": chk["liq"], "why": chk["note"],
        "low": chk["low"], "avg": chk["avg"], "per_h": chk["per_h"], "liq": chk["liq"],
    }


def collect(status=None):
    def say(msg):
        log(msg)
        if status:
            status(msg)

    say(f"Фарм, сразу {min(WORKERS, len(FARM))} предметов")
    farm = []
    for row in parallel(FARM, _farm_one):
        if isinstance(row, Exception):
            farm.append({"name": "фарм", "err": str(row)})
        elif row:
            farm.append(row)
    say(f"Перекуп, сразу {min(WORKERS, len(FLIP))} предметов")
    flip = []
    for row in parallel(FLIP, _flip_one):
        if isinstance(row, Exception):
            flip.append({"name": "перекуп", "err": str(row)})
        elif row:
            flip.append(row)
    say("Арты")
    arts, checked = art_deals()
    say("Наборы и расходники")
    session = session_deals()
    return farm, flip, arts, checked, session


def write_files(farm, flip, arts, checked, session):
    now = datetime.now().strftime("%d.%m.%Y %H:%M")

    def row(r, cls_fn):
        if r.get("err"):
            return f"<tr><td>{r['name']}</td><td colspan='3'>{r['err']}</td></tr>"
        cls = cls_fn(r["act"])
        return (
            f"<tr class='{cls}'><td>{r['name']}</td><td>{rub(r['last'])}</td><td>{rub(r['med'])}</td>"
            f"<td><b>{r['act']}</b><br><small>{r['why']}</small></td></tr>"
        )

    def art_row(r):
        if r.get("err"):
            return f"<tr><td>{r['name']}</td><td colspan='7'>{r['err']}</td></tr>"
        cls = "buy" if r.get("liq") == "СКУПАТЬ" else "skip"
        return (
            f"<tr class='{cls}'><td>{r['name']}</td><td>{r['qlt']}</td><td>{r['n']}</td>"
            f"<td>{rub(r['cheap'])}</td><td>{rub(r['med'])}</td><td>{rub(r['net'])}</td>"
            f"<td><b>{r.get('liq', '')}</b></td></tr>"
        )

    def sess_cls(act):
        if act == "СКУПАТЬ":
            return "buy"
        if act in ("НЕ СКУПАТЬ", "НЕ ТРОГАТЬ", "МАЛО ДАННЫХ"):
            return "skip"
        return "hold"

    def sess_row(r):
        if r.get("err"):
            return f"<tr><td>{r['name']}</td><td colspan='5'>{r['err']}</td></tr>"
        extra = (" · " + r["extra"]) if r.get("extra") else ""
        return (
            f"<tr class='{sess_cls(r['act'])}'><td>{r['name']}</td>"
            f"<td>{rub(r.get('low', 0))}</td><td>{rub(r.get('avg', r.get('med', 0)))}</td>"
            f"<td>{r.get('per_h', 0):.0f}</td><td><b>{r['act']}</b><br><small>{r['why']}{extra}</small></td></tr>"
        )

    def flip_row(r):
        if r.get("err"):
            return f"<tr><td>{r['name']}</td><td colspan='3'>{r['err']}</td></tr>"
        cls = "buy" if r.get("act") == "СКУПАТЬ" else "skip"
        return (
            f"<tr class='{cls}'><td>{r['name']}</td><td>{rub(r.get('low', 0))}</td>"
            f"<td>{rub(r.get('avg', 0))}</td><td><b>{r['act']}</b><br><small>{r['why']}</small></td></tr>"
        )

    arts_body = "".join(art_row(r) for r in arts) or (
        "<tr><td colspan='7'>Спреда нет: дешёвые сделки не отбивают 12% после комиссии.</td></tr>"
    )
    html = f"""<!doctype html><meta charset="utf-8">
<title>STALZONE агент {now}</title>
<style>
body{{font:15px/1.4 sans-serif;background:#111;color:#eee;margin:24px}}
table{{border-collapse:collapse;width:100%;max-width:980px;margin:8px 0 28px}}
td,th{{border-bottom:1px solid #333;padding:8px 10px;text-align:left;vertical-align:top}}
.sell{{background:#163216}} .hold{{background:#3a2a12}}
.buy{{background:#12243a}} .skip{{background:#1a1a1a}}
small{{color:#aaa}}
</style>
<h1>STALZONE агент</h1>
<p>Обновлено {now}. Цены EXBO. Комиссия 5%. Перед слотом сверь лот в игре.</p>
<h2>Слив фарма</h2>
<table><tr><th>Предмет</th><th>Last</th><th>Мед 30</th><th>Действие</th></tr>
{''.join(row(r, lambda a: 'hold' if a.startswith('ДЕРЖ') else 'sell') for r in farm)}
</table>
<h2>Перекуп кэша</h2>
<table><tr><th>Предмет</th><th>Низ</th><th>Средняя</th><th>Скуп</th></tr>
{''.join(flip_row(r) for r in flip)}
</table>
<h2>Наборы и расходники</h2>
<table><tr><th>Предмет</th><th>Низ</th><th>Средняя продажа</th><th>Продаж/час</th><th>Скуп</th></tr>
{''.join(sess_row(r) for r in session)}
</table>
<h2>Арты</h2>
<p>Проверено {checked}.</p>
<table><tr><th>Арт</th><th>Качество</th><th>Сделок</th><th>Низ</th><th>Средняя</th><th>Профит</th><th>Скуп</th></tr>
{arts_body}
</table>
"""
    HTML.write_text(html, encoding="utf-8")
    lines = [f"STALZONE агент  {now}", "комиссия 5%", "", "=== СЛИВ ФАРМА ==="]
    for r in farm:
        lines.append(f"{r['name']}: {r['err']}" if r.get("err") else f"{r['name']}: last {rub(r['last'])} / мед {rub(r['med'])} → {r['act']} ({r['why']})")
    lines += ["", "=== ПЕРЕКУП ==="]
    for r in flip:
        lines.append(f"{r['name']}: {r['err']}" if r.get("err") else f"{r['name']}: низ {rub(r.get('low', 0))} / средняя {rub(r.get('avg', 0))} → {r['act']} ({r['why']})")
    lines += ["", "=== НАБОРЫ ==="]
    for r in session:
        lines.append(f"{r['name']}: {r['err']}" if r.get("err") else f"{r['name']}: низ {rub(r.get('low', 0))} / средняя {rub(r.get('avg', 0))} / {r.get('per_h', 0):.0f} в час → {r['act']}")
    lines += ["", f"=== АРТЫ ({checked}) ==="]
    if not arts:
        lines.append("спреда нет")
    for r in arts:
        lines.append(f"{r['name']}: {r['err']}" if r.get("err") else f"{r['name']} [{r['qlt']}] x{r['n']}: низ {rub(r['cheap'])} / средняя {rub(r['med'])} / профит {rub(r['net'])} / {r.get('liq')}")
    TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


_PACE = threading.Lock()
_NEXT_AT = 0.0
_GAP = 0.05
_CLIENT = None
_CLIENT_LOCK = threading.Lock()


def _reset_client():
    global _CLIENT
    with _CLIENT_LOCK:
        old = _CLIENT
        _CLIENT = None
    if old is not None:
        try:
            old.close()
        except Exception:
            pass


def _client():
    global _CLIENT
    with _CLIENT_LOCK:
        if _CLIENT is None:
            _CLIENT = httpx.Client(
                timeout=httpx.Timeout(12.0, connect=8.0),
                follow_redirects=True,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=8),
            )
        return _CLIENT


_EXBO = None


def exbo_headers():
    global _EXBO
    if _EXBO is None:
        path = DIR / "exbo.json"
        if not path.exists():
            raise RuntimeError("нет exbo.json рядом со скриптом")
        raw = json.loads(path.read_text(encoding="utf-8"))
        _EXBO = (str(raw["client_id"]), str(raw["client_secret"]))
    client_id, secret = _EXBO
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Client-Id": client_id,
        "Client-Secret": secret,
    }


def get_json(url):
    """Один запрос к EXBO. Соединение держится открытым, пауза общая на все потоки."""
    global _NEXT_AT, _GAP
    for attempt in range(2):
        with _PACE:
            now = time.time()
            slot = max(_NEXT_AT, now)
            wait = slot - now
            _NEXT_AT = slot + _GAP
        if wait > 0:
            time.sleep(wait)
        try:
            resp = _client().get(url, headers=exbo_headers())
            resp.raise_for_status()
            data = resp.json()
            with _PACE:
                _GAP = max(0.03, _GAP * 0.85)
            return data
        except httpx.HTTPStatusError as error:
            failure = error
            code = error.response.status_code
            if attempt or not (code in (408, 425, 429) or code >= 500):
                raise
            limited = code == 429
            delay = 0.6 if limited else 0.3
            if limited:
                try:
                    retry_after = float(error.response.headers.get("Retry-After", "0"))
                    if 0 <= retry_after < float("inf"):
                        delay = min(5.0, max(delay, retry_after))
                except ValueError:
                    pass
        except httpx.TransportError as error:
            failure = error
            if attempt:
                raise
            limited, delay = False, 0.3
        # httpx drops failed connections itself. Closing the shared client here
        # would abort unrelated requests running in other scan threads.
        with _PACE:
            _GAP = min(0.16, _GAP + (0.03 if limited else 0.02))
        if HALT.wait(delay):
            raise failure


def market_unit(slug):
    data = history_json(slug)
    units = []
    for p in data.get("prices") or []:
        amt = max(p.get("amount") or 1, 1)
        units.append(p["price"] / amt)
    if len(units) < 8:
        return None
    return statistics.median(_clip(units))


_LIVE = {}
_LIVE_LOCK = threading.Lock()
_BOOK = {}
_BOOK_LOCK = threading.Lock()


def cached_live(slug):
    with _LIVE_LOCK:
        hit = _LIVE.get(slug)
    if hit is not None:
        return hit
    lots = live_lots(slug)
    with _LIVE_LOCK:
        _LIVE[slug] = lots
    return lots


def live_lots(slug, pages=4):
    out = []
    offset = 0
    total = None
    while total is None or offset < total:
        if HALT.is_set():
            break
        data = get_json(
            f"{EXBO}/RU/auction/{slug}/lots?additional=true&limit=200&offset={offset}"
            "&sort=buyout_price&order=asc"
        )
        total = data.get("total") or 0
        batch = data.get("lots") or []
        if not batch:
            break
        out.extend(batch)
        offset += 200
        if offset >= pages * 200 or offset >= total:
            break
    return out


def _sniper_item(item):
    slug, name = item
    med = market_unit(slug)
    grouped = {}
    if not med:
        return []
    ceiling = med * BUY_AT
    for lot in cached_live(slug):
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0 or buy > BUDGET:
            continue
        unit = buy / amt
        if unit > ceiling:
            continue
        net_u = med * COMM - unit
        if net_u <= 0:
            continue
        key = (slug, amt, buy)
        row = grouped.get(key)
        if row is None:
            grouped[key] = {
                "name": name, "slug": slug, "amount": amt, "buyout": buy,
                "unit": unit, "med": med, "net_u": net_u, "profit": net_u * amt,
                "roi": net_u / unit, "count": 1,
            }
        else:
            row["count"] += 1
    return list(grouped.values())


def sniper(budget=BUDGET, status=None):
    items = list(ARSENAL) + list(CONSUMABLES)
    if status:
        status(f"Выкуп, сразу {min(WORKERS, len(items))} предметов")
    grouped = {}
    done = 0
    for part in parallel(items, _sniper_item):
        done += 1
        if status and done % 4 == 0:
            status(f"Выкуп готово {done}/{len(items)}")
        if isinstance(part, Exception):
            log(str(part))
            continue
        for row in part or []:
            key = (row["slug"], row["amount"], row["buyout"])
            have = grouped.get(key)
            if have is None:
                grouped[key] = row
            else:
                have["count"] += row["count"]
    rows = sorted(grouped.values(), key=lambda r: r["roi"], reverse=True)
    chosen, left = [], budget
    for r in rows:
        if r["buyout"] > left:
            continue
        copies = min(r["count"], left // r["buyout"])
        if copies <= 0:
            continue
        item = dict(r)
        item["copies"] = copies
        item["spend"] = copies * r["buyout"]
        item["gain"] = copies * r["profit"]
        chosen.append(item)
        left -= item["spend"]
        if len(chosen) >= 12:
            break
    return chosen


def catalog():
    rows = []
    seen = set()
    groups = (
        ("Фарм", BARTER_FARM),
        ("Арсенал", ARSENAL),
        ("Убежище", list(SHELTER_BUY) + list(SHELTER_SELL)),
        ("Расходники", CONSUMABLES),
        ("Арты", ARTS),
        ("Прото", [PROTO]),
    )
    for group, items in groups:
        for slug, name in items:
            if slug in seen:
                continue
            seen.add(slug)
            rows.append((name, slug, group))
    rows.sort(key=lambda r: r[0].lower())
    return rows


AUCTION_CATS = (
    ("all", "Все предметы"),
    ("fav", "Избранное"),
    ("recent", "Недавние"),
    ("weapon", "Оружие"),
    ("armor", "Броня"),
    ("artefact", "Артефакты"),
    ("attachment", "Обвесы"),
    ("container", "Контейнеры"),
    ("backpack", "Рюкзаки"),
    ("medicine", "Медицина"),
    ("supply", "Снабжение"),
    ("grenade", "Гранаты"),
    ("bullet", "Патроны"),
    ("other", "Другое"),
)
AUCTION_CAT_KEYS = {
    "weapon": {"weapon"},
    "armor": {"armor"},
    "artefact": {"artefact"},
    "attachment": {"attachment", "weapon_modules"},
    "container": {"containers", "container"},
    "backpack": {"backpacks", "backpack"},
    "medicine": {"medicine"},
    "supply": {"supply", "food", "drink"},
    "grenade": {"grenade"},
    "bullet": {"bullet"},
    "other": {"other", "misc", "barter", "device"},
}
RANK_NAME = {
    "RANK_LEGEND": "Легенда",
    "RANK_MASTER": "Мастер",
    "RANK_VETERAN": "Ветеран",
    "RANK_STALKER": "Сталкер",
    "RANK_NEWBIE": "Новичок",
    "DEFAULT": "Обычный",
    "QUEST_ITEM": "Квест",
}
RANK_ORDER = {"RANK_LEGEND": 0, "RANK_MASTER": 1, "RANK_VETERAN": 2, "RANK_STALKER": 3, "RANK_NEWBIE": 4, "DEFAULT": 5, "QUEST_ITEM": 6}
_LISTING = None
_LISTING_LOCK = threading.Lock()
_OFF = None
_OFF_LOCK = threading.Lock()
_QUIET = None
_QUIET_LOCK = threading.Lock()
QUIET_FOR = 30 * 60
_SELL = None
_SELL_LOCK = threading.Lock()
SELL_FOR = 20 * 60


def auction_listing(force=False):
    """Каталог из официальной базы предметов EXBO. Сайт не вызывается."""
    global _LISTING
    with _LISTING_LOCK:
        if _LISTING is not None and not force:
            return _LISTING
    items = _load_catalog(force)
    off = _off_auction()
    items = [item for item in items if item["id"] not in off]
    with _LISTING_LOCK:
        _LISTING = items
    return items


def _load_catalog(force=False):
    path = DIR / "catalog.json"
    fresh = path.exists() and time.time() - path.stat().st_mtime < 3 * 86400
    if fresh and not force:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        items = _catalog_from_exbo()
    except Exception:
        if path.exists():
            log("База EXBO не скачалась, беру прошлый каталог")
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def _catalog_from_exbo():
    """Официальная база предметов EXBO. Один архив, дальше три дня из файла."""
    log("Качаю базу предметов EXBO, около 150 МБ, один раз на три дня")
    tmp = DIR / "stalzone-database.zip"
    try:
        with httpx.Client(timeout=180, follow_redirects=True) as client:
            with client.stream("GET", DB_ZIP, headers={"User-Agent": UA}) as src:
                src.raise_for_status()
                with tmp.open("wb") as dst:
                    for chunk in src.iter_bytes(1024 * 1024):
                        dst.write(chunk)
        return _items_in_zip(tmp)
    finally:
        tmp.unlink(missing_ok=True)


def _items_in_zip(path):
    found = {}
    with zipfile.ZipFile(path) as zf:
        for name in zf.namelist():
            if "/ru/items/" not in name or not name.endswith(".json"):
                continue
            stem = Path(name).stem
            if stem.isdigit():
                continue
            data = json.loads(zf.read(name))
            item_id = data.get("id") or stem
            if data.get("color") == "QUEST_ITEM":
                continue
            parts = name.split("/")
            try:
                cat = parts[parts.index("items") + 1]
            except ValueError:
                continue
            title = ((data.get("name") or {}).get("lines") or {}).get("ru") or item_id
            found[item_id] = {
                "id": item_id,
                "name": title,
                "cat": cat,
                "color": data.get("color") or "DEFAULT",
            }
    items = list(found.values())
    items.sort(key=lambda item: item["name"].lower())
    log(f"В базе EXBO {len(items)} предметов")
    return items


def _off_auction():
    """Предметы, у которых EXBO не показывает ни лотов, ни истории продаж."""
    now = time.time()
    fresh = set()
    for slug, ts in _off_map().items():
        if now - ts < 14 * 86400:
            fresh.add(slug)
    return fresh


def _off_map():
    global _OFF
    with _OFF_LOCK:
        if _OFF is None:
            path = DIR / "not_on_auction.json"
            _OFF = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _OFF = {k: float(v) for k, v in raw.items()}
                    elif isinstance(raw, list):
                        _OFF = {k: time.time() for k in raw}
                except Exception:
                    _OFF = {}
        return _OFF


def _remember_off(slug):
    global _LISTING
    book = _off_map()
    with _OFF_LOCK:
        book[slug] = time.time()
        (DIR / "not_on_auction.json").write_text(
            json.dumps(book, ensure_ascii=False), encoding="utf-8"
        )
    with _LISTING_LOCK:
        _LISTING = None


def _quiet_map():
    global _QUIET
    with _QUIET_LOCK:
        if _QUIET is None:
            path = DIR / "quiet_lots.json"
            _QUIET = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _QUIET = {k: float(v) for k, v in raw.items()}
                except Exception:
                    _QUIET = {}
        return _QUIET


def quiet_lots():
    """Пустые лоты не трогаем повторно следующие полчаса. История при этом не запрашивается."""
    now = time.time()
    return {slug for slug, ts in _quiet_map().items() if now - ts < QUIET_FOR}


def _remember_quiet(slug):
    book = _quiet_map()
    with _QUIET_LOCK:
        book[slug] = time.time()
        now = time.time()
        fresh = {key: ts for key, ts in book.items() if now - ts < QUIET_FOR}
        book.clear()
        book.update(fresh)
        try:
            (DIR / "quiet_lots.json").write_text(json.dumps(book), encoding="utf-8")
        except OSError:
            pass


def _sell_map():
    global _SELL
    with _SELL_LOCK:
        if _SELL is None:
            path = DIR / "sell_cache.json"
            _SELL = {}
            if path.exists():
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        _SELL = raw
                except Exception:
                    _SELL = {}
        return _SELL


def _sell_id(slug, key, amount):
    return f"{slug}|{amount}|{key}"


def _still_dear(slug, lots):
    """Историю не качаем, если даже прошлая обычная цена не даёт запаса."""
    book = _sell_map()
    now = time.time()
    groups = {}
    for lot in lots:
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0:
            continue
        groups.setdefault(_sell_id(slug, side_key(lot.get("additional")), amt), []).append(buy / amt)
    if not groups:
        return False
    with _SELL_LOCK:
        for sid, units in groups.items():
            hit = book.get(sid) or {}
            sell = hit.get("sell")
            ts = hit.get("ts") or 0
            if not sell or now - ts > SELL_FOR or min(units) <= sell * 0.92:
                return False
    return True


def _note_exits(slug, book):
    now = time.time()
    store = _sell_map()
    with _SELL_LOCK:
        for key, rows in (book.get("sales") or {}).items():
            by_amount = {}
            for row in rows:
                if len(row) < 3:
                    continue
                by_amount.setdefault(row[0], []).append((row[1], row[2]))
            for amount, samples in by_amount.items():
                got = _fair_exit(samples, now, 4 if key is not None else 6)
                if not got:
                    continue
                store[_sell_id(slug, key, amount)] = {"sell": got[0], "ts": now}


def flush_sells():
    book = _sell_map()
    now = time.time()
    with _SELL_LOCK:
        fresh = {key: row for key, row in book.items() if now - (row.get("ts") or 0) <= SELL_FOR}
        book.clear()
        book.update(fresh)
        try:
            (DIR / "sell_cache.json").write_text(json.dumps(book), encoding="utf-8")
        except OSError:
            pass


def _qname(qlt):
    if qlt is None:
        return "—"
    qlt = int(qlt)
    return QLT[qlt] if 0 <= qlt < len(QLT) else str(qlt)


def _stamp(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return ""
    return dt.astimezone(MSK).strftime("%d.%m %H:%M")


def _left(value):
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return ""
    sec = int((dt - datetime.now(timezone.utc)).total_seconds())
    if sec <= 0:
        return "0м"
    hours, minutes = sec // 3600, (sec % 3600) // 60
    return f"{hours}ч {minutes}м" if hours else f"{minutes}м"


def item_view(slug):
    """Живые лоты и последние продажи одного предмета с EXBO."""
    lots_raw = []
    offset = 0
    total = None
    while total is None or offset < total:
        data = get_json(
            f"{EXBO}/RU/auction/{slug}/lots?additional=true&limit=200&offset={offset}"
            "&sort=buyout_price&order=asc"
        )
        total = data.get("total") or 0
        batch = data.get("lots") or []
        if not batch:
            break
        lots_raw.extend(batch)
        offset += 200
        if offset >= 600 or offset >= total:
            break
    hist = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset=0")
    lots = []
    for lot in lots_raw:
        add = lot.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        lots.append({
            "qlt": None if qlt is None else int(qlt),
            "qname": _qname(qlt),
            "ptn": 0 if ptn is None else int(ptn),
            "amount": amt,
            "start": int(lot.get("startPrice") or 0),
            "buyout": buy,
            "unit": (buy / amt) if buy > 0 and amt > 0 else 0,
            "left": _left(lot.get("endTime")),
        })
    sales = []
    for p in hist.get("prices") or []:
        add = p.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        amt = max(int(p.get("amount") or 1), 1)
        price = int(p.get("price") or 0)
        sales.append({
            "time": _stamp(p.get("time")),
            "qlt": None if qlt is None else int(qlt),
            "qname": _qname(qlt),
            "ptn": 0 if ptn is None else int(ptn),
            "amount": amt,
            "price": price,
            "unit": price / amt,
        })
    return {"lots": lots, "sales": sales, "total": total or len(lots_raw)}


def write_buys(rows):
    now = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    body, lines = [], [f"Выкуп  {now}", "комиссия 5% с продажи. В таблицу, если после неё остаётся хотя бы 6% от вложенных и пачку ещё покупают.", ""]
    if not rows:
        body.append("<tr><td colspan='8'>Сейчас нет лота, который после 5% даст хотя бы 6% и который ещё покупают.</td></tr>")
        lines.append("выкупать нечего")
    for r in rows:
        body.append(
            "<tr>"
            f"<td>{r['name']}</td><td>{r['copies']} x {r['amount']} шт</td>"
            f"<td>{r['buyout']:,}</td><td>{r['unit']:.0f}</td><td>{r['med']:.0f}</td>"
            f"<td>{r['gain']:,.0f}</td><td>{r['roi'] * 100:.0f}%</td><td>{r['spend']:,}</td></tr>".replace(",", " ")
        )
        lines.append(r.get("plan") or (
            f"{r['name']}: выкупить {r['copies']} лот(ов) по {r['buyout']} "
            f"за {r['amount']} шт ({r['unit']:.0f}/шт, рынок {r['med']:.0f}) прибыль ~{r['gain']:.0f}"
        ))
    html = f"""<!doctype html><meta charset="utf-8"><title>Выкуп {now}</title>
<style>body{{font:15px/1.4 sans-serif;background:#111;color:#eee;margin:24px}}
table{{border-collapse:collapse;width:100%;max-width:980px}}
td,th{{border-bottom:1px solid #333;padding:6px 10px;text-align:left}}</style>
<h1>Что выкупать</h1>
<p>Обновлено {now}. Бюджет {BUDGET:,} руб.</p>
<table><tr><th>Предмет</th><th>Лоты</th><th>Выкуп</th><th>За штуку</th><th>Продают</th><th>Прибыль</th><th>Доходность</th><th>Потратить</th></tr>
{''.join(body)}</table>"""
    BUY_HTML.write_text(html, encoding="utf-8")
    (DIR / "buy_now.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"записано {BUY_HTML.name}, позиций {len(rows)}")



SELL_STACK = {"7l127": 3000}


def side_key(add):
    add = add or {}
    attrs = add.get("attributes") or []
    sig = tuple(sorted(a.get("definitionId") or "" for a in attrs if a.get("definitionId")))
    if "qlt" not in add and "ptn" not in add and not sig:
        return None
    qlt = add.get("qlt")
    ptn = add.get("ptn")
    qlt = 0 if qlt is None else int(qlt)
    ptn = 0 if ptn is None else int(ptn)
    if ptn < 0 or ptn > 15:
        ptn = 0
    base = (qlt, ptn)
    if sig:
        # Модуль без одинаковых свойств — другой предмет. Общую медиану к нему не клеим.
        return ("mod", base, sig)
    if "qlt" not in add and "ptn" not in add:
        return None
    return base


def module_name(key):
    base, sig = key[1], key[2]
    parts = []
    for raw in sig:
        parts.append(raw.replace("_pre", "").replace("_aff", "").replace("_suf", "").replace("_", " "))
    q = qlabel(base[0], base[1]) if base else ""
    return f"{q} [{', '.join(parts)}]".strip()


def market_book(slug, pages):
    key = (slug, pages)
    with _BOOK_LOCK:
        hit = _BOOK.get(key)
    if hit is not None:
        return hit
    sales = {}
    for page in range(pages):
        if HALT.is_set():
            break
        data = get_json(f"{EXBO}/RU/auction/{slug}/history?additional=true&limit=200&offset={page * 200}")
        batch = data.get("prices") or []
        for p in batch:
            amt = max(int(p.get("amount") or 1), 1)
            price = p.get("price")
            if not price:
                continue
            ts = _epoch(p.get("time"))
            sales.setdefault(side_key(p.get("additional")), []).append((amt, price / amt, ts))
        if len(batch) < 200:
            break
    live = {}
    for lot in cached_live(slug):
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0:
            continue
        unit = buy / amt
        k = side_key(lot.get("additional"))
        if k not in live or unit < live[k]:
            live[k] = unit
    book = {"sales": sales, "live": live}
    with _BOOK_LOCK:
        _BOOK[key] = book
    return book


def usual_sale(prices):
    units = [p[1] if isinstance(p, tuple) else p for p in prices]
    if len(units) < 6:
        return None
    last = units[0]
    ordered = sorted(units)
    mid = statistics.median(ordered)
    if mid <= 0:
        return None
    usable = [v for v in ordered if v >= mid * 0.4]
    if len(usable) < 6:
        return None
    return last, statistics.median(usable), len(usable)


def _epoch(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return time.time()


def drop_market(slug):
    with _BOOK_LOCK:
        for key in list(_BOOK):
            if key[0] == slug:
                _BOOK.pop(key, None)
    with _LIVE_LOCK:
        _LIVE.pop(slug, None)


def _fair_exit(samples, now, need):
    """Обычная цена без разовых многомиллионных сделок. Продажи идут от новых к старым."""
    recent = [row for row in samples if now - row[1] <= 12 * 3600]
    if len(recent) < need:
        return None
    recent.sort(key=lambda row: row[1], reverse=True)
    if now - recent[0][1] > 2 * 3600:
        return None
    units = [row[0] for row in recent[:12]]
    ordered = sorted(units)
    base = statistics.median(ordered[: max(1, len(ordered) // 2)])
    if base <= 0:
        return None
    cap = base * 2.5
    kept = [unit for unit in units if unit <= cap]
    if len(kept) < need:
        return None
    normal = [row for row in recent if row[0] <= cap]
    if len(normal) < need or now - normal[0][1] > 2 * 3600:
        return None
    span = max(now - normal[-1][1], 20 * 60)
    per_h = len(normal) / (span / 3600)
    return statistics.median(kept), per_h


def find_flips(book, slug, name, allow_single=False):
    """Лот выгоден, только если его реально покупают прямо сейчас и после комиссии есть запас."""
    now = time.time()
    offers = {}
    for lot in cached_live(slug):
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        add = lot.get("additional") or {}
        if buy <= 0 or amt <= 0 or add.get("personal_on_get"):
            continue
        key = side_key(add)
        if amt <= 1 and not (allow_single or key is not None):
            continue
        offers.setdefault((key, amt), []).append((buy / amt, buy))
    deals = []
    for (key, amt), rows in offers.items():
        hist = []
        need = 4 if key is not None else 6
        for row in book["sales"].get(key) or []:
            if row[0] != amt:
                continue
            ts = row[2] if len(row) > 2 else now
            hist.append((row[1], ts))
        got = _fair_exit(hist, now, need)
        if not got or got[1] < 0.5:
            continue
        exit_hist, per_h = got
        rows.sort()
        # Only clearing the cheapest tier can expose the next asking price.
        unit, buy = rows[0]
        j = 1
        while j < len(rows) and rows[j][1] == buy:
            j += 1
        nxt = rows[j][0] if j < len(rows) else None
        sell_at = exit_hist if nxt is None else min(exit_hist, nxt)
        net_u = sell_at * COMM - unit
        if net_u <= 0 or net_u / unit < 0.06:
            continue
        copies = j
        if copies > max(1, int(per_h * 1.5)):
            continue
        qlt_i = None
        qlt_name = ""
        ptn_s = ""
        if isinstance(key, tuple) and key and key[0] != "mod":
            qlt_i = int(key[0])
            qlt_name = QLT[qlt_i] if 0 <= qlt_i < len(QLT) else str(qlt_i)
            ptn_s = f"+{int(key[1])}"
            label = name
        elif isinstance(key, tuple) and key and key[0] == "mod":
            label = f"{name} {module_name(key)}"
        else:
            label = name
        deals.append({
            "name": label, "slug": slug, "amount": amt, "buyout": buy,
            "unit": unit, "med": sell_at, "net_u": net_u, "profit": net_u * amt,
            "roi": net_u / unit, "count": copies, "required_copies": copies, "per_h": per_h,
            "qlt": qlt_name, "ptn": ptn_s, "qlt_i": qlt_i,
        })
    deals.sort(key=lambda r: ((r["profit"] * r["per_h"]), r["profit"] * r["count"]), reverse=True)
    return deals[:3]


def sell_call(last, sold, live):
    if live is None:
        if last < sold * 0.9:
            return "ДЕРЖАТЬ", sold, f"последняя {last:.0f}, обычная {sold:.0f}, выкупа нет"
        return "СЛИТЬ", sold, f"ставь {sold:.0f}"
    if live < sold * 0.9:
        return "ДЕРЖАТЬ", sold, f"лоты просели до {live:.0f}, обычная продажа {sold:.0f}"
    ask = sold if live > sold else live
    return "СЛИТЬ", ask, f"лот {live:.0f}, продажи {sold:.0f}, ставь {ask:.0f}"


def sell_advice(item):
    slug, name = item[0], item[1]
    try:
        book = market_book(slug, 2)
    except Exception as e:
        return {"name": name, "err": str(e)}
    sales = book["sales"]
    if not sales:
        return {"name": name, "err": "нет сделок"}
    key = max(sales, key=lambda k: len(sales[k]))
    got = usual_sale(sales[key])
    if not got:
        return {"name": name, "err": "мало сделок"}
    last, sold, n = got
    act, ask, why = sell_call(last, sold, book["live"].get(key))
    stack = SELL_STACK.get(slug, 0)
    pack = ""
    if stack and ask:
        gross = stack * ask
        pack = f"{rub(gross)} на руки {rub(gross * COMM)}"
    return {
        "name": name, "last": last, "med": sold, "ask": ask,
        "farm": act, "buy": act, "why": why, "pack": pack, "deals": [], "n": n,
    }


def item_advice(item):
    slug, name = item
    try:
        book = market_book(slug, 2)
    except Exception as e:
        return {"name": name, "err": str(e)}
    sales = book["sales"]
    if not sales:
        return {"name": name, "err": "нет сделок"}
    key = max(sales, key=lambda k: len(sales[k]))
    got = usual_sale(sales[key])
    if not got:
        return {"name": name, "err": "мало сделок"}
    last, sold, n = got
    act, ask, why_sell = sell_call(last, sold, book["live"].get(key))
    deals = []
    best = book["live"].get(key)
    try:
        deals = find_flips(book, slug, name, allow_single=False)
    except Exception as e:
        return {"name": name, "last": last, "med": sold, "farm": act, "buy": "НЕ ВЫКУПАТЬ", "why": str(e), "deals": []}
    if deals:
        top = deals[0]
        buy_act = "ВЫКУПИТЬ"
        why = f"{top['amount']} шт за {int(top['buyout'])}, продашь около {top['med']:.0f}, покупок {top['per_h']:.1f} в час"
    elif best:
        buy_act = "НЕ ВЫКУПАТЬ"
        why = f"дешевле всех {best:.0f}, свежих покупок пачками мало или запаса после комиссии нет"
    else:
        buy_act = "НЕ ВЫКУПАТЬ"
        why = "выкупа пачкой нет"
    return {"name": name, "last": last, "med": sold, "ask": ask, "farm": act, "buy": buy_act, "why": why, "why_sell": why_sell, "deals": deals, "n": n}



def _skip_buy(cat, name, color=""):
    low = (name or "").lower()
    if cat in ("bullet", "grenade"):
        return True
    if "подсумок" in low:
        return True
    if any(w in low for w in ("гранатом", "гп-25", "m203", "костер")):
        return True
    if "гранат" in low and cat != "armor":
        return True
    if "пуля" in low and cat in ("misc", "other", "bullet"):
        return True
    if "ящик" in low and any(w in low for w in ("патрон", "гранат", "картеч", "дроб", "вог", "светошум", "m381", "m397")):
        return True
    if "сумка" in low and any(w in low for w in ("патрон", "дроб", "картеч", "пластин")):
        return True
    if "патрон" in low or (cat != "attachment" and "картеч" in low):
        return True
    if cat == "backpacks" and color in ("RANK_NEWBIE", "RANK_STALKER"):
        return True
    if cat in ("weapon", "armor") and color in ("RANK_NEWBIE", "RANK_STALKER"):
        return True
    return False


ERROR_NAMES = {
    "Набор для шитья", "Кислота", "Морозная смесь", "Раствор йода", "Электросмесь",
    "Нитроглицерин", "Анилин", "Антитоксин", "Ноотроп", "Сверло", "Сосуд реактора",
    "Полиэтиленовая основа", "Кевлар", "Баллон с горючей смесью",
    "Патрон 7.62 мм специальный", "Патрон 12.7 мм", "Патрон 12.7 мм ПП",
    "Патрон 12.7 мм снайперский", "Боевая пуля 23x75", "Картечь 23x75", "Баррикада",
    "Патрон 12 калибра жгучий", "Патрон 9 мм жгучий", "Патрон 5.45 мм жгучий",
    "Патрон 5.56 мм жгучий", "Патрон 7.62 мм жгучий", "Патрон 9x39 мм жгучий",
    "Патрон 10 мм бронебойный",
    "«Жребий гладиатора»", "«Горохострел»", "«JFG»", "«Ларец Пандоры»",
    "«Морозный перевал»", "«Ящеробой»", "«Мудрость Перуна»",
    "«USS-01»", "«Магмовый воин»", "«Легенда»", "«Цельнометаллический»",
    "«Взрыв красок»", "«Капеллан»", "«Печь»", "«Псих»",
    "L85A1", "Walther MPK", "АКС-74У", "HK MP5", "ПП-19 «Бизон-2-01»",
    "ПП-19-01 «Витязь»", "FN P90", "АС «Вал»",
    "Прицел оптический Trijicon ACOG", "Прицел оптический Elcan",
    "Прицел оптический Sig Sauer", "Прицел оптический Elcan M145",
    "Прицел оптический Acecare", "Прицел широкоугольный «Ракурс»",
    "Прицел оптический ПСО", "Прицел оптический ПОСП",
    "Прицел оптический ПУ на боковой кронштейн", "Прицел оптический ПУ для СВТ",
    "Прицел оптический «Тюльпан»", "Прицел коллиматорный Micro",
    "Прицел коллиматорный EoTech",
    "Теплый свитер", "Костюм «Штрих»", "«Гражданин»",
    "Тяжелый бронекостюм «Легионер»", "Защитный бронекостюм «Йорш»",
    "Солянка", "Макароны по-флотски", "Заливное", "Фасолевый суп",
    "Портативный квантовый генератор", "Псалмы «Шепота»", "Покрышка",
    "Протоартефакт", "«ClearMind+»", "Рука шныря",
    "Набор компонентов оружия (Сталкер)", "Тройник", "Контейнер 2-го уровня",
}


def buy_targets():
    """Весь продаваемый каталог. У арта каждая редкость и каждая точка считаются отдельно."""
    single_cats = {
        "artefact", "weapon", "armor", "attachment",
        "containers", "container", "backpacks", "backpack", "grenade", "device",
    }
    try:
        catalog = auction_listing()
    except Exception as e:
        log(f"каталог аукциона: {e}")
        catalog = []
    if catalog:
        rows = []
        off = _off_auction()
        quiet = quiet_lots()
        for item in catalog:
            if item["cat"] == "weapon_modules" or item["name"] in ERROR_NAMES or item["id"] in off or item["id"] in quiet or _skip_buy(item["cat"], item["name"], item.get("color")):
                continue
            rows.append((item["id"], item["name"], item["cat"] in single_cats, 1, 1))
        if PROTO[0] not in {row[0] for row in rows} and PROTO[1] not in ERROR_NAMES:
            rows.append((PROTO[0], PROTO[1], True, 1, 1))
        return rows
    seen = {}
    for slug, name in list(SHELTER_BUY) + list(CONSUMABLES):
        seen[slug] = (slug, name, False, 1, 1)
    for slug, name in ARTS:
        seen[slug] = (slug, name, True, 3, 2)
    return list(seen.values())


def _buy_one(item):
    slug, name, single, hist_pages, lot_pages = item
    if HALT.is_set():
        return []
    try:
        lots = live_lots(slug, pages=lot_pages)
        with _LIVE_LOCK:
            _LIVE[slug] = lots
        if HALT.is_set() or not lots:
            if not lots and not HALT.is_set():
                _remember_quiet(slug)
            return []
        if not any(int(lot.get("buyoutPrice") or 0) > 0 for lot in lots):
            return []
        if _still_dear(slug, lots):
            return []
        book = market_book(slug, hist_pages)
        _note_exits(slug, book)
        return find_flips(book, slug, name, allow_single=single)
    except Exception as e:
        log(f"{name}: {e}")
        return []


def parse_money(text):
    raw = str(text or "").strip().lower().replace(" ", "").replace("\u00a0", "")
    if not raw:
        return 0
    mult = 1
    if raw.endswith("кк"):
        mult = 1_000_000
        raw = raw[:-2]
    elif raw.endswith("м"):
        mult = 1_000_000
        raw = raw[:-1]
    elif raw.endswith("к"):
        mult = 1000
        raw = raw[:-1]
    raw = raw.replace(",", ".")
    if raw.count(".") > 1:
        raw = raw.replace(".", "")
    return max(0, int(float(raw) * mult))


def _hour_gain(item):
    copies = int(item.get("copies") or item.get("count") or 1)
    if copies <= 0:
        return 0.0
    gain = item.get("gain")
    if gain is None:
        gain = float(item.get("profit") or 0) * copies
    return float(gain) * float(item.get("per_h") or 0) / copies


def fit_budget(deals, budget):
    """Сначала то, что приносит больше рублей в час. Тонкий плюс на зависшем лоте уходит вниз."""
    ranked = sorted(deals, key=lambda r: (_hour_gain(r), r.get("gain") or 0), reverse=True)
    if not budget or budget <= 0:
        return ranked[:40]
    left = int(budget)
    chosen = []
    for row in ranked:
        price = int(row.get("buyout") or 0)
        if price <= 0 or price > left:
            continue
        copies = min(int(row.get("copies") or 1), left // price)
        if copies <= 0 or copies < int(row.get("required_copies") or 1):
            continue
        item = dict(row)
        item["copies"] = copies
        item["spend"] = copies * price
        item["gain"] = copies * (row.get("profit") or 0)
        item["hour_gain"] = _hour_gain(item)
        item["plan"] = _plan(item)
        chosen.append(item)
        left -= item["spend"]
        if len(chosen) >= 40:
            break
    return chosen


def buy_scan(status=None, budget=0, on_update=None):
    global _GAP
    _GAP = 0.05
    if status:
        status("Собираю каталог аукциона")
    items = buy_targets()
    items.sort(key=lambda row: 0 if row[3] > 1 else 1)
    total = len(items)
    if status:
        status(f"Выкуп по всему аукциону: {total} предметов. Таблица будет заполняться по ходу")
    deals = []
    done = 0
    if not items or HALT.is_set():
        return []
    with ThreadPoolExecutor(max_workers=AUCTION_WORKERS) as pool:
        remaining = iter(items)
        pending = set()
        def fill():
            while len(pending) < AUCTION_WORKERS and not HALT.is_set():
                item = next(remaining, None)
                if item is None:
                    break
                pending.add(pool.submit(_buy_one, item))
        fill()
        try:
            while pending and not HALT.is_set():
                finished, pending = wait(pending, timeout=0.2, return_when=FIRST_COMPLETED)
                for fut in finished:
                    if HALT.is_set():
                        break
                    done += 1
                    try:
                        part = fut.result()
                    except Exception:
                        part = []
                    changed = False
                    if isinstance(part, list) and part:
                        deals.extend(_as_buys(part))
                        changed = True
                    if changed or done % 15 == 0 or done == total:
                        shown = fit_budget(deals, budget)
                        if status:
                            status(f"Выкуп {done}/{total}, в бюджете {len(shown)}")
                        if on_update and (changed or done == total):
                            on_update(shown, done, total)
                fill()
        finally:
            for fut in pending:
                fut.cancel()
            flush_sells()
    return fit_budget(deals, budget)


def _flip_arts(item):
    slug, name = item
    try:
        return find_flips(market_book(slug, 4), slug, name, allow_single=True)
    except Exception:
        return []


def _plan(item):
    if "med" not in item or "amount" not in item:
        return item.get("plan") or ""
    copies = int(item.get("copies") or item.get("count") or 1)
    buy = int(item["buyout"])
    ask = float(item["med"]) * int(item["amount"])
    hand = ask * COMM
    gain = float(item.get("gain") or 0)
    spent = copies * buy
    roi = gain / spent * 100 if spent else 0
    hour = _hour_gain(item)
    return (
        f"Купи {copies} по {buy}. Выстави пачку за {ask:.0f}. "
        f"После 5% придёт {hand:.0f}. Плюс {gain:.0f} ({roi:.0f}%). "
        f"Плюс в час {hour:.0f}."
    )


def _as_buys(deals):
    found = []
    for deal in deals:
        item = dict(deal)
        item["copies"] = item["count"]
        item["spend"] = item["copies"] * item["buyout"]
        item["gain"] = item["copies"] * item["profit"]
        item["hour_gain"] = _hour_gain(item)
        item["plan"] = _plan(item)
        found.append(item)
    return found


def _pack(rows):
    out = []
    for row in rows:
        if isinstance(row, Exception):
            out.append({"name": "позиция", "err": str(row)})
        elif row:
            out.append(row)
    return out


def proto_deals():
    slug, name = PROTO
    try:
        sales = sale_points(art_history(slug))
        lots = cached_live(slug)
    except Exception as e:
        return [{"name": name, "err": str(e)}]
    by = {}
    for price, qlt, ptn in sales:
        by.setdefault((qlt, ptn), []).append(price)
    best = {}
    for lot in lots:
        add = lot.get("additional") or {}
        qlt = add.get("qlt")
        ptn = add.get("ptn")
        if qlt is None:
            qlt = 0
        if ptn is None:
            ptn = 0
        qlt, ptn = int(qlt), int(ptn)
        buy = int(lot.get("buyoutPrice") or 0)
        amt = int(lot.get("amount") or 0)
        if buy <= 0 or amt <= 0:
            continue
        unit = buy / amt
        key = (qlt, ptn)
        if key not in best or unit < best[key]:
            best[key] = unit
    rows = []
    for (qlt, ptn), vals in sorted(by.items()):
        qname = qlabel(qlt, ptn)
        if len(vals) < ART_MIN_SALES:
            rows.append({"name": name, "qlt": qname, "n": len(vals), "buy": "МАЛО ДАННЫХ", "farm": "ДЕРЖАТЬ", "cheap": 0, "med": 0, "net": 0})
            continue
        last = vals[0]
        ordered = sorted(vals)
        med = statistics.median(ordered)
        low = ordered[max(0, int(len(ordered) * 0.10) - 1)]
        net = med * COMM - low
        unit = best.get((qlt, ptn))
        if unit and unit <= med * BUY_AT and med * COMM - unit > 0:
            buy = "ВЫКУПИТЬ"
            cheap = unit
            net = med * COMM - unit
        elif net > 0 and low <= med * BUY_AT:
            buy = "ВЫКУПАТЬ НИЖЕ"
            cheap = low
        else:
            buy = "НЕ ВЫКУПАТЬ"
            cheap = unit or low
            net = (med * COMM - cheap) if cheap else 0
        farm = "ДЕРЖАТЬ" if med and last < med * 0.9 else "СЛИТЬ"
        rows.append({"name": name, "qlt": qname, "n": len(vals), "buy": buy, "farm": farm, "cheap": cheap, "med": med, "net": net})
    rows.sort(key=lambda r: r.get("net") or 0, reverse=True)
    return rows


def run_once(status=None, only=None, budget=0, on_update=None):
    _HIST.clear()
    _LIVE.clear()
    _BOOK.clear()
    log("прогон старт" if not only else f"прогон: {only}")

    def say(msg):
        log(msg)
        if status:
            status(msg)

    want = only or None
    out = {}
    if want == "buys":
        deals = buy_scan(say, budget, on_update)
        out["buys"] = deals
        if deals:
            spent = sum(r["spend"] for r in deals)
            gain = sum(r["gain"] for r in deals)
            say(f"Выкуп: {len(deals)} лотов, вложено {rub(spent)} из {rub(budget)}, плюс {rub(gain)}")
            if not HALT.is_set():
                write_buys(deals)
        else:
            say("Выкуп: сейчас нет лота, который купят и который даст плюс")
        log("выкуп готов")
        return out
    out = {}
    sell_rank = {"ДЕРЖАТЬ": 0, "СЛИТЬ": 1}
    buy_rank = {"ВЫКУПИТЬ": 0, "НЕ ВЫКУПАТЬ": 1}

    def sell_sort(rows):
        rows.sort(key=lambda r: (sell_rank.get(r.get("farm"), 2), -(r.get("med") or 0)))
        return rows

    def buy_sort(rows):
        rows.sort(key=lambda r: (buy_rank.get(r.get("buy"), 2), r.get("name") or ""))
        return rows

    if want in (None, "farm") and not HALT.is_set():
        say(f"Фарм, цена продажи: {len(BARTER_FARM)}")
        out["farm"] = sell_sort(_pack(parallel(BARTER_FARM, sell_advice)))
    if want in (None, "arsenal") and not HALT.is_set():
        say(f"Арсенал, цена продажи: {len(ARSENAL)}")
        out["arsenal"] = sell_sort(_pack(parallel(ARSENAL, sell_advice)))
    if want in (None, "shelter_buy") and not HALT.is_set():
        say(f"Убежище, купить материалы: {len(SHELTER_BUY)}")
        out["shelter_buy"] = buy_sort(_pack(parallel(SHELTER_BUY, item_advice)))
    if want in (None, "shelter_sell") and not HALT.is_set():
        say(f"Убежище, продать готовое: {len(SHELTER_SELL)}")
        out["shelter_sell"] = sell_sort(_pack(parallel(SHELTER_SELL, sell_advice)))
    if want in (None, "consumables") and not HALT.is_set():
        say(f"Расходники, {len(CONSUMABLES)} позиций")
        out["consumables"] = buy_sort(_pack(parallel(CONSUMABLES, item_advice)))
    if want in (None, "arts") and not HALT.is_set():
        say("Популярные арты")
        arts, checked = art_deals()
        out["arts"] = [r for r in arts if (r.get("net") or 0) > 0 or r.get("err")]
        out["checked"] = checked
    buys = []
    if "shelter_buy" in out or "consumables" in out:
        for row in out.get("shelter_buy", []) + out.get("consumables", []):
            buys.extend(_as_buys(row.get("deals") or []))
    if want in (None, "arts") and not HALT.is_set():
        say("Перекуп артов, только то что покупают")
        for part in parallel(ARTS, _flip_arts):
            if isinstance(part, list):
                buys.extend(_as_buys(part))
    if buys:
        buys = fit_budget(buys, budget)
        out["buys"] = buys
        spent = sum(r["spend"] for r in buys)
        gain = sum(r["gain"] for r in buys)
        say(f"Выкуп: {len(buys)} лотов, вложено {rub(spent)} из {rub(budget)}, плюс {rub(gain)}")
        if not HALT.is_set():
            write_buys(buys)
    elif want in (None, "shelter_buy", "consumables", "arts"):
        out["buys"] = []
        say("Выкуп: сейчас нет лота, который купят и который даст плюс")
    if want in (None, "protos") and not HALT.is_set():
        say("Протоартефакты")
        out["protos"] = proto_deals()
    log("раздел готов" if want else "общий прогон готов")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--once", action="store_true")
    p.add_argument("--every", type=int, default=30)
    p.add_argument("--buys", action="store_true")
    args = p.parse_args()
    if args.buys:
        log("считаю выгодный выкуп")
        write_buys(sniper())
        return
    run_once()
    if args.once:
        return
    log(f"фон каждые {args.every} мин. остановить: Ctrl+C")
    while True:
        time.sleep(max(args.every, 5) * 60)
        try:
            run_once()
        except Exception:
            log(traceback.format_exc())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("стоп")
        sys.exit(0)
