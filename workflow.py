"""Ordered slug screening, completion access, pressure and incremental economics.

Sequential slugs share a fixed mixed treatment annulus per interval. This is not
a spatial reactive-transport solver. All closures and limitations are in MODEL_NOTES.
"""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass, fields, replace
from .calculations import (HorizontalSegment,
    HorizontalEvaluation, SegmentEvaluation, ReactionResult, CalculationError,
    MODEL_VERSION, PI, _range, _hydraulics, _indices, _treatment, react,
    validate_parameters, validate_segments, segment_depth,
    wellbore_temperature_profile, formation_temperature, hydraulic_coefficients, permeability_cv)
from .data import STAGE_KINDS


@dataclass(frozen=True)
class ConstructionStage:
    name: str
    segment: str
    kind: str
    acid_system: str
    volume: float
    rate: float


@dataclass(frozen=True)
class CompletionInterval:
    start_md: float
    end_md: float


@dataclass(frozen=True)
class Economics:
    base_oil_t_day: float = 10.0
    oil_density_t_m3: float = .85
    oil_price_usd_bbl: float = 80.0
    exchange_rate_cny_usd: float = 7.0
    effective_days: float = 180.0
    annual_decline: float = .0  # 指数递减率，单位 1/年
    annual_discount: float = .08
    treatment_cost_cny_m3: float = 1200.0
    preflush_cost_cny_m3: float = 800.0
    postflush_cost_cny_m3: float = 500.0
    displacement_cost_cny_m3: float = 100.0
    crew_cost_cny: float = 500000.0
    other_cost_cny: float = 0.0
    operating_cost_cny_t: float = 300.0


@dataclass(frozen=True)
class OptimizationConstraints:
    max_total_volume: float = 5000.0
    max_rate: float = 2.0
    target_ratio: float = 1.2
    target_coverage: float = .8


def validate_economics(e):
    for f in fields(e):
        _range(getattr(e, f.name), 0, 1e12, f.name)
    _range(e.oil_density_t_m3, .1, 2, "原油密度(t/m³)")
    _range(e.exchange_rate_cny_usd, 0, 1000, "汇率", True)
    _range(e.effective_days, 0, 36500, "评价天数", True)
    _range(e.annual_decline, 0, 10, "年递减系数")
    _range(e.annual_discount, 0, 10, "年折现率")


def economic_evaluation(e, ratio, volumes):
    validate_economics(e)
    _range(ratio, 0, 1e12, "产能倍比")
    barrels = 1 / (e.oil_density_t_m3 * .158987294928)
    delta = e.base_oil_t_day * (ratio - 1)
    decline = e.annual_decline / 365
    discount = math.log1p(e.annual_discount) / 365
    def integral(rate):
        return -math.expm1(-rate * e.effective_days) / rate if rate else e.effective_days
    tonnes = delta * integral(decline)
    price_t = barrels * e.oil_price_usd_bbl * e.exchange_rate_cny_usd
    fluid_cost = sum(volumes.get(k, 0)*getattr(e, k+"_cost_cny_m3")
                     for k in STAGE_KINDS)
    investment = fluid_cost + e.crew_cost_cny + e.other_cost_cny
    revenue = tonnes * price_t
    operating = tonnes * e.operating_cost_cny_t
    net = revenue - operating - investment
    npv = delta * (price_t-e.operating_cost_cny_t)*integral(decline+discount)-investment
    daily_margin = delta * (price_t-e.operating_cost_cny_t)
    payback = None
    if investment == 0:
        payback = 0.0
    elif daily_margin > 0:
        if decline == 0:
            payback = investment/daily_margin
        elif investment*decline/daily_margin < 1:
            payback = -math.log1p(-investment*decline/daily_margin)/decline
        if payback is not None and payback > e.effective_days:
            payback = None
    return {"barrels_per_tonne": barrels, "oil_price_cny_t": price_t,
            "initial_incremental_oil_t_day": delta, "incremental_oil_t": tonnes,
            "incremental_revenue_cny": revenue, "fluid_cost_cny": fluid_cost,
            "investment_cny": investment, "incremental_operating_cost_cny": operating,
            "net_benefit_cny": net, "npv_cny": npv, "payback_days": payback,
            "assumption": "同压差下油相产量随产能指数变化；所有价格均为用户情景输入；税前增量评价"}


