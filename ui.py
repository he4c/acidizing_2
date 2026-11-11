from __future__ import annotations

import os
from dataclasses import asdict, fields, replace
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from .calculations import (
    MODEL_VERSION,
    AcidSystem, default_acid_systems, validate_acid, validate_segments, validate_parameters,
    AcidizingParameters,
    CalculationError,
    HorizontalSegment,
    build_default_segments,
    get_val,
)
from .workflow import origin_md
from .data import FLUID_FIELDS, RESERVOIR_FIELDS, STAGE_SPECS, WELL_FIELDS, MINERAL_FIELDS, ACID_FIELD_LABELS, PARAMETER_CHOICES
from .database import DatabaseConfig, delete_case, list_cases, load_case, save_case, test_connection
from .exporters import export_inputs
from .model_api import INTERFACE_VERSION, calculate_design, load_request, save_request, save_response, parse_request


COLORS = {
    "nav": "#18252f", "nav_hover": "#243746", "accent": "#087f8c",
    "accent_dark": "#086673", "canvas": "#eef2f5", "card": "#ffffff",
    "line": "#d8e0e6", "text": "#17242d", "muted": "#667783",
    "good": "#2f855a", "warn": "#bd6b17", "risk": "#c2413b",
}
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 20, "bold")
FONT_KPI = ("Segoe UI", 23, "bold")

# 主入口共七个，细项工具放到各自的页签里
NAV_ITEMS = (
    ("parameters", "井身结构"),
    ("reservoir", "储层流体"),
    ("fluids", "酸液体系"),
    ("construction", "施工参数"),
    ("dashboard", "综合评价"),
    ("economics", "经济评价"),
    ("model", "数据导出"),
)


def make_tree(parent, columns, headings, widths, height=10):
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    tree = ttk.Treeview(frame, columns=columns, show="headings", height=height)
    ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    for column in columns:
        tree.heading(column, text=headings[column])
        tree.column(column, width=widths.get(column, 100), minwidth=65, anchor="center", stretch=True)
    tree.grid(row=0, column=0, sticky="nsew")
    ybar.grid(row=0, column=1, sticky="ns")
    xbar.grid(row=1, column=0, sticky="ew")
    return frame, tree


class ScrollFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self, background=COLORS["card"], highlightthickness=0)
        self.body = ttk.Frame(self.canvas, padding=14)
        self.window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.bind("<Enter>", lambda _e: self.canvas.bind_all("<MouseWheel>", self._wheel))
        self.canvas.bind("<Leave>", lambda _e: self.canvas.unbind_all("<MouseWheel>"))

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class AcidizingApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SandPro Acidizing | 砂岩酸化设计与效果评价")
        self.geometry("1380x860")
        self.minsize(1120, 720)
        self.configure(background=COLORS["canvas"])
        self.section_entries = {"well": {}, "reservoir": {}, "fluid": {}, "minerals": {}}
        self.parameter_values = asdict(AcidizingParameters())
        self.acid_systems = default_acid_systems()
        self.radial_acid_var = tk.StringVar(value=next(iter(self.acid_systems)))
        self.stage_entries = {}
        self.pages = {}
        self.main_pages = {}
        self.nav_buttons = {}
        self.nav_indicators = {}
        self.latest_result = None
        self.latest_response = None
        self.latest_horizontal = None
        self.status_var = tk.StringVar(value="模型已就绪")
        self.case_var = tk.StringVar(value="未命名方案")
        self._configure_styles()
        self._create_shell()
        self._build_pages()
        self.show_page("parameters")
        self.after(250, lambda: self.calculate_current(show=False))

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=FONT)
        style.configure("TFrame", background=COLORS["card"])
        style.configure("Canvas.TFrame", background=COLORS["canvas"])
        style.configure("TLabel", background=COLORS["card"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", foreground=COLORS["muted"])
        style.configure("PageTitle.TLabel", font=FONT_TITLE, foreground=COLORS["text"])
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"), foreground="white", background=COLORS["accent"], padding=(16, 9))
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"])])
        style.configure("TButton", padding=(12, 8))
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("TNotebook", background=COLORS["card"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.configure("Treeview", rowheight=30, fieldbackground="white", background="white")
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"), background="#e7edf1")
        style.map("Treeview", background=[("selected", COLORS["accent"])])

    def _create_shell(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        header = tk.Frame(self, background="#ffffff", height=64, highlightbackground=COLORS["line"], highlightthickness=1)
        header.grid(row=0, column=0, columnspan=2, sticky="nsew")
        header.grid_propagate(False)
        tk.Label(header, text="SANDPRO", font=("Segoe UI", 18, "bold"), fg=COLORS["accent"], bg="white").pack(side="left", padx=(24, 8))
        tk.Label(header, text="砂岩酸化设计与效果评价平台", font=("Microsoft YaHei UI", 12), fg=COLORS["text"], bg="white").pack(side="left")
        ttk.Button(header, text="运行评价", style="Accent.TButton", command=self.calculate_current).pack(side="right", padx=22, pady=12)
        tk.Label(header, textvariable=self.case_var, font=FONT, fg=COLORS["muted"], bg="white").pack(side="right", padx=10)

        nav = tk.Frame(self, background=COLORS["nav"], width=218)
        nav.grid(row=1, column=0, sticky="nsew")
        nav.pack_propagate(False)
        for index, (key, label) in enumerate(NAV_ITEMS, 1):
            group = {1: "基础资料", 4: "设计与评价", 7: "成果管理"}.get(index)
            if group:
                tk.Label(nav, text=group, font=FONT_SMALL, fg="#8fa4b2", bg=COLORS["nav"]).pack(anchor="w", padx=22, pady=(20, 7))
            row = tk.Frame(nav, background=COLORS["nav"])
            row.pack(fill="x", padx=10, pady=3)
            indicator = tk.Frame(row, width=3, background=COLORS["nav"])
            indicator.pack(side="left", fill="y")
            button = tk.Button(row, text="%02d  %s" % (index, label), command=lambda name=key: self.show_page(name), font=("Microsoft YaHei UI", 11), fg="#dce7ed", bg=COLORS["nav"], activeforeground="white", activebackground=COLORS["nav_hover"], relief="flat", bd=0, anchor="w", padx=14, pady=13, cursor="hand2")
            button.pack(side="left", fill="x", expand=True)
            self.nav_buttons[key] = button
            self.nav_indicators[key] = indicator
        footer = tk.Frame(nav, background=COLORS["nav"])
        footer.pack(side="bottom", fill="x", padx=22, pady=18)
        tk.Label(footer, text="历史方案与数据库\n请进入「数据导出」", font=FONT_SMALL, fg="#a9beca", bg=COLORS["nav"], justify="left").pack(anchor="w", pady=(0, 12))
        tk.Label(footer, text="MODEL  %s\nINTERFACE  %s" % (MODEL_VERSION, INTERFACE_VERSION), font=("Consolas", 8), fg="#78909c", bg=COLORS["nav"], justify="left").pack(anchor="w")

        self.content = tk.Frame(self, background=COLORS["canvas"])
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)
        status = tk.Frame(self, background="#ffffff", height=27)
        status.grid(row=2, column=0, columnspan=2, sticky="ew")
        tk.Label(status, textvariable=self.status_var, font=FONT_SMALL, fg=COLORS["muted"], bg="white").pack(side="left", padx=16)
        tk.Label(status, text="本结果用于方案筛选，现场实施前需结合岩心实验与压力资料校核", font=FONT_SMALL, fg=COLORS["warn"], bg="white").pack(side="right", padx=16)

    def _build_pages(self):
        from .workflow_ui import ConstructionPage, EconomicsPage
        # 页面键名先沿用，计算、导入和保存都用到了
        # 先注册参数变量，再建水平段编辑器
        self.pages["parameters"] = ParametersPage(self.content, self)
        self.pages["reservoir"] = ReservoirPage(self.content, self)
        self.pages["fluids"] = FluidsPage(self.content, self)
        well_book = self.pages["parameters"].notebook
        self.pages["horizontal"] = HorizontalPage(well_book, self)
        well_book.add(self.pages["horizontal"], text="水平井分段")
        self.pages["parameters"].sync_well_type()
        self.pages["construction"] = ConstructionPage(self.content, self)
        self.pages["dashboard"] = DashboardPage(self.content, self)
        self.pages["economics"] = EconomicsPage(self.content, self)
        exports = DataExportPage(self.content, self)
        self.pages["model"] = ModelPage(exports.notebook, self)
        self.pages["database"] = DatabasePage(exports.notebook, self)
        exports.notebook.add(self.pages["model"], text="数模接口与模型依据")
        exports.notebook.add(self.pages["database"], text="方案数据库")
        self.main_pages = {key: self.pages[key] for key, _ in NAV_ITEMS if key != "model"}
        self.main_pages["model"] = exports
        for page in self.main_pages.values():
            page.grid(row=0, column=0, sticky="nsew", padx=18, pady=16)

    def show_page(self, name):
        # 旧快捷入口也能跳到对应的子页签
        if name == "horizontal":
            parameters = self.pages["parameters"]
            target = self.pages[name] if self.section_entries["well"]["well_type"].get() == "水平井" else parameters.well_form
            parameters.notebook.select(target)
            name = "parameters"
        elif name in ("database", "interface"):
            self.main_pages["model"].notebook.select(self.pages["model" if name == "interface" else name])
            name = "model"
        self.main_pages[name].tkraise()
        self.current_page = name
        for key, button in self.nav_buttons.items():
            selected = key == name
            button.configure(bg=COLORS["accent"] if selected else COLORS["nav"],
                             fg="white" if selected else "#dce7ed",
                             font=("Microsoft YaHei UI", 11, "bold" if selected else "normal"))
            self.nav_indicators[key].configure(bg="#7ce2dc" if selected else COLORS["nav"])

    def collect_parameters(self):
        values = dict(self.parameter_values)
        for section in self.section_entries.values():
            for key, variable in section.items():
                try:
                    values[key] = variable.get() if key in PARAMETER_CHOICES else get_val(variable.get())
                except CalculationError as exc:
                    raise CalculationError("%s：%s" % (key, exc))
        for key in ("V_per_m",):
            values[key] = get_val(self.stage_entries[key].get())
        params = AcidizingParameters(**values)
        validate_parameters(params)
        return params

    def set_parameters(self, values):
        self.parameter_values = asdict(AcidizingParameters())
        self.parameter_values.update(values)
        for section in self.section_entries.values():
            for key, variable in section.items():
                variable.set(str(self.parameter_values[key]))
        for key in ("V_per_m",):
            self.stage_entries[key].set(str(self.parameter_values[key]))

    def collect_stage_rows(self, result=None):
        if result is not None and self.latest_response:
            return list(self.latest_response['construction_stage_results'])
        if "construction" in self.pages:
            from .model_api import parse_workflow
            return [asdict(t) for t in parse_workflow(self.request_payload())[5]]
        acid = self.acid_systems[self.radial_acid_var.get()]
        volumes = {}
        if result:
            volumes = {"preflush": result.basic.preflush_volume, "treatment": result.basic.treatment_volume,
                       "postflush": result.basic.postflush_volume, "displacement": result.basic.displacement_volume}
        return [{"key": spec.key, "name": spec.label, "fluid_type": getattr(acid, spec.key + "_type"),
                 "concentration": getattr(acid, spec.key + "_formula"), "volume_text": "直井参考方案",
                 "volume": volumes.get(spec.key, "")} for spec in STAGE_SPECS]

    def calculate_current(self, show=True):
        # print("开始计算当前方案，显示结果：", show)
        self.latest_result = None
        self.latest_horizontal = None
        self.latest_response = None
        try:
            payload = self.request_payload()
            result, horizontal, response = calculate_design(payload, return_objects=True)
        except Exception as exc:
            messagebox.showerror("计算未完成，请检查输入", str(exc), parent=self)
            self.status_var.set("计算未完成；不会导出或保存上次结果")
            return False
        self.latest_result = result
        self.latest_horizontal = horizontal
        self.latest_response = response
        self.pages["dashboard"].update_results(result, horizontal)
        self.pages["construction"].update_results(response)
        self.pages["economics"].update_results(response)
        self.status_var.set("评价完成 · %s · %s · %d 段" % (datetime.now().strftime("%H:%M:%S"), response["active_well_type"],len(horizontal.segments)))
        if show:
            self.show_page("dashboard")
        return True

    def request_payload(self):
        if self.collect_parameters().well_type == "水平井":
            self.pages["horizontal"].commit_editor(silent=True)
        payload = {"interface_version": INTERFACE_VERSION, "model_version": MODEL_VERSION,
                "parameters": asdict(self.collect_parameters()),
                "horizontal_segments": [asdict(row) for row in self.pages["horizontal"].get_segments()],
                "acid_systems": {key: asdict(value) for key, value in self.acid_systems.items()},
                "radial_acid_system": self.radial_acid_var.get()}
        if "construction" in self.pages:
            payload.update(self.pages["construction"].get_config())
        if "economics" in self.pages:
            payload["economics"] = self.pages["economics"].get_config()
        return payload

    def apply_payload(self, payload):
        legacy = payload.get("interface_version", "1.0") != INTERFACE_VERSION
        params, segments, acids, radial_name = parse_request(payload)
        self.set_parameters(asdict(params))
        self.acid_systems = acids
        self.radial_acid_var.set(radial_name)
        self.pages["fluids"].refresh_library()
        self.pages["horizontal"].set_segments([asdict(row) for row in segments])
        self.pages["construction"].set_config(payload)
        self.pages["economics"].set_config(payload.get("economics",{}))
        self.calculate_current()
        if legacy:
            messagebox.showinfo("旧版数据已转换", "新增井形默认水平井、完井默认射孔；开放位置按处理段补齐。摩阻现按1m³/min参考排量解释。请核对井形、完井位置、矿物、配方和液量后使用。", parent=self)

    def export_input_data(self):
        try:
            payload = self.request_payload()
            message = export_inputs(self.collect_parameters(), self.collect_stage_rows(),
                                    self.pages["horizontal"].get_segments(), payload)
            messagebox.showinfo("导出完成", message, parent=self)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)

    def export_result_data(self):
        if not self.calculate_current(show=False):
            return
        try:
            from .exchange import export_bundle
            message = str(export_bundle(self.latest_response,self.case_var.get()))
            messagebox.showinfo("导出完成", message, parent=self)
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)

    def export_report(self):
        if not self.calculate_current(show=False):
            return
        path = filedialog.asksaveasfilename(title="导出分析报告与施工方案初稿", defaultextension=".docx",
                                          filetypes=[("Word报告", "*.docx"), ("可打印报告", "*.html")], parent=self)
        if path:
            try:
                from .exchange import export_word, export_html
                (export_word if path.lower().endswith('.docx') else export_html)(path,self.latest_response,self.case_var.get())
                messagebox.showinfo("报告已保存", path, parent=self)
            except Exception as exc:
                messagebox.showerror("导出失败", str(exc), parent=self)

    def save_current_case(self):
        if not self.calculate_current(show=False) or not self.pages["database"].apply_settings():
            return
        name = simpledialog.askstring("保存方案", "方案名称", initialvalue=self.case_var.get(), parent=self)
        if not name:
            return
        try:
            case_id = save_case(name.strip(), self.collect_parameters(), self.collect_stage_rows(self.latest_result),
                               self.latest_result,
                               horizontal_segments=self.pages["horizontal"].get_segments(),
                               horizontal_result=self.latest_horizontal,
                               design_payload=self.latest_response['input_snapshot'],
                               economics_result=self.latest_response['economics'])
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.case_var.set(name.strip())
        messagebox.showinfo("保存成功", "方案及自定义酸液库已保存，编号 %s" % case_id, parent=self)


class Page(ttk.Frame):
    def __init__(self, parent, app, title, subtitle):
        super().__init__(parent, style="Canvas.TFrame")
        self.app = app
        if isinstance(parent, ttk.Notebook):
            self.configure(padding=(12, 12))
        else:
            ttk.Label(self, text=title, style="PageTitle.TLabel", background=COLORS["canvas"]).pack(anchor="w")
        self.subtitle_label = ttk.Label(self, text=subtitle, style="Muted.TLabel", background=COLORS["canvas"], wraplength=820)
        self.subtitle_label.pack(anchor="w", pady=(2, 14))

    def card(self, parent=None):
        return tk.Frame(parent or self, bg=COLORS["card"], highlightbackground=COLORS["line"], highlightthickness=1)


class DashboardPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "综合评价", "按当前井形查看处理井段的作用深度、覆盖率与产能评价")
        actions = ttk.Frame(self, style="Canvas.TFrame")
        actions.pack(fill="x", pady=(0, 12))
        ttk.Button(actions, text="运行评价", style="Accent.TButton", command=app.calculate_current).pack(side="left")
        ttk.Button(actions, text="保存方案", command=app.save_current_case).pack(side="left", padx=8)
        ttk.Button(actions, text="导出结果", command=app.export_result_data).pack(side="left")
        ttk.Button(actions, text="分析报告 / 施工初稿", command=app.export_report).pack(side="left", padx=8)
        ttk.Button(actions, text="查看温度与反应明细", command=self.show_details).pack(side="left")
        metrics = ttk.Frame(self, style="Canvas.TFrame")
        metrics.pack(fill="x", pady=(0, 12))
        self.metric_vars = {}
        self.metric_labels = {}
        specs = [("radius", "最大井壁外作用深度", "m"), ("coverage", "平均覆盖率", "%"), ("ratio", "综合增产倍比", "×"), ("risk", "高风险水平段", "段")]
        for index, (key, label, unit) in enumerate(specs):
            metrics.columnconfigure(index, weight=1)
            card = tk.Frame(metrics, bg="white", highlightbackground=COLORS["line"], highlightthickness=1, padx=16, pady=12)
            card.grid(row=0, column=index, sticky="ew", padx=(0 if index == 0 else 6, 0 if index == 3 else 6))
            self.metric_labels[key] = tk.Label(card, text=label, bg="white", fg=COLORS["muted"], font=FONT_SMALL)
            self.metric_labels[key].pack(anchor="w")
            line = tk.Frame(card, bg="white")
            line.pack(fill="x", pady=(7, 0))
            variable = tk.StringVar(value="--")
            self.metric_vars[key] = variable
            tk.Label(line, textvariable=variable, bg="white", fg=COLORS["text"], font=FONT_KPI).pack(side="left")
            tk.Label(line, text=unit, bg="white", fg=COLORS["muted"], font=FONT).pack(side="left", padx=6, pady=(10, 0))
        body = ttk.Frame(self, style="Canvas.TFrame")
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        left = self.card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self.treatment_title = tk.Label(left, text="井段处理效果", bg="white", fg=COLORS["text"], font=("Microsoft YaHei UI", 12, "bold"))
        self.treatment_title.pack(anchor="w", padx=16, pady=(14, 4))
        tk.Label(left, text="颜色表示评价结论，柱高表示污染覆盖率", bg="white", fg=COLORS["muted"], font=FONT_SMALL).pack(anchor="w", padx=16)
        self.chart = tk.Canvas(left, bg="white", highlightthickness=0, height=190)
        self.chart.pack(fill="x", padx=12, pady=8)
        frame, self.tree = make_tree(left, ("name", "md", "skin", "acid", "coverage", "ratio", "status"), {"name": "处理井段", "md": "绝对测深 MD(m)", "skin": "污染表皮", "acid": "分配酸量(m³)", "coverage": "覆盖率", "ratio": "增产倍比", "status": "结论"}, {"name": 90, "md": 180, "skin": 90, "acid": 105, "coverage": 90, "ratio": 90, "status": 85}, 7)
        frame.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        right = self.card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        tk.Label(right, text="工程结论与建议", bg="white", fg=COLORS["text"], font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=16, pady=(14, 8))
        self.summary = tk.Text(right, wrap="word", relief="flat", bg="#f7f9fa", fg=COLORS["text"], font=FONT, padx=12, pady=10, height=14)
        self.summary.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        self.summary.configure(state="disabled")

    def update_results(self, result, horizontal):
        params = AcidizingParameters(**self.app.latest_response["input_snapshot"]["parameters"])
        well_type = params.well_type
        is_horizontal = well_type == "水平井"
        self.treatment_title.configure(text="水平段处理效果" if is_horizontal else well_type + "处理效果")
        self.subtitle_label.configure(text=well_type + "评价：查看实际处理井段的作用深度、污染覆盖率与产能；井段坐标从井口起算。")
        self.metric_labels["risk"].configure(text="高风险水平段" if is_horizontal else "高风险井段")
        self.tree.heading("name", text="水平段" if is_horizontal else "处理井段")
        offset = origin_md(params, horizontal.segments)
        self.metric_vars["radius"].set("%.2f" % max(s.penetration_depth for s in horizontal.segments))
        self.metric_vars["coverage"].set("%.2f" % (horizontal.average_coverage * 100.0))
        self.metric_vars["ratio"].set("%.2f" % horizontal.expected_productivity_ratio)
        self.metric_vars["risk"].set(str(horizontal.risk_segment_count))
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in horizontal.segments:
            self.tree.insert("", "end", values=(row.name, "%.2f–%.2f" % (offset + row.start_md, offset + row.end_md), "%.2f" % row.skin_before, "%.2f" % row.allocated_acid, "%.2f%%" % (row.coverage_ratio * 100), "%.2f" % row.productivity_ratio, row.status))
        lines = list(horizontal.conclusions)
        lines.extend(["", "当前施工方案", "• 总液量：%.2f m³" % horizontal.total_fluid_volume,
                      "• J原始 / J污染 / J处理后：%.2f / %.2f / %.2f m³/(d·MPa)" % (horizontal.productivity_undamaged,horizontal.productivity_damaged,horizontal.productivity_after),
                      "• 表格与结果保留两位小数；编辑、计算与数据导出保留原始精度。", "", "需复核的井段"])
        lines.extend(self.app.latest_response['water_analysis']['warnings'])
        ranked = sorted(horizontal.segments, key=lambda item: item.coverage_ratio)[:3]
        lines.extend("• %s：%s" % (row.name, row.recommendation) for row in ranked)
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", "\n".join(lines))
        self.summary.configure(state="disabled")
        self._draw_chart(horizontal, is_horizontal)

    def show_details(self):
        if not self.app.calculate_current(show=False):
            return
        window = tk.Toplevel(self)
        window.title("每段产能、矿物反应与井筒温度")
        window.geometry("1150x700")
        book = ttk.Notebook(window)
        book.pack(fill="both", expand=True)
        columns = ("name", "acid", "depth", "j0", "jd", "ja", "ratio", "inlet", "temp", "heat", "diss", "precip", "kclean", "knet", "rate", "limit")
        labels = ("井段", "酸液", "作用深度m", "J原始", "J污染", "J处理后", "J后/J污染", "到段温度℃", "反应温度℃", "放热温升℃", "溶蚀kg", "沉淀kg", "无沉淀k", "净k(mD)", "输入排量", "建议排量上限")
        frame, tree = make_tree(book, columns, dict(zip(columns, labels)), {c: 120 for c in columns}, 16)
        book.add(frame, text="反应 / 产能（J单位m³/d/MPa）")
        for r in self.app.latest_horizontal.segments:
            rx = r.reaction
            values = (r.name, r.acid_system, r.penetration_depth, r.productivity_undamaged, r.productivity_damaged,
                      r.productivity_after, r.productivity_ratio, r.inlet_temperature, rx.temperature,
                      rx.reaction_temperature_rise, rx.dissolved_rock_kg, rx.precipitate_kg,
                      rx.permeability_without_precipitation, rx.permeability_after, r.required_rate, r.allowed_rate)
            tree.insert("", "end", values=["%.2f" % v if isinstance(v, (int, float)) else v for v in values])
        cols = ("segment", "md", "tvd", "earth", "fluid", "gradient")
        frame, tree = make_tree(book, cols, dict(zip(cols, ("段", "井口起算MD(m)", "垂深(m)", "地层℃", "酸液℃", "酸液温度梯度℃/m"))), {c: 150 for c in cols}, 16)
        book.add(frame, text="沿井筒温度剖面")
        for r in self.app.latest_horizontal.segments:
            for point in r.temperature_profile:
                tree.insert("", "end", values=(r.name,) + tuple("%.2f" % v for v in asdict(point).values()))

    def _draw_chart(self, horizontal, is_horizontal=True):
        self.chart.delete("all")
        self.chart.update_idletasks()
        width = max(self.chart.winfo_width(), 600)
        height = max(self.chart.winfo_height(), 170)
        margin = 38
        usable = width - margin * 2
        count = len(horizontal.segments)
        gap = 2 if count > 20 else 8
        bar_width = max((usable - gap * (count - 1)) / max(count, 1), 1)
        self.chart.create_line(margin, height - 30, width - margin, height - 30, fill=COLORS["line"])
        for index, row in enumerate(horizontal.segments):
            x1 = margin + index * (bar_width + gap)
            x2 = x1 + bar_width
            ratio = min(row.coverage_ratio, 1.25) / 1.25
            y1 = height - 30 - ratio * (height - 60)
            color = COLORS["good"] if row.status == "有效" else COLORS["warn"] if row.status == "可改善" else COLORS["risk"]
            self.chart.create_rectangle(x1, y1, x2, height - 30, fill=color, outline="")
            if count <= 30 or index % max(1, count // 15) == 0:
                label = row.name.replace("第", "").replace("段", "") if is_horizontal else row.name
                self.chart.create_text((x1 + x2) / 2, height - 16, text=label, fill=COLORS["muted"], font=FONT_SMALL)
            if count <= 15:
                self.chart.create_text((x1 + x2) / 2, max(y1 - 10, 10), text="%.2f%%" % (row.coverage_ratio * 100), fill=COLORS["text"], font=FONT_SMALL)


def parameter_form(parent, app, groups):
    """Lay out existing field metadata without changing values or section keys."""
    scroll = ScrollFrame(parent)
    scroll.body.columnconfigure(0, weight=1, uniform="fields")
    scroll.body.columnconfigure(1, weight=1, uniform="fields")
    index = 0
    for section, specs in groups:
        for spec in specs:
            box = tk.Frame(scroll.body, bg="white", highlightbackground=COLORS["line"], highlightthickness=1, padx=12, pady=9)
            box.grid(row=index // 2, column=index % 2, sticky="nsew", padx=6, pady=6)
            box.columnconfigure(0, weight=1)
            tk.Label(box, text=spec.label, bg="white", fg=COLORS["text"], font=FONT, wraplength=330, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
            variable = tk.StringVar(value=spec.default)
            app.section_entries[section][spec.key] = variable
            widget = ttk.Combobox(box, textvariable=variable, values=PARAMETER_CHOICES[spec.key], state="readonly", width=18) if spec.key in PARAMETER_CHOICES else ttk.Entry(box, textvariable=variable, width=16, justify="right")
            widget.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 8))
            tk.Label(box, text=spec.unit, bg="white", fg=COLORS["muted"], font=FONT_SMALL, width=13, anchor="w").grid(row=1, column=1, sticky="w")
            index += 1
    return scroll


class ParametersPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "井身结构", "先选择井形和完井方式，再填写下方参数；开放/射孔位置在「施工参数」页设置。")
        selectors = self.card()
        selectors.pack(fill="x", pady=(0, 8))
        selector_keys = ("well_type", "completion_type")
        for column, key in enumerate(selector_keys):
            spec = next(spec for spec in WELL_FIELDS if spec.key == key)
            box = ttk.Frame(selectors, padding=(12, 10))
            box.grid(row=0, column=column, sticky="ew")
            selectors.columnconfigure(column, weight=1)
            ttk.Label(box, text=spec.label).pack(side="left", padx=(0, 10))
            variable = tk.StringVar(value=spec.default)
            app.section_entries["well"][key] = variable
            widget = ttk.Combobox(box, textvariable=variable, values=PARAMETER_CHOICES[key], state="readonly", width=16)
            widget.pack(side="left", fill="x", expand=True)
            if key == "well_type":
                widget.bind("<<ComboboxSelected>>", self.change_well_type)
        ttk.Button(selectors, text="恢复全部工程默认值", command=self.reset).grid(row=0, column=2, padx=12, pady=10)
        self.segment_hint = tk.StringVar()
        ttk.Label(self, textvariable=self.segment_hint, style="Muted.TLabel", background=COLORS["canvas"], wraplength=820).pack(anchor="w", pady=(0, 8))
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        first = ("Zh", "vertical_depth", "inclination_deg")
        specs = [next(spec for spec in WELL_FIELDS if spec.key == key) for key in first]
        specs.extend(spec for spec in WELL_FIELDS if spec.key not in first + selector_keys)
        self.well_form = parameter_form(self.notebook, app, [("well", specs)])
        self.notebook.add(self.well_form, text="井身与完井参数")
        # 导入和重置也会改这个变量，这里只同步界面
        app.section_entries["well"]["well_type"].trace_add("write", self.sync_well_type)
        self.sync_well_type()

    def sync_well_type(self, *_):
        well_type = self.app.section_entries["well"]["well_type"].get()
        is_horizontal = well_type == "水平井"
        horizontal = self.app.pages.get("horizontal")
        if horizontal is not None:
            if not is_horizontal and self.notebook.select() == str(horizontal):
                self.notebook.select(self.well_form)
            self.notebook.tab(horizontal, state="normal" if is_horizontal else "disabled")
        self.segment_hint.set("水平井：可编辑「水平井分段」，各段参数参与评价。" if is_horizontal else
                              "%s：按主处理段评价；水平井分段已停用，原分段内容保留，切回水平井后可继续编辑。" % well_type)

    def change_well_type(self,_event=None):
        well=self.app.section_entries['well']
        if well['well_type'].get()=='直井':
            well['Zh'].set(well['vertical_depth'].get())
            well['inclination_deg'].set('0')
        elif well['well_type'].get()=='水平井':
            well['inclination_deg'].set('90')
        else:
            well['inclination_deg'].set('45')
        if 'construction' in self.app.pages:
            self.app.pages['construction'].set_config({})
        self.app.status_var.set('井形已切换；请核对测深、垂深、井斜角及开放区间')

    def reset(self):
        for section, specs in [("well", WELL_FIELDS), ("reservoir", RESERVOIR_FIELDS), ("fluid", FLUID_FIELDS), ("minerals", MINERAL_FIELDS)]:
            for spec in specs:
                self.app.section_entries[section][spec.key].set(spec.default)
        self.app.status_var.set("工程参数已恢复默认值")


class ReservoirPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "储层流体", "集中录入储层物性、油气水性质、矿物组成和地层水资料；保留原有单位、默认值与计算精度。")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        fluid_keys = {"oil_viscosity", "oil_volume_factor", "water_saturation",
                      "oil_saturation", "gas_saturation", "oil_relative_permeability"}
        mineral_keys = {"quartz", "feldspar", "clay", "carbonate", "other_minerals"}
        groups = [
            ("储层与污染", "reservoir", [s for s in RESERVOIR_FIELDS if s.key not in fluid_keys]),
            ("油气水性质", "reservoir", [s for s in RESERVOIR_FIELDS if s.key in fluid_keys]),
            ("矿物组成", "minerals", [s for s in MINERAL_FIELDS if s.key in mineral_keys]),
            ("地层水与沉淀", "minerals", [s for s in MINERAL_FIELDS if s.key not in mineral_keys]),
        ]
        for title, section, specs in groups:
            self.notebook.add(parameter_form(self.notebook, app, [(section, specs)]), text=title)


