"""Backtest: reapura o 2º turno de 2018 e de 2022 seção a seção, em ordens de
chegada simuladas, e mede o erro da projeção em cada ponto da apuração.

A apuração parcial é montada com as seções reais (votos do 2º turno de cada
seção), então capta a heterogeneidade dentro dos municípios grandes. A ordem
de chegada é simulada porque o TSE não publica o horário de totalização de
cada seção. Cenários:

  aleatorio  municípios chegam em ordem aleatória
  regional   Sul/Centro-Oeste/Sudeste primeiro, Nordeste e exterior por último
             (padrão parecido com 2022, quando Bolsonaro liderou até ~67%)
  vies_A     municípios mais favoráveis a A chegam primeiro (cenário adversarial)
  vies_B     o oposto

Para não "colar", o prior de transferência usado no backtest é neutro (50/50
para todos os terceiros) — o modelo tem que aprender a transferência com os
dados apurados.

Uso: python -m eleicoes.backtest [--anos 2022 2018] [--seeds 5]
"""
import argparse

import numpy as np
import pandas as pd

from .config import PROCESSED, REGIAO, REPORTS
from .model import Modelo, Parametros, logit

COBERTURAS = [0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.40, 0.60, 0.80]
OFFSET_REGIAO = {"Sul": -0.8, "Centro-Oeste": -0.6, "Sudeste": -0.3, "Norte": 0.0, "Nordeste": 0.9, "Exterior": 1.5}


def carregar_secoes(ano):
    s = pd.read_parquet(PROCESSED / f"secao_{ano}.parquet")
    voto_cols = [c for c in s.columns if c not in ("turno", "uf", "cd_mun", "zona", "secao")]
    s["n"] = s[voto_cols].sum(axis=1)
    t1 = s[s.turno == 1].set_index(["uf", "cd_mun", "zona", "secao"]).n.rename("n1")
    t2 = s[s.turno == 2].set_index(["uf", "cd_mun", "zona", "secao"])[["A", "B"]]
    t2 = t2.join(t1, how="left").fillna({"n1": 0}).reset_index()
    t2["regiao"] = t2.uf.map(REGIAO)
    return t2


def ordem(sec, cenario, rng):
    m = sec.groupby(["uf", "cd_mun"]).agg(A=("A", "sum"), B=("B", "sum"), ns=("secao", "size"), regiao=("regiao", "first"))
    off = rng.normal(0, 1, len(m))
    if cenario == "regional":
        off = off * 0.6 + m.regiao.map(OFFSET_REGIAO).to_numpy()
    elif cenario in ("vies_A", "vies_B"):
        z = logit(m.A / (m.A + m.B))
        z = (z - z.mean()) / z.std()
        off = off * 0.5 + (-1 if cenario == "vies_A" else 1) * z.to_numpy()
    spread = 0.2 + 0.25 * np.log10(m.ns.to_numpy())
    m["off"], m["spread"] = off, spread
    s = sec.join(m[["off", "spread"]], on=["uf", "cd_mun"])
    zona = s.groupby(["uf", "cd_mun", "zona"]).ngroup().to_numpy()
    zoff = rng.normal(0, 0.3, zona.max() + 1)[zona]
    t = s.off.to_numpy() + s.spread.to_numpy() * (rng.random(len(s)) + zoff)
    return np.argsort(t)


def observacao(sec, ordem_idx, cobertura, n1_mun):
    k = int(round(cobertura * len(sec)))
    parc = sec.iloc[ordem_idx[:k]]
    o = parc.groupby(["uf", "cd_mun"])[["A", "B", "n1"]].sum()
    o["pi"] = (o.n1 / n1_mun.reindex(o.index)).clip(0, 1).fillna(0)
    return o


def rodar(ano, seeds=5, cenarios=("aleatorio", "regional", "vies_A", "vies_B"), params=None, n_sim=1000, verbose=True):
    sec = carregar_secoes(ano)
    n1_mun = sec.groupby(["uf", "cd_mun"]).n1.sum()
    real = sec.A.sum() / (sec.A.sum() + sec.B.sum())
    prior = {k: 0.5 for k in Modelo(ano).prior}
    modelo = Modelo(ano, params=params, prior=prior)
    linhas = []
    for cen in cenarios:
        for seed in range(seeds):
            rng = np.random.default_rng(1000 * seed + cenarios.index(cen))
            idx = ordem(sec, cen, rng)
            for c in COBERTURAS:
                o = observacao(sec, idx, c, n1_mun)
                r = modelo.projetar(o, n_sim=n_sim, seed=seed)
                lo, hi = r["A_ic90"]
                lo95, hi95 = r["A_ic95"]
                linhas.append({
                    "ano": ano, "cenario": cen, "seed": seed, "cobertura_secoes": 100 * c,
                    "pct_votos_apurados": r["pct_apurado_votos"], "real_A": 100 * real,
                    "parcial_A": r["parcial_A"], "proj_A": r["A"], "erro": r["A"] - 100 * real,
                    "erro_parcial": r["parcial_A"] - 100 * real, "ic90_lo": lo, "ic90_hi": hi,
                    "dentro_ic90": lo <= 100 * real <= hi, "dentro_ic95": lo95 <= 100 * real <= hi95,
                    "prob_A": r["prob_A"], "acerta_vencedor": (r["A"] > 50) == (real > .5),
                })
            if verbose:
                ult = linhas[-len(COBERTURAS):]
                print(f"{ano} {cen:9s} seed {seed}: " + " ".join(f"{l['cobertura_secoes']:.1f}%→{l['erro']:+.2f}" for l in ult))
    return pd.DataFrame(linhas)


def resumir(df):
    g = df.groupby(["ano", "cobertura_secoes"])
    return pd.DataFrame({
        "votos_apurados_%": g.pct_votos_apurados.mean(),
        "erro_medio_pp": g.erro.mean(),
        "erro_abs_medio_pp": g.erro.apply(lambda x: x.abs().mean()),
        "erro_abs_max_pp": g.erro.apply(lambda x: x.abs().max()),
        "erro_abs_parcial_pp": g.erro_parcial.apply(lambda x: x.abs().mean()),
        "largura_ic90_pp": g.apply(lambda x: (x.ic90_hi - x.ic90_lo).mean()),
        "cobertura_ic90_%": 100 * g.dentro_ic90.mean(),
        "cobertura_ic95_%": 100 * g.dentro_ic95.mean(),
        "acerta_vencedor_%": 100 * g.acerta_vencedor.mean(),
    })


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anos", nargs="+", type=int, default=[2022, 2018])
    ap.add_argument("--seeds", type=int, default=5)
    a = ap.parse_args()
    df = pd.concat([rodar(ano, a.seeds) for ano in a.anos], ignore_index=True)
    (REPORTS / "tabelas").mkdir(parents=True, exist_ok=True)
    df.to_csv(REPORTS / "tabelas" / "backtest_detalhe.csv", index=False)
    res = resumir(df)
    res.to_csv(REPORTS / "tabelas" / "backtest_resumo.csv")
    pd.set_option("display.width", 220)
    print(res.round(2).to_string())
    print(df.groupby(["ano", "cenario"]).apply(lambda x: x.erro.abs().mean()).round(2))
