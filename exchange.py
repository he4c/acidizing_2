"""Portable result exports and explicit, validated Eclipse connection mapping."""
from __future__ import annotations
import html
import json
import math
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape
from .calculations import CalculationError
from .exporters import _folder, _write_csv, _records_csv



def report_tables(response, format_money=False):
    h=response['horizontal_summary']; e=response['economics']
    summary=[['当前井形',response['active_well_type']],['模型版本',response['model_version']],
        ['增产倍比',h['expected_productivity_ratio']],['平均覆盖率',h['average_coverage']],
        ['总施工液量(m³)',h['total_fluid_volume']],['初期增油(t/d)',e['initial_incremental_oil_t_day']],
        ['总投入(元)',e['investment_cny']],['税前净收益(元)',e['net_benefit_cny']],['税前净现值(元)',e['npv_cny']],
        ['未满足压力约束的段塞数',sum(not r['within_limits'] for r in response['construction_stage_results'])]]
    if format_money:
        for row in summary:
            if row[0].endswith('(元)'):
                row[1] = format(row[1], '.2f')
    segments=[[s['name'],s['penetration_depth'],s['productivity_ratio'],s['reaction']['porosity_after'],
        s['reaction']['permeability_after'],s['skin_after']] for s in response['segment_results']]
    stages=[[x['name'],x['segment'],x['acid_system'],x['volume'],x['rate'],x['within_limits']] for x in response['construction_stage_results']]
    return [('方案汇总',['指标','结果'],summary),
        ('分段评价',['井段','作用深度m','增产倍比','孔隙度','渗透率mD','表皮'],segments),
        ('施工段塞',['段塞','井段','配方','体积m³','排量m³/min','压力满足'],stages)]


def export_excel(path,response):
    # print("导出 Excel：", path)
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.chart import ScatterChart, Series, Reference
    except ImportError:
        raise CalculationError('Excel导出需要openpyxl，请安装requirements.txt；CSV和JSON不依赖此库')
    wb=Workbook(); wb.remove(wb.active)
    tables=report_tables(response)
    pressure=response['pressure_curve']
    pressure_keys=['time_min','stage','rate_m3_min','surface_pressure_mpa','bottom_pressure_mpa','surface_limit_mpa','bottom_limit_mpa']
    tables.append(('压力时序',['时间min','段塞','排量m³/min','井口MPa','井底MPa','井口限压MPa','井底限压MPa'],[[r[k] for k in pressure_keys] for r in pressure]))
    tables.append(('完整输入',['字段','值'],[[k,json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v] for k,v in response['input_snapshot']['parameters'].items()]))
    tables.append(('经济输入',['字段','值'],list(response['input_snapshot']['economics'].items())))
    tables.append(('酸液配方',['配方','字段','值'],[[name,k,v] for name,acid in response['input_snapshot']['acid_systems'].items() for k,v in acid.items()]))
    for title,headers,rows in tables:
        ws=wb.create_sheet(title); ws.append(headers)
        for values in rows:
            ws.append(values)
        ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]:
            cell.font=Font(name='Microsoft YaHei',bold=True,color='FFFFFF')
            cell.fill=PatternFill('solid',fgColor='176576')
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value,str):
                    cell.data_type='s'  # 输入的文本不能被 Excel 当公式执行
                cell.font=Font(name='Microsoft YaHei',size=10)
                cell.alignment=Alignment(vertical='center',wrap_text=True)
                if isinstance(cell.value,float):
                    cell.number_format='0.00####'
            ws.row_dimensions[row[0].row].height=32
        for col in ws.columns:
            letter=col[0].column_letter
            ws.column_dimensions[letter].width=min(48,max(18,max(len(str(c.value or '')) for c in col)+3))
        ws.sheet_view.showGridLines=False
    if pressure:
        ws=wb['压力时序']; chart=ScatterChart(); chart.title='施工压力预测（准稳态）'
        chart.x_axis.title='时间 min'; chart.y_axis.title='压力 MPa'; chart.width=25; chart.height=12
        x=Reference(ws,min_col=1,min_row=2,max_row=len(pressure)+1)
        for col in (4,5,6,7):
            y=Reference(ws,min_col=col,min_row=1,max_row=len(pressure)+1)
            series=Series(y,x,title_from_data=True); chart.series.append(series)
        ws.add_chart(chart,'I2')
    wb.save(str(path)); return Path(path)


