# backend/api.py
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
from universal_mc import example_cma, portfolio_from_dict, run_mc, MCConfig
from parser_docx import parse_portfolio_overview_docx
import numpy as np

app = FastAPI(title="Advisor Monte Carlo API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SimRequest(BaseModel):
    portfolio: Dict[str, Any]
    cma_override: Optional[Dict[str, Any]] = None
    n_paths: int = 10000
    seed: int = 42

@app.post("/parse-docx")
async def parse_docx(file: UploadFile = File(...)):
    # Save & parse
    tmp_path = f"/tmp/{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    portfolio_dict = parse_portfolio_overview_docx(tmp_path)
    return {"portfolio": portfolio_dict}

@app.post("/simulate")
def simulate(req: SimRequest):
    # CMA
    cma = example_cma()
    # Optional: support full override of mu/vol/corr (if supplied)
    if req.cma_override:
        mu = req.cma_override.get("mu_ann") or cma.mu_ann
        vol = req.cma_override.get("vol_ann") or cma.vol_ann
        corr = req.cma_override.get("corr") or cma.corr
        from universal_mc import CMA
        cma = CMA(mu_ann=mu, vol_ann=vol, corr=corr)

    from universal_mc import portfolio_from_dict
    portfolio = portfolio_from_dict(req.portfolio)
    cfg = MCConfig(n_paths=req.n_paths, seed=req.seed, store_percentiles=True)
    result = run_mc(portfolio, cma, cfg)

    resp = {
        "prob_by_goal": result.prob_by_goal,
        "summary": result.summary,
        "ptiles_over_time": {
            "p10": result.ptiles_over_time["p10"].tolist(),
            "p50": result.ptiles_over_time["p50"].tolist(),
            "p90": result.ptiles_over_time["p90"].tolist()
        } if result.ptiles_over_time else None
    }
    return resp

