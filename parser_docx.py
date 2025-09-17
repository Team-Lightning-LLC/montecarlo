# backend/parser_docx.py
import re
from typing import Dict, List, Tuple
from docx import Document

MONEY = r"[-+]?\$?\s?[\d,]+(?:\.\d{1,2})?"
PCT   = r"[-+]?\d{1,3}(?:\.\d+)?\s?%"

def _to_float_money(s: str) -> float:
    s = s.replace(',', '').replace('$','').strip()
    try: return float(s)
    except: return 0.0

def _to_float_pct(s: str) -> float:
    s = s.replace('%','').strip()
    try: return float(s)/100.0
    except: return 0.0

def parse_portfolio_overview_docx(path: str) -> Dict:
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs)

    # Client name (optional)
    m_client = re.search(r"Client\s*:\s*([A-Za-z ,.'-]+)", text, re.IGNORECASE)
    name = m_client.group(1).strip() if m_client else "Client"

    # Time horizon (years)
    m_horizon = re.search(r"(Time\s*Horizon|Horizon)\D+(\d{1,2})\s*(?:years|yrs)?", text, re.IGNORECASE)
    horizon_years = int(m_horizon.group(2)) if m_horizon else 20

    # Goal (retirement target)
    m_goal = re.search(r"(Goal|Retirement)\D+(" + MONEY + ")", text, re.IGNORECASE)
    goal_target = _to_float_money(m_goal.group(2)) if m_goal else 2500000.0

    # Recurring savings (monthly taxable)
    m_sav_m = re.search(r"(Monthly\s+Savings|Savings\s+Monthly)\D+(" + MONEY + ")", text, re.IGNORECASE)
    monthly_taxable = _to_float_money(m_sav_m.group(2)) if m_sav_m else 0.0

    # Annual 401k / tax-advantaged
    m_sav_a = re.search(r"(401k|Tax-advantaged|Retirement\s+Plan)\D+(" + MONEY + ")", text, re.IGNORECASE)
    annual_taxadv = _to_float_money(m_sav_a.group(2)) if m_sav_a else 0.0

    # Liquidity floor
    m_liq = re.search(r"(Liquidity\s*(?:Need|Floor|Requirement))\D+(" + PCT + ")", text, re.IGNORECASE)
    liq_floor = _to_float_pct(m_liq.group(2)) if m_liq else 0.0

    # Account balances (coarse patterns)
    accounts: List[Tuple[str,str,float]] = []
    for line in text.splitlines():
        # Examples: "Fidelity Brokerage ... $578,325", "401(k) ... $571,366", "Money Market ... $150,000"
        m = re.search(r"([A-Za-z0-9 ()./-]{3,60})\s+(?:balance|value|total)?\s*(" + MONEY + r")", line, re.IGNORECASE)
        if m:
            name_line = m.group(1).strip()
            amt = _to_float_money(m.group(2))
            if amt <= 0: continue
            lower = name_line.lower()
            if "401" in lower or "ira" in lower: acc_type = "tax-advantaged"
            elif "money market" in lower or "cash" in lower: acc_type = "cash_like"
            else: acc_type = "taxable"
            accounts.append((name_line, acc_type, amt))

    # Asset allocation section
    # Lines like: "Equity ... 70%", "Fixed Income ... 25%", "Cash ... 15%" or more granular sleeves
    sleeves = []
    for line in text.splitlines():
        m = re.search(r"([A-Za-z_ /&()-]{3,40})\s+(" + PCT + ")", line)
        if m:
            lbl = m.group(1).strip().replace(' ','_').replace('/','_')
            pct = _to_float_pct(m.group(2))
            # Basic normalization of labels to our taxonomy
            norm = (
                "Equity_US" if "us" in lbl.lower() and "equity" in lbl.lower()
                else "Equity_Intl_Dev" if "intl" in lbl.lower() or "international" in lbl.lower()
                else "Fixed_Income_IG" if "fixed" in lbl.lower() or "bond" in lbl.lower()
                else "Alternatives_Other" if "altern" in lbl.lower() or "reit" in lbl.lower()
                else "Cash" if "cash" in lbl.lower() or "money" in lbl.lower()
                else None
            )
            if norm:
                sleeves.append((norm, pct))
    # If nothing parsed, default to simple 70/25/5
    if not sleeves:
        sleeves = [("Equity_US", 0.70), ("Fixed_Income_IG", 0.25), ("Alternatives_Other", 0.05)]

    # Normalize weights
    wsum = sum(p for _,p in sleeves)
    if wsum > 0: sleeves = [(c, p/wsum) for c,p in sleeves]

    # Fallback accounts if none found
    if not accounts:
        accounts = [("Taxable Account", "taxable", 500000.0)]

    portfolio_dict = {
        "client": {"name": name, "time_horizon_years": horizon_years},
        "accounts": [{"name": n, "type": t, "balance": v} for (n,t,v) in accounts],
        "asset_breakdown": [{"class": c, "weight": p} for (c,p) in sleeves],
        "target_allocation": [{"class": c, "weight": p} for (c,p) in sleeves],  # target= current by default
        "cash_flows": {
            "recurring": [
                {"account_type":"taxable", "amount_monthly": monthly_taxable},
                {"account_type":"tax-advantaged", "amount_annual": annual_taxadv}
            ],
            "scheduled": []
        },
        "constraints": {"liquidity_floor_pct": liq_floor, "rebalance_frequency":"monthly"},
        "goals": [{"year": horizon_years, "target": goal_target, "label": "Retirement"}]
    }
    return portfolio_dict