def active_segments(p, segments, acid_name):
    if p.well_type == "水平井":
        return list(segments)
    cosine = math.cos(math.radians(p.inclination_deg))
    if cosine < .05:
        raise CalculationError("非水平井的层厚换算要求井斜角小于87.13°；近水平段请选择水平井并输入实际长度")
    length = p.h / cosine
    if length >= p.Zh:
        raise CalculationError("处理层段长度不能超过井深")
    return [HorizontalSegment("主处理段", 0, length, p.ko, p.kd, porosity=p.o,
            damage_depth=p.Rd-p.rw, acid_volume=p.h*p.V_per_m, acid_system=acid_name,
            contact_time=120)]


def origin_md(p, segments):
    return p.Zh if p.well_type == "水平井" else p.Zh-segments[-1].end_md


def default_completions(p, segments):
    origin = origin_md(p, segments)
    return [CompletionInterval(origin+s.start_md, origin+s.end_md) for s in segments]


def validate_completions(p, segments, intervals):
    if not intervals:
        raise CalculationError("至少输入一个开放/射孔区间（绝对测深）")
    origin = origin_md(p, segments)
    previous = 0
    for row in intervals:
        _range(row.start_md, previous, origin+segments[-1].end_md, "开放区间起点")
        _range(row.end_md, row.start_md, origin+segments[-1].end_md, "开放区间终点", True)
        previous = row.end_md


def open_geometry(p, segment, segments, intervals):
    origin = origin_md(p, segments)
    a, b = origin+segment.start_md, origin+segment.end_md
    overlaps = [(max(a,i.start_md), min(b,i.end_md)) for i in intervals
                if min(b,i.end_md) > max(a,i.start_md)]
    length = sum(y-x for x,y in overlaps)
    center = sum((y-x)*(y+x)/2 for x,y in overlaps)/length if length else (a+b)/2
    dz = math.cos(math.radians(p.inclination_deg))
    tvd = p.vertical_depth+(center-p.Zh)*dz
    _range(tvd,0,15000,"活动段垂深",True)
    _range(formation_temperature(p, tvd),-20,250,"活动段地层温度")
    local = replace(p, vertical_depth=tvd)
    return length, center, local


def default_stages(p, segments, acids, intervals):
    stages=[]
    for s in segments:
        length, md, local = open_geometry(p,s,segments,intervals)
        if not length or not s.acid_volume:
            continue
        selected=s.acid_system
        acid=acids[selected]
        try:
            allowed=.9*_hydraulics(local,length,s.permeability,s.damaged_permeability,
                    p.rw+segment_depth(s,p),acid.viscosity,acid.density,md)[3]
        except CalculationError:
            allowed=s.acid_volume/s.contact_time
        rate=min(s.acid_volume/s.contact_time,allowed)
        for kind,volume,name in (("preflush",s.acid_volume*p.preflush_ratio,"前置盐酸10%（示例）"),
                    ("treatment",s.acid_volume,selected),
                    ("postflush",s.acid_volume*p.postflush_ratio,"后置盐酸3%（示例）")):
            if volume:
                # 用户导入的库里可能没有默认的前后置液
                stages.append(ConstructionStage(s.name+"-"+kind,s.name,kind,
                              name if name in acids else selected,volume,rate))
    if stages:
        volume=PI*p.rti**2*(origin_md(p,segments)+segments[-1].end_md)
        stages.append(ConstructionStage("末次顶替",stages[-1].segment,"displacement",
            "配伍盐水（示例）" if "配伍盐水（示例）" in acids else stages[-1].acid_system,
            volume,stages[-1].rate))
    return stages


def validate_stages(stages, segments, acids):
    if len(stages)>500:
        raise CalculationError("施工段塞最多500条")
    names=set()
    targets={s.name for s in segments}
    for stage in stages:
        if not stage.name.strip() or stage.name in names:
            raise CalculationError("施工段塞名称不能为空或重复")
        names.add(stage.name)
        if stage.segment not in targets:
            raise CalculationError("段塞 %s 的目标井段不存在：%s"%(stage.name,stage.segment))
        if stage.kind not in STAGE_KINDS:
            raise CalculationError("段塞类型应为 " + "/".join(STAGE_KINDS))
        if stage.acid_system not in acids:
            raise CalculationError("段塞引用的配方不存在："+stage.acid_system)
        _range(stage.volume,0,1e6,"段塞体积",True)
        _range(stage.rate,0,1000,"段塞排量",True)


def pressure_state(p, length, k, acid, md, rate, skin=0.0, k0=None):
    linear, quadratic = hydraulic_coefficients(p, length, k0 or k, acid.viscosity, acid.density, skin)
    bottom = p.Ps + rate * linear + quadratic * rate ** 2
    friction=p.f*md*rate**2
    surface=bottom-acid.density*9.80665*p.vertical_depth/1e6+friction
    return surface,bottom


