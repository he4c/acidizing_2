from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional

from .calculations import (
    MODEL_VERSION,
    AcidizingParameters,
    HorizontalEvaluation,
    HorizontalSegment,
    SimulationResult,
)


class DatabaseUnavailable(RuntimeError):
    """Raised when the MySQL driver or server configuration is unavailable."""


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "acidizing_app"
    password: str = ""
    database: str = "acidizing_design"

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        return cls(
            host=os.getenv("ACIDIZING_DB_HOST", cls.host),
            port=int(os.getenv("ACIDIZING_DB_PORT", str(cls.port))),
            user=os.getenv("ACIDIZING_DB_USER", cls.user),
            password=os.getenv("ACIDIZING_DB_PASSWORD", cls.password),
            database=os.getenv("ACIDIZING_DB_NAME", cls.database),
        )


def format_config_help() -> str:
    return (
        "数据库位置：新增的 MySQL 数据库代码在 acidizing/database.py。\n"
        "默认连接：%s:%s，用户 %s，数据库 %s。\n"
        % (DatabaseConfig.host, DatabaseConfig.port, DatabaseConfig.user, DatabaseConfig.database) +
        "可在 Windows 环境变量中设置：\n"
        "ACIDIZING_DB_HOST、ACIDIZING_DB_PORT、ACIDIZING_DB_USER、"
        "ACIDIZING_DB_PASSWORD、ACIDIZING_DB_NAME。\n"
        "还需要在当前 Python 环境安装 mysql-connector-python。"
    )


def _load_connector():
    try:
        import mysql.connector
    except ImportError as exc:
        raise DatabaseUnavailable("未安装 MySQL 驱动 mysql-connector-python。") from exc
    return mysql.connector


