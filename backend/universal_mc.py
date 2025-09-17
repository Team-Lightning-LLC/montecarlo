# backend/universal_mc.py
from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# ---------------------------
# Data structures
# ---------------------------

@dataclass
class Account:
    name: str
    type: str                 # "taxable" | "tax-advantaged" | "cash_like"
    balance: float

@dataclass
class AssetWeight:
    cls: str
    weight: float

@dataclass
class RecurringFlow:
    account_type: str
    amount_monthly: float = 0.0
    amount_annual: float = 0.0

@dataclass
class ScheduledFlow:
    year: int
    amount: float
    label: str = ""
    repeat_months: Optional[int] = None

@dataclass
class Constraints:
    liquidity_floor_pct: float = 0.0
    rebalance_frequency: str = "monthly"

@dataclass
class Goal:
    year: int
    target: float
    label: str = "Goal"

@dataclass
class ClientPortfolio:
    client: Dict
    accounts: List[Account]
    asset_breakdown: List[AssetWeight]
    target_allocation: List[AssetWeight]
    cash_flows: Dict[str, List]
    constraints: Constraints
    goals: List[Goal]
    horizon_years: int
    steps_per_year: int = 12

# ---------------------------
# Capital Market Assumptions
# ---------------------------

@dataclass
class CMA:
    mu_ann: Dict[str, float]               # expected return (annual)
    vol_ann: Dict[str, float]              # volatility (annual)
    corr: Dict[Tuple[str,str], float]      # pairwise correlations

def example_cma() -> CMA:
    mu_ann = {
        "Equity_US": 0.07, "Equity_US_SmallMid": 0.08,
        "Equity_Intl_Dev": 0.065, "Equity_Intl_EM": 0.085,
        "Fixed_Income_IG": 0.035, "Fixed_Income_Muni": 0.03,
        "Fixed_Income_Intl": 0.03,
        "Alternatives_REIT": 0.055, "Alternatives_Other": 0.05,
        "Cash": 0.02
    }
    vol_ann = {
        "Equity_US": 0.16, "Equity_US_SmallMid": 0.20,
        "Equity_Intl_Dev": 0.17, "Equity_Intl_EM": 0.23,
        "Fixed_Income_IG": 0.07, "Fixed_Income_Muni": 0.06,
        "Fixed_Income_Intl": 0.08,
        "Alternatives_REIT": 0.18, "Alternatives_Other": 0.12,
        "Cash": 0.01
    }
    base = list(mu_ann.keys())
    corr = {}
    for a in base:
        for b in base:
            if a == b: corr[(a,b)] = 1.0
            else:
                if "Equity" in a and "Equity" in b: corr[(a,b)] = 0.75
                elif ("Equity" in a and "REIT" in b) or ("REIT" in a and "Equity" in b): corr[(a,b)] = 0.65
                elif ("Equity" in a and "Fixed" in b) or ("Fixed" in a and "Equity" in b): corr[(a,b)] = 0.20
                elif "Fixed" in a and "Fixed" in b: corr[(a,b)] = 0.35
                elif "Cash" in a or "Cash" in b: corr[(a,b)] = 0.05
                else: corr[(a,b)] = 0.30
    return CMA(mu_ann, vol_ann, corr)

# ---------------------------
# Helpers
# ---------------------------

def _mk_order(target_classes: List[str]) -> List[str]:
    return list(dict.fromkeys(target_classes))

def _monthly_params(cma: CMA, classes: List[str], steps_per_year: int):
    mu = np.array([cma.mu_ann[c] for c in classes])
    vol = np.array([cma.vol_ann[c] for c in classes])
    C = np.zeros((len(classes), len(classes)))
    for i,a in enumerate(classes):
        for j,b in enumerate(classes):
            C[i,j] = cma.corr[(a,b)] * vol[i] * vol[j]
    mu_m = np.log1p(mu)/steps_per_year
    cov_m = C/steps_per_year
    chol = np.linalg.cholesky(cov_m)
    return mu_m, chol

# ---------------------------
# MC Core
# ---------------------------

@dataclass
class MCConfig:
    n_paths: int = 10000
    seed: Optional[int] = 42
    store_percentiles: bool = True

@dataclass
class MCResult:
    terminal: np.ndarray
    ptiles_over_time: Optional[Dict[str, np.ndarray]]
    prob_by_goal: Dict[str, float]
    summary: Dict[str, float]