def simulate_schedule(p, segments, acids, stages, intervals):
    # print("施工计算，井段/段塞数：", len(segments), len(stages))
    validate_parameters(p)
    validate_segments(p,segments,acids)
    validate_completions(p,segments,intervals)
    validate_stages(stages,segments,acids)
    states={}
    # 每段固定一个混合环带体积，各反应段塞共用
    for s in segments:
        length,md,local=open_geometry(p,s,segments,intervals)
        target=[t for t in stages if t.segment==s.name]
        if target and not length:
            raise CalculationError(s.name+"没有开放/射孔区间，不能注入施工液")
        reactive=[t for t in target if t.kind!="displacement" and
                  sum((acids[t.acid_system].hcl_fraction,acids[t.acid_system].hf_fraction,
                       acids[t.acid_system].organic_fraction))>0]
        active_volume=0.
        for t in reactive:
            acid=acids[t.acid_system]
            thermal_p=p if p.well_type=="水平井" else replace(p,Zh=md,vertical_depth=local.vertical_depth)
            temps=wellbore_temperature_profile(thermal_p,t.rate,md-p.Zh if p.well_type=="水平井" else 0,acid)
            reach,_=_treatment(local,acid,t.volume,t.volume/t.rate,length,s.porosity,
                               s.permeability,s.damaged_permeability,temps[-1].fluid_temperature)
            active_volume+=PI*length*s.porosity*(reach**2-p.rw**2)
        radius=math.sqrt(p.rw**2+active_volume/(PI*length*s.porosity)) if length and active_volume else p.rw
        radius=min(radius,p.rw+p.max_penetration)
        bulk=PI*(radius**2-p.rw**2)*length
        mass=bulk*(1-s.porosity)*p.pr*1000
        states[s.name]={"s":s,"length":length,"md":md,"p":local,"radius":radius,
            "bulk":bulk,"phi":s.porosity,"k":s.damaged_permeability,"initial_mass":mass,
            "minerals":{k:mass*getattr(p,k) for k in ("quartz","feldspar","clay","carbonate","other_minerals")},
            "dissolved":0.,"silicate":0.,"carbonate":0.,"precip":0.,"heat":0.,
            "risk":0.,"average_rate":0.,"clean_k":s.damaged_permeability,
            "acid_in":0.,"acid_out":0.,"temperature":p.Tf,"inlet":p.Tf,
            "warnings":[],"profiles":[],"stages":{k:0. for k in STAGE_KINDS},
            "max_rate":0.,"allowed":float('inf'),"last_acid":s.acid_system,"pre_volume":0.}
    curve=[]
    stage_results=[]
    clock=0.
    for stage in stages:
        state=states[stage.segment]
        s=state['s']; local=state['p']; acid=acids[stage.acid_system]
        length=state['length']; md=state['md']; duration=stage.volume/stage.rate
        sb,skin_before,_,_,_= _indices(local,length,s.permeability,s.damaged_permeability,
            p.rw+segment_depth(s,p),state['radius'],state['k'])
        # 没处理到的环带仍取污染渗透率，保持初始表皮值不变
        if not state['dissolved']:
            skin_before=sb
        surface0,bottom0=pressure_state(local,length,state['k'],acid,md,stage.rate,skin_before,s.permeability)
        if p.well_type=="水平井":
            temps=wellbore_temperature_profile(p,stage.rate,md-p.Zh,acid)
        else:
            temps=wellbore_temperature_profile(replace(p,Zh=md,vertical_depth=local.vertical_depth),stage.rate,acid=acid)
        inlet=temps[-1].fluid_temperature
        state['inlet']=inlet; state['profiles']=temps
        state['stages'][stage.kind]+=stage.volume
        if stage.kind=="preflush":
            state['pre_volume']+=stage.volume
        current_minerals=sum(state['minerals'].values())
        reactive=stage.kind!="displacement" and state['bulk']>0 and current_minerals>0
        if reactive:
            mineral_fractions={key:value/current_minerals for key,value in state['minerals'].items()}
            # 只有已经注入的前置液才起保护作用，后面的液体不能提前算
            local_rx=replace(local,**mineral_fractions,
                preflush_ratio=state['pre_volume']/max(stage.volume,1e-12),postflush_ratio=0.)
            rx=react(local_rx,acid,stage.volume,duration,state['bulk'],state['phi'],
                     s.permeability,state['k'],inlet,
                     available_silicate=sum(state['minerals'][k] for k in ("quartz","feldspar","clay")),
                     available_carbonate=state['minerals']['carbonate'])
            state['phi']=rx.porosity_after; state['k']=rx.permeability_after
            state['temperature']=rx.temperature; state['heat']+=rx.reaction_temperature_rise
            state['dissolved']+=rx.dissolved_rock_kg; state['precip']+=rx.precipitate_kg
            state['risk']=max(state['risk'],rx.precipitation_risk)
            state['average_rate']=max(state['average_rate'],rx.average_rate)
            state['clean_k']=rx.permeability_without_precipitation
            state['silicate']+=rx.dissolved_silicate_kg; state['carbonate']+=rx.dissolved_carbonate_kg
            silicate_mass=sum(state['minerals'][key] for key in ("quartz","feldspar","clay"))
            for key in ("quartz","feldspar","clay"):
                state['minerals'][key]*=max(0,1-rx.dissolved_silicate_kg/max(silicate_mass,1e-12))
            state['minerals']['carbonate']=max(0,state['minerals']['carbonate']-rx.dissolved_carbonate_kg)
            mass=stage.volume*acid.density*(acid.hcl_fraction+acid.hf_fraction+acid.organic_fraction)
            state['acid_in']+=mass; state['acid_out']+=mass*rx.acid_remaining_fraction
            state['warnings'].extend(rx.warnings)
        _,skin_after,j0,jd,ja=_indices(local,length,s.permeability,s.damaged_permeability,
            p.rw+segment_depth(s,p),state['radius'] if state['dissolved'] else p.rw,state['k'])
        surface1,bottom1=pressure_state(local,length,state['k'],acid,md,stage.rate,skin_after,s.permeability)
        allowed=.0
        try:
            allowed=.9*_hydraulics(local,length,s.permeability,s.damaged_permeability,
                p.rw+segment_depth(s,p),acid.viscosity,acid.density,md)[3]
        except CalculationError as exc:
            state['warnings'].append(str(exc))
        state['allowed']=min(state['allowed'],allowed)
        state['max_rate']=max(state['max_rate'],stage.rate)
        state['last_acid']=acid.name
        feasible=max(surface0,surface1)<=p.limit_p and max(bottom0,bottom1)<=.9*p.alpha*local.vertical_depth
        if not feasible:
            state['warnings'].append(stage.name+"超出井口限压或90%破裂压力约束")
        for fraction in (0.,.25,.5,.75,1.):
            curve.append({"time_min":clock+duration*fraction,"stage":stage.name,"segment":stage.segment,
                "rate_m3_min":stage.rate,"cumulative_stage_volume_m3":stage.volume*fraction,
                "surface_pressure_mpa":surface0+(surface1-surface0)*fraction,
                "bottom_pressure_mpa":bottom0+(bottom1-bottom0)*fraction,
                "bottom_limit_mpa":.9*p.alpha*local.vertical_depth,"surface_limit_mpa":p.limit_p,
                "inlet_temperature_c":inlet,"within_limits":feasible})
        clock+=duration
        stage_results.append({**asdict(stage),"duration_min":duration,"end_time_min":clock,
            "inlet_temperature_c":inlet,"skin_after":skin_after,"porosity_after":state['phi'],
            "permeability_after_md":state['k'],"within_limits":feasible,
            "reaction_temperature_c":state['temperature'],
            "temperature_within_range":max(inlet,state['temperature'],formation_temperature(local))<=acid.max_temperature})
    evaluations=[]
    for state in states.values():
        s=state['s']; length=state['length']; local=state['p']; depth=segment_depth(s,p)
        radius=state['radius'] if state['dissolved'] else p.rw
        sb,sa,j0,jd,ja=_indices(local,length,s.permeability,s.damaged_permeability,p.rw+depth,radius,state['k'])
        coverage=min(1.,(radius-p.rw)/depth)
        ratio=ja/jd if jd else 1.
        notes=list(dict.fromkeys(state['warnings']))
        if depth>p.max_penetration:
            notes.append("污染深度超过用户设置的作用深度上限")
        if not length:
            notes.append("无开放区间：本段不计入产能与注入")
        if ratio<1:
            notes.append("处理后产能下降")
        status="高风险" if notes or ratio<1 else "有效" if coverage>=.99 else "可改善"
        rx=ReactionResult(state['acid_out']/state['acid_in'] if state['acid_in'] else 1.,
            state['dissolved'],state['dissolved']/state['initial_mass'] if state['initial_mass'] else 0.,
            state['precip'],state['risk'],state['temperature'],state['heat'],state['average_rate'],state['phi'],state['k'],state['clean_k'],notes,
            state['silicate'],state['carbonate'])
        evaluations.append(SegmentEvaluation(s.name,s.start_md,s.end_md,length,sb,state['stages']['treatment'],
            radius,coverage,sa,ratio,100*coverage,status,"；".join(notes) or "按分段封隔、顺序段塞近似计算",
            depth,radius-p.rw,state['last_acid'],j0,jd,ja,ja/j0 if j0 else 1.,state['inlet'],rx,
            state['stages'],state['profiles'],state['max_rate'],state['allowed'] if math.isfinite(state['allowed']) else 0.,
            p.limit_p,sum(t.volume/t.rate for t in stages if t.segment==s.name),notes))
    length=sum(s.length for s in evaluations)
    if length<=0:
        raise CalculationError("所有处理段均无开放区间，请检查完井位置")
    totals={key:sum(s.stage_volumes[key] for s in evaluations) for key in STAGE_KINDS}
    j0=sum(s.productivity_undamaged for s in evaluations); jd=sum(s.productivity_damaged for s in evaluations); ja=sum(s.productivity_after for s in evaluations)
    coverage=sum(s.coverage_ratio*s.length for s in evaluations)/length
    cv = permeability_cv(segments)
    notes=["%s，%s，开放长度 %.2f m；%d 个施工段塞。"%(p.well_type,p.completion_type,length,len(stages)),
           "顺序段塞集总筛选：同一井段共享混合反应域；未求解段塞前缘与完整化学输运。",
           "分段产能采用共用压差、独立径向近似；饱和度为记录值，油相相对渗透率需实验输入。",
           "压力曲线为段塞起止准稳态压力的线性连接，不含泵启停、水击及实时监测。",
           "各段放热温升为段塞温升累计指标，不代表井底峰值温升。"]
    horizontal=HorizontalEvaluation(MODEL_VERSION,"非均质" if cv>=.25 else "近似均质",length,cv,coverage,ja/jd,
          sum(s.status=="高风险" for s in evaluations),evaluations,notes,totals['treatment'],totals,sum(totals.values()),j0,jd,ja)
    return horizontal,curve,stage_results