class HorizontalPage(Page):
    FIELDS = [("name", "名称"), ("start_md", "起点（距水平段入口m）"), ("end_md", "终点（距水平段入口m）"),
              ("permeability", "原始渗透率(mD)"), ("damaged_permeability", "污染渗透率(mD)"),
              ("damage_depth", "井壁外污染深度(0.1–10m)"), ("porosity", "孔隙度(0–1)"),
              ("acid_volume", "本段处理液量(m³)"), ("acid_system", "本段酸液体系"),
              ("contact_time", "处理液注入/接触时间(min)"), ("drilling_exposure_days", "钻井液暴露天数（记录）")]

    def __init__(self, parent, app):
        super().__init__(parent, app, "水平段个性化设计", "仅水平井启用本页。默认30段，支持1–100段；每段独立设置用量与配方。表格固定显示两位小数，编辑与计算保留完整精度。")
        self.mode_var = tk.StringVar(value="均质")
        self.length_var = tk.StringVar(value="1000")
        self.count_var = tk.StringVar(value="30")
        self.rows = []
        self._edit_index = None
        self.editor_vars = {key: tk.StringVar() for key, _ in self.FIELDS}
        controls = self.card()
        controls.pack(fill="x", pady=(0, 10))
        for i, (label, variable) in enumerate((("水平段长度(m)", self.length_var), ("分段数1–100", self.count_var))):
            ttk.Label(controls, text=label).grid(row=0, column=i * 2, padx=8, pady=10)
            ttk.Entry(controls, textvariable=variable, width=8).grid(row=0, column=i * 2 + 1)
        ttk.Combobox(controls, textvariable=self.mode_var, values=("均质", "非均质"), state="readonly", width=9).grid(row=0, column=4, padx=8)
        ttk.Button(controls, text="重新生成分段", command=self.regenerate).grid(row=0, column=5, padx=6)
        ttk.Button(controls, text="运行评价", command=app.calculate_current).grid(row=0, column=6, padx=6)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        columns = tuple(key for key, _ in self.FIELDS)
        frame, self.tree = make_tree(body, columns, dict(self.FIELDS), {c: 125 for c in columns}, 16)
        frame.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", self.load_selected)
        editor = ScrollFrame(body)
        editor.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        for key, label in self.FIELDS:
            ttk.Label(editor.body, text=label).pack(anchor="w", pady=(5, 2))
            if key == "acid_system":
                self.acid_combo = ttk.Combobox(editor.body, textvariable=self.editor_vars[key], values=list(app.acid_systems), state="readonly", width=25)
                self.acid_combo.pack(fill="x")
            else:
                ttk.Entry(editor.body, textvariable=self.editor_vars[key]).pack(fill="x")
        ttk.Button(editor.body, text="更新本段", command=self.commit_editor).pack(fill="x", pady=12)
        ttk.Label(editor.body, text="切换段、计算或导出时会自动保存当前段。\n暴露天数不自动换算污染深度。", wraplength=245).pack(anchor="w")
        self.regenerate()

    def regenerate(self):
        try:
            count_value = get_val(self.count_var.get())
            if count_value != int(count_value):
                raise CalculationError("分段数量必须是整数")
            rows = build_default_segments(self.app.collect_parameters(), get_val(self.length_var.get()), int(count_value), self.mode_var.get())
            if self.rows and not messagebox.askyesno("重新生成", "将用默认值替换当前分段设置，是否继续？", parent=self):
                return
            # 导入的酸液库里不一定有默认名称
            self.rows = [replace(row, acid_system=self.app.radial_acid_var.get()) for row in rows]
            self.render()
        except Exception as exc:
            messagebox.showerror("无法生成分段", str(exc), parent=self)

    def _values(self, row):
        return [format(getattr(row,key),'.2f') if isinstance(getattr(row,key),(int,float)) else getattr(row,key) for key,_ in self.FIELDS]

    def render(self, selected=0):
        self._edit_index = None
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, row in enumerate(self.rows):
            self.tree.insert("", "end", iid=str(i), values=self._values(row))
        if self.rows:
            self.tree.selection_set(str(selected))
            self.tree.focus(str(selected))
            self.load_selected()

    def load_selected(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        index = int(selected[0])
        if index == self._edit_index:
            return
        if self._edit_index is not None:
            try:
                self.commit_editor(silent=True)
            except Exception as exc:
                self.tree.selection_set(str(self._edit_index))
                messagebox.showerror("请先修正本段参数", str(exc), parent=self)
                return
        self._edit_index = index
        for key, _ in self.FIELDS:
            self.editor_vars[key].set(str(getattr(self.rows[index], key)))
        self.acid_combo.configure(values=list(self.app.acid_systems))

    def commit_editor(self, silent=False):
        if self._edit_index is None:
            return True
        try:
            values = {key: var.get().strip() if key in ("name", "acid_system") else get_val(var.get())
                      for key, var in self.editor_vars.items()}
            updated = HorizontalSegment(**values)
            candidate = list(self.rows)
            candidate[self._edit_index] = updated
            validate_segments(self.app.collect_parameters(), candidate, self.app.acid_systems)
            self.rows = candidate
            self.tree.item(str(self._edit_index), values=self._values(updated))
            return True
        except Exception as exc:
            if silent:
                raise
            messagebox.showerror("水平段参数错误", str(exc), parent=self)
            return False

    def get_segments(self):
        return list(self.rows)

    def set_segments(self, records):
        self.rows = [HorizontalSegment(**record) for record in records]
        self.length_var.set(str(self.rows[-1].end_md))
        self.count_var.set(str(len(self.rows)))
        self.render()


class FluidsPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "酸液体系", "新增体系输入有效组分、动力学、溶蚀和放热参数；施工参数页可为每个段塞分别选择配方。")
        bar = self.card()
        bar.pack(fill="x", pady=(0, 12))
        ttk.Label(bar, text="查看 / 直井参考体系").pack(side="left", padx=10)
        self.library_var = app.radial_acid_var
        self.combo = ttk.Combobox(bar, textvariable=self.library_var, values=list(app.acid_systems), state="readonly", width=28)
        self.combo.pack(side="left", padx=5, pady=12)
        self.combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_library())
        ttk.Button(bar, text="编辑体系", command=lambda: self.edit_acid(False)).pack(side="left", padx=5)
        ttk.Button(bar, text="复制并新增", command=lambda: self.edit_acid(True)).pack(side="left", padx=5)
        ttk.Button(bar, text="保存酸液库", command=self.save_library).pack(side="left", padx=5)
        ttk.Button(bar, text="载入酸液库", command=self.load_library).pack(side="left", padx=5)
        card = self.card()
        card.pack(fill="both", expand=True)
        self.summary = tk.Text(card, wrap="word", relief="flat", font=FONT, padx=20, pady=15, height=15)
        self.summary.pack(fill="both", expand=True)
        settings = ttk.Frame(card, padding=15)
        settings.pack(fill="x")
        for i, (key, label, default) in enumerate((("V_per_m", "非水平井处理液(m³/m)", "1.7"),)):
            var = tk.StringVar(value=default)
            app.stage_entries[key] = var
            ttk.Label(settings, text=label).grid(row=0, column=i * 2, padx=5)
            ttk.Entry(settings, textvariable=var, width=10).grid(row=0, column=i * 2 + 1, padx=5)
        self.refresh_library()

    def refresh_library(self):
        self.combo.configure(values=list(self.app.acid_systems))
        acid = self.app.acid_systems[self.library_var.get()]
        lines = ["当前体系：" + acid.name, ""]
        for spec in STAGE_SPECS:
            lines.append(spec.label + "：" + getattr(acid, spec.key + "_type") + " | " + getattr(acid, spec.key + "_formula"))
        lines += ["", "计算采用数值浓度：HCl %.2f%% / HF %.2f%% / 有机酸 %.2f%%" % (100 * acid.hcl_fraction, 100 * acid.hf_fraction, 100 * acid.organic_fraction),
                  "参考速率 %.4g /min；活化能 %.2f kJ/mol；放热 %.2f kJ/mol 酸。" % (acid.rate_constant, acid.activation_energy, acid.reaction_heat),
                  "标定依据：" + acid.calibration_note, "", "配方文字用于施工记录；计算使用数值浓度与实验系数，请保持一致。",
                  "各段处理液量直接输入；前/后置液比例在工程参数中设置；末次顶替按全井管内容积估算。",
                  "当前反应模型："+acid.reaction_model+"；等效传质速率 %.4g /min。"%acid.mass_transfer_rate,
                  "施工页采用顺序段塞集总模型，前后置酸液按实际数值配方反应；顶替液仅计水力与费用。",
                  "矿物质量分数与地层水离子在“工程参数 → 矿物组成与地层水”录入。"]
        self.summary.configure(state="normal")
        self.summary.delete("1.0", "end")
        self.summary.insert("1.0", "\n".join(lines))
        self.summary.configure(state="disabled")
        if "horizontal" in self.app.pages:
            self.app.pages["horizontal"].acid_combo.configure(values=list(self.app.acid_systems))

    def edit_acid(self, new):
        source = self.app.acid_systems[self.library_var.get()]
        dialog = tk.Toplevel(self)
        dialog.title("新增酸液体系" if new else "编辑酸液体系")
        dialog.geometry("800x730")
        scroll = ScrollFrame(dialog)
        scroll.pack(fill="both", expand=True)
        values = {}
        for item in fields(source):
            ttk.Label(scroll.body, text=ACID_FIELD_LABELS[item.name]).pack(anchor="w", pady=(8, 2))
            value = getattr(source, item.name)
            if new and item.name == "name":
                value += " - 自定义"
            values[item.name] = tk.StringVar(value=str(value))
            if item.name == "reaction_model":
                ttk.Combobox(scroll.body,textvariable=values[item.name],values=("arrhenius","transport_limited"),state="readonly").pack(fill="x")
            else:
                ttk.Entry(scroll.body, textvariable=values[item.name], width=76).pack(fill="x")
        def save():
            try:
                acid = AcidSystem(**{item.name: values[item.name].get().strip() if isinstance(item.default, str)
                                     else get_val(values[item.name].get()) for item in fields(source)})
                validate_acid(acid)
                if acid.name != source.name and acid.name in self.app.acid_systems:
                    raise CalculationError("该体系名称已存在，请换一个名称")
                if new and acid.name == source.name:
                    raise CalculationError("新增体系请使用新名称")
                self.app.acid_systems[acid.name] = acid
                self.library_var.set(acid.name)
                self.refresh_library()
                self.app.status_var.set("酸液库已更新；保存方案或酸液库可保留本次修改")
                dialog.destroy()
            except Exception as exc:
                messagebox.showerror("酸液参数错误", str(exc), parent=dialog)
        ttk.Button(dialog, text="保存体系", style="Accent.TButton", command=save).pack(fill="x", padx=15, pady=10)

    def save_library(self):
        path = filedialog.asksaveasfilename(title="保存酸液库", defaultextension=".json", filetypes=[("JSON", "*.json")], parent=self)
        if path:
            try:
                save_response(path, {"acid_systems": {k: asdict(v) for k, v in self.app.acid_systems.items()}})
                messagebox.showinfo("保存完成", path, parent=self)
            except Exception as exc:
                messagebox.showerror("保存失败", str(exc), parent=self)

    def load_library(self):
        path = filedialog.askopenfilename(title="载入酸液库（合并）", filetypes=[("JSON", "*.json")], parent=self)
        if not path:
            return
        try:
            import json
            from pathlib import Path
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))["acid_systems"]
            payload = self.app.request_payload()
            payload["acid_systems"].update(raw)
            _, _, acids, _ = parse_request(payload)
            self.app.acid_systems = acids
            self.refresh_library()
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc), parent=self)


class DataExportPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "数据导出", "统一导出输入、评价结果和报告；数模接口与历史方案数据库在下方标签页中管理。")
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        files = ScrollFrame(self.notebook)
        self.notebook.add(files, text="文件与报告导出")
        actions = [
            ("输入参数", "导出工程参数、施工阶段和水平井分段输入，便于核对与归档。", "导出输入数据", app.export_input_data),
            ("完整评价结果", "导出当前方案的结果数据包，包含 Excel、Word、CSV 等成果。", "导出结果包", app.export_result_data),
            ("分析报告与施工方案", "单独保存 Word 分析报告或可打印的 HTML 施工方案初稿。", "导出报告", app.export_report),
        ]
        for title, description, label, command in actions:
            card = self.card(files.body)
            card.pack(fill="x", pady=(0, 12))
            card.columnconfigure(0, weight=1)
            tk.Label(card, text=title, font=("Microsoft YaHei UI", 12, "bold"), bg="white", fg=COLORS["text"]).grid(row=0, column=0, sticky="w", padx=18, pady=(16, 5))
            tk.Label(card, text=description, font=FONT, bg="white", fg=COLORS["muted"], wraplength=510, justify="left").grid(row=1, column=0, sticky="w", padx=18, pady=(0, 16))
            ttk.Button(card, text=label, command=command, width=16).grid(row=0, column=1, rowspan=2, padx=18, pady=16)
        ttk.Label(files.body, text="JSON 导入/导出与 Eclipse 映射：进入「数模接口与模型依据」。\n保存、载入、查询历史方案及连接设置：进入「方案数据库」。", style="Muted.TLabel", wraplength=740, justify="left").pack(anchor="w", pady=6)


