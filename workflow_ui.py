"""Construction and economics controls; numbers stay full precision internally."""
from dataclasses import asdict, fields
import tkinter as tk
from tkinter import ttk, messagebox
from .ui import Page, ScrollFrame, make_tree, parameter_form, FONT
from .data import FLUID_FIELDS, STAGE_LABELS
from .calculations import CalculationError, get_val
from .model_api import INTERFACE_VERSION, parse_workflow
from .workflow import ConstructionStage, Economics, OptimizationConstraints, optimize_construction

ECON_LABELS={
    "base_oil_t_day":"酸化前日产油（t/d）", "oil_density_t_m3":"原油密度（t/m³）",
    "oil_price_usd_bbl":"油价情景（美元/桶）", "exchange_rate_cny_usd":"汇率（人民币/美元）",
    "effective_days":"有效期（天）", "annual_decline":"年指数递减系数（1/年）",
    "annual_discount":"年折现率（0–1）", "treatment_cost_cny_m3":"主体液单价（元/m³）",
    "preflush_cost_cny_m3":"前置液单价（元/m³）", "postflush_cost_cny_m3":"后置液单价（元/m³）",
    "displacement_cost_cny_m3":"顶替液单价（元/m³）", "crew_cost_cny":"施工队费用（元）",
    "other_cost_cny":"其他一次费用（元）", "operating_cost_cny_t":"增量采油运营成本（元/t）"}
ECON_OUTPUT={"barrels_per_tonne":"密度换算桶/吨", "oil_price_cny_t":"油价（元/t）",
    "initial_incremental_oil_t_day":"初期增油（t/d）", "incremental_oil_t":"累计增油（t）",
    "incremental_revenue_cny":"增油收入（元）", "fluid_cost_cny":"施工液费用（元）",
    "investment_cny":"总投入（元）", "incremental_operating_cost_cny":"增量运营费用（元）",
    "net_benefit_cny":"税前净收益（元）", "npv_cny":"税前净现值（元）", "payback_days":"评价期内回收期（天）"}


class EconomicsPage(Page):
    def __init__(self,parent,app):
        super().__init__(parent,app,"经济评价","日产油、原油密度、油价、汇率与作业成本均可输入；默认价格仅为演示情景。")
        bar=ttk.Frame(self); bar.pack(fill='x',pady=(0,8))
        ttk.Button(bar,text='计算当前方案经济性',command=app.calculate_current).pack(side='left')
        body=ttk.Panedwindow(self,orient='horizontal'); body.pack(fill='both',expand=True)
        form=ScrollFrame(body); body.add(form,weight=1)
        self.vars={}
        for f in fields(Economics):
            ttk.Label(form.body,text=ECON_LABELS[f.name]).pack(anchor='w',pady=(7,2))
            var=tk.StringVar(value=str(f.default)); self.vars[f.name]=var
            ttk.Entry(form.body,textvariable=var).pack(fill='x')
        frame,self.tree=make_tree(body,('item','value'),{'item':'评价指标','value':'数值'},{'item':230,'value':180},16)
        body.add(frame,weight=2)

    def get_config(self):
        return {key:get_val(v.get()) for key,v in self.vars.items()}

    def set_config(self,record):
        for f in fields(Economics):
            self.vars[f.name].set(str(record.get(f.name,f.default)))

    def update_results(self,response):
        self.tree.delete(*self.tree.get_children())
        for key,label in ECON_OUTPUT.items():
            value=response['economics'][key]
            self.tree.insert('','end',values=(label,'未回收' if value is None else format(value,',.2f')))