def optimize_construction(p, segments, acids, stages, intervals, constraints):
    for f in fields(constraints):
        _range(getattr(constraints,f.name),0,1e8,f.name,True)
    _range(constraints.target_coverage,0,1,"目标覆盖率",True)
    if not stages:
        raise CalculationError("请先生成或录入施工段塞")
    candidates=[]
    best=None
    for scale in (.25,.5,.75,1.,1.25,1.5,2.):
        for speed in (.5,.8,1.):
            plan=[]
            for t in stages:
                s=next(x for x in segments if x.name==t.segment)
                length,md,local=open_geometry(p,s,segments,intervals)
                if not length:
                    raise CalculationError(s.name+"没有开放区间")
                acid=acids[t.acid_system]
                allowed=.9*_hydraulics(local,length,s.permeability,s.damaged_permeability,
                            p.rw+segment_depth(s,p),acid.viscosity,acid.density,md)[3]
                plan.append(replace(t,volume=t.volume if t.kind=="displacement" else t.volume*scale,
                             rate=min(constraints.max_rate,allowed)*speed))
            total=sum(t.volume for t in plan)
            if total>constraints.max_total_volume:
                continue
            h,curve,details=simulate_schedule(p,segments,acids,plan,intervals)
            feasible=all(x['within_limits'] for x in curve) and all(x['temperature_within_range'] for x in details)
            meets=h.expected_productivity_ratio>=constraints.target_ratio and h.average_coverage>=constraints.target_coverage
            row={"scale":scale,"rate_fraction":speed,"total_volume_m3":total,
                 "productivity_ratio":h.expected_productivity_ratio,"coverage":h.average_coverage,
                 "within_limits":feasible,"meets_target":meets,"minutes":sum(t.volume/t.rate for t in plan)}
            candidates.append(row)
            if feasible:
                score=(int(meets),-total if meets else h.expected_productivity_ratio,h.average_coverage,-row['minutes'])
                if best is None or score>best[0]:
                    best=(score,plan,row)
    if best is None:
        raise CalculationError("有限候选集中没有满足总液量、排量及压力约束的方案，请调整约束")
    return best[1],candidates,{**best[2],"note":"有限候选筛选，不保证全局最优；未使用价格或经济指标"}
