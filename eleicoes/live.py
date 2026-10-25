"""Coleta a apuração ao vivo no site de resultados do TSE e roda a projeção.

O sistema de divulgação publica um JSON por município:
  {RESULTADOS}/ele2026/6258/dados/{uf}/{uf}{cd_mun}-c0001-e006258-u.json
com votos de cada candidato, brancos, nulos e o eleitorado das seções já
totalizadas ("e.est" / "e.te"), que usamos como fração apurada do município.
O TSE não divulga resultado por zona durante a apuração (só por município,
UF e Brasil); a projeção por zona é derivada do desvio estimado do município
aplicado ao vetor de 1º turno de cada zona.

Uso:
  python -m eleicoes.live                       # 2º turno 2026, a cada 120 s
  python -m eleicoes.live --uma-vez             # uma rodada só
  python -m eleicoes.live --eleicao 6257        # teste com o 1º turno (já 100% apurado)
"""
import argparse
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

from .config import CARGO_PRESIDENTE, CICLO_2026, ELEICAO_T2_2026, FINALISTAS, LIVE, PROCESSED, PRIOR_TRANSFERENCIA, RESULTADOS, TERCEIROS
from .model import Modelo, expit, logit

ANO = 2026
BRT = ZoneInfo("America/Sao_Paulo")
NUM_A, NUM_B = str(FINALISTAS[ANO]["A"]), str(FINALISTAS[ANO]["B"])


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


class ColetorTSE:
    def __init__(self, eleicao=ELEICAO_T2_2026, workers=10, timeout=20):
        self.eleicao = eleicao
        self.base = f"{RESULTADOS}/{CICLO_2026}/{eleicao}"
        self.s = requests.Session()
        ad = requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers, max_retries=2)
        self.s.mount("https://", ad)
        self.s.headers["User-Agent"] = "projecao-eleicoes/1.0 (pesquisa)"
        self.workers, self.timeout = workers, timeout
        self.etag, self.cache, self.falhas = {}, {}, 0
        self.municipios = self._municipios()

    def _get(self, url, chave=None):
        h = {}
        if chave and chave in self.etag:
            h["If-None-Match"] = self.etag[chave]
        for tentativa in range(6):
            r = self.s.get(url, headers=h, timeout=self.timeout)
            if r.status_code != 429:
                break
            # limite de requisições do TSE (janela de 1 s): espera e tenta de novo
            time.sleep(float(r.headers.get("x-ratelimit-reset", 1) or 1) + random.random() * (1 + tentativa))
        if r.status_code == 304:
            return None
        r.raise_for_status()
        if chave and r.headers.get("ETag"):
            self.etag[chave] = r.headers["ETag"]
        return r.json()

    def _municipios(self):
        d = self._get(f"{self.base}/config/mun-e{int(self.eleicao):06d}-cm.json")
        return [(a["cd"], m["cd"]) for a in d["abr"] for m in a["mu"]]

    @staticmethod
    def _parse(d):
        cands = {}
        for ag in d["carg"][0]["agr"]:
            for p in ag["par"]:
                for c in p["cand"]:
                    cands[c["n"]] = _int(c.get("vap"))
        e, v = d.get("e", {}), d.get("v", {})
        te = _int(e.get("te"))
        return {
            "A": cands.get(NUM_A, 0), "B": cands.get(NUM_B, 0),
            "brancos": _int(v.get("vb")), "nulos": _int(v.get("tvn")),
            "comparecimento": _int(e.get("c")), "eleitorado": te,
            "pi": _int(e.get("est")) / te if te else 0.0,
            "pct_secoes": float(str(d.get("s", {}).get("pstn", "0")).replace(",", ".") or 0),
            "hora": d.get("ht", ""),
        }

    def _municipio(self, uf, mun):
        chave = f"{uf}{mun}"
        url = f"{self.base}/dados/{uf}/{uf}{mun}-c{CARGO_PRESIDENTE}-e{int(self.eleicao):06d}-u.json"
        try:
            d = self._get(url, chave)
            if d is not None:
                self.cache[chave] = self._parse(d)
        except Exception:  # mantém o último dado bom
            self.falhas += 1
        return (uf.upper(), int(mun)), self.cache.get(chave)

    def coletar(self):
        self.falhas = 0
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda um: self._municipio(*um), self.municipios))
        linhas = {k: v for k, v in res if v}
        df = pd.DataFrame.from_dict(linhas, orient="index")
        df.index = pd.MultiIndex.from_tuples(df.index, names=["uf", "cd_mun"])
        return df

    def nacional(self):
        d = self._get(f"{self.base}/dados/br/br-c{CARGO_PRESIDENTE}-e{int(self.eleicao):06d}-u.json")
        p = self._parse(d)
        p["pct_secoes"] = float(str(d["s"]["pstn"]).replace(",", "."))
        return p


