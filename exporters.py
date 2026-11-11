"""Shared CSV/JSON export helpers and engineering input export."""
from __future__ import annotations
import csv
import json
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "acidizing_outputs"


def _cell(value):
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    # 名称、配方这些文本写进表格时，不能变成公式
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _write_csv(path, headers, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.writer(fp)
        writer.writerow([_cell(x) for x in headers])
        writer.writerows([_cell(x) for x in row] for row in rows)
    return path


def _records_csv(path, records):
    records = list(records)
    keys = list(records[0]) if records else []
    return _write_csv(path, keys, ([r.get(k, "") for k in keys] for r in records))


def _folder(prefix):
    folder = OUTPUT_DIR / (prefix + "_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def export_inputs(params, stage_rows, segments=None, payload=None):
    # print("导出输入，施工段数：", len(stage_rows))
    folder = _folder("输入")
    _write_csv(folder / "工程参数.csv", ["参数", "数值"], asdict(params).items())
    _records_csv(folder / "直井参考阶段.csv", stage_rows)
    _records_csv(folder / "水平段输入.csv", (asdict(s) for s in (segments or [])))
    if payload:
        from .model_api import save_request
        save_request(str(folder / "完整方案含酸液库.json"), payload)
    return "已导出输入文件：%s" % folder