def run_mc(portfolio: ClientPortfolio, cma: CMA, mc: MCConfig) -> MCResult:
    if mc.seed is not None:
        np.random.seed(mc.seed)

    classes = _mk_order([w.cls for w in portfolio.target_allocation])
    steps = portfolio.horizon_years * portfolio.steps_per_year
    mu_m, chol = _monthly_params(cma, classes, portfolio.steps_per_year)

    w_target = np.array([w.weight for w in portfolio.target_allocation], dtype=float)
    w_target = w_target / w_target.sum()

    pv0 = sum(a.balance for a in portfolio.accounts)
    balances = pv0 * w_target

    liq_floor = getattr(portfolio.constraints, 'liquidity_floor_pct', 0.0)
    rebalance_monthly = (portfolio.constraints.rebalance_frequency.lower() == "monthly")

    # normalize flows
    rec = [RecurringFlow(**rf) for rf in portfolio.cash_flows.get("recurring", [])]
    sch = [ScheduledFlow(**sf) for sf in portfolio.cash_flows.get("scheduled", [])]

    def add_recurring(balances: np.ndarray):
        add_taxable = sum(r.amount_monthly for r in rec if r.account_type == "taxable")
        add_taxadv_m = sum(r.amount_annual for r in rec if r.account_type == "tax-advantaged") / portfolio.steps_per_year
        total_add = add_taxable + add_taxadv_m
        if total_add != 0.0:
            balances += total_add * w_target
        return balances

    def apply_scheduled(t: int, balances: np.ndarray):
        yr = (t-1) // portfolio.steps_per_year + 1
        for s in sch:
            if s.repeat_months is None and s.year == yr:
                balances += s.amount * w_target
            elif s.repeat_months is not None:
                if yr == s.year:
                    m0 = (s.year-1)*portfolio.steps_per_year + 1
                    m_end = m0 + s.repeat_months
                    if m0 <= t < m_end:
                        balances += (s.amount) * w_target
        return balances

    idx_cash_like = None
    for i,c in enumerate(classes):
        if "Cash" in c or "Money" in c or "TBill" in c:
            idx_cash_like = i
            break
    if idx_cash_like is None:
        for i,c in enumerate(classes):
            if "Fixed_Income" in c:
                idx_cash_like = i
                break

    def rebalance(balances: np.ndarray):
        total = balances.sum()
        if liq_floor > 0 and idx_cash_like is not None:
            min_cash = liq_floor * total
            if balances[idx_cash_like] < min_cash:
                deficit = min_cash - balances[idx_cash_like]
                others = np.arange(len(balances)) != idx_cash_like
                pool = balances[others].sum()
                if pool > 0:
                    balances[others] -= deficit * (balances[others]/pool)
                    balances[idx_cash_like] += deficit
        total = balances.sum()
        return total * w_target

    terminal = np.empty(mc.n_paths)
    sample_paths = None
    if mc.store_percentiles:
        keep = min(1500, mc.n_paths)
        sample_paths = np.empty((keep, steps+1))

    for path in range(mc.n_paths):
        bal = balances.copy()
        if sample_paths is not None and path < sample_paths.shape[0]:
            sample_paths[path,0] = bal.sum()
        for t in range(1, steps+1):
            z = chol @ np.random.randn(len(classes))
            r = np.exp(mu_m + z) - 1.0
            bal *= (1.0 + r)
            bal = add_recurring(bal)
            bal = apply_scheduled(t, bal)
            if rebalance_monthly:
                bal = rebalance(bal)
            if sample_paths is not None and path < sample_paths.shape[0]:
                sample_paths[path,t] = bal.sum()
        terminal[path] = bal.sum()

    ptiles_over_time = None
    if sample_paths is not None:
        ptiles_over_time = {
            "p10": np.percentile(sample_paths, 10, axis=0),
            "p50": np.percentile(sample_paths, 50, axis=0),
            "p90": np.percentile(sample_paths, 90, axis=0)
        }

    prob_by_goal = {}
    for g in portfolio.goals:
        label = g.label or f"Goal@Y{g.year}"
        prob_by_goal[label] = float((terminal >= g.target).mean())

    summary = {
        "median_terminal": float(np.median(terminal)),
        "p5_terminal": float(np.percentile(terminal, 5)),
        "p95_terminal": float(np.percentile(terminal, 95))
    }
    return MCResult(terminal, ptiles_over_time, prob_by_goal, summary)

# ---------------------------
# Builder
# ---------------------------

def portfolio_from_dict(d: Dict) -> ClientPortfolio:
    accounts = [Account(**a) for a in d["accounts"]]
    ab = [AssetWeight(cls=x["class"], weight=x["weight"]) for x in d.get("asset_breakdown", [])]
    ta = [AssetWeight(cls=x["class"], weight=x["weight"]) for x in d["target_allocation"]]
    constraints = Constraints(**d.get("constraints", {}))
    goals = [Goal(**g) for g in d.get("goals", [])]
    horizon = d.get("client", {}).get("time_horizon_years", d.get("time_horizon_years", 20))
    return ClientPortfolio(
        client=d.get("client", {}),
        accounts=accounts,
        asset_breakdown=ab,
        target_allocation=ta,
        cash_flows=d.get("cash_flows", {"recurring":[], "scheduled":[]}),
        constraints=constraints,
        goals=goals,
        horizon_years=horizon,
        steps_per_year=d.get("steps_per_year", 12)
    )