class ConstructionPage(Page):
    COLUMNS=('name','segment','kind','acid_system','volume','rate')
    HEADINGS=dict(zip(COLUMNS,('段塞名称','目标井段','阶段','配方名称','体积(m³)','排量(m³/min)')))

    def __init__(self,parent,app):
        super().__init__(parent,app,"施工参数","先检查开放位置，再按顺序输入段塞。自优化仅按工程约束筛选；压力为准稳态预测。阶段用量比例在同名标签页设置。")
        self.rows=[]; self.edit_index=None; self.loading=False
        self.mode=tk.StringVar(value='按分段生成')
        self.vars={k:tk.StringVar() for k in self.COLUMNS}
        self.constraints={f.name:tk.StringVar(value=str(f.default)) for f in fields(OptimizationConstraints)}
        book=ttk.Notebook(self); book.pack(fill='both',expand=True)
        self.notebook = book
        plan=ttk.Frame(book,padding=8); book.add(plan,text='施工段塞')
        completion=ttk.Frame(book,padding=14); book.add(completion,text='完井开放位置')
        pressure=ttk.Frame(book,padding=8); book.add(pressure,text='压力曲线')
        optimization=ttk.Frame(book,padding=14); book.add(optimization,text='施工自优化')
        book.add(parameter_form(book, app, [('fluid', FLUID_FIELDS)]), text='阶段用量比例')
        bar=ttk.Frame(plan); bar.pack(fill='x')
        ttk.Label(bar,text='方案方式').pack(side='left')
        ttk.Combobox(bar,textvariable=self.mode,values=('按分段生成','手动段塞'),state='readonly',width=14).pack(side='left',padx=6)
        ttk.Button(bar,text='从分段参数生成',command=self.generate).pack(side='left')
        ttk.Button(bar,text='运行当前方案',command=app.calculate_current).pack(side='right')
        frame,self.tree=make_tree(plan,self.COLUMNS,self.HEADINGS,{'name':150,'segment':90,'kind':85,'acid_system':220,'volume':100,'rate':120},10)
        frame.pack(fill='both',expand=True,pady=8)
        self.tree.bind('<<TreeviewSelect>>',self.select)
        editor=ttk.Frame(plan); editor.pack(fill='x')
        self.combos={}
        for i,key in enumerate(self.COLUMNS):
            ttk.Label(editor,text=self.HEADINGS[key]).grid(row=0,column=i,sticky='w',padx=3)
            if key in ('segment','kind','acid_system'):
                widget=ttk.Combobox(editor,textvariable=self.vars[key],state='readonly',width=16)
                self.combos[key]=widget
            else:
                widget=ttk.Entry(editor,textvariable=self.vars[key],width=15)
            widget.grid(row=1,column=i,sticky='ew',padx=3)
            editor.columnconfigure(i,weight=1)
            self.vars[key].trace_add('write',self.changed)
        buttons=ttk.Frame(plan); buttons.pack(fill='x',pady=8)
        for text,command in (('更新本条',self.commit),('新增段塞',self.add),('删除本条',self.delete),('上移',lambda:self.move(-1)),('下移',lambda:self.move(1))):
            ttk.Button(buttons,text=text,command=command).pack(side='left',padx=3)
        ttk.Label(completion,text='逐行输入开放区间的绝对测深：起点,终点（m）。\n空白时按当前处理井段生成开放区间；射孔完井仅允许在这些位置进液。\n裸眼、筛管和砾石充填也仅在指定开放区间注入。',wraplength=850).pack(anchor='w',pady=(0,10))
        self.intervals_text=tk.Text(completion,height=18,font=('Consolas',11)); self.intervals_text.pack(fill='both',expand=True)
        ttk.Button(completion,text='显示当前默认开放区间',command=self.show_intervals).pack(anchor='w',pady=8)
        self.pressure_canvas=tk.Canvas(pressure,bg='white',height=220,highlightthickness=0); self.pressure_canvas.pack(fill='x')
        cols=('time_min','stage','rate_m3_min','surface_pressure_mpa','bottom_pressure_mpa','within_limits')
        frame,self.pressure_tree=make_tree(pressure,cols,dict(zip(cols,('时间min','段塞','排量m³/min','井口MPa','井底MPa','压力约束'))),{x:140 for x in cols},9)
        frame.pack(fill='both',expand=True)
        labels={'max_total_volume':'总液量上限（m³，含顶替）','max_rate':'排量上限（m³/min）','target_ratio':'目标增产倍比','target_coverage':'目标覆盖率（0–1）'}
        for i,(key,var) in enumerate(self.constraints.items()):
            ttk.Label(optimization,text=labels[key]).grid(row=i,column=0,sticky='w',pady=8)
            ttk.Entry(optimization,textvariable=var).grid(row=i,column=1,padx=12)
        ttk.Button(optimization,text='自优化并载入建议施工方案',command=self.optimize).grid(row=4,column=0,columnspan=2,sticky='w',pady=12)
        self.optimization_status=tk.StringVar(value='21个有限候选；满足目标时优先少用液，达不到目标时明确提示。')
        ttk.Label(optimization,textvariable=self.optimization_status,wraplength=820).grid(row=5,column=0,columnspan=3,sticky='w')

    def changed(self,*_):
        if not self.loading:
            self.mode.set('手动段塞')

    def base_payload(self):
        # 组装施工方案时别再调用 app.request_payload，会递归
        if self.app.collect_parameters().well_type=='水平井':
            self.app.pages['horizontal'].commit_editor(silent=True)
        return {'interface_version':INTERFACE_VERSION,'parameters':asdict(self.app.collect_parameters()),
            'horizontal_segments':[asdict(s) for s in self.app.pages['horizontal'].get_segments()],
            'acid_systems':{k:asdict(v) for k,v in self.app.acid_systems.items()},
            'radial_acid_system':self.app.radial_acid_var.get(),'completion_intervals':self.read_intervals()}

    def read_intervals(self):
        raw=self.intervals_text.get('1.0','end').strip()
        if not raw:
            return None
        records=[]
        for line in raw.splitlines():
            if not line.strip():
                continue
            values=line.replace('，',',').split(',')
            if len(values)!=2:
                raise CalculationError('开放位置每行应为：起点,终点')
            records.append({'start_md':get_val(values[0]),'end_md':get_val(values[1])})
        return records

    def get_config(self):
        if self.mode.get()=='手动段塞':
            self.commit(silent=True)
        return {'construction_stages':[asdict(t) for t in self.rows] if self.mode.get()=='手动段塞' else None,
                'completion_intervals':self.read_intervals(),
                'optimization_constraints':{k:get_val(v.get()) for k,v in self.constraints.items()}}

    def set_config(self,payload):
        self.edit_index=None
        raw=payload.get('construction_stages')
        self.rows=[ConstructionStage(**r) for r in raw] if raw is not None else []
        self.mode.set('手动段塞' if raw is not None else '按分段生成')
        self.intervals_text.delete('1.0','end')
        if payload.get('completion_intervals') is not None:
            self.intervals_text.insert('1.0','\n'.join('%.12g,%.12g'%(x['start_md'],x['end_md']) for x in payload['completion_intervals']))
        for f in fields(OptimizationConstraints):
            self.constraints[f.name].set(str(payload.get('optimization_constraints',{}).get(f.name,f.default)))
        self.render()

    def generate(self):
        try:
            parsed=parse_workflow(self.base_payload())
            self.rows=parsed[5]; self.edit_index=None; self.mode.set('按分段生成'); self.render()
        except Exception as exc:
            messagebox.showerror('无法生成',str(exc),parent=self)

    def show_intervals(self):
        try:
            parsed=parse_workflow({**self.base_payload(),'completion_intervals':None})
            self.intervals_text.delete('1.0','end')
            self.intervals_text.insert('1.0','\n'.join('%.12g,%.12g'%(x.start_md,x.end_md) for x in parsed[4]))
        except Exception as exc:
            messagebox.showerror('开放区间错误',str(exc),parent=self)

    def render(self,index=0):
        self.edit_index=None
        self.tree.delete(*self.tree.get_children())
        for i,t in enumerate(self.rows):
            self.tree.insert('','end',iid=str(i),values=(t.name,t.segment,STAGE_LABELS[t.kind],t.acid_system,format(t.volume,'.2f'),format(t.rate,'.2f')))
        if self.rows:
            self.tree.selection_set(str(min(index,len(self.rows)-1))); self.select()

    def select(self,_event=None):
        selected=self.tree.selection()
        if not selected:
            return
        index=int(selected[0])
        if index==self.edit_index:
            return
        if self.edit_index is not None:
            try:
                self.commit(silent=True)
            except Exception as exc:
                self.tree.selection_set(str(self.edit_index))
                messagebox.showerror('段塞参数错误',str(exc),parent=self)
                return
        self.edit_index=index; self.loading=True
        for k,v in asdict(self.rows[index]).items():
            self.vars[k].set(str(v))
        self.combos['kind'].configure(values=tuple(STAGE_LABELS))
        names=[s.name for s in self.app.pages['horizontal'].get_segments()]
        if self.app.collect_parameters().well_type!='水平井':
            names=['主处理段']
        self.combos['segment'].configure(values=names)
        self.combos['acid_system'].configure(values=list(self.app.acid_systems))
        self.loading=False

    def commit(self,silent=False):
        if self.edit_index is None:
            return True
        try:
            values={k:get_val(v.get()) if k in ('volume','rate') else v.get().strip() for k,v in self.vars.items()}
            t=ConstructionStage(**values)
            candidate=list(self.rows); candidate[self.edit_index]=t
            parse_workflow({**self.base_payload(),'construction_stages':[asdict(x) for x in candidate]})
            self.rows=candidate
            self.tree.item(str(self.edit_index),values=(t.name,t.segment,STAGE_LABELS[t.kind],t.acid_system,format(t.volume,'.2f'),format(t.rate,'.2f')))
            return True
        except Exception as exc:
            if silent:
                raise
            messagebox.showerror('段塞参数错误',str(exc),parent=self)
            return False

    def add(self):
        if not self.commit():
            return
        try:
            parsed=parse_workflow(self.base_payload())
            segment=parsed[1][0].name
            self.rows.append(ConstructionStage('新增段塞%d'%(len(self.rows)+1),segment,'treatment',self.app.radial_acid_var.get(),10.,.1))
            self.mode.set('手动段塞'); self.render(len(self.rows)-1)
        except Exception as exc:
            messagebox.showerror('无法新增',str(exc),parent=self)

    def delete(self):
        if self.edit_index is not None:
            self.rows.pop(self.edit_index); self.mode.set('手动段塞'); self.render()

    def move(self,offset):
        if not self.commit() or self.edit_index is None:
            return
        i=self.edit_index; j=i+offset
        if 0<=j<len(self.rows):
            self.rows[i],self.rows[j]=self.rows[j],self.rows[i]
            self.mode.set('手动段塞'); self.render(j)

    def optimize(self):
        # print("开始优化施工参数")
        try:
            payload=self.app.request_payload()
            p,segments,acids,_,intervals,stages,_,constraints=parse_workflow(payload)
            self.app.configure(cursor='watch'); self.app.update_idletasks()
            plan,candidates,best=optimize_construction(p,segments,acids,stages,intervals,constraints)
            self.rows=plan; self.mode.set('手动段塞'); self.render()
            self.app.latest_optimization=candidates
            self.optimization_status.set(('达到目标。' if best['meets_target'] else '未达到设定目标，载入约束内表现最好的候选。')+
                '总液量 %.2f m³，增产倍比 %.2f，覆盖率 %.2f%%。%s'%(best['total_volume_m3'],best['productivity_ratio'],100*best['coverage'],best['note']))
            self.app.calculate_current(show=False)
        except Exception as exc:
            messagebox.showerror('施工自优化未完成',str(exc),parent=self)
        finally:
            self.app.configure(cursor='')

    def update_results(self,response):
        if self.mode.get()=='按分段生成':
            self.rows=[ConstructionStage(**r) for r in response['input_snapshot']['construction_stages']]
            self.render()
        self.pressure_tree.delete(*self.pressure_tree.get_children())
        for row in response['pressure_curve']:
            self.pressure_tree.insert('','end',values=(format(row['time_min'],'.2f'),row['stage'],format(row['rate_m3_min'],'.2f'),
                format(row['surface_pressure_mpa'],'.2f'),format(row['bottom_pressure_mpa'],'.2f'),'满足' if row['within_limits'] else '超限'))
        self.draw_pressure(response['pressure_curve'])

    def draw_pressure(self,rows):
        canvas=self.pressure_canvas; canvas.delete('all'); canvas.update_idletasks()
        if not rows:
            canvas.create_text(300,100,text='当前无施工段塞',font=FONT); return
        w=max(canvas.winfo_width(),700); h=220; left=60; bottom=h-35
        tmax=max(r['time_min'] for r in rows) or 1
        vmax=max(max(r[k] for k in ('surface_pressure_mpa','bottom_pressure_mpa','bottom_limit_mpa','surface_limit_mpa')) for r in rows)*1.1
        vmin=min(0,min(r['surface_pressure_mpa'] for r in rows))
        for j in range(5):
            value=vmin+(vmax-vmin)*j/4; y=bottom-(bottom-25)*j/4
            canvas.create_line(left,y,w-20,y,fill='#d8e0e6')
            canvas.create_text(left-8,y,text='%.2f'%value,anchor='e')
        for key,color,label in (('surface_pressure_mpa','#087f8c','井口'),('bottom_pressure_mpa','#b36b12','井底'),('bottom_limit_mpa','#c2413b','井底限压'),('surface_limit_mpa','#7344ad','井口限压')):
            coords=[]
            for r in rows:
                coords += [left+(w-left-20)*r['time_min']/tmax,bottom-(bottom-25)*(r[key]-vmin)/(vmax-vmin)]
            if len(coords)>=4:
                canvas.create_line(*coords,fill=color,width=2)
            canvas.create_text(left+110*list(('surface_pressure_mpa','bottom_pressure_mpa','bottom_limit_mpa','surface_limit_mpa')).index(key),12,text=label,fill=color,anchor='w')
        canvas.create_text(w/2,h-10,text='时间 min（0 至 %.2f）；纵轴 MPa'%tmax)
