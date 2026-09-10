#!/usr/bin/env python3
"""Fantasy basketball TOTAL projection + $210 auction + FA salary. Spec: fantasy_basketball_value_salary_engine.md"""
from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "fantasy_basketball_list.csv"
CAL_PATH = HERE / "calibration.json"

CATS = ("FG", "FT", "THREE_PM", "PTS", "REB", "AST", "STL", "BLK", "TO")
POS_CATS = CATS[:-1]
LAMBDA = 1e-6
FLOOR = -2.0
TEAMS = 12
ROSTER = 13
DRAFTED = TEAMS * ROSTER
CAP = 210
LEAGUE_BUDGET = TEAMS * CAP
MIN_SAL = 1
PREMIUM = LEAGUE_BUDGET - DRAFTED * MIN_SAL
MAX_FA = 15
FA_FACTOR = 0.30
REPLACEMENT_RANK = 157
FINAL_ROUND_FROM = 145
WEIGHTS = {c: 1.0 for c in CATS}
MARKET_BANDS = (
    (1, 3, 1.25),
    (4, 12, 1.15),
    (13, 24, 1.08),
    (25, 48, 1.00),
    (49, 84, 0.95),
    (85, 120, 0.85),
    (121, 144, 0.70),
)

COUNTING = ("fgm", "fga", "ftm", "fta", "threePM", "pts", "reb", "ast", "stl", "blk", "tov", "minutes")


def slug(name: str) -> str:
    s = name.lower().replace("'", "").replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def parse_players(path: Path = CSV_PATH) -> list[dict]:
    rows = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            name = r["PLAYER"].strip()
            gp = float(r["GP"] or 0)
            p = {
                "rank": int(float(r["RANK"])),
                "rankChange": int(float(r["RANK_CHANGE"] or 0)) if r["RANK_CHANGE"] else 0,
                "name": name,
                "id": slug(name),
                "pos": r.get("POS") or "",
                "team": r.get("TEAM") or "",
                "gp": gp,
                "minutes": float(r["MPG"] or 0),
                "fgPct": float(r["FG_PCT"] or 0),
                "fgm": float(r["FGM"] or 0),
                "fga": float(r["FGA"] or 0),
                "ftPct": float(r["FT_PCT"] or 0),
                "ftm": float(r["FTM"] or 0),
                "fta": float(r["FTA"] or 0),
                "threePM": float(r["3PM"] or 0),
                "pts": float(r["PTS"] or 0),
                "reb": float(r["TREB"] or 0),
                "ast": float(r["AST"] or 0),
                "stl": float(r["STL"] or 0),
                "blk": float(r["BLK"] or 0),
                "tov": float(r["TO"] or 0),
                "total": float(r["TOTAL"] or 0),
            }
            rows.append(p)
    return rows


def league_pcts(players: list[dict]) -> tuple[float, float]:
    fgm = sum(p["fgm"] for p in players)
    fga = sum(p["fga"] for p in players)
    ftm = sum(p["ftm"] for p in players)
    fta = sum(p["fta"] for p in players)
    return fgm / fga, ftm / fta


def feature_row(p: dict, league_fg: float, league_ft: float) -> np.ndarray:
    return np.array([
        p["fgm"] - p["fga"] * league_fg,
        p["ftm"] - p["fta"] * league_ft,
        p["threePM"], p["pts"], p["reb"], p["ast"], p["stl"], p["blk"], p["tov"],
    ], dtype=float)


def features(players: list[dict], league_fg: float, league_ft: float) -> np.ndarray:
    return np.vstack([feature_row(p, league_fg, league_ft) for p in players])


def init_theta(X: np.ndarray) -> np.ndarray:
    mean = X.mean(axis=0)
    sd = X.std(axis=0, ddof=0)
    sd = np.where(sd == 0, 1.0, sd)
    theta = np.zeros(18)
    for c in range(8):
        theta[2 * c + 1] = 1.0 / sd[c]
        theta[2 * c] = -mean[c] / sd[c]
    theta[17] = -1.0 / sd[8]
    theta[16] = mean[8] / sd[8]
    return theta


