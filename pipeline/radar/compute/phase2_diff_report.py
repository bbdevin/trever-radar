"""Phase 2 tech/final score diff report.

Compare current decoupled scores against a legacy baseline where S1-S10
strategy points were still added into tech_score.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .. import config
from .scores import combine
from .read_only_sqlite import get_read_only_sqlite_engine, safe_report_output_path

_S_CODE_RE = re.compile(r"^S([1-9]|10)_")


def _legacy_bonus(reasons_json: str | None) -> int:
    if not reasons_json:
        return 0
    try:
        reasons = json.loads(reasons_json)
    except json.JSONDecodeError:
        return 0
    bonus = 0
    for r in reasons:
        code = (r or {}).get("code", "")
        if isinstance(code, str) and _S_CODE_RE.match(code):
            bonus += int((r or {}).get("points") or 0)
    return bonus


def _clamp_score(v: int) -> int:
    return max(0, min(100, v))


def _fmt_pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def build_phase2_diff_report(date: str | None = None, out: str | None = None) -> dict:
    # Reject a dangerous explicit output path before even reading report data.
    if out is not None:
        safe_report_output_path(out, report_name="phase2 diff report")
    engine = get_read_only_sqlite_engine(
        report_name="phase2 diff report",
        required_tables=("daily_scores", "indicators_daily", "stocks"),
    )
    try:
        with engine.connect() as conn:
            latest = conn.execute(text("SELECT MAX(date) FROM daily_scores")).scalar()
            if not latest:
                raise RuntimeError("daily_scores is empty; run compute-scores first")
            if date:
                target_date = f"{date[:4]}-{date[4:6]}-{date[6:8]}"
            else:
                # Prefer a date that actually contains S-strategy reasons, so the
                # diff report is decision-useful by default.
                target_date = conn.execute(
                    text(
                        """
                        SELECT MAX(ds.date)
                        FROM daily_scores ds
                        JOIN indicators_daily id
                          ON id.stock_id = ds.stock_id AND id.date = ds.date
                        WHERE id.reasons LIKE '%"code": "S%'
                        """
                    )
                ).scalar() or latest

            rows = conn.execute(
                text(
                    """
                    SELECT
                      ds.stock_id,
                      s.name,
                      ds.branch_score,
                      ds.warrant_score,
                      ds.tech_score,
                      ds.inst_score,
                      ds.theme_score,
                      ds.risk_penalty,
                      ds.final,
                      id.reasons
                    FROM daily_scores ds
                    JOIN stocks s ON s.id = ds.stock_id
                    LEFT JOIN indicators_daily id
                      ON id.stock_id = ds.stock_id AND id.date = ds.date
                    WHERE ds.date = :d
                    ORDER BY ds.stock_id
                    """
                ),
                {"d": target_date},
            ).fetchall()
    finally:
        engine.dispose()

    if not rows:
        raise RuntimeError(f"no daily_scores rows on {target_date}")

    detail = []
    tech_diffs: list[int] = []
    final_diffs: list[int] = []
    crossed_watch = 0
    for r in rows:
        tech_new = r.tech_score
        if tech_new is None:
            continue
        bonus = _legacy_bonus(r.reasons)
        tech_old = _clamp_score(int(tech_new) + bonus)
        tech_diff = tech_old - int(tech_new)
        base_old = combine(r.branch_score, r.warrant_score, tech_old, r.inst_score, r.theme_score)
        if base_old is None:
            continue
        final_old = _clamp_score(base_old + int(r.risk_penalty or 0))
        final_new = int(r.final)
        final_diff = final_old - final_new
        if final_new < 65 <= final_old:
            crossed_watch += 1
        tech_diffs.append(tech_diff)
        final_diffs.append(final_diff)
        detail.append(
            {
                "stock_id": r.stock_id,
                "name": r.name,
                "tech_new": int(tech_new),
                "tech_old": tech_old,
                "tech_diff": tech_diff,
                "final_new": final_new,
                "final_old": final_old,
                "final_diff": final_diff,
                "legacy_bonus": bonus,
            }
        )

    if not detail:
        raise RuntimeError("no comparable rows with tech_score found")

    detail_sorted = sorted(detail, key=lambda x: (x["final_diff"], x["tech_diff"]), reverse=True)
    tech_up_rows = sum(1 for x in detail if x["tech_diff"] > 0)
    final_up_rows = sum(1 for x in detail if x["final_diff"] > 0)

    p95_idx = max(0, min(len(tech_diffs) - 1, round(len(tech_diffs) * 0.95) - 1))
    tech_sorted = sorted(tech_diffs)
    final_sorted = sorted(final_diffs)

    lines: list[str] = []
    lines.append("# Phase 2 舊/新分數差異報告")
    lines.append("")
    lines.append(f"- 產生時間: {datetime.now(ZoneInfo(config.TZ)).isoformat(timespec='seconds')}")
    lines.append(f"- 資料日: `{target_date}`")
    lines.append("- 比較定義:")
    lines.append("  - **新制**: 目前上線邏輯（S1-S13 只產生 reason，不加分）")
    lines.append("  - **舊制模擬**: 將 indicators reasons 中 `S1~S10` points 回加到 `tech_score`（再 `clamp 0~100`）")
    lines.append("")
    lines.append("## 摘要")
    lines.append("")
    lines.append(f"- 比較樣本數: **{len(detail)}** 檔")
    lines.append(f"- `tech_score` 受影響檔數: **{tech_up_rows}** / {len(detail)} ({_fmt_pct(tech_up_rows / len(detail))})")
    lines.append(f"- `final` 受影響檔數: **{final_up_rows}** / {len(detail)} ({_fmt_pct(final_up_rows / len(detail))})")
    lines.append(f"- `final` 由 `<65` 變 `>=65`（舊制會多進觀察池）: **{crossed_watch}** 檔")
    lines.append(f"- `tech_diff` 平均/中位/P95: **{mean(tech_diffs):.2f} / {median(tech_diffs):.2f} / {tech_sorted[p95_idx]:.0f}**")
    lines.append(f"- `final_diff` 平均/中位/P95: **{mean(final_diffs):.2f} / {median(final_diffs):.2f} / {final_sorted[p95_idx]:.0f}**")
    lines.append("")
    lines.append("## 影響最大 Top 20（依 final_diff）")
    lines.append("")
    lines.append("| stock_id | name | tech_new | tech_old | tech_diff | final_new | final_old | final_diff |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for x in detail_sorted[:20]:
        lines.append(
            f"| {x['stock_id']} | {x['name']} | {x['tech_new']} | {x['tech_old']} | +{x['tech_diff']} | "
            f"{x['final_new']} | {x['final_old']} | +{x['final_diff']} |"
        )
    lines.append("")
    lines.append("> 注意: 此報告僅為 Phase 2 決策用途，不會回寫資料庫，也不會改正式榜單。")
    lines.append("")

    out_path = Path(out) if out else (config.ROOT / "docs" / "reports" / f"phase2_score_diff_{target_date}.md")
    out_path = safe_report_output_path(out_path, report_name="phase2 diff report")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "date": target_date,
        "rows": len(detail),
        "tech_affected": tech_up_rows,
        "final_affected": final_up_rows,
        "crossed_watch": crossed_watch,
        "out": str(out_path),
    }