def projecao_zonas(res, ano=ANO):
    """Projeção por zona: vetor do 1º turno de cada zona + desvio estimado do
    seu município (o TSE não divulga zona durante a apuração)."""
    v = pd.read_parquet(PROCESSED / "munzona_votos.parquet")
    v = v[(v.ano == ano) & (v.turno == 1)]
    w = v.pivot_table(index=["uf", "cd_mun", "zona"], columns="nr", values="votos", fill_value=0)
    fin, terc = FINALISTAS[ano], TERCEIROS[ano]
    prior = PRIOR_TRANSFERENCIA[ano]
    A1, B1 = w[fin["A"]], w[fin["B"]]
    num = A1.astype(float)
    den = A1 + B1
    usados = {fin["A"], fin["B"]}
    for nr, nome in terc.items():
        if nr in w:
            num = num + prior[nome] * w[nr]
            den = den + w[nr]
            usados.add(nr)
    outros = w[[c for c in w.columns if c not in usados]].sum(axis=1)
    num, den = num + prior["outros"] * outros, den + outros
    z = pd.DataFrame({"validos_1t": w.sum(axis=1), "base_A": (num + .5) / (den + 1)})
    mun = res["municipios"][["desvio_logit", "pi"]]
    z = z.join(mun, on=["uf", "cd_mun"])
    z["proj_A"] = 100 * expit(logit(z.base_A) + z.desvio_logit.fillna(0))
    z["base_A"] *= 100
    z["proj_B"] = 100 - z.proj_A
    return z.reset_index()


def imprimir(res, tse, df, modelo, t0):
    nA, nB = FINALISTAS[ANO]["nome_A"], FINALISTAS[ANO]["nome_B"]
    lo, hi = res["A_ic90"]
    print("\n" + "=" * 78)
    print(f"[{datetime.now(BRT):%H:%M:%S}]  seções totalizadas (TSE): {tse['pct_secoes']:.2f}%   "
          f"municípios com dados: {res['municipios_com_dados']} ({res['municipios_completos']} completos)")
    if tse["A"] + tse["B"]:
        tA = tse["A"] / (tse["A"] + tse["B"]) * 100
        print(f"  parcial TSE ..........  {nA} {tA:.2f}%  x  {nB} {100 - tA:.2f}%")
    else:
        print("  parcial TSE ..........  sem votos apurados (projeção = linha de base do 1º turno)")
    print(f"  PROJEÇÃO FINAL .......  {nA} {res['A']:.2f}%  x  {nB} {res['B']:.2f}%")
    print(f"  IC 90% {nA}: {lo:.2f}% – {hi:.2f}%   |   IC 95%: {res['A_ic95'][0]:.2f}% – {res['A_ic95'][1]:.2f}%")
    print(f"  P({nA} vence) = {100 * res['prob_A']:.1f}%   P({nB} vence) = {100 * (1 - res['prob_A']):.1f}%")
    print(f"  válidos projetados: {res['validos_proj'] / 1e6:.2f} mi   desvio médio vs. base 1º turno: {res['swing_medio']:+.3f} logit")
    g = modelo.resumo_por(res, "regiao")
    g["apurado_%"] = res["municipios"].assign(w=modelo.V1 * res["municipios"].pi, v=modelo.V1).groupby("regiao").apply(
        lambda x: 100 * x.w.sum() / x.v.sum())
    print("  por região:  " + " | ".join(f"{r}: {row.A_pct:.1f}% ({row['apurado_%']:.0f}% apurado)" for r, row in g.iterrows()))
    print(f"  (rodada em {time.time() - t0:.1f}s)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eleicao", default=ELEICAO_T2_2026)
    ap.add_argument("--intervalo", type=int, default=120)
    ap.add_argument("--uma-vez", action="store_true")
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--transf", default=None,
                    help="divisão dos terceiros em %% para A, ex.: cury=50,renan=50,caiado=70,zema=80,outros=35")
    ap.add_argument("--prior-A", type=float, default=None,
                    help="calibra a linha de base para este %% de A antes da apuração (ex.: 50 = pesquisas)")
    a = ap.parse_args()
    LIVE.mkdir(parents=True, exist_ok=True)
    col = ColetorTSE(a.eleicao)
    prior = dict(PRIOR_TRANSFERENCIA[ANO])
    if a.transf:
        for par in a.transf.split(","):
            k, v = par.split("=")
            prior[k.strip()] = float(v) / 100
    modelo = Modelo(ANO, prior=prior, alvo_prior=None if a.prior_A is None else a.prior_A / 100)
    print(f"{len(col.municipios)} municípios no feed do TSE; prior de transferência: {modelo.prior}")
    hist = LIVE / f"historico_{a.eleicao}.csv"
    while True:
        t0 = time.time()
        try:
            df = col.coletar()
            tse = col.nacional()
            res = modelo.projetar(df[["A", "B", "pi"]], n_sim=a.sims, detalhe=True)
            imprimir(res, tse, df, modelo, t0)
            stamp = datetime.now(BRT).isoformat(timespec="seconds")
            linha = {"hora": stamp, "pct_secoes_tse": tse["pct_secoes"], "parcial_A": res["parcial_A"],
                     "proj_A": res["A"], "ic90_lo": res["A_ic90"][0], "ic90_hi": res["A_ic90"][1],
                     "prob_A": res["prob_A"], "municipios": res["municipios_com_dados"]}
            pd.DataFrame([linha]).to_csv(hist, mode="a", header=not hist.exists(), index=False)
            df.to_csv(LIVE / f"apuracao_municipios_{a.eleicao}.csv")
            res["municipios"].to_csv(LIVE / f"projecao_municipios_{a.eleicao}.csv")
            projecao_zonas(res).to_csv(LIVE / f"projecao_zonas_{a.eleicao}.csv", index=False)
            modelo.resumo_por(res, "uf").to_csv(LIVE / f"projecao_uf_{a.eleicao}.csv")
            with open(LIVE / f"ultima_{a.eleicao}.json", "w") as f:
                json.dump({k: v for k, v in linha.items()}, f, ensure_ascii=False, indent=1)
        except Exception as exc:
            print(f"erro na rodada: {exc!r}")
        if a.uma_vez:
            break
        time.sleep(max(5, a.intervalo - (time.time() - t0)))


if __name__ == "__main__":
    main()
