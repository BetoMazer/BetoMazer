"""Projeção rodando nesta sessão do Claude Code e publicada num painel do claude.ai.

O painel publicado não acessa o TSE: o Python roda aqui, grava o estado de cada
rodada num JSON, e o Claude envia esse JSON para o banco de dados do painel.
O botão e as premissas do painel são gravados no mesmo banco; o Claude os lê e
repassa ao Python pelo arquivo data/live/controle.json.

Uso:
  python -m eleicoes.nuvem exportar SAIDA_DIR   # estado inicial, pesquisas e análise (JSON)
  python -m eleicoes.nuvem demo ARQ.json        # apuração simulada para o botão "Ver simulação"
  python -m eleicoes.nuvem pagina MODELO.html SAIDA.html  # injeta os dados fixos na página
  python -m eleicoes.nuvem loop SAIDA.json [--intervalo 90]  # apuração ao vivo
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from . import pesquisas
from .config import FINALISTAS, LIVE, PROCESSED, REPORTS
from .painel import Estado, _limpo

CONTROLE = LIVE / "controle.json"


def _arred(o, nd=3):
    if isinstance(o, dict):
        return {k: _arred(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_arred(v, nd) for v in o]
    if isinstance(o, float):
        return round(o, nd)
    return o


def _agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def payload(est, status, rodada=0):
    d = est.estado()
    d.pop("nomes_terc", None)
    d["status"], d["rodada"], d["atualizado_iso"] = status, rodada, _agora()
    return _arred(_limpo(d))


def payload_pesquisas():
    r = pesquisas.resumo()
    r["atualizado_iso"] = _agora()
    return _arred(_limpo(r))


def analise():
    """Números fixos da análise histórica (TSE), embutidos na página."""
    t = REPORTS / "tabelas"
    cand = pd.read_csv(PROCESSED / "candidatos.csv")
    reg = pd.read_csv(t / "regional.csv")
    uf = pd.read_csv(t / "uf_2022_2026.csv")
    bt = pd.read_csv(t / "backtest_resumo.csv")
    terc = pd.read_csv(t / "terceiros_2026_regiao.csv")
    zonas = pd.read_csv(t / "zonas_vencedor.csv")
    transf = {a: pd.read_csv(t / f"transferencia_{a}.csv", index_col=0) for a in (2018, 2022)}
    out = {
        "candidatos": cand[cand.pct_validos >= 0.2].to_dict("records"),
        "regional": reg.drop(columns=["peso_eleitorado_pct"]).to_dict("records"),
        "peso": reg[(reg.ano == 2026)][["regiao", "peso_eleitorado_pct"]].to_dict("records"),
        "uf": uf.to_dict("records"),
        "backtest": bt.to_dict("records"),
        "terceiros_regiao": terc.to_dict("records"),
        "zonas": zonas.to_dict("records"),
        "transferencia": {a: (100 * m).round(1).reset_index().rename(columns={"index": "origem"}).to_dict("records")
                          for a, m in transf.items()},
        "finalistas": {str(k): v for k, v in FINALISTAS.items()},
    }
    return _arred(_limpo(out), 2)


def exportar(saida):
    saida.mkdir(parents=True, exist_ok=True)
    est = Estado(sims=2000)
    (saida / "estado.json").write_text(json.dumps(payload(est, "aguardando"), ensure_ascii=False))
    (saida / "pesquisas.json").write_text(json.dumps(payload_pesquisas(), ensure_ascii=False))
    (saida / "analise.json").write_text(json.dumps(analise(), ensure_ascii=False))
    print("ok", [p.name for p in saida.iterdir()])


def demo(arq, passos=36):
    est = Estado(demo=True, sims=1000)
    est.coletor = None
    snaps = []
    from .painel import ColetorDemo
    est.coletor = ColetorDemo(est.modelo, passos=passos)
    for i in range(passos + 2):
        est.rodada()
        d = payload(est, "simulacao", i + 1)
        d.pop("historico")
        d.pop("premissas", None)
        snaps.append(d)
    hist = _arred(_limpo(est.historico))
    arq.write_text(json.dumps({"snaps": snaps, "historico": hist, "real": est.coletor.real()}, ensure_ascii=False))
    print("demo", len(snaps), "rodadas; real", round(est.coletor.real(), 2))


def pagina(modelo, saida, dados_dir):
    html = modelo.read_text()
    blob = {k: json.loads((dados_dir / f"{k}.json").read_text()) for k in ("estado", "pesquisas", "analise")}
    js = json.dumps(blob, ensure_ascii=False).replace("</", "<\\/")
    saida.write_text(html.replace("/*__DADOS__*/null", js))
    print("pagina", saida, len(html) + len(js))


def _controle():
    try:
        return json.loads(CONTROLE.read_text())
    except Exception:
        return {}


def loop(saida, intervalo):
    est = Estado(intervalo=intervalo, sims=3000)
    ult_prem = None
    n = 0
    while True:
        t0 = time.time()
        c = _controle()
        prem = c.get("premissas")
        if prem and prem != ult_prem:
            try:
                est.set_premissas(prem)
                ult_prem = prem
            except Exception as exc:
                print(f"PREMISSAS_INVALIDAS {exc}", flush=True)
        if (c.get("comando") or {}).get("acao") == "parar":
            saida.write_text(json.dumps(payload(est, "parado", n), ensure_ascii=False))
            print("PARADO", flush=True)
            return
        try:
            est.rodada()
            n += 1
            status = "coletando"
        except Exception as exc:
            est.erro = f"{type(exc).__name__}: {exc}"
            status = "erro"
        p = payload(est, status, n)
        tmp = saida.with_suffix(".tmp")
        tmp.write_text(json.dumps(p, ensure_ascii=False))
        tmp.replace(saida)
        pr = p["proj"]
        print(f"RODADA {n} secoes={p['tse']['pct_secoes']:.2f}% proj_A={pr['A']:.2f} "
              f"ic90={pr['A_ic90'][0]:.2f}-{pr['A_ic90'][1]:.2f} prob_A={pr['prob_A']:.3f} "
              f"status={status} {est.erro or ''}", flush=True)
        if p["tse"]["pct_secoes"] >= 99.99:
            print("APURACAO_COMPLETA", flush=True)
        time.sleep(max(5, intervalo - (time.time() - t0)))


if __name__ == "__main__":
    from pathlib import Path
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["exportar", "demo", "pagina", "loop"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--intervalo", type=int, default=90)
    a = ap.parse_args()
    LIVE.mkdir(parents=True, exist_ok=True)
    if a.cmd == "exportar":
        exportar(Path(a.args[0]))
    elif a.cmd == "demo":
        demo(Path(a.args[0]))
    elif a.cmd == "pagina":
        pagina(Path(a.args[0]), Path(a.args[1]), Path(a.args[2]))
    else:
        loop(Path(a.args[0]), a.intervalo)
    sys.exit(0)