def _format(v):
    if isinstance(v,bool): return '是' if v else '否'
    if isinstance(v,float): return '%.4g'%v
    return str(v)


def export_word(path,response,case_name='未命名方案'):
    """Small standards-based OOXML report, requiring neither Office nor python-docx."""
    def paragraph(text,style=None):
        prop='<w:pPr><w:pStyle w:val="%s"/></w:pPr>'%style if style else ''
        return '<w:p>%s<w:r><w:t xml:space="preserve">%s</w:t></w:r></w:p>'%(prop,escape(str(text)))
    def table(headers,rows):
        widths=([4100,4900] if len(headers)==2 else [1400,1100,2300,1400,1400,1400] if headers[0]=='段塞' else [1500]*len(headers))
        total=sum(widths)
        parts=['<w:tbl><w:tblPr><w:tblW w:w="%d" w:type="dxa"/><w:tblLayout w:type="fixed"/>'%total,
          '<w:tblBorders>'+''.join('<w:%s w:val="single" w:sz="4" w:color="D9D9D9"/>'%b for b in ('top','left','bottom','right','insideH','insideV'))+'</w:tblBorders>',
          '<w:tblCellMar><w:top w:w="80" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/><w:right w:w="100" w:type="dxa"/></w:tblCellMar></w:tblPr>',
          '<w:tblGrid>'+''.join('<w:gridCol w:w="%d"/>'%w for w in widths)+'</w:tblGrid>']
        for i,row in enumerate([headers]+rows):
            parts.append('<w:tr><w:trPr><w:cantSplit/>'+('<w:tblHeader/>' if i==0 else '')+'</w:trPr>')
            for width,value in zip(widths,row):
                parts.append('<w:tc><w:tcPr><w:tcW w:w="%d" w:type="dxa"/><w:vAlign w:val="center"/>%s</w:tcPr>'%(width,'<w:shd w:fill="E2EDF0"/>' if i==0 else ''))
                parts.append(paragraph(_format(value),'TableText')+'</w:tc>')
            parts.append('</w:tr>')
        return ''.join(parts)+'</w:tbl>'+paragraph('')
    body=[paragraph('砂岩酸化施工方案评价','Title'),paragraph(case_name),
        paragraph('本报告汇总当前输入方案的施工顺序、分段结果、压力约束和税前经济性。计算用于方案筛选，动力学与沉淀参数仍需目标储层实验标定。')]
    for title,headers,rows in report_tables(response, format_money=True):
        body.extend([paragraph(title,'Heading1'),table(headers,rows)])
    body.append(paragraph('模型边界与待验证事项','Heading1'))
    body.extend(paragraph(x) for x in response['horizontal_summary']['conclusions'])
    body.extend(paragraph(x) for x in response['water_analysis']['warnings'])
    for s in response['segment_results']:
        if s['warnings']:
            body.append(paragraph(s['name']+'：'+'；'.join(s['warnings'])))
    body.append('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>')
    document='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(body)+'</w:body></w:document>'
    styles='''<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei"/><w:sz w:val="22"/><w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="300" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="36"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:b/><w:sz w:val="28"/><w:color w:val="000000"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="40" w:line="260" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="19"/></w:rPr></w:style></w:styles>'''
    with zipfile.ZipFile(str(path),'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr('word/_rels/document.xml.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        z.writestr('word/document.xml',document); z.writestr('word/styles.xml',styles)
    return Path(path)


def export_html(path,response,case_name):
    parts=['<!doctype html><meta charset="utf-8"><title>酸化评价</title><style>body{font:16px Microsoft YaHei,sans-serif;max-width:1100px;margin:40px auto}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #ddd;padding:8px}th{background:#e2edf0}</style>', '<h1>砂岩酸化施工方案评价</h1><p>'+html.escape(case_name)+'</p>']
    for title,headers,rows in report_tables(response, format_money=True):
        parts+=['<h2>'+title+'</h2><table><tr>'+''.join('<th>'+h+'</th>' for h in headers)+'</tr>']
        parts+=['<tr>'+''.join('<td>'+html.escape(_format(v))+'</td>' for v in row)+'</tr>' for row in rows]
        parts+=['</table>']
    parts+=['<p>'+html.escape(x)+'</p>' for x in response['horizontal_summary']['conclusions']]
    Path(path).write_text(''.join(parts),encoding='utf-8'); return Path(path)


def radial_properties(response):
    """Near-well annular properties for downstream LGR/cell intersection mapping."""
    p=response['input_snapshot']['parameters']; records=[]
    for s in response['segment_results']:
        damage=p['rw']+s['damage_depth']; treated=s['predicted_radius']
        original=next((r for r in response['input_snapshot']['horizontal_segments'] if r['name']==s['name']),None)
        kd=original['damaged_permeability'] if original else p['kd']
        ko=original['permeability'] if original else p['ko']
        phi=original['porosity'] if original else p['o']
        boundaries=sorted(set([p['rw'],damage,treated,p['re']]))
        for a,b in zip(boundaries,boundaries[1:]):
            if b<=a: continue
            k=s['reaction']['permeability_after'] if b<=treated else kd if b<=damage else ko
            poro=s['reaction']['porosity_after'] if b<=treated else phi
            records.append({'segment':s['name'],'inner_radius_m':a,'outer_radius_m':b,
                'open_length_m':s['length'],'annulus_bulk_volume_m3':math.pi*(b*b-a*a)*s['length'],
                'permeability_md':k,'porosity':poro,'skin_before':s['skin_before'],
                'skin_after':s['skin_after'],'delta_skin':s['skin_after']-s['skin_before']})
    return records


MAPPING_FIELDS=['segment','well','i','j','k','base_skin','direction','diameter_m','kh_md_m','sat_table','state','d_factor','pressure_radius_m']


def export_mapping_template(path,response):
    rows=[[s['name'],'','','','','','','','','','OPEN','',''] for s in response['segment_results']]
    return _write_csv(path,MAPPING_FIELDS,rows)


def export_eclipse(path,response,mapping):
    # print("导出 Eclipse：", path)
    """One existing COMPDAT connection per interval, METRIC units only.

    Explicit connection transmissibilities are deliberately unsupported: they can
    override skin. Existing skin must include this model's baseline damage skin.
    """
    records={s['name']:s for s in response['segment_results']}
    if not mapping:
        raise CalculationError('必须填写真实井名、I/J/K和原始完井属性映射，不能自动猜测网格')
    lines=['-- METRIC units. Insert in SCHEDULE after original completions.',
           '-- Skin_new = supplied baseline skin + model skin_after - model skin_before.',
           '-- Recompute connection factor (item 8 default). Do not combine with PERM/WI modifications.',
           'COMPDAT']
    connections=set(); used=set()
    for r in mapping:
        if set(MAPPING_FIELDS)-set(r):
            raise CalculationError('映射缺少字段：'+','.join(sorted(set(MAPPING_FIELDS)-set(r))))
        if r['segment'] not in records:
            raise CalculationError('映射井段不存在：'+str(r['segment']))
        if r['segment'] in used:
            raise CalculationError('当前接口每个井段限一条完井映射；多网格井段请先拆段')
        used.add(r['segment'])
        well=str(r['well'])
        if not re.fullmatch(r'[A-Za-z0-9_\-]{1,8}',well):
            raise CalculationError('Eclipse井名须为1–8位ASCII字母、数字、下划线或连字符')
        integers=[]
        for key in ('i','j','k','sat_table'):
            try:
                value=float(r[key]); n=int(value)
            except (ValueError,TypeError,OverflowError):
                raise CalculationError('映射 '+key+' 必须为整数')
            if n!=value or n<(0 if key=='sat_table' else 1):
                raise CalculationError('映射 '+key+' 超出合法整数范围')
            integers.append(n)
        i,j,k,sat=integers
        if (well,i,j,k) in connections:
            raise CalculationError('重复完井连接；请先在目标网格中合并/细分，不能重复叠加表皮')
        connections.add((well,i,j,k))
        numeric={}
        for key in ('base_skin','diameter_m','kh_md_m','d_factor','pressure_radius_m'):
            try: value=float(r[key])
            except (ValueError,TypeError): raise CalculationError('映射 '+key+' 必须填真实数值')
            if not math.isfinite(value) or (key!='base_skin' and value<0):
                raise CalculationError('映射 '+key+' 无效')
            numeric[key]=value
        if numeric['diameter_m']<=0 or numeric['kh_md_m']<=0:
            raise CalculationError('完井直径和Kh必须大于0')
        if r['direction'] not in ('X','Y','Z') or r['state'] not in ('OPEN','SHUT','AUTO'):
            raise CalculationError('完井方向或状态无效')
        s=records[r['segment']]
        skin=numeric['base_skin']+s['skin_after']-s['skin_before']
        lines.append("'%s' %d %d %d %d %s %d 1* %.12g %.12g %.12g %.12g %s %.12g /"%
            (well,i,j,k,k,r['state'],sat,numeric['diameter_m'],numeric['kh_md_m'],skin,
             numeric['d_factor'],r['direction'],numeric['pressure_radius_m']))
    if used!=set(records):
        raise CalculationError('需覆盖所有活动井段；遗漏：'+'、'.join(sorted(set(records)-used)))
    lines.append('/')
    Path(path).write_text('\n'.join(lines)+'\n',encoding='ascii'); return Path(path)


def export_bundle(response,case_name):
    folder=_folder('方案交付')
    (folder/'完整结果.json').write_text(json.dumps(response,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (folder/'完整输入.json').write_text(json.dumps(response['input_snapshot'],ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    _records_csv(folder/'施工段塞.csv',response['construction_stage_results'])
    _records_csv(folder/'压力时序.csv',response['pressure_curve'])
    _records_csv(folder/'近井径向属性.csv',radial_properties(response))
    _write_csv(folder/'经济评价.csv',['指标','结果'],response['economics'].items())
    _records_csv(folder/'分段评价.csv',({**{k:v for k,v in s.items() if k not in ('reaction','temperature_profile')},
        **{'reaction_'+k:v for k,v in s['reaction'].items()}} for s in response['segment_results']))
    export_mapping_template(folder/'Eclipse映射待填写.csv',response)
    export_word(folder/'施工评价报告.docx',response,case_name)
    export_html(folder/'施工评价报告.html',response,case_name)
    try:
        export_excel(folder/'施工评价.xlsx',response)
    except CalculationError as exc:
        (folder/'Excel导出说明.txt').write_text(str(exc),encoding='utf-8')
    (folder/'数模导入说明.txt').write_text(
        '近井径向属性.csv供局部网格映射，不是可直接导入的完整GRDECL或Petrel项目。\n'
        'Eclipse映射待填写.csv需要填写目标模型真实井名、I/J/K、原始表皮、方向、直径、Kh、饱和度表、状态、D因子和压力等效半径。\n'
        '在软件的导出与数模接口页读取映射，生成COMPDAT include。仅支持METRIC，每段一条既有连接。\n'
        '原始表皮必须已经包含处理前伤害；新表皮=原始表皮+(处理后表皮-处理前表皮)。\n'
        '连接传导系数采用默认重算；不支持保留显式CF的模型。不与孔渗或WI重复修正叠加。\n'
        '没有目标网格和Eclipse/Petrel安装环境，本次未完成目标模拟器端到端导入验证。\n',encoding='utf-8')
    return folder