class DatabasePage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "方案数据库", "保存完整输入、水平段模型、评价结果和模型版本，便于方案追溯")
        defaults = asdict(DatabaseConfig())
        self.db_vars = {
            key: tk.StringVar(value=os.getenv(
                "ACIDIZING_DB_NAME" if key == "database" else "ACIDIZING_DB_" + key.upper(), str(value)))
            for key, value in defaults.items()
        }
        settings = self.card()
        settings.pack(fill="x", pady=(0, 12))
        for column in range(3):
            settings.columnconfigure(column, weight=1, uniform="database")
        for index, (key, label) in enumerate([("host", "主机"), ("port", "端口"), ("user", "用户名"), ("password", "密码"), ("database", "数据库")]):
            field = ttk.Frame(settings)
            field.grid(row=index // 3, column=index % 3, sticky="ew", padx=12, pady=10)
            field.columnconfigure(0, weight=1)
            ttk.Label(field, text=label, style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
            ttk.Entry(field, textvariable=self.db_vars[key], width=14, show="*" if key == "password" else "").grid(row=1, column=0, sticky="ew")
        action = ttk.Frame(self, style="Canvas.TFrame")
        action.pack(fill="x", pady=(0, 8))
        ttk.Button(action, text="刷新历史记录", command=self.refresh).pack(side="left")
        ttk.Button(action, text="载入选中方案", command=self.load_selected).pack(side="left", padx=8)
        ttk.Button(action, text="删除选中方案", command=self.delete_selected).pack(side="left")
        ttk.Button(action, text="测试连接", command=self.test).pack(side="left", padx=8)
        ttk.Button(action, text="保存当前方案", style="Accent.TButton", command=app.save_current_case).pack(side="left")
        self.db_status = tk.StringVar(value="未连接")
        ttk.Label(action, textvariable=self.db_status, style="Muted.TLabel", background=COLORS["canvas"]).pack(side="right")
        frame, self.tree = make_tree(self, ("id", "name", "time", "radius", "volume", "benefit"), {"id": "编号", "name": "方案名称", "time": "保存时间", "radius": "有效半径(m)", "volume": "总液量(m3)", "benefit": "净收益"}, {"id": 70, "name": 250, "time": 170, "radius": 120, "volume": 120, "benefit": 130}, 14)
        frame.pack(fill="both", expand=True)

    def apply_settings(self):
        port = self.db_vars["port"].get().strip()
        if not port.isdigit():
            messagebox.showwarning("数据库设置", "端口必须是数字。", parent=self)
            return False
        mapping = {"ACIDIZING_DB_HOST": "host", "ACIDIZING_DB_PORT": "port", "ACIDIZING_DB_USER": "user", "ACIDIZING_DB_PASSWORD": "password", "ACIDIZING_DB_NAME": "database"}
        for env_name, key in mapping.items():
            os.environ[env_name] = self.db_vars[key].get() if key == "password" else self.db_vars[key].get().strip()
        return True

    def test(self):
        if not self.apply_settings():
            return
        try:
            message = test_connection()
        except Exception as exc:
            self.db_status.set("连接失败")
            messagebox.showerror("数据库连接失败", str(exc), parent=self)
            return
        self.db_status.set("连接正常")
        messagebox.showinfo("数据库连接", message, parent=self)

    def refresh(self):
        if not self.apply_settings():
            return
        try:
            records = list_cases()
        except Exception as exc:
            self.db_status.set("连接失败")
            messagebox.showerror("读取失败", str(exc), parent=self)
            return
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in records:
            self.tree.insert("", "end", iid=str(row["id"]), values=(row["id"], row["case_name"], row["created_at"], self._fmt(row.get("effective_radius")), self._fmt(row.get("total_acid_volume")), self._fmt(row.get("net_benefit"))))
        self.db_status.set("已连接 · %d 条记录" % len(records))

    def load_selected(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("载入方案", "请先选择一条记录。", parent=self)
            return
        try:
            record = load_case(int(selection[0]))
            payload = record.get("design_payload") or {"parameters": record.get("parameters", {}), "horizontal_segments": record.get("horizontal_segments") or None}
            self.app.apply_payload(payload)
            self.app.case_var.set(record.get("case_name", "已载入方案"))
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc), parent=self)

    def delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        if messagebox.askyesno("删除记录", "确定删除选中的数据库记录吗？", parent=self):
            try:
                delete_case(int(selection[0]))
                self.refresh()
            except Exception as exc:
                messagebox.showerror("删除失败", str(exc), parent=self)

    @staticmethod
    def _fmt(value):
        try:
            return "%.2f" % float(value)
        except (TypeError, ValueError):
            return "-"


class ModelPage(Page):
    def __init__(self, parent, app):
        super().__init__(parent, app, "模型依据与数据接口", "")
        self.subtitle_label.pack_forget()
        actions = ttk.Frame(self, style="Canvas.TFrame")
        actions.pack(fill="x", pady=(0, 12))
        for index, (label, command) in enumerate((("导入 JSON 参数", self.import_json), ("导出 JSON 参数", self.export_json), ("导出 JSON 结果", self.export_result), ("Eclipse 映射导出", self.export_eclipse))):
            ttk.Button(actions, text=label, command=command).grid(row=index // 3, column=index % 3, sticky="ew", padx=(0, 8), pady=(0, 6))


    def export_eclipse(self):
        if not self.app.calculate_current(show=False):
            return
        from .exchange import export_mapping_template, export_eclipse
        import csv
        source=filedialog.askopenfilename(title="选择已填写的Eclipse映射CSV；取消可保存空白模板",filetypes=[("CSV","*.csv")],parent=self)
        try:
            if not source:
                target=filedialog.asksaveasfilename(title="保存待填写的映射模板",defaultextension='.csv',filetypes=[('CSV','*.csv')],parent=self)
                if target:
                    export_mapping_template(target,self.app.latest_response)
                    messagebox.showinfo('映射模板已保存','请填写目标模型真实井名、I/J/K和原完井属性；不得对同一改造重复使用表皮和孔渗修正。',parent=self)
                return
            with open(source,encoding='utf-8-sig',newline='') as fp:
                mapping=list(csv.DictReader(fp))
            target=filedialog.asksaveasfilename(title='保存COMPDAT include（METRIC）',defaultextension='.inc',filetypes=[('Eclipse include','*.inc')],parent=self)
            if target:
                export_eclipse(target,self.app.latest_response,mapping)
                messagebox.showinfo('导出完成','已生成SCHEDULE段COMPDAT数据。请在目标数模中校验连接、单位和产能；当前未做Eclipse/Petrel端到端验证。',parent=self)
        except Exception as exc:
            messagebox.showerror('数模导出失败',str(exc),parent=self)

    def import_json(self):
        path = filedialog.askopenfilename(title="导入模型参数", filetypes=[("JSON", "*.json"), ("所有文件", "*.*")], parent=self)
        if not path:
            return
        try:
            payload = load_request(path)
            self.app.apply_payload(payload)
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc), parent=self)

    def export_json(self):
        path = filedialog.asksaveasfilename(title="导出模型参数", defaultextension=".json", filetypes=[("JSON", "*.json")], parent=self)
        if path:
            try:
                save_request(path, self.app.request_payload())
                messagebox.showinfo("导出完成", "模型输入参数已保存。", parent=self)
            except Exception as exc:
                messagebox.showerror("导出失败", str(exc), parent=self)

    def export_result(self):
        path = filedialog.asksaveasfilename(title="导出模型结果", defaultextension=".json", filetypes=[("JSON", "*.json")], parent=self)
        if path:
            try:
                save_response(path, calculate_design(self.app.request_payload()))
                messagebox.showinfo("导出完成", "标准接口结果已保存。", parent=self)
            except Exception as exc:
                messagebox.showerror("导出失败", str(exc), parent=self)
