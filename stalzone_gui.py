# -*- coding: utf-8 -*-
"""Окно агента: разделы цен, прогон, автопрогон, стоп и лог."""
import json
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import ttk
import sys

import stalzone_agent as agent


def money(n):
    return agent.rub(n)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("STALZONE")
        self.root.geometry("1180x760")
        self.root.minsize(960, 600)
        self.root.configure(bg="#14120f")
        self.worker = None
        self.ui = queue.Queue()
        self._watch = []
        self._style()
        self._build()
        self.log("Ждёт. Вкладка «Аукцион» — поиск по всему каталогу, лоты и история.")
        from stalzone_overlay import Overlay
        self.overlay = Overlay(self, agent.DIR / 'overlay_settings.json')
        self._pump_id = self.root.after(150, self._pump)

    def _style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#14120f", borderwidth=0)
        style.configure("TNotebook.Tab", background="#221e18", foreground="#d9d3c7", padding=[16, 8], borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", "#3a3122")], foreground=[("selected", "#f0d7a2")])
        style.configure("Treeview", background="#1b1814", fieldbackground="#1b1814", foreground="#efeae2", rowheight=28, borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background="#2a251c", foreground="#cbbfa8", relief="flat", font=("Segoe UI", 10, "bold"))
        style.map("Treeview", background=[("selected", "#4a3b24")])
        style.configure("Gold.TButton", background="#e0b15a", foreground="#1a140c", padding=[14, 8], font=("Segoe UI", 10, "bold"), borderwidth=0)
        style.map("Gold.TButton", background=[("active", "#f0d7a2"), ("disabled", "#6a5a3a")])
        style.configure("Dark.TButton", background="#2a251c", foreground="#f0d7a2", padding=[14, 8], font=("Segoe UI", 10), borderwidth=0)
        style.map("Dark.TButton", background=[("active", "#3a3122"), ("disabled", "#221e18")])
        style.configure("Stop.TButton", background="#6b3030", foreground="#f6d0c8", padding=[14, 8], font=("Segoe UI", 10), borderwidth=0)
        style.map("Stop.TButton", background=[("active", "#8a3c3c"), ("disabled", "#2a2220")])

    def _build(self):
        self.full_frame = tk.Frame(self.root, bg="#14120f")
        self.full_frame.pack(fill='both', expand=True)
        top = tk.Frame(self.full_frame, bg="#14120f")
        self.full_header = top
        top.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(top, text="STALZONE", bg="#14120f", fg="#f0d7a2", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Button(top, text='Свернуть в оверлей', style='Dark.TButton',
                   command=lambda: self.overlay.collapse()).pack(side='right')
        self.state = tk.StringVar(value="ожидание")
        tk.Label(top, textvariable=self.state, bg="#14120f", fg="#9c9486", font=("Segoe UI", 11)).pack(side="left", padx=16)

        bar = tk.Frame(self.full_frame, bg="#14120f")
        bar.pack(fill="x", padx=16, pady=(0, 8))
        self.btn_run = ttk.Button(bar, text="Прогон", style="Gold.TButton", command=self.start_once)
        self.btn_run.pack(side="left")
        self.btn_auto = ttk.Button(bar, text="Автопрогон", style="Dark.TButton", command=self.start_auto)
        self.btn_auto.pack(side="left", padx=8)
        self.btn_live = ttk.Button(bar, text="Онлайн", style="Dark.TButton", command=self.start_live)
        self.btn_live.pack(side="left")
        tk.Label(bar, text="каждые", bg="#14120f", fg="#9c9486", font=("Segoe UI", 10)).pack(side="left")
        self.minutes = ttk.Spinbox(bar, from_=1, to=180, width=5, font=("Segoe UI", 11), justify="center")
        self.minutes.set("30")
        self.minutes.pack(side="left", padx=6)
        tk.Label(bar, text="мин", bg="#14120f", fg="#9c9486", font=("Segoe UI", 10)).pack(side="left")
        tk.Label(bar, text="бюджет", bg="#14120f", fg="#9c9486", font=("Segoe UI", 10)).pack(side="left", padx=(12, 4))
        saved = "5000000"
        budget_path = agent.DIR / "flip_budget.txt"
        if budget_path.exists():
            saved = budget_path.read_text(encoding="utf-8").strip() or saved
        self.budget = tk.StringVar(value=saved)
        self.budget_box = tk.Entry(bar, textvariable=self.budget, width=12, bg="#100e0c", fg="#efeae2", insertbackground="#efeae2", relief="flat", font=("Segoe UI", 11), justify="center")
        self.budget_box.pack(side="left", ipady=4)
        self.btn_stop = ttk.Button(bar, text="Стоп", style="Stop.TButton", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=12)
        self.section_map = {
            "Общий": None,
            "Выкуп": "buys",
            "Фарм": "farm",
            "Арсенал": "arsenal",
            "Убежище купить": "shelter_buy",
            "Убежище продать": "shelter_sell",
            "Расходники": "consumables",
            "Арты": "arts",
            "Протоартефакты": "protos",
        }
        self.section = tk.StringVar(value="Общий")
        self.section_box = ttk.Combobox(bar, textvariable=self.section, values=list(self.section_map), width=18, state="readonly", font=("Segoe UI", 10))
        self.section_box.pack(side="left", padx=8)

        book = ttk.Notebook(self.full_frame)
        book.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.trees = {}
        specs = [
            ("Выкуп", ("Предмет", "Редкость", "Точка", "Лоты", "Цена лота", "За штуку", "Продашь", "Сумма пачки", "Прибыль", "В час", "Решение")),
            ("Фарм", ("Предмет", "Продают", "Продавать от", "Пачка", "Решение")),
            ("Арсенал", ("Предмет", "Продают", "Продавать от", "Решение")),
            ("Убежище купить", ("Предмет", "Продают", "Выкуп", "Решение")),
            ("Убежище продать", ("Предмет", "Продают", "Продавать от", "Решение")),
            ("Расходники", ("Предмет", "Продают", "Выкуп", "Фарм")),
            ("Арты", ("Арт", "Редкость", "Точка", "Сделок", "Покупали", "Продавали", "Профит", "Решение")),
            ("Протоартефакты", ("Редкость", "Сделок", "Выкуп", "Фарм", "Цена", "Продают", "Профит")),
        ]
        for title, cols in specs:
            frame = tk.Frame(book, bg="#1b1814")
            book.add(frame, text=title)
            tree = ttk.Treeview(frame, columns=cols, show="headings")
            tree._order = {}
            for col in cols:
                tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_col(t, c))
                width = 260 if col in ("Предмет", "Арт", "Выкуп", "Решение", "Редкость", "Пачка", "Сумма пачки", "Продавать от") else 90
                tree.column(col, width=width, anchor="w")
            scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            tree.configure(yscrollcommand=scroll.set)
            tree.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            menu = tk.Menu(tree, tearoff=0, bg="#2a251c", fg="#efeae2")
            menu.add_command(label="Копировать название", command=lambda t=tree: self._copy_name(t))
            tree.bind("<Button-3>", lambda e, t=tree, m=menu: self._popup(e, t, m))
            tree.bind("<Control-c>", lambda e, t=tree: self._copy_name(t))
            tree.bind("<Control-C>", lambda e, t=tree: self._copy_name(t))
            tree.bind("<Double-1>", lambda e, t=tree: self._copy_name(t))
            tree.tag_configure("buy", foreground="#9dccff")
            tree.tag_configure("sell", foreground="#9ddeaf")
            tree.tag_configure("hold", foreground="#e0b15a")
            tree.tag_configure("skip", foreground="#8d877c")
            for qi, color in (
                (0, "#c8c2b8"),
                (1, "#7dcea0"),
                (2, "#5dade2"),
                (3, "#c39bd3"),
                (4, "#e07a7a"),
                (5, "#f0d78c"),
            ):
                tree.tag_configure(f"q{qi}", foreground=color)
            self.trees[title] = tree

        self._build_lots(book)

        tk.Label(self.full_frame, text="Лог", bg="#14120f", fg="#9c9486", anchor="w", font=("Segoe UI", 10)).pack(fill="x", padx=16)
        self.box = tk.Text(self.full_frame, height=6, bg="#100e0c", fg="#e6e0d6", insertbackground="#e6e0d6", relief="flat", font=("Consolas", 10), wrap="word")
        self.box.pack(fill="x", padx=16, pady=(0, 14))
        self.box.configure(state="disabled")

    def _build_lots(self, book):
        frame = tk.Frame(book, bg="#1b1814")
        book.add(frame, text="Аукцион")
        bar = tk.Frame(frame, bg="#1b1814")
        bar.pack(fill="x", padx=8, pady=(8, 4))
        self.auc_query = tk.StringVar()
        search = tk.Entry(bar, textvariable=self.auc_query, width=28, bg="#100e0c", fg="#efeae2", insertbackground="#efeae2", relief="flat", font=("Segoe UI", 11))
        search.pack(side="left", ipady=4)
        search.bind("<KeyRelease>", lambda e: self._render_auction())
        self.auc_cat = tk.StringVar(value="Все предметы")
        self.auc_cat_box = ttk.Combobox(bar, textvariable=self.auc_cat, values=[title for _key, title in agent.AUCTION_CATS], width=16, state="readonly", font=("Segoe UI", 10))
        self.auc_cat_box.pack(side="left", padx=8)
        self.auc_cat_box.bind("<<ComboboxSelected>>", lambda e: self._render_auction())
        self.auc_sort = tk.StringVar(value="По имени")
        sort = ttk.Combobox(bar, textvariable=self.auc_sort, values=["По имени", "По рангу"], width=12, state="readonly", font=("Segoe UI", 10))
        sort.pack(side="left")
        sort.bind("<<ComboboxSelected>>", lambda e: self._render_auction())
        ttk.Button(bar, text="В избранное", style="Dark.TButton", command=self._toggle_fav).pack(side="left", padx=8)
        self._auction = []
        self._fav = set(self._read_json("auction_fav.json"))
        self._recent = self._read_json("auction_recent.json")
        self._lot_data = None
        self._lot_name = ""
        self._open_slug = None
        pane = tk.PanedWindow(frame, orient="horizontal", bg="#14120f", sashwidth=6, sashrelief="flat")
        pane.pack(fill="both", expand=True, padx=8, pady=4)
        left = tk.Frame(pane, bg="#1b1814")
        right = tk.Frame(pane, bg="#1b1814")
        pane.add(left, minsize=300)
        pane.add(right, minsize=520)
        self.item_tree = ttk.Treeview(left, columns=("Предмет", "Раздел", "Ранг"), show="headings")
        self.item_tree._order = {}
        for col, width in (("Предмет", 220), ("Раздел", 110), ("Ранг", 90)):
            self.item_tree.heading(col, text=col)
            self.item_tree.column(col, width=width, anchor="w")
        for rank, color in (
            ("RANK_LEGEND", "#e0b15a"), ("RANK_MASTER", "#e07a7a"), ("RANK_VETERAN", "#c4a3ff"),
            ("RANK_STALKER", "#8ebfff"), ("RANK_NEWBIE", "#9ddeaf"), ("DEFAULT", "#efeae2"), ("QUEST_ITEM", "#efeae2"),
        ):
            self.item_tree.tag_configure(rank, foreground=color)
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.item_tree.yview)
        self.item_tree.configure(yscrollcommand=scroll.set)
        self.item_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.item_tree.bind("<Double-1>", lambda e: self.show_lots())
        self.item_tree.bind("<Return>", lambda e: self.show_lots())
        filters = tk.Frame(right, bg="#1b1814")
        filters.pack(fill="x", pady=(0, 4))
        tk.Label(filters, text="Редкость", bg="#1b1814", fg="#9c9486", font=("Segoe UI", 10)).pack(side="left")
        self.lot_q = tk.StringVar(value="Все")
        qbox = ttk.Combobox(filters, textvariable=self.lot_q, values=["Все", *agent.QLT], width=16, state="readonly", font=("Segoe UI", 10))
        qbox.pack(side="left", padx=4)
        qbox.bind("<<ComboboxSelected>>", self._refill_open)
        tk.Label(filters, text="Заточка", bg="#1b1814", fg="#9c9486", font=("Segoe UI", 10)).pack(side="left", padx=(8, 4))
        self.lot_ptn_min = ttk.Spinbox(filters, from_=0, to=15, width=3, font=("Segoe UI", 10), command=self._refill_open)
        self.lot_ptn_max = ttk.Spinbox(filters, from_=0, to=15, width=3, font=("Segoe UI", 10), command=self._refill_open)
        self.lot_ptn_min.set("0")
        self.lot_ptn_max.set("15")
        self.lot_ptn_min.pack(side="left")
        tk.Label(filters, text="—", bg="#1b1814", fg="#9c9486").pack(side="left", padx=2)
        self.lot_ptn_max.pack(side="left")
        ttk.Button(filters, text="Открыть", style="Gold.TButton", command=self.show_lots).pack(side="left", padx=8)
        self.lot_info = tk.StringVar(value="Каталог грузится…")
        tk.Label(right, textvariable=self.lot_info, bg="#1b1814", fg="#cbbfa8", anchor="w", font=("Segoe UI", 10)).pack(fill="x")
        inner = ttk.Notebook(right)
        inner.pack(fill="both", expand=True, pady=4)
        self.lot_tree = self._make_tree(inner, "Сейчас", ("Качество", "Заточка", "Штук", "Ставка", "Выкуп", "За штуку", "Осталось"))
        self.sale_tree = self._make_tree(inner, "История", ("Когда", "Качество", "Заточка", "Штук", "Цена", "За штуку"))
        threading.Thread(target=self._load_auction, daemon=True).start()

    def _read_json(self, name):
        path = agent.DIR / name
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _write_json(self, name, data):
        (agent.DIR / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_auction(self):
        try:
            items = agent.auction_listing()
        except Exception as e:
            self.root.after(0, lambda err=e: self.lot_info.set(f"Каталог не загрузился: {err}"))
            return
        self._auction = items
        self.root.after(0, self._render_auction)

    def _cat_key(self):
        title = self.auc_cat.get()
        for key, name in agent.AUCTION_CATS:
            if name == title:
                return key
        return "all"

    def _render_auction(self):
        if not self._auction:
            return
        query = self.auc_query.get().strip().casefold()
        key = self._cat_key()
        items = list(self._auction)
        if key == "fav":
            items = [i for i in items if i["id"] in self._fav]
        elif key == "recent":
            order = {slug: n for n, slug in enumerate(self._recent)}
            items = [i for i in items if i["id"] in order]
            items.sort(key=lambda i: order[i["id"]])
        else:
            allowed = agent.AUCTION_CAT_KEYS.get(key)
            if key == "other":
                named = set().union(*agent.AUCTION_CAT_KEYS.values())
                items = [i for i in items if i["cat"] in allowed or i["cat"] not in named]
            elif allowed:
                items = [i for i in items if i["cat"] in allowed]
            if self.auc_sort.get() == "По рангу":
                items.sort(key=lambda i: (agent.RANK_ORDER.get(i["color"], 9), i["name"].casefold()))
            else:
                items.sort(key=lambda i: i["name"].casefold())
        if query:
            items = [i for i in items if query in i["name"].casefold() or query in i["id"].casefold()]
        shown = items[:500]
        kids = self.item_tree.get_children()
        if kids:
            self.item_tree.delete(*kids)
        seen = set()
        for item in shown:
            iid = item["id"]
            if iid in seen:
                continue
            seen.add(iid)
            self.item_tree.insert("", "end", iid=iid, values=(item["name"], item["cat"], agent.RANK_NAME.get(item["color"], item["color"])), tags=(item["color"],))
        self.lot_info.set(f"Найдено {len(items)}. Показано {len(shown)}. Двойной клик открывает лоты и историю.")

    def _toggle_fav(self):
        sel = self.item_tree.selection()
        if not sel:
            return
        slug = sel[0]
        if slug in self._fav:
            self._fav.remove(slug)
            self.log("Убрано из избранного")
        else:
            self._fav.add(slug)
            self.log("Добавлено в избранное")
        self._write_json("auction_fav.json", sorted(self._fav))
        if self._cat_key() == "fav":
            self._render_auction()

    def _refill_open(self, *_args):
        if self._lot_data and self._open_slug:
            self._fill_lots(self._lot_name, self._lot_data)

    def show_lots(self):
        sel = self.item_tree.selection()
        if not sel:
            self.log("Выбери предмет слева")
            return
        slug = sel[0]
        name = self.item_tree.set(sel[0], "Предмет")
        self._open_slug = slug
        self._lot_name = name
        self._recent = [slug] + [x for x in self._recent if x != slug]
        self._recent = self._recent[:30]
        self._write_json("auction_recent.json", self._recent)
        self.lot_info.set(f"{name}: читаю лоты…")

        def job():
            try:
                data = agent.item_view(slug)
            except Exception as e:
                self.root.after(0, lambda err=e: self.lot_info.set(f"Ошибка: {err}"))
                return
            self._lot_data = data
            self.root.after(0, lambda: self._fill_lots(name, data))

        threading.Thread(target=job, daemon=True).start()

    def _make_tree(self, book, title, cols):
        frame = tk.Frame(book, bg="#1b1814")
        book.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        tree._order = {}
        for col in cols:
            tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_col(t, c))
            tree.column(col, width=150 if col in ("Качество", "Когда") else 100, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        menu = tk.Menu(tree, tearoff=0, bg="#2a251c", fg="#efeae2")
        menu.add_command(label="Копировать строку", command=lambda t=tree: self._copy_row(t))
        tree.bind("<Button-3>", lambda e, t=tree, m=menu: self._popup(e, t, m))
        tree.bind("<Control-c>", lambda e, t=tree: self._copy_row(t))
        tree.tag_configure("buy", foreground="#9dccff")
        tree.tag_configure("skip", foreground="#8d877c")
        for qi, color in (
            (0, "#c8c2b8"),
            (1, "#7dcea0"),
            (2, "#5dade2"),
            (3, "#c39bd3"),
            (4, "#e07a7a"),
            (5, "#f0d78c"),
        ):
            tree.tag_configure(f"q{qi}", foreground=color)
        return tree

    def _pass_lot(self, row):
        qname = self.lot_q.get()
        if qname != "Все" and row["qname"] != qname:
            return False
        try:
            lo = int(self.lot_ptn_min.get() or 0)
            hi = int(self.lot_ptn_max.get() or 15)
        except ValueError:
            lo, hi = 0, 15
        if row["qlt"] is not None and not lo <= row["ptn"] <= hi:
            return False
        return True

    def _fill_lots(self, name, data):
        lots = [r for r in data["lots"] if self._pass_lot(r)]
        sales = [r for r in data["sales"] if self._pass_lot(r)]
        lot_rows = []
        for r in lots:
            buy = money(r["buyout"]) if r["buyout"] else "—"
            unit = f"{r['unit']:.0f}" if r["unit"] else "—"
            start = money(r["start"]) if r["start"] else "—"
            ptn = f"+{r['ptn']}" if r["qlt"] is not None else "—"
            tag = f"q{r['qlt']}" if r["qlt"] is not None else ("buy" if r["buyout"] else "skip")
            lot_rows.append(((r["qname"], ptn, r["amount"], start, buy, unit, r["left"]), tag))
        sale_rows = []
        for r in sales:
            ptn = f"+{r['ptn']}" if r["qlt"] is not None else "—"
            tag = f"q{r['qlt']}" if r["qlt"] is not None else "skip"
            sale_rows.append(((r["time"], r["qname"], ptn, r["amount"], money(r["price"]), f"{r['unit']:.0f}"), tag))
        self._put_tree(self.lot_tree, lot_rows)
        self._put_tree(self.sale_tree, sale_rows)
        priced = [r["unit"] for r in lots if r["unit"]]
        cheap = min(priced) if priced else 0
        self.lot_info.set(
            f"{name}: на аукционе {data['total']}, показано {len(lots)}. "
            + (f"Самый дешёвый выкуп {money(cheap)} за штуку." if cheap else "С выкупом ничего нет.")
        )
        self.log(self.lot_info.get())

    def _put_tree(self, tree, rows):
        kids = tree.get_children()
        if kids:
            tree.delete(*kids)
        for values, tag in rows:
            tree.insert("", "end", values=values, tags=(tag,))

    def _copy_row(self, tree):
        sel = tree.selection()
        if not sel:
            return "break"
        text = "  ".join(str(v) for v in tree.item(sel[0], "values"))
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.log(f"Скопировано: {text}")
        return "break"

    def log(self, msg):
        line = f"{time.strftime('%H:%M:%S')}  {msg}\n"
        self.box.configure(state="normal")
        self.box.insert("end", line)
        self.box.see("end")
        last = int(float(self.box.index("end-1c")))
        if last > 80:
            self.box.delete("1.0", f"{last - 80}.0")
        self.box.configure(state="disabled")
        self.state.set(msg[:80])

    def post(self, msg):
        self.ui.put(("log", msg))

    def show(self, data):
        self.ui.put(("fill", data))

    def _pump(self):
        try:
            while True:
                kind, payload = self.ui.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "fill":
                    self.fill(payload)
                elif kind == "busy":
                    self._busy(payload)
        except queue.Empty:
            pass
        self._pump_id = self.root.after(150, self._pump)

    def _busy(self, on):
        self.overlay.set_busy(on)
        state = "disabled" if on else "normal"
        self.btn_run.configure(state=state)
        self.btn_auto.configure(state=state)
        self.btn_live.configure(state=state)
        self.btn_stop.configure(state="normal" if on else "disabled")
        self.minutes.configure(state=state)
        self.budget_box.configure(state=state)
        self.section_box.configure(state="disabled" if on else "readonly")

    def start_live(self):
        items = [i for i in self._auction if i["id"] in self._fav][:25]
        if not items and self._watch:
            by_id = {i["id"]: i for i in self._auction}
            items = [by_id[slug] for slug in self._watch if slug in by_id][:25]
        if not items:
            self.log("Онлайн следит за избранным или за текущим выкупом. Отметь предметы или дождись первого прогона.")
            return
        self.log(f"Нажат «Онлайн», предметов {len(items)}")
        try:
            self._launch_live(items)
        except Exception as e:
            self.log(f"Онлайн не стартовал: {e}")
            self.ui.put(("busy", False))

    def _launch_live(self, items):
        if self.worker and self.worker.is_alive():
            return
        agent.HALT.clear()
        self._busy(True)
        budget = self._budget()
        self.worker = threading.Thread(target=self._live_job, args=(items, budget), daemon=True)
        self.worker.start()

    def _budget(self):
        try:
            value = agent.parse_money(self.budget.get())
        except Exception:
            value = 5_000_000
        try:
            (agent.DIR / "flip_budget.txt").write_text(str(value), encoding="utf-8")
        except Exception:
            pass
        return value

    def _live_job(self, items, budget):
        while not agent.HALT.is_set():
            deals = []
            for it in items:
                if agent.HALT.is_set():
                    break
                try:
                    agent.drop_market(it["id"])
                    book = agent.market_book(it["id"], 1)
                    single = it.get("cat") != "other" and it.get("cat") not in ("misc", "supply", "bullet", "medicine")
                    deals.extend(agent._as_buys(agent.find_flips(book, it["id"], it["name"], allow_single=single or it.get("cat") == "artefact")))
                except Exception as e:
                    self.post(f"{it['name']}: {e}")
                shown = agent.fit_budget(deals, budget)
                self.show({"buys": shown})
                self.post(f"Онлайн: {it['name']}, в таблице {len(shown)}")
            for _ in range(3):
                if agent.HALT.is_set():
                    break
                time.sleep(1)
        self.post("Онлайн остановлен")
        self.ui.put(("busy", False))

    def start_once(self):
        self.log("Нажата кнопка «Прогон»")
        try:
            self._launch(False)
        except Exception as e:
            self.log(f"Прогон не стартовал: {e}")
            self._busy(False)

    def start_auto(self):
        self.log("Нажата кнопка «Автопрогон»")
        try:
            self._launch(True)
        except Exception as e:
            self.log(f"Автопрогон не стартовал: {e}")
            self._busy(False)

    def _launch(self, auto):
        if self.worker and self.worker.is_alive():
            return
        try:
            mins = max(1, int(self.minutes.get()))
        except ValueError:
            mins = 30
        only = self.section_map.get(self.section.get())
        if only != "buys":
            mins = max(5, mins)
        agent.HALT.clear()
        self._busy(True)
        only = self.section_map.get(self.section.get())
        title = self.section.get()
        self.log(("Автопрогон: " if auto else "Прогон: ") + title)
        budget = self._budget()
        self.worker = threading.Thread(target=self._job, args=(auto, mins, only, budget), daemon=True)
        self.worker.start()

    def stop(self):
        agent.HALT.set()
        self.log("Стоп")

    def _job(self, auto, mins, only, budget):
        while not agent.HALT.is_set():
            self.post("Читаю цены")
            try:
                def on_update(deals, done, total):
                    self.show({"buys": list(deals)})
                    self.post(f"Выкуп {done}/{total}, в таблице {len(deals)}")
                data = agent.run_once(status=self.post, only=only, budget=budget, on_update=on_update if only == "buys" else None)
            except Exception as e:
                self.post(f"Ошибка: {e}")
                data = {}
            if agent.HALT.is_set():
                self.post("Прогон остановлен")
                break
            self.show(data or {})
            n = len((data or {}).get("buys") or [])
            self.post("Готово" if only else f"Готово. Выкупать позиций: {n}")
            if not auto:
                break
            self.post(f"Дальше цены выкупа обновляются сразу, полный круг через {mins} мин")
            deadline = time.time() + mins * 60
            while time.time() < deadline and not agent.HALT.is_set():
                slugs = list(self._watch)
                if slugs and only == "buys":
                    fresh = self._refresh(slugs, budget)
                    self.show({"buys": fresh})
                    spent = sum(r["spend"] for r in fresh)
                    self.post(f"Сейчас: {len(fresh)} лотов, вложено {agent.rub(spent)}")
                for _ in range(12):
                    if agent.HALT.is_set() or time.time() >= deadline:
                        break
                    time.sleep(1)
            if agent.HALT.is_set():
                self.post("Автопрогон остановлен")
                break
        self.ui.put(("busy", False))

    def _refresh(self, slugs, budget):
        by_id = {i["id"]: i for i in self._auction}
        stack_cats = {"other", "misc", "supply", "bullet", "medicine"}
        deals = []
        for slug in slugs:
            if agent.HALT.is_set():
                break
            info = by_id.get(slug) or {"id": slug, "name": slug, "cat": ""}
            try:
                agent.drop_market(slug)
                book = agent.market_book(slug, 1)
                single = info.get("cat") not in stack_cats
                deals.extend(agent._as_buys(agent.find_flips(book, slug, info.get("name") or slug, allow_single=single)))
            except Exception as e:
                self.post(f"{info.get('name') or slug}: {e}")
        return agent.fit_budget(deals, budget)

    def _put(self, title, rows):
        tree = self.trees[title]
        kids = tree.get_children()
        if kids:
            tree.delete(*kids)
        for values, tag in rows:
            tree.insert("", "end", values=values, tags=(tag,))
        if tree._order:
            col, desc = next(iter(tree._order.items()))
            self._apply_sort(tree, col, desc)

    def _popup(self, event, tree, menu):
        row = tree.identify_row(event.y)
        if row:
            tree.selection_set(row)
            tree.focus(row)
        menu.tk_popup(event.x_root, event.y_root)
        menu.grab_release()

    def _copy_name(self, tree):
        sel = tree.selection()
        if not sel:
            return "break"
        vals = tree.item(sel[0], "values")
        if not vals:
            return "break"
        name = str(vals[0])
        self.root.clipboard_clear()
        self.root.clipboard_append(name)
        self.log(f"Скопировано: {name}")
        return "break"

    def _sort_value(self, text):
        raw = str(text).strip().replace(" ", "").replace(",", ".").lower()
        if raw in ("", "—", "-"):
            return (1, 0.0, "")
        mult = 1.0
        body = raw
        if body.endswith("кк"):
            mult = 1000000.0
            body = body[:-2]
        elif body.endswith("к"):
            mult = 1000.0
            body = body[:-1]
        try:
            return (0, float(body) * mult, "")
        except ValueError:
            nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw)]
            if nums:
                return (0, max(nums), raw)
            return (2, 0.0, raw)

    def _sort_col(self, tree, col):
        desc = False if tree._order.get(col) else True
        tree._order = {col: desc}
        self._apply_sort(tree, col, desc)

    def _apply_sort(self, tree, col, desc):
        kids = list(tree.get_children(""))
        kids.sort(key=lambda k: self._sort_value(tree.set(k, col)), reverse=desc)
        for i, k in enumerate(kids):
            tree.move(k, "", i)
        for c in tree["columns"]:
            mark = ""
            if c == col:
                mark = " ↓" if desc else " ↑"
            tree.heading(c, text=c + mark, command=lambda name=c, t=tree: self._sort_col(t, name))

    def _tag(self, act):
        text = act or ""
        if "ВЫКУП" in text and "НЕ" not in text:
            return "buy"
        if text.startswith("СЛИТ"):
            return "sell"
        if text.startswith("ДЕРЖ"):
            return "hold"
        return "skip"

    def _side(self, rows):
        out = []
        for r in rows:
            if r.get("err"):
                out.append(((r["name"], "—", r["err"], "—"), "skip"))
                continue
            why = r.get("why") or ""
            buy = r.get("buy") or ""
            note = f"{buy} · {why}" if why else buy
            out.append(((r["name"], money(r.get("med", 0)), note, r.get("farm") or ""), self._tag(buy)))
        return out

    def _sell(self, rows, pack=False):
        out = []
        for r in rows:
            if r.get("err"):
                vals = (r["name"], "—", r["err"], "—", "—") if pack else (r["name"], "—", r["err"], "—")
                out.append((vals, "skip"))
                continue
            price = money(r.get("ask", r.get("med", 0)))
            note = r.get("farm") or ""
            if r.get("why"):
                note = f"{note}: {r['why']}"
            if pack:
                vals = (r["name"], money(r.get("med", 0)), price, r.get("pack") or "—", note)
            else:
                vals = (r["name"], money(r.get("med", 0)), price, note)
            out.append((vals, self._tag(r.get("farm"))))
        return out

    def fill(self, data):
        if "buys" in data:
            self.overlay.update_deals(data.get('buys') or [])
            seen = []
            for r in data.get("buys") or []:
                slug = r.get("slug")
                if slug and slug not in seen:
                    seen.append(slug)
            if seen:
                self._watch = seen
            buys = []
            for r in data.get("buys") or []:
                tag = f"q{r['qlt_i']}" if r.get("qlt_i") is not None else "buy"
                buys.append((
                    (r["name"], r.get("qlt") or "—", r.get("ptn") or "—", f"{r['copies']} x {r['amount']}", money(r["buyout"]), f"{r['unit']:.0f}", f"{r['med']:.0f}", money(r["med"] * r["amount"]), money(r["gain"]), f"{r.get('per_h', 0):.1f}", "ВЫКУПИТЬ"),
                    tag,
                ))
            self._put("Выкуп", buys)
        if "farm" in data:
            self._put("Фарм", self._sell(data.get("farm") or [], pack=True))
        if "arsenal" in data:
            self._put("Арсенал", self._sell(data.get("arsenal") or []))
        if "shelter_buy" in data:
            mats = []
            for r in data.get("shelter_buy") or []:
                if r.get("err"):
                    mats.append(((r["name"], "—", r["err"], "—"), "skip"))
                else:
                    mats.append(((r["name"], money(r.get("med", 0)), r.get("why") or "", r.get("buy") or ""), self._tag(r.get("buy"))))
            self._put("Убежище купить", mats)
        if "shelter_sell" in data:
            self._put("Убежище продать", self._sell(data.get("shelter_sell") or []))
        if "consumables" in data:
            self._put("Расходники", self._side(data.get("consumables") or []))
        if "arts" in data:
            arts = []
            for r in data.get("arts") or []:
                if r.get("err"):
                    arts.append(((r["name"], "—", "—", "—", "—", "—", "—", r["err"]), "skip"))
                else:
                    tag = f"q{r['qlt_i']}" if r.get("qlt_i") is not None else "skip"
                    arts.append(((r["name"], r.get("qlt") or "—", r.get("ptn") or "—", r["n"], money(r["cheap"]), money(r["med"]), money(r["net"]), r.get("liq") or "БРАТЬ"), tag))
            self._put("Арты", arts)
        if "protos" in data:
            protos = []
            for r in data.get("protos") or []:
                if r.get("err"):
                    protos.append(((r.get("qlt") or r["name"], "—", r["err"], "—", "—", "—", "—"), "skip"))
                else:
                    decision = r.get("buy") or ""
                    protos.append((
                        (r.get("qlt", ""), r.get("n", ""), decision, r.get("farm", ""), money(r.get("cheap", 0)), money(r.get("med", 0)), money(r.get("net", 0))),
                        self._tag(decision if decision == "ВЫКУПИТЬ" else r.get("farm")),
                    ))
            self._put("Протоартефакты", protos)


if __name__ == "__main__":
    try:
        from pathlib import Path
        folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        if not (folder / "exbo.json").exists():
            root = tk.Tk()
            root.withdraw()
            from tkinter import messagebox
            messagebox.showerror(
                "STALZONE",
                "Рядом с программой нет exbo.json.\nПоложи ключ EXBO в ту же папку и запусти ещё раз.",
            )
            raise SystemExit(1)
        App().root.mainloop()
    except SystemExit:
        raise
    except Exception:
        import traceback
        from pathlib import Path
        text = traceback.format_exc()
        folder = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        (folder / "stalzone_gui_error.log").write_text(text, encoding="utf-8")
        raise
