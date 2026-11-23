"""Fundamental quality scoring using Upstox Company Fundamentals APIs."""
from __future__ import annotations

import logging
import threading
import time
from urllib.parse import quote

import requests

log = logging.getLogger("daily_nse_scanner.fundamentals")
_lock = threading.Lock()
_last = 0.0
_GAP = 0.15
_BASE = "https://api.upstox.com/v2/fundamentals"


def _get(url: str, headers: dict, params: dict | None = None) -> dict:
    global _last
    with _lock:
        wait = _GAP - (time.monotonic() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.monotonic()
    response = requests.get(url, headers=headers, params=params, timeout=25)
    if response.status_code == 429:
        raise RuntimeError("Upstox fundamentals rate limit (429)")
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") != "success":
        raise RuntimeError(f"Upstox fundamentals returned non-success: {payload}")
    return payload.get("data") or {}


def _num(value):
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _ratio(data, name):
    for item in data if isinstance(data, list) else []:
        if str(item.get("name", "")).strip().upper() == name.upper():
            return _num(item.get("company_value")), _num(item.get("sector_value"))
    return None, None


def _category_history(data, field, category):
    for item in data.get(field, []) if isinstance(data, dict) else []:
        if str(item.get("category", "")).lower() == category.lower():
            values = []
            for row in item.get("history", []):
                val = _num(row.get("value"))
                if val is not None:
                    values.append(val)
            return values
    return []


def _growth(history):
    # API history is newest-first. Compare latest with 3-years-back where available.
    vals = [x for x in history if x is not None]
    if len(vals) >= 4 and vals[0] > 0 and vals[3] > 0:
        return ((vals[0] / vals[3]) ** (1 / 3) - 1) * 100
    if len(vals) >= 2 and vals[0] > 0 and vals[-1] > 0:
        years = len(vals) - 1
        return ((vals[0] / vals[-1]) ** (1 / years) - 1) * 100
    return None


def _balance_ratio(data):
    history = data.get("history", []) if isinstance(data, dict) else []
    if not history:
        return None
    latest = history[0]
    assets = _num(latest.get("total_asset"))
    liabilities = _num(latest.get("total_liability"))
    if assets is None or assets <= 0 or liabilities is None:
        return None
    return liabilities / assets


def _positive_cashflow_ratio(data):
    history = _category_history(data, "cash_flow", "operating")
    if not history:
        return None
    return sum(1 for v in history[:5] if v > 0) / min(len(history[:5]), 5)


def score_fundamentals(isin: str, headers: dict) -> dict | None:
    """Return scored fundamentals, or None when data is incomplete/unhealthy."""
    if not isin:
        return None
    encoded = quote(isin, safe="")
    ratios = _get(f"{_BASE}/{encoded}/key-ratios", headers)
    income = _get(f"{_BASE}/{encoded}/income-statement", headers,
                   {"type": "consolidated", "time_period": "yearly"})
    cash = _get(f"{_BASE}/{encoded}/cash-flow", headers, {"type": "consolidated"})
    balance = _get(f"{_BASE}/{encoded}/balance-sheet", headers, {"type": "consolidated"})

    roce, sector_roce = _ratio(ratios, "ROCE")
    roe, sector_roe = _ratio(ratios, "ROE")
    pe, sector_pe = _ratio(ratios, "P/E")
    ev, sector_ev = _ratio(ratios, "EV/EBITDA")
    revenue_growth = _growth(_category_history(income, "income_statement", "revenue"))
    profit_growth = _growth(_category_history(income, "income_statement", "net_profit"))
    cash_consistency = _positive_cashflow_ratio(cash)
    liabilities_assets = _balance_ratio(balance)

    # Require a meaningful set of independent metrics. Missing data is not treated as good.
    available = [x for x in (roce, roe, revenue_growth, profit_growth, pe, ev,
                               cash_consistency, liabilities_assets) if x is not None]
    if len(available) < 5:
        log.info("Fundamental data coverage too low for %s (%d/8 metrics)", isin, len(available))
        return None

    score = 0
    reasons = []
    if roce is not None:
        pts = 20 if roce >= 18 else 15 if roce >= 14 else 10 if roce >= 9 else 4 if roce > 0 else 0
        score += pts
        if pts >= 10: reasons.append(f"ROCE {roce:.1f}%")
    if roe is not None:
        pts = 15 if roe >= 18 else 11 if roe >= 13 else 7 if roe >= 8 else 2 if roe > 0 else 0
        score += pts
        if pts >= 7: reasons.append(f"ROE {roe:.1f}%")
    if revenue_growth is not None:
        pts = 15 if revenue_growth >= 15 else 11 if revenue_growth >= 8 else 6 if revenue_growth > 0 else 0
        score += pts
        if pts >= 6: reasons.append(f"revenue growth {revenue_growth:.1f}%")
    if profit_growth is not None:
        pts = 15 if profit_growth >= 15 else 10 if profit_growth >= 7 else 4 if profit_growth > 0 else 0
        score += pts
        if pts >= 4: reasons.append(f"profit growth {profit_growth:.1f}%")
    if pe is not None and sector_pe is not None and sector_pe > 0:
        rel = pe / sector_pe
        score += 10 if rel <= 0.85 else 7 if rel <= 1.1 else 4 if rel <= 1.35 else 0
        if rel <= 1.1: reasons.append("P/E at/below sector")
    if ev is not None and sector_ev is not None and sector_ev > 0:
        rel = ev / sector_ev
        score += 8 if rel <= 0.85 else 6 if rel <= 1.1 else 3 if rel <= 1.35 else 0
        if rel <= 1.1: reasons.append("EV/EBITDA at/below sector")
    if cash_consistency is not None:
        score += 10 if cash_consistency >= 0.8 else 6 if cash_consistency >= 0.6 else 0
        if cash_consistency >= 0.6: reasons.append("positive operating cash flow")
    if liabilities_assets is not None:
        score += 7 if liabilities_assets <= 0.45 else 4 if liabilities_assets <= 0.65 else 0
        if liabilities_assets <= 0.65: reasons.append("moderate liabilities/assets")

    return {
        "fundamental_score": min(score, 100),
        "fundamental_reasons": reasons,
        "fundamental_metrics": {
            "ROCE": roce, "ROE": roe, "revenue_growth": revenue_growth,
            "profit_growth": profit_growth, "PE": pe, "sector_PE": sector_pe,
            "EV_EBITDA": ev, "sector_EV_EBITDA": sector_ev,
            "positive_OCF_ratio": cash_consistency, "liabilities_assets": liabilities_assets,
        },
    }
