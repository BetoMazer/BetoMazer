"""Painel web ao vivo: apuração + projeção + premissas + pesquisas.

Roda um servidor local (só biblioteca padrão) que:
  * coleta o feed do TSE a cada --intervalo segundos e roda a projeção;
  * deixa editar no navegador a divisão dos votos dos terceiros (e o ponto
    de partida antes da apuração) — a projeção é refeita na hora;
  * atualiza as pesquisas da Wikipédia a cada 30 min.

Uso:
  python -m eleicoes.painel                 # domingo: abra http://localhost:8050
  python -m eleicoes.painel --demo          # ensaio com apuração simulada
"""
import argparse
import json
import math
import threading
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import pandas as pd

from . import pesquisas
from .config import ELEICAO_T2_2026, FINALISTAS, LIVE, PRIOR_TRANSFERENCIA
from .live import BRT, ColetorTSE, projecao_zonas
from .model import Modelo, expit, logit

ANO = 2026
WEB = Path(__file__).resolve().parent / "web"
TERC = ["cury", "renan", "caiado", "zema", "outros"]
NOMES_TERC = {"cury": "Augusto Cury", "renan": "Renan Santos", "caiado": "Ronaldo Caiado",
              "zema": "Romeu Zema", "outros": "Demais (UP, PSTU, PCB, PCO, DC, Democrata)"}


