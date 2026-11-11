from dataclasses import dataclass

# 下面这些字段，酸液编辑界面也要用
ACID_FIELD_LABELS = {
    "name": "体系名称", "preflush_type": "前置液类型", "preflush_formula": "前置液配方",
    "treatment_type": "处理液类型", "treatment_formula": "处理液配方（与下方数值核对）",
    "postflush_type": "后置液类型", "postflush_formula": "后置液配方",
    "displacement_type": "顶替液类型", "displacement_formula": "顶替液配方",
    "hcl_fraction": "处理液 HCl 质量分数 (0–1)", "hf_fraction": "处理液 HF 质量分数 (0–1)",
    "organic_fraction": "处理液有机酸质量分数 (乙酸当量)", "density": "密度 (kg/m³)",
    "viscosity": "黏度 (mPa·s)", "heat_capacity": "比热 (J/kg/K)",
    "reference_temperature": "参考温度 (℃)", "rate_constant": "参考集总速率 (1/min，需标定)",
    "activation_energy": "表观活化能 (kJ/mol，需标定)", "reaction_heat": "放热量 (kJ/mol 酸，需标定)",
    "dissolving_capacity": "HF 溶蚀能力 (kg岩石/kg HF)", "retardation_factor": "缓速因子 (>0，1为不缓速)",
    "preflush_efficiency": "前置液最大有效系数 (0–1)", "flowback_efficiency": "后置液最大携出系数 (0–1)",
    "max_temperature": "实验支持的最高温度 (℃)", "calibration_note": "实验/文献/标定依据（必填）",
}


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    unit: str
    default: str


@dataclass(frozen=True)
class StageSpec:
    key: str
    label: str


STAGE_SPECS = (
    StageSpec("preflush", "前置液"),
    StageSpec("treatment", "主体液"),
    StageSpec("postflush", "后置液"),
    StageSpec("displacement", "顶替液"),
)
STAGE_KINDS = tuple(stage.key for stage in STAGE_SPECS)
STAGE_LABELS = {stage.key: stage.label for stage in STAGE_SPECS}