def clip_theta(theta: np.ndarray) -> np.ndarray:
    t = theta.copy()
    for c in range(8):
        t[2 * c + 1] = max(0.0, t[2 * c + 1])
    t[17] = min(0.0, t[17])
    return t


def predicted_and_jac(X: np.ndarray, theta: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    n = X.shape[0]
    pred = np.zeros(n)
    J = np.zeros((n, 18))
    for c in range(9):
        a, b = theta[2 * c], theta[2 * c + 1]
        raw = a + b * X[:, c]
        active = raw > FLOOR
        val = np.where(active, raw, FLOOR)
        pred += w[c] * val
        J[:, 2 * c] = np.where(active, w[c], 0.0)
        J[:, 2 * c + 1] = np.where(active, w[c] * X[:, c], 0.0)
    return pred, J


def calibrate(players: list[dict], league_fg: float, league_ft: float) -> dict:
    X = features(players, league_fg, league_ft)
    y = np.array([p["total"] for p in players], dtype=float)
    w = np.array([WEIGHTS[c] for c in CATS])
    theta0 = init_theta(X)
    theta = clip_theta(theta0)
    n, k = X.shape[0], 18
    mu = 1e-3
    for _ in range(80):
        pred, J = predicted_and_jac(X, theta, w)
        r = pred - y
        J_aug = np.vstack([J, math.sqrt(LAMBDA) * np.eye(k)])
        r_aug = np.concatenate([r, math.sqrt(LAMBDA) * (theta - theta0)])
        A = J_aug.T @ J_aug + mu * np.eye(k)
        g = J_aug.T @ r_aug
        try:
            delta = np.linalg.solve(A, -g)
        except np.linalg.LinAlgError:
            mu *= 10
            continue
        trial = clip_theta(theta + delta)
        pred2, _ = predicted_and_jac(X, trial, w)
        sse2 = float(np.square(pred2 - y).sum() + LAMBDA * np.square(trial - theta0).sum())
        sse1 = float(np.square(r).sum() + LAMBDA * np.square(theta - theta0).sum())
        if sse2 < sse1:
            theta = trial
            mu = max(mu / 3, 1e-12)
            if np.linalg.norm(delta) < 1e-12:
                break
        else:
            mu *= 3
            if mu > 1e8:
                break
    pred, _ = predicted_and_jac(X, theta, w)
    err = pred - y
    mae = float(np.mean(np.abs(err)))
    rmse = float(math.sqrt(np.mean(err ** 2)))
    max_err = float(np.max(np.abs(err)))
    coef = {CATS[c]: {"a": float(theta[2 * c]), "b": float(theta[2 * c + 1])} for c in range(9)}
    return {
        "leagueFG": float(league_fg),
        "leagueFT": float(league_ft),
        "coefficients": coef,
        "categoryWeights": dict(WEIGHTS),
        "sourceDatasetVersion": CSV_PATH.name,
        "mae": mae,
        "rmse": rmse,
        "maxError": max_err,
        "n": n,
        "_theta": theta,
        "_theta0": theta0,
        "_w": w,
    }


def score_features(x: np.ndarray, cal: dict) -> float:
    total = 0.0
    for c, name in enumerate(CATS):
        a, b = cal["coefficients"][name]["a"], cal["coefficients"][name]["b"]
        w = cal["categoryWeights"][name]
        total += w * max(FLOOR, a + b * float(x[c]))
    return total


def score_player(p: dict, cal: dict) -> float:
    return score_features(feature_row(p, cal["leagueFG"], cal["leagueFT"]), cal)


def scale_player(p: dict, target_gp: float) -> dict:
    if p["gp"] <= 0:
        raise ValueError(f"{p['name']} GP=0")
    s = target_gp / p["gp"]
    q = dict(p)
    for k in COUNTING:
        q[k] = p[k] * s
    q["gp"] = target_gp
    q["scaleFactor"] = s
    q["fgPct"] = q["fgm"] / q["fga"] if q["fga"] else 0.0
    q["ftPct"] = q["ftm"] / q["fta"] if q["fta"] else 0.0
    return q


def market_weight(rank: int) -> float:
    if rank >= FINAL_ROUND_FROM:
        return 0.0
    for lo, hi, m in MARKET_BANDS:
        if lo <= rank <= hi:
            return m
    return 0.0


def competition_rank(total: float, others: list[float]) -> int:
    return 1 + sum(1 for t in others if t > total)


def auction_table(totals: list[float]) -> list[dict]:
    """totals aligned to players already sorted by TOTAL desc (stable)."""
    order = sorted(range(len(totals)), key=lambda i: (-totals[i], i))
    repl = totals[order[REPLACEMENT_RANK - 1]] if len(order) >= REPLACEMENT_RANK else 0.0
    rows = []
    scores = []
    for slot, i in enumerate(order, 1):
        surplus = max(0.0, totals[i] - repl)
        wt = market_weight(slot)
        ms = surplus * wt if slot <= 144 else 0.0
        scores.append(ms)
        rows.append({"index": i, "rank": slot, "total": totals[i], "surplus": surplus, "marketScore": ms})
    prem = sum(r["marketScore"] for r in rows if r["rank"] <= 144)
    dps = PREMIUM / prem if prem else 0.0
    for r in rows:
        if r["rank"] >= FINAL_ROUND_FROM:
            r["auctionMarketValue"] = float(MIN_SAL) if r["rank"] <= DRAFTED else float(MIN_SAL)
        else:
            r["auctionMarketValue"] = MIN_SAL + r["marketScore"] * dps
        r["replacementTotal"] = repl
        r["dollarPerMarketScore"] = dps
    out = [None] * len(totals)
    for r in rows:
        out[r["index"]] = r
    return out


def fa_salary(market_value: float) -> float:
    return min(MAX_FA, MIN_SAL + FA_FACTOR * max(0.0, market_value - MIN_SAL))


def project(players: list[dict], cal: dict, player_id: str, target_gp: float) -> dict:
    target = next((p for p in players if p["id"] == player_id or p["name"].lower() == player_id.lower()), None)
    if target is None:
        raise KeyError(player_id)
    scaled = scale_player(target, target_gp)
    projected_total = score_player(scaled, cal)
    others = [p["total"] for p in players if p is not target]
    new_rank = competition_rank(projected_total, others)
    mixed = []
    for p in players:
        mixed.append(projected_total if p is target else p["total"])
    table = auction_table(mixed)
    econ = table[players.index(target)]
    mv = econ["auctionMarketValue"]
    fa = fa_salary(mv)
    return {
        "player": target["name"],
        "playerId": target["id"],
        "original": {"games": target["gp"], "rank": target["rank"], "total": target["total"]},
        "projection": {
            "games": target_gp,
            "scaleFactor": scaled["scaleFactor"],
            "stats": {k: scaled[k] for k in ("fgm", "fga", "ftm", "fta", "threePM", "pts", "reb", "ast", "stl", "blk", "tov")},
            "total": projected_total,
            "rank": new_rank,
        },
        "economics": {
            "auctionMarketValue": mv,
            "auctionMarketValueRounded": int(round(mv)),
            "faSalary": fa,
            "faSalaryRounded": int(round(fa)),
            "faSalaryCap": MAX_FA,
            "marketSurplusIfFA": mv - fa,
            "replacementTotal": econ["replacementTotal"],
        },
        "change": {
            "total": projected_total - target["total"],
            "rank": target["rank"] - new_rank,
        },
        "calibration": {"mae": cal["mae"], "rmse": cal["rmse"], "maxError": cal["maxError"]},
        "warning": cal["mae"] >= 0.01,
    }


def explain(res: dict) -> str:
    o, p, e = res["original"], res["projection"], res["economics"]
    return (
        f"{res['player']} {o['games']:.0f} maçta {o['total']:.2f} TOTAL ile {o['rank']}. sırada.\n\n"
        f"{p['games']:.0f} maç projeksiyonunda mevcut maç-başı performansının değişmediği varsayıldı.\n\n"
        f"Ham counting istatistikleri {p['games']:.0f}/{o['games']:.0f} = {p['scaleFactor']:.4f} katsayısıyla ölçeklendi.\n\n"
        f"FG% ve FT% doğrudan çarpılmadı; şut hacmi dikkate alınarak weighted percentage impact yeniden hesaplandı.\n\n"
        f"Ardından her kategori kalibre edilmiş z-score benzeri değer fonksiyonundan geçirildi ve H2H negatif kategori floor'u uygulandı.\n\n"
        f"Son projected TOTAL yaklaşık {p['total']:.2f} oldu. Bu değer mevcut oyuncu havuzuna yerleştirildiğinde yaklaşık {p['rank']}. sıraya karşılık geliyor.\n\n"
        f"Auction market value ≈ ${e['auctionMarketValue']:.2f} (${e['auctionMarketValueRounded']}). "
        f"FA maaşı = min(15, 1 + 0.30×(MV−1)) ≈ ${e['faSalary']:.2f} (${e['faSalaryRounded']})."
    )


def dump_calibration(cal: dict, path: Path = CAL_PATH) -> None:
    keep = {k: cal[k] for k in (
        "leagueFG", "leagueFT", "coefficients", "categoryWeights",
        "sourceDatasetVersion", "mae", "rmse", "maxError", "n",
    )}
    path.write_text(json.dumps(keep, indent=2), encoding="utf-8")


def _close(a, b, tol):
    return abs(a - b) <= tol


def self_check() -> None:
    players = parse_players()
    dej = next(p for p in players if p["name"] == "Dejounte Murray")
    assert dej["rank"] == 346 and dej["rankChange"] == 1
    assert dej["gp"] == 14 and dej["total"] == 5.15
    lg, lt = league_pcts(players)
    cal = calibrate(players, lg, lt)
    dump_calibration(cal)
    print(f"calibration MAE={cal['mae']:.6f} RMSE={cal['rmse']:.6f} MAX={cal['maxError']:.6f}")
    assert cal["mae"] < 0.01, f"Test A MAE {cal['mae']}"

    pred = np.array([score_player(p, cal) for p in players])
    obs = np.array([p["total"] for p in players])
    assert float(np.mean(np.abs(pred - obs))) < 0.01

    # Test B Dejounte 64
    b = project(players, cal, "dejounte-murray", 64)
    st = b["projection"]["stats"]
    assert _close(st["fga"], 832.0, 1e-6)
    assert _close(st["fgm"], 402.2857, 5e-4)
    assert _close(st["pts"], 1069.7143, 5e-4)
    assert _close(b["projection"]["total"], 16.98, 0.05), b["projection"]["total"]
    assert b["projection"]["rank"] == 42, b["projection"]["rank"]

    # Test C Jokic market on observed pool
    totals = [p["total"] for p in players]
    table = auction_table(totals)
    jokic = table[0]
    assert jokic["rank"] == 1
    mv = jokic["auctionMarketValue"]
    print(f"Jokic MV={mv:.2f}")
    assert 75 <= mv <= 82, mv

    # Test D final round $1
    for r in table:
        if 145 <= r["rank"] <= 156:
            assert r["auctionMarketValue"] == 1, (r["rank"], r["auctionMarketValue"])

    # Test E budget
    s156 = sum(r["auctionMarketValue"] for r in table if r["rank"] <= 156)
    print(f"budget sum={s156:.6f}")
    assert abs(s156 - 2520) < 1e-6, s156

    # Test F FA cap
    assert fa_salary(80) == 15

    # Test G Nickeil 65
    g = project(players, cal, "nickeil-alexander-walker", 65)
    print(f"Nickeil TOTAL={g['projection']['total']:.4f} rank={g['projection']['rank']} "
          f"MV={g['economics']['auctionMarketValue']:.2f} FA={g['economics']['faSalary']:.2f}")
    assert _close(g["projection"]["total"], 17.97, 0.15), g["projection"]["total"]
    assert abs(g["projection"]["rank"] - 34) <= 2, g["projection"]["rank"]
    mvn = g["economics"]["auctionMarketValue"]
    assert 24 <= mvn <= 25.5, mvn
    assert g["economics"]["faSalaryRounded"] == 8

    # never scale TOTAL
    wrong = dej["total"] * 64 / 14
    assert abs(wrong - 23.54) < 0.02
    assert abs(b["projection"]["total"] - wrong) > 1

    print("ok")
    print(explain(b))


if __name__ == "__main__":
    self_check()
