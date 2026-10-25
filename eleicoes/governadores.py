"""2º turno de governador 2026 (AC, AM, DF, ES, RN, TO): mesmo modelo do presidente.

Para cada estado, a linha de base de cada município é o 1º turno de governador
com os votos dos eliminados divididos 50/50 (premissa neutra: não há base
para outra divisão estadual), e o desvio é aprendido com as urnas apuradas
nos municípios do próprio estado. Coleta: eleição 6260, cargo 3.

Uso:
  python -m eleicoes.governadores preparar   # gera data/processed/governador_2026_t1.parquet
"""
import json
import sys
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .config import CICLO_2026, LIVE, PROCESSED, RAW, REGIAO, RESULTADOS
from .model import Modelo
from .painel import BRT, _limpo, trajetoria

ELEICAO = "6260"
CARGO = "0003"
UFS = ["AC", "AM", "DF", "ES", "RN", "TO"]
ARQ = PROCESSED / "governador_2026_t1.parquet"
ARQ_CAND = PROCESSED / "governador_2026_candidatos.csv"
PRIOR = {"cury": 0.5, "renan": 0.5, "caiado": 0.5, "zema": 0.5, "outros": 0.5}


def preparar():
    zc = zipfile.ZipFile(RAW / "votacao_candidato_munzona_2026.zip")
    zd = zipfile.ZipFile(RAW / "detalhe_votacao_munzona_2026.zip")
    linhas, cands = [], []
    for uf in UFS:
        v = pd.read_csv(zc.open(f"votacao_candidato_munzona_2026_{uf}.csv"), sep=";", encoding="latin1", dtype=str,
                        usecols=["NR_TURNO", "CD_CARGO", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_CANDIDATO", "NM_URNA_CANDIDATO",
                                 "SG_PARTIDO", "QT_VOTOS_NOMINAIS_VALIDOS", "DS_SIT_TOT_TURNO"])
        v = v[(v.CD_CARGO == "3") & (v.NR_TURNO == "1")].copy()
        v["votos"] = v.QT_VOTOS_NOMINAIS_VALIDOS.astype(int)
        c = (v.groupby(["NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "DS_SIT_TOT_TURNO"]).votos.sum()
             .reset_index().sort_values("votos", ascending=False))
        fin = c[c.DS_SIT_TOT_TURNO.str.contains("2º TURNO")].head(2)
        nA, nB = fin.NR_CANDIDATO.iloc[0], fin.NR_CANDIDATO.iloc[1]
        c["uf"] = uf
        c["pct_validos_1t"] = 100 * c.votos / c.votos.sum()
        c["papel"] = np.where(c.NR_CANDIDATO == nA, "A", np.where(c.NR_CANDIDATO == nB, "B", "outro"))
        cands.append(c)
        d = pd.read_csv(zd.open(f"detalhe_votacao_munzona_2026_{uf}.csv"), sep=";", encoding="latin1", dtype=str)
        d = d[(d.CD_CARGO == "3") & (d.NR_TURNO == "1")]
        num = {"aptos": "QT_APTOS", "comparecimento": "QT_COMPARECIMENTO", "brancos": "QT_VOTOS_BRANCOS",
               "nulos": "QT_TOTAL_VOTOS_NULOS", "validos": "QT_TOTAL_VOTOS_VALIDOS"}
        dm = pd.DataFrame({k: d[c_].astype(int).values for k, c_ in num.items()})
        dm["cd_mun"] = d.CD_MUNICIPIO.astype(int).values
        dm = dm.groupby("cd_mun").sum()
        vm = v.assign(cd_mun=v.CD_MUNICIPIO.astype(int)).groupby(["cd_mun", "NR_CANDIDATO"]).votos.sum().unstack(fill_value=0)
        nomes = v.assign(cd_mun=v.CD_MUNICIPIO.astype(int)).groupby("cd_mun").NM_MUNICIPIO.first()
        p = pd.DataFrame(index=dm.index)
        p["uf"], p["nm_mun"], p["regiao"], p["n_zonas"] = uf, nomes, REGIAO[uf], 1
        for k in num:
            p["2026t1_" + k] = dm[k]
        p["2026t1_A"] = vm[nA]
        p["2026t1_B"] = vm[nB]
        for k in ("cury", "renan", "caiado", "zema"):
            p["2026t1_" + k] = 0
        p["2026t1_outros"] = vm.drop(columns=[nA, nB]).sum(axis=1)
        linhas.append(p.reset_index())
    pd.concat(linhas, ignore_index=True).to_parquet(ARQ, index=False)
    cc = pd.concat(cands, ignore_index=True)
    cc.to_csv(ARQ_CAND, index=False)
    print(cc[cc.papel != "outro"][["uf", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "SG_PARTIDO", "pct_validos_1t", "papel"]].to_string(index=False))


def _i(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


class EstadoGov:
    """Coleta e projeção dos 6 segundos turnos estaduais."""

    def __init__(self, sims=2000, workers=12):
        self.painel = pd.read_parquet(ARQ)
        cand = pd.read_csv(ARQ_CAND, dtype={"NR_CANDIDATO": str})
        self.fin = {uf: {p: g[g.papel == p].iloc[0] for p in ("A", "B")} for uf, g in cand.groupby("uf")}
        self.outros = {uf: g[g.papel == "outro"].nlargest(3, "votos")[["NM_URNA_CANDIDATO", "SG_PARTIDO", "pct_validos_1t"]]
                       .to_dict("records") for uf, g in cand.groupby("uf")}
        self.modelos = {uf: Modelo(2026, painel=self.painel[self.painel.uf == uf], prior=PRIOR) for uf in UFS}
        self.hist = {uf: [] for uf in UFS}
        self.inicio_uf = {}
        self.sims = sims
        self.base = f"{RESULTADOS}/{CICLO_2026}/{ELEICAO}"
        self.s = requests.Session()
        self.s.mount("https://", requests.adapters.HTTPAdapter(pool_connections=workers, pool_maxsize=workers, max_retries=2))
        self.workers, self.cache, self.etag = workers, {}, {}
        ordem = pd.read_csv(PROCESSED / "mapa_municipios.csv")
        self.ordem = {uf: ordem[ordem.uf == uf] for uf in UFS}
        self.arq_hist = LIVE / "governador_historico.json"
        if self.arq_hist.exists():
            try:
                self.hist = json.loads(self.arq_hist.read_text())
            except Exception:
                pass

    def _get(self, url, chave):
        h = {"If-None-Match": self.etag[chave]} if chave in self.etag else {}
        r = self.s.get(url, headers=h, timeout=20)
        if r.status_code == 304:
            return None
        r.raise_for_status()
        if r.headers.get("ETag"):
            self.etag[chave] = r.headers["ETag"]
        return r.json()

    def _parse(self, d, uf):
        nA, nB = self.fin[uf]["A"].NR_CANDIDATO, self.fin[uf]["B"].NR_CANDIDATO
        votos = {c["n"]: _i(c.get("vap")) for ag in d["carg"][0]["agr"] for p in ag["par"] for c in p["cand"]}
        e = d.get("e", {})
        te = _i(e.get("te"))
        return {"A": votos.get(nA, 0), "B": votos.get(nB, 0), "pi": _i(e.get("est")) / te if te else 0.0,
                "pct_secoes": float(str(d.get("s", {}).get("pstn", "0")).replace(",", ".") or 0)}

    def _um(self, uf, mun):
        chave = f"{uf}{mun:05d}"
        url = f"{self.base}/dados/{uf.lower()}/{uf.lower()}{mun:05d}-c{CARGO}-e00{ELEICAO}-u.json"
        try:
            d = self._get(url, chave)
            if d is not None:
                self.cache[chave] = self._parse(d, uf)
        except Exception:
            pass
        return (uf, mun), self.cache.get(chave)

    def coletar(self):
        alvo = [(r.uf, int(r.cd_mun)) for r in self.painel.itertuples()]
        with ThreadPoolExecutor(self.workers) as ex:
            res = list(ex.map(lambda um: self._um(*um), alvo))
        df = pd.DataFrame.from_dict({k: v for k, v in res if v}, orient="index")
        if len(df):
            df.index = pd.MultiIndex.from_tuples(df.index, names=["uf", "cd_mun"])
        tot = {}
        for uf in UFS:
            try:
                d = self._get(f"{self.base}/dados/{uf.lower()}/{uf.lower()}-c{CARGO}-e00{ELEICAO}-u.json", uf)
                if d is not None:
                    self.cache[uf] = self._parse(d, uf)
            except Exception:
                pass
            tot[uf] = self.cache.get(uf, {"A": 0, "B": 0, "pct_secoes": 0.0})
        return df, tot

    def _uf(self, uf, df, tot, registrar):
        m = self.modelos[uf]
        obs = df.xs(uf, level="uf", drop_level=False)[["A", "B", "pi"]] if len(df) and uf in df.index.get_level_values("uf") else None
        res = m.projetar(obs, n_sim=self.sims, detalhe=True)
        t = tot[uf]
        n = t["A"] + t["B"]
        if registrar and obs is not None and float(obs.pi.max()) > 0:
            self.inicio_uf.setdefault(uf, float(len(self.hist[uf])))
            self.hist[uf].append({"hora": datetime.now(BRT).strftime("%H:%M:%S"), "pct_secoes": t["pct_secoes"],
                                  "parcial_A": 100 * t["A"] / n if n else None, "proj_A": res["A"],
                                  "lo": res["A_ic90"][0], "hi": res["A_ic90"][1], "prob_A": res["prob_A"]})
            self.hist[uf] = self.hist[uf][-300:]
        d = res["municipios"].copy()
        d["V1"] = m.V1
        d = d.reset_index()
        o = obs[["A", "B"]].astype(float) if obs is not None else pd.DataFrame({"A": [], "B": []}, index=pd.MultiIndex.from_tuples([], names=["uf", "cd_mun"]))
        d = d.merge(o.rename(columns={"A": "A_obs", "B": "B_obs"}), left_on=["uf", "cd_mun"], right_index=True, how="left").fillna({"A_obs": 0.0, "B_obs": 0.0})
        d["V_obs"] = d.A_obs + d.B_obs
        ordem = self.ordem[uf]
        x = d.set_index("cd_mun").reindex(ordem.cd_mun.values)
        parcial = np.where(x.V_obs > 0, 100 * x.A_obs / x.V_obs.where(x.V_obs > 0, 1), -1)
        nomes = self.painel[self.painel.uf == uf].set_index("cd_mun").nm_mun
        d["desvio_pp"] = d.proj_A - d.base_1t_A
        com = d[d.pi > 0]

        def mun(z):
            return [{"municipio": str(nomes.get(r.cd_mun, r.cd_mun)).title(), "apurado": 100 * r.pi, "base_A": r.base_1t_A,
                     "proj_A": r.proj_A, "desvio_pp": r.desvio_pp} for r in z.itertuples()]

        fa, fb = self.fin[uf]["A"], self.fin[uf]["B"]
        return {
            "nomes": {"A": str(fa.NM_URNA_CANDIDATO).title(), "B": str(fb.NM_URNA_CANDIDATO).title(),
                      "partido_A": fa.SG_PARTIDO, "partido_B": fb.SG_PARTIDO,
                      "pct1t_A": float(fa.pct_validos_1t), "pct1t_B": float(fb.pct_validos_1t)},
            "outros_1t": self.outros[uf],
            "tse": {"pct_secoes": t["pct_secoes"], "parcial_A": 100 * t["A"] / n if n else None, "votos_apurados": n},
            "proj": {k: res[k] for k in ("A", "B", "A_ic90", "A_ic95", "prob_A", "validos_proj", "municipios_com_dados", "municipios_completos")},
            "base": float(100 * np.average(m.s0, weights=m.V1)),
            "historico": self.hist[uf],
            "trajetoria": trajetoria(d, obs, t["pct_secoes"], self.inicio_uf, len(self.hist[uf])) if obs is not None else {},
            "mapa_idx": ordem.idx.astype(int).tolist(),
            "mapa": {"pi": np.round(100 * x.pi.fillna(0)).astype(int).tolist(), "a": np.round(parcial).astype(int).tolist(),
                     "p": np.round(x.proj_A.fillna(-1)).astype(int).tolist()},
            "mais_A": mun(com.nlargest(8, "desvio_pp")), "mais_B": mun(com.nsmallest(8, "desvio_pp")),
            "municipios": len(d),
        }

    def rodada(self, registrar=True):
        df, tot = self.coletar() if registrar else (pd.DataFrame(), {uf: {"A": 0, "B": 0, "pct_secoes": 0.0} for uf in UFS})
        out = {"ufs": {uf: self._uf(uf, df, tot, registrar) for uf in UFS},
               "atualizado_iso": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if registrar:
            self.arq_hist.write_text(json.dumps(self.hist))
        return _limpo(out)


if __name__ == "__main__":
    if sys.argv[1:] == ["preparar"]:
        preparar()
    else:
        est = EstadoGov(sims=500)
        r = est.rodada(registrar="--coletar" in sys.argv)
        for uf, e in r["ufs"].items():
            print(uf, e["nomes"]["A"], round(e["proj"]["A"], 2), e["nomes"]["B"], e["tse"]["pct_secoes"], len(e["mapa"]["pi"]))
        print(len(json.dumps(r)))