def _quote_identifier(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", identifier):
        raise DatabaseUnavailable("数据库名只能包含字母、数字和下划线。")
    return "`%s`" % identifier


def _connect(config: Optional[DatabaseConfig] = None, with_database: bool = True):
    connector = _load_connector()
    cfg = config or DatabaseConfig.from_env()
    kwargs = {
        "host": cfg.host,
        "port": cfg.port,
        "user": cfg.user,
        "password": cfg.password,
        "charset": "utf8mb4",
        "use_unicode": True,
        "connection_timeout": 5,
    }
    if with_database:
        kwargs["database"] = cfg.database
    try:
        return connector.connect(**kwargs)
    except Exception as exc:
        raise DatabaseUnavailable("无法连接 MySQL：%s" % exc) from exc


def ensure_schema(config: Optional[DatabaseConfig] = None) -> None:
    cfg = config or DatabaseConfig.from_env()
    database_name = _quote_identifier(cfg.database)

    server_conn = _connect(cfg, with_database=False)
    try:
        cursor = server_conn.cursor()
        cursor.execute(
            "CREATE DATABASE IF NOT EXISTS %s CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci" % database_name
        )
        server_conn.commit()
    finally:
        server_conn.close()

    conn = _connect(cfg, with_database=True)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS acidizing_cases (
                id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                case_name VARCHAR(160) NOT NULL,
                parameters_json LONGTEXT NOT NULL,
                stages_json LONGTEXT NOT NULL,
                result_summary_json LONGTEXT NOT NULL,
                profile_rows_json LONGTEXT NOT NULL,
                productivity_rows_json LONGTEXT NOT NULL,
                optimization_rows_json LONGTEXT NOT NULL,
                horizontal_segments_json LONGTEXT NULL,
                horizontal_result_json LONGTEXT NULL,
                model_version VARCHAR(80) NULL,
                design_payload_json LONGTEXT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_created_at (created_at),
                INDEX idx_case_name (case_name)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        _ensure_column(cursor, cfg.database, "horizontal_segments_json", "LONGTEXT NULL")
        _ensure_column(cursor, cfg.database, "horizontal_result_json", "LONGTEXT NULL")
        _ensure_column(cursor, cfg.database, "model_version", "VARCHAR(80) NULL")
        _ensure_column(cursor, cfg.database, "design_payload_json", "LONGTEXT NULL")
        conn.commit()
    finally:
        conn.close()


def test_connection() -> str:
    cfg = DatabaseConfig.from_env()
    ensure_schema(cfg)
    return "已连接 MySQL：%s:%s/%s，数据表 acidizing_cases 可用。" % (cfg.host, cfg.port, cfg.database)


def save_case(
    case_name: str,
    parameters: AcidizingParameters,
    stage_rows: List[Dict[str, Any]],
    result: SimulationResult,
    horizontal_segments: Optional[Iterable[HorizontalSegment]] = None,
    horizontal_result: Optional[HorizontalEvaluation] = None,
    design_payload: Optional[Dict[str, Any]] = None,
    economics_result: Optional[Dict[str, Any]] = None,
) -> int:
    # print("保存方案：", case_name, "段数：", len(stage_rows))
    if design_payload is not None:
        from .model_api import parse_request
        parse_request(design_payload)
    ensure_schema()
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO acidizing_cases (
                case_name,
                parameters_json,
                stages_json,
                result_summary_json,
                profile_rows_json,
                productivity_rows_json,
                optimization_rows_json,
                horizontal_segments_json,
                horizontal_result_json,
                model_version,
                design_payload_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                case_name or "未命名方案",
                _dumps(asdict(parameters)),
                _dumps(stage_rows),
                _dumps(_result_summary(result, horizontal_result, economics_result)),
                _dumps(result.profile_rows),
                _dumps(result.productivity_rows),
                _dumps([]),  # 旧数据库里有这一列，先保留
                _dumps([asdict(row) for row in (horizontal_segments or [])]),
                _dumps(asdict(horizontal_result)) if horizontal_result else "",
                MODEL_VERSION,
                _dumps(design_payload) if design_payload is not None else None,
            ),
        )
        conn.commit()
        return int(cursor.lastrowid)
    finally:
        conn.close()


def list_cases(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_schema()
    conn = _connect()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id, case_name, created_at, result_summary_json, optimization_rows_json
            FROM acidizing_cases
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        records = []
        for row in cursor.fetchall():
            summary = _loads(row.pop("result_summary_json"), {})
            optimization_rows = _loads(row.pop("optimization_rows_json"), [])
            last_optimization = max(optimization_rows, key=lambda item: item.get("net_benefit", float("-inf"))) if optimization_rows else {}
            records.append(
                {
                    **row,
                    "created_at": str(row["created_at"]),
                    "effective_radius": summary.get("effective_radius"),
                    "total_acid_volume": summary.get("total_acid_volume"),
                    "net_benefit": summary.get("net_benefit_cny", last_optimization.get("net_benefit")),
                }
            )
        return records
    finally:
        conn.close()


def load_case(case_id: int) -> Dict[str, Any]:
    # print("读取方案编号：", case_id)
    ensure_schema()
    conn = _connect()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT *
            FROM acidizing_cases
            WHERE id = %s
            """,
            (int(case_id),),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError("未找到编号为 %s 的数据库记录。" % case_id)
        return {
            "id": row["id"],
            "case_name": row["case_name"],
            "created_at": str(row["created_at"]),
            "parameters": _loads(row["parameters_json"], {}),
            "stages": _loads(row["stages_json"], []),
            "result_summary": _loads(row["result_summary_json"], {}),
            "profile_rows": _loads(row["profile_rows_json"], []),
            "productivity_rows": _loads(row["productivity_rows_json"], []),
            "optimization_rows": _loads(row["optimization_rows_json"], []),
            "horizontal_segments": _loads(row.get("horizontal_segments_json"), []),
            "horizontal_result": _loads(row.get("horizontal_result_json"), {}),
            "model_version": row.get("model_version") or "legacy",
            "design_payload": _loads(row.get("design_payload_json"), None),
        }
    finally:
        conn.close()


def delete_case(case_id: int) -> None:
    ensure_schema()
    conn = _connect()
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM acidizing_cases WHERE id = %s", (int(case_id),))
        conn.commit()
    finally:
        conn.close()


def _result_summary(
    result: SimulationResult,
    horizontal: Optional[HorizontalEvaluation] = None,
    economics_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    summary = {
        "skin_factor": result.basic.skin_factor,
        "fracture_pressure": result.basic.fracture_pressure,
        "max_rate": result.basic.max_rate,
        "construction_rate": result.basic.construction_rate,
        "preflush_volume": result.basic.preflush_volume,
        "treatment_volume": result.basic.treatment_volume,
        "postflush_volume": result.basic.postflush_volume,
        "displacement_volume": result.basic.displacement_volume,
        "total_acid_volume": result.basic.total_acid_volume,
        "effective_radius": result.effective_radius,
        "warnings": result.warnings,
    }
    if horizontal:
        summary.update(
            {
                "horizontal_mode": horizontal.mode,
                "heterogeneity_cv": horizontal.heterogeneity_cv,
                "average_coverage": horizontal.average_coverage,
                "expected_productivity_ratio": horizontal.expected_productivity_ratio,
                "risk_segment_count": horizontal.risk_segment_count,
                "total_acid_volume": horizontal.total_fluid_volume,
                "total_treatment_volume": horizontal.total_treatment_volume,
            }
        )
    if economics_result is not None:
        summary["economics"] = dict(economics_result)
        summary["net_benefit_cny"] = economics_result["net_benefit_cny"]
    return summary


def _ensure_column(cursor, database: str, column: str, definition: str) -> None:
    allowed = {
        "horizontal_segments_json": "LONGTEXT NULL",
        "horizontal_result_json": "LONGTEXT NULL",
        "model_version": "VARCHAR(80) NULL",
        "design_payload_json": "LONGTEXT NULL",
    }
    if column not in allowed or definition != allowed[column]:
        raise DatabaseUnavailable("数据库字段定义不受支持。")
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'acidizing_cases' AND COLUMN_NAME = %s
        """,
        (database, column),
    )
    if not cursor.fetchone()[0]:
        cursor.execute("ALTER TABLE acidizing_cases ADD COLUMN `%s` %s" % (column, definition))


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _loads(value: str, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