WELL_FIELDS = [
    FieldSpec("rw", "井筒半径", "m", "0.05221"),
    FieldSpec("rti", "油管内半径", "m", "0.033755"),
    FieldSpec("Zh", "处理段底部测深（水平井填入口）", "m", "4969"),
    FieldSpec("vertical_depth", "储层垂深", "m", "3000"),
    FieldSpec("Tb", "恒温点温度", "℃", "25"),
    FieldSpec("Zb", "恒温点垂深", "m", "20"),
    FieldSpec("aT", "垂向地温梯度", "℃/m", "0.02"),
    FieldSpec("Tf", "井口注入温度", "℃", "20"),
    FieldSpec("heat_transfer_u", "井筒有效传热系数", "W/m²/K", "12"),
    FieldSpec("h", "直井参考产层厚度", "m", "17.5"),
    FieldSpec("re", "泄油半径", "m", "200"),
    FieldSpec("Ps", "地层压力", "MPa", "47.1062"),
    FieldSpec("alpha", "破裂压力梯度", "MPa/m", "0.029"),
    FieldSpec("limit_p", "井口施工限压", "MPa", "70"),
    FieldSpec("Np", "有效射孔孔数", "个", "250"),
    FieldSpec("Dp", "孔眼直径", "m", "0.012"),
    FieldSpec("aM", "孔眼流量系数", "0–1", "0.82"),
    FieldSpec("f", "1m³/min参考排量下的摩阻梯度", "MPa/m", "0.003"),
    FieldSpec("well_type", "井形", "", "水平井"),
    FieldSpec("completion_type", "完井方式", "", "射孔完井"),
    FieldSpec("inclination_deg", "处理段井斜角（相对铅垂线）", "°", "90"),
    FieldSpec("completion_resistance", "筛管/砾石附加阻力", "MPa/(m³/min)", "0"),
]
RESERVOIR_FIELDS = [
    FieldSpec("ko", "原始渗透率", "mD", "36.12"),
    FieldSpec("kd", "污染渗透率", "mD", "12.3"),
    FieldSpec("o", "孔隙度", "0–1", "0.145"),
    FieldSpec("Rd", "直井污染半径（井轴起算）", "m", "1.05221"),
    FieldSpec("max_penetration", "井壁外最大作用深度", "≤2 m", "2"),
    FieldSpec("pr", "岩石颗粒密度", "g/cm³", "2.6"),
    FieldSpec("rock_cp", "岩石比热", "J/kg/K", "850"),
    FieldSpec("oil_viscosity", "产出流体黏度", "mPa·s", "2"),
    FieldSpec("oil_volume_factor", "产出流体体积系数", "-", "1.1"),
    FieldSpec("damage_solid_fraction", "等效伤害固相体积分数", "需标定", "0.005"),
    FieldSpec("water_saturation", "含水饱和度", "0–1", "0.3"),
    FieldSpec("oil_saturation", "含油饱和度", "0–1", "0.7"),
    FieldSpec("gas_saturation", "含气饱和度", "0–1", "0"),
    FieldSpec("oil_relative_permeability", "油相相对渗透率（实验输入）", "0–1", "1"),
]
MINERAL_FIELDS = [
    FieldSpec("quartz", "石英（SiO₂）质量分数", "0–1", "0.70"),
    FieldSpec("feldspar", "长石（铝硅酸盐）质量分数", "0–1", "0.15"),
    FieldSpec("clay", "黏土矿物质量分数", "0–1", "0.10"),
    FieldSpec("carbonate", "碳酸盐（CaCO₃当量）质量分数", "0–1", "0.03"),
    FieldSpec("other_minerals", "其他矿物（按惰性）质量分数", "0–1", "0.02"),
    FieldSpec("calcium_mg_l", "地层水 Ca²⁺", "mg/L", "1000"),
    FieldSpec("sodium_mg_l", "地层水 Na⁺", "mg/L", "5000"),
    FieldSpec("potassium_mg_l", "地层水 K⁺", "mg/L", "200"),
    FieldSpec("magnesium_mg_l", "地层水 Mg²⁺", "mg/L", "200"),
    FieldSpec("chloride_mg_l", "地层水 Cl⁻", "mg/L", "10000"),
    FieldSpec("sulfate_mg_l", "地层水 SO₄²⁻", "mg/L", "200"),
    FieldSpec("bicarbonate_mg_l", "地层水 HCO₃⁻", "mg/L", "300"),
    FieldSpec("salinity_mg_l", "实测矿化度", "mg/L", "16000"),
    FieldSpec("water_mode", "地层水处理：ions仅离子/normalize_tds归一化", "", "ions"),
    FieldSpec("precipitation_enabled", "考虑二次沉淀（1开/0关）", "0 或 1", "1"),
    FieldSpec("precipitation_yield", "沉淀质量系数", "需标定", "0.6"),
    FieldSpec("plugging_sensitivity", "孔喉堵塞敏感系数", "需标定", "30"),
]
FLUID_FIELDS = [
    FieldSpec("preflush_ratio", "每段前置液/处理液体积比", "m³/m³", "0.25"),
    FieldSpec("postflush_ratio", "每段后置液/处理液体积比", "m³/m³", "0.20"),
]

ACID_FIELD_LABELS.update({"reaction_model":"反应模型：arrhenius动力学 / transport_limited动力学与传质串联",
                         "mass_transfer_rate":"等效传质速率（1/min，需岩心标定）"})

PARAMETER_CHOICES = {"well_type":("直井","斜井","定向井","水平井"),
    "completion_type":("射孔完井","裸眼完井","筛管完井","砾石充填"),
    "water_mode":("ions","normalize_tds")}