def _limpo(o):
    """JSON sem NaN/inf (o navegador não aceita) e com tipos numpy convertidos."""
    if isinstance(o, dict):
        return {k: _limpo(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_limpo(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


class ColetorDemo:
    """Apuração sintética para ensaiar o painel: um "2º turno verdadeiro" é
    sorteado a partir do 1º turno (com transferências diferentes do prior e
    efeitos por UF) e revelado aos poucos, Sul/Sudeste primeiro e Nordeste
    por último, como em 2022."""

    def __init__(self, modelo, passos=45, seed=7):
        rng = np.random.default_rng(seed)
        verdade = {"cury": 0.42, "renan": 0.58, "caiado": 0.66, "zema": 0.8, "outros": 0.3}
        m = Modelo(ANO, prior=verdade)
        uf_ef = {u: rng.normal(0, 0.05) for u in np.unique(m.uf)}
        share = expit(logit(m.s0) + np.array([uf_ef[u] for u in m.uf]) + rng.normal(0, 0.06, len(m.s0)))
        votos = m.V1 * np.exp(rng.normal(-0.01, 0.03, len(m.V1)))
        self.idx, self.uf, self.regiao = m.idx, m.uf, m.regiao
        self.A, self.B = votos * share, votos * (1 - share)
        off = {"Sul": 0.0, "Centro-Oeste": 0.05, "Sudeste": 0.12, "Norte": 0.2, "Nordeste": 0.3, "Exterior": 0.4}
        self.ini = np.array([off.get(r, 0.2) for r in self.regiao]) + rng.uniform(0, 0.35, len(votos))
        self.dur = 0.05 + 0.1 * np.log10(votos + 10) / 6 + rng.uniform(0, 0.15, len(votos))
        self.passos, self.t = passos, 0
        self.ruido = rng.normal(0, 0.04, len(votos))
        self.municipios = list(self.idx)

    def coletar(self):
        self.t += 1
        tt = min(self.t / self.passos, 1.0) * 1.1
        pi = np.clip((tt - self.ini) / self.dur, 0, 1)
        # parte apurada de um município grande não é amostra perfeita
        sA = expit(logit(self.A / (self.A + self.B)) + self.ruido * (1 - pi))
        n = (self.A + self.B) * pi
        df = pd.DataFrame({"A": np.round(n * sA), "B": np.round(n * (1 - sA)), "pi": pi}, index=self.idx)
        self._ult = df
        return df[df.pi > 0]

    def nacional(self):
        d = self._ult
        return {"A": d.A.sum(), "B": d.B.sum(), "pct_secoes": 100 * float(np.average(d.pi, weights=self.A + self.B))}

    def real(self):
        return 100 * self.A.sum() / (self.A.sum() + self.B.sum())


_ORDEM_MAPA = None


def mapa_payload(d):
    """Arrays alinhados à ordem de eleicoes/web/mapa.json: % apurado, parcial
    de A (-1 sem votos) e projeção de A, inteiros, para o mapa municipal."""
    global _ORDEM_MAPA
    if _ORDEM_MAPA is None:
        arq = Path(__file__).resolve().parent.parent / "data/processed/mapa_municipios.csv"
        _ORDEM_MAPA = pd.read_csv(arq).set_index(["uf", "cd_mun"]).index
    x = d.set_index(["uf", "cd_mun"]).reindex(_ORDEM_MAPA)
    parcial = np.where(x.V_obs > 0, 100 * x.A_obs / x.V_obs.where(x.V_obs > 0, 1), -1)
    return {"pi": np.round(100 * x.pi.fillna(0)).astype(int).tolist(),
            "a": np.round(parcial).astype(int).tolist(),
            "p": np.round(x.proj_A.fillna(-1)).astype(int).tolist()}


def trajetoria(d, snapshot, pct_secoes, inicio_uf=None, agora=0.0, pontos=41):
    """Trajetória esperada da parcial do TSE daqui até 100% das seções.

    O que falta apurar em cada município vem da projeção do modelo; a ordem
    de chegada vem do ritmo de cada UF: a UF que apurou a fração a desde que
    começou (há T rodadas) precisa de mais (1 - a) / a * T no mesmo ritmo, e
    seus votos restantes chegam uniformemente nesse intervalo. Quando cada
    UF pendente (sem nenhuma urna) vai começar é desconhecido, então há três
    cenários: começam já, no meio, ou depois que a iniciada mais lenta
    termina. Retorna a curva central e a faixa entre os cenários, num grid
    de % de seções."""
    if snapshot is None or not len(snapshot) or not pct_secoes:
        return {}
    obs = snapshot[["A", "B"]].astype(float)
    dd = d.set_index(["uf", "cd_mun"]).join(obs, how="left").fillna({"A": 0.0, "B": 0.0})
    dd["V"] = dd.A + dd.B
    dd["R"] = (dd.validos_proj - dd.V).clip(lower=0)
    dd["RA"] = (dd.A_proj_votos - dd.A).clip(lower=0).clip(upper=dd.R)
    dd["V1pi"] = dd.V1 * dd.pi
    g = dd.groupby(level="uf")[["R", "RA", "V1pi", "V1"]].sum()
    a = (g.V1pi / g.V1).clip(0, 1)
    iniciou = a > 0.005
    A0, V0, Rt = dd.A.sum(), dd.V.sum(), g.R.sum()
    if not iniciou.any() or Rt <= 0:
        return {}
    inicio_uf = inicio_uf or {}
    T = pd.Series({u: max(agora - inicio_uf.get(u, 0.0), 0.0) + 1.0 for u in g.index})
    D = ((1 - a) / a.where(iniciou) * T).clip(lower=1e-3, upper=200.0)
    dmax = float(D.max())
    dmed = float(D.median())
    grid = np.linspace(pct_secoes, 100, pontos)
    curvas = []
    for atraso in (0.0, 0.5 * dmax, dmax):
        ini = pd.Series(0.0, index=g.index).where(iniciou, atraso)
        fim = D.where(iniciou, atraso + max(dmed, 1.0))
        xs, ys = [], []
        for tau in np.linspace(0, float(fim.max()), 200):
            f = ((tau - ini) / (fim - ini)).clip(0, 1)
            chegou = float((g.R * f).sum())
            xs.append(pct_secoes + (100 - pct_secoes) * chegou / Rt)
            ys.append(100 * (A0 + float((g.RA * f).sum())) / (V0 + chegou))
        curvas.append(np.interp(grid, xs, ys))
    c = np.vstack(curvas)
    return {"x": grid.round(2).tolist(), "centro": c[1].round(3).tolist(),
            "lo": c.min(axis=0).round(3).tolist(), "hi": c.max(axis=0).round(3).tolist(),
            "ufs_pendentes": [u for u in g.index if not iniciou[u]]}


class Estado:
    def __init__(self, demo=False, intervalo=60, sims=3000, eleicao=ELEICAO_T2_2026):
        self.lock = threading.Lock()
        self.demo, self.intervalo, self.sims, self.eleicao = demo, intervalo, sims, eleicao
        LIVE.mkdir(parents=True, exist_ok=True)
        self.arq_premissas = LIVE / "premissas.json"
        self.premissas = {"transf": {k: 100 * v for k, v in PRIOR_TRANSFERENCIA[ANO].items()}, "prior_A": None}
        if self.arq_premissas.exists() and not demo:
            try:
                self.premissas.update(json.loads(self.arq_premissas.read_text()))
            except Exception:
                pass
        self._modelo()
        self.coletor = None
        self.snapshot, self.tse, self.res = None, None, None
        self.historico, self.erro, self.atualizado = [], None, None
        self.arq_hist = LIVE / f"painel_historico_{eleicao}.csv"
        if not demo and self.arq_hist.exists():
            # painel reiniciado no meio da apuração: recupera a curva
            try:
                self.historico = pd.read_csv(self.arq_hist).to_dict("records")
            except Exception:
                pass
        self.pesq, self.pesq_erro, self.pesq_atualizado = None, None, None
        self.inicio_uf = {}  # rodada em que cada UF teve as primeiras urnas

    # -------------------------------------------------------------- modelo
    def _modelo(self):
        t = {k: float(v) / 100 for k, v in self.premissas["transf"].items()}
        pa = self.premissas.get("prior_A")
        self.modelo = Modelo(ANO, prior=t, alvo_prior=None if pa in (None, "") else float(pa) / 100)
        self.base_nacional = 100 * float(np.average(self.modelo.s0, weights=self.modelo.V1))

    def set_premissas(self, p):
        with self.lock:
            tr = {k: min(max(float(p["transf"][k]), 0), 100) for k in TERC}
            pa = p.get("prior_A")
            self.premissas = {"transf": tr, "prior_A": None if pa in (None, "") else min(max(float(pa), 30), 70)}
            if not self.demo:
                self.arq_premissas.write_text(json.dumps(self.premissas))
            self._modelo()
            if self.snapshot is not None:
                self._projetar(registrar=False)

    # ------------------------------------------------------------ apuração
    def _projetar(self, registrar=True):
        obs = self.snapshot[["A", "B", "pi"]] if self.snapshot is not None and len(self.snapshot) else None
        self.res = self.modelo.projetar(obs, n_sim=self.sims, detalhe=True)
        if registrar and self.tse is not None:
            tot = self.tse["A"] + self.tse["B"]
            self.historico.append({
                "hora": datetime.now(BRT).strftime("%H:%M:%S"), "pct_secoes": self.tse["pct_secoes"],
                "parcial_A": 100 * self.tse["A"] / tot if tot else None, "proj_A": self.res["A"],
                "lo": self.res["A_ic90"][0], "hi": self.res["A_ic90"][1], "prob_A": self.res["prob_A"]})

    def rodada(self):
        if self.coletor is None:
            self.coletor = ColetorDemo(self.modelo) if self.demo else ColetorTSE(self.eleicao)
        df = self.coletor.coletar()
        tse = self.coletor.nacional()
        with self.lock:
            self.snapshot, self.tse = df, tse
            if len(df):
                ufs = df[df.pi > 0].index.get_level_values("uf").unique()
                for u in ufs:
                    self.inicio_uf.setdefault(u, float(len(self.historico)))
            self._projetar()
            self.atualizado = datetime.now(BRT).strftime("%d/%m %H:%M:%S")
            self.erro = None
            res = self.res
        if not self.demo:
            pd.DataFrame([self.historico[-1]]).to_csv(self.arq_hist, mode="a", header=not self.arq_hist.exists(), index=False)
            res["municipios"].to_csv(LIVE / f"projecao_municipios_{self.eleicao}.csv")
            df.to_csv(LIVE / f"apuracao_municipios_{self.eleicao}.csv")
            try:
                projecao_zonas(res).to_csv(LIVE / f"projecao_zonas_{self.eleicao}.csv", index=False)
            except Exception:
                pass

    def loop(self):
        while True:
            t0 = time.time()
            try:
                self.rodada()
            except Exception as exc:
                self.erro = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            time.sleep(max(2, self.intervalo - (time.time() - t0)))

    def loop_pesquisas(self, a_cada=1800):
        while True:
            try:
                pesquisas.atualizar()
                self.pesq_erro = None
                self.pesq_atualizado = datetime.now(BRT).strftime("%d/%m %H:%M")
            except Exception as exc:
                self.pesq_erro = f"não foi possível atualizar da Wikipédia ({type(exc).__name__}); usando a última versão salva"
            try:
                self.pesq = pesquisas.resumo()
            except Exception as exc:
                self.pesq_erro = f"erro ao ler pesquisas: {exc}"
            time.sleep(a_cada)

    # ------------------------------------------------------------- saídas
    def estado(self):
        with self.lock:
            m, res = self.modelo, self.res
            if res is None:
                res = m.projetar(None, n_sim=1000, detalhe=True)
            d = res["municipios"].copy()
            d["V1"] = m.V1
            d = d.reset_index()
            d["base_votos"] = d.validos_proj * d.base_1t_A / 100
            obs = (self.snapshot[["A", "B"]].astype(float) if self.snapshot is not None and len(self.snapshot)
                   else pd.DataFrame({"A": [], "B": []}, dtype=float,
                                     index=pd.MultiIndex.from_tuples([], names=["uf", "cd_mun"])))
            d = d.merge(obs.rename(columns={"A": "A_obs", "B": "B_obs"}), left_on=["uf", "cd_mun"], right_index=True, how="left")
            d[["A_obs", "B_obs"]] = d[["A_obs", "B_obs"]].fillna(0.0)
            d["V_obs"] = d.A_obs + d.B_obs

            def agrega(chave):
                g = d.groupby(chave).apply(lambda x: pd.Series({
                    "proj_A": 100 * x.A_proj_votos.sum() / x.validos_proj.sum(),
                    "base_A": 100 * x.base_votos.sum() / x.validos_proj.sum(),
                    "apurado": 100 * (x.V1 * x.pi).sum() / x.V1.sum(),
                    "restante": max(x.validos_proj.sum() - x.V_obs.sum(), 0.0),
                    "peso": x.validos_proj.sum()}), include_groups=False)
                g["peso"] = 100 * g.peso / g.peso.sum()
                g["desvio_pp"] = g.proj_A - g.base_A
                return [{"nome": k, **v} for k, v in g.round(3).to_dict("index").items()]

            com = d[d.pi > 0].copy()
            com["desvio_pp"] = com.proj_A - com.base_1t_A
            com = com[com.V1 > 5000]
            nomes = {}
            try:
                pm = pd.read_parquet(Path(__file__).resolve().parent.parent / "data/processed/municipio.parquet",
                                     columns=["uf", "cd_mun", "nm_mun"]).set_index(["uf", "cd_mun"]).nm_mun
                nomes = pm.to_dict()
            except Exception:
                pass

            def mun(x):
                return [{"municipio": f"{nomes.get((r.uf, r.cd_mun), r.cd_mun)} ({r.uf})", "apurado": 100 * r.pi, "base_A": r.base_1t_A,
                         "proj_A": r.proj_A, "desvio_pp": r.desvio_pp} for _, r in x.iterrows()]

            tse = self.tse or {"A": 0, "B": 0, "pct_secoes": 0.0}
            tot = tse["A"] + tse["B"]
            out = {
                "modo": "demo" if self.demo else "ao_vivo",
                "atualizado": self.atualizado, "erro": self.erro, "intervalo": self.intervalo,
                "nomes": {"A": FINALISTAS[ANO]["nome_A"], "B": FINALISTAS[ANO]["nome_B"]},
                "tse": {"pct_secoes": tse["pct_secoes"], "parcial_A": 100 * tse["A"] / tot if tot else None,
                        "votos_apurados": tot},
                "proj": {k: res[k] for k in ("A", "B", "A_ic90", "A_ic95", "prob_A", "validos_proj",
                                             "cobertura_eleitorado", "municipios_com_dados", "municipios_completos",
                                             "swing_medio")},
                "base_nacional": self.base_nacional,
                "historico": self.historico[-500:],
                "regioes": agrega("regiao"), "ufs": agrega("uf"),
                "mapa": mapa_payload(d),
                "trajetoria": trajetoria(d, self.snapshot, tse["pct_secoes"], self.inicio_uf, len(self.historico)),
                "mais_A": mun(com.nlargest(10, "desvio_pp")), "mais_B": mun(com.nsmallest(10, "desvio_pp")),
                "premissas": self.premissas, "nomes_terc": NOMES_TERC,
                "real_demo": self.coletor.real() if self.demo and self.coletor else None,
            }
        return _limpo(out)


def servidor(estado, porta):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            b = json.dumps(_limpo(obj), ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                b = (WEB / "painel.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b)
            elif self.path.startswith("/api/estado"):
                self._json(estado.estado())
            elif self.path.startswith("/api/pesquisas"):
                self._json({"dados": estado.pesq, "erro": estado.pesq_erro, "atualizado": estado.pesq_atualizado})
            else:
                self.send_error(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            corpo = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/premissas":
                try:
                    estado.set_premissas(corpo)
                    self._json({"ok": True})
                except Exception as exc:
                    self._json({"ok": False, "erro": str(exc)}, 400)
            else:
                self.send_error(404)

    httpd = ThreadingHTTPServer(("127.0.0.1", porta), H)
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=8050)
    ap.add_argument("--intervalo", type=int, default=None, help="segundos entre coletas (padrão 60; 4 no demo)")
    ap.add_argument("--sims", type=int, default=3000)
    ap.add_argument("--demo", action="store_true", help="ensaio com apuração simulada")
    ap.add_argument("--eleicao", default=ELEICAO_T2_2026)
    a = ap.parse_args()
    intervalo = a.intervalo or (4 if a.demo else 60)
    est = Estado(demo=a.demo, intervalo=intervalo, sims=a.sims, eleicao=a.eleicao)
    threading.Thread(target=est.loop, daemon=True).start()
    threading.Thread(target=est.loop_pesquisas, daemon=True).start()
    httpd = servidor(est, a.porta)
    print(f"Painel em http://localhost:{a.porta}  ({'DEMO' if a.demo else 'eleição ' + a.eleicao}; coleta a cada {intervalo}s)")
    print("Ctrl+C para encerrar.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
