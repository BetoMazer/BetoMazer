"""Pesquisas eleitorais: coleta, dispersão e comparação com o 1º turno.

Fonte: página da Wikipédia "Pesquisas de opinião para a eleição presidencial
no Brasil em 2026", que consolida as pesquisas registradas no TSE (inclusive
as registradas e ainda não divulgadas). É uma fonte editável por qualquer um:
os números devem ser conferidos no registro do TSE (PesqEle) quando usados
para algo além de referência.

Pesquisas que não estejam na Wikipédia podem ser incluídas à mão em
data/pesquisas/manuais_2t.csv (mesmas colunas de pesquisas_2t.csv, mais
"fonte"); uma linha manual com o mesmo instituto e datas de campo de uma
linha da Wikipédia a substitui.

Uso: python -m eleicoes.pesquisas     # atualiza data/pesquisas/*.csv
"""
import io
import re
from datetime import date

import numpy as np
import pandas as pd
import requests

from .config import DATA

URL = "https://pt.wikipedia.org/wiki/Pesquisas_de_opini%C3%A3o_para_a_elei%C3%A7%C3%A3o_presidencial_no_Brasil_em_2026"
DIR = DATA / "pesquisas"
ANO = 2026
DATA_1T = date(2026, 10, 4)
DATA_2T = date(2026, 10, 25)
MESES = {"jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6, "jul": 7, "ago": 8,
         "set": 9, "out": 10, "nov": 11, "dez": 12}
# resultado oficial do 1º turno (% dos válidos, TSE)
RESULTADO_1T = {"flavio": 47.03, "lula": 45.16, "cury": 2.89, "renan": 2.24, "caiado": 2.18, "zema": 0.27}
CAND_1T = {"Lula PT": "lula", "Flávio PL": "flavio", "Cury Avante": "cury", "Caiado PSD": "caiado",
           "Renan MISSÃO": "renan", "Zema NOVO": "zema"}


def baixar_html():
    r = requests.get(URL, timeout=60, headers={"User-Agent": "Mozilla/5.0 projecao-eleicoes/1.0 (pesquisa academica)"})
    r.raise_for_status()
    return r.text


def _num(x):
    """'42,6%' -> 42.6 ; '<0,9%' -> 0.45 ; '—' -> NaN."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return np.nan
    s = re.sub(r"\[.*?\]", "", str(x)).strip().replace("%", "").replace("−", "-")
    if not s or s in {"—", "-", "–"} or "divulgad" in s:
        return np.nan
    menor = s.startswith("<")
    s = s.lstrip("<>~ ").replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return np.nan
    return v / 2 if menor else v


def _datas(s):
    """'29 Set – 3 Out' / '1 – 3 Out' / '3 Out' -> (inicio, fim)."""
    s = re.sub(r"\[.*?\]", "", str(s)).lower()
    partes = re.findall(r"(\d{1,2})\s*([a-zç]{3})?", s)
    dias = [(int(d), MESES.get(m[:3]) if m else None) for d, m in partes]
    dias = [d for d in dias if d[0] <= 31]
    if not dias:
        return pd.NaT, pd.NaT
    mes_fim = next((m for _, m in reversed(dias) if m), None)
    if mes_fim is None:
        return pd.NaT, pd.NaT
    d_fim = date(ANO, mes_fim, dias[-1][0])
    m_ini = dias[0][1] or mes_fim
    d_ini = date(ANO, m_ini, dias[0][0])
    return pd.Timestamp(d_ini), pd.Timestamp(d_fim)


ALIAS = {"Vox Brasil": "Vox", "Datafolha": "DataFolha"}


def _limpar(s):
    s = re.sub(r"\[.*?\]", "", str(s)).strip()
    return ALIAS.get(s, s)


def _tabelas(html):
    ts = pd.read_html(io.StringIO(html), thousands=None, decimal="~")
    out = []
    for t in ts:
        if not isinstance(t.columns, pd.MultiIndex):
            continue
        cols = [c[1] if len(c) > 1 else c[0] for c in t.columns]
        t = t.copy()
        t.columns = cols
        out.append(t)
    return out


def _base(t):
    c0 = [c for c in t.columns if c.startswith("Contratante")][0]
    cd = [c for c in t.columns if c.lower().startswith("data")][0]
    ca = [c for c in t.columns if c.lower().startswith("tamanho")][0]
    cm = [c for c in t.columns if c.lower().startswith("margem")][0]
    t = t[t[c0].astype(str).map(_limpar) != _limpar(c0)]
    datas = t[cd].map(_datas)
    return pd.DataFrame({
        "instituto": t[c0].map(_limpar),
        "inicio": [d[0] for d in datas], "fim": [d[1] for d in datas],
        "amostra": t[ca].map(lambda x: _num(str(x).replace(" ", "").replace("\xa0", ""))),
        "margem": t[cm].map(_num),
    }, index=t.index), t


def parse(html):
    tabs = _tabelas(html)
    # 2º turno Lula x Flávio: a maior tabela com exatamente esses dois candidatos
    seg = [t for t in tabs if "Lula PT" in t.columns and "Flávio PL" in t.columns
           and any(c.startswith("Contratante") for c in t.columns) and len(t.columns) <= 9]
    seg = max(seg, key=len)
    b, t = _base(seg)
    b["lula"] = t["Lula PT"].map(_num)
    b["flavio"] = t["Flávio PL"].map(_num)
    ci = [c for c in t.columns if c.lower().startswith("indecis")]
    b["indecisos"] = t[ci[0]].map(_num) if ci else np.nan
    b["divulgada"] = b.lula.notna() & b.flavio.notna()
    b["flavio_validos"] = 100 * b.flavio / (b.flavio + b.lula)
    p2 = b.reset_index(drop=True)

    # 1º turno: tabelas com Cury e Renan (meses de setembro e outubro)
    pri = [t for t in tabs if "Cury Avante" in t.columns and "Renan MISSÃO" in t.columns
           and any(c.startswith("Contratante") for c in t.columns)]
    linhas = []
    for t in pri:
        b, t = _base(t)
        cand_cols = [c for c in t.columns if re.search(r"[A-ZÁÉÍÓÚ][a-zá-ú]+ [A-Z]", c) and c not in ("Margem de erro",)]
        for c, nome in CAND_1T.items():
            b[nome] = t[c].map(_num) if c in t.columns else np.nan
        outros = [c for c in t.columns if c not in CAND_1T and c in cand_cols] + (["Outros"] if "Outros" in t.columns else [])
        b["outros"] = t[outros].apply(lambda col: col.map(_num)).sum(axis=1, min_count=1) if outros else np.nan
        linhas.append(b)
    p1 = pd.concat(linhas).reset_index(drop=True) if linhas else pd.DataFrame()
    if len(p1):
        cand = list(CAND_1T.values())
        soma = p1[cand].sum(axis=1, min_count=4) + p1.outros.fillna(0)  # exige cenário completo
        for c in cand:
            p1[c + "_validos"] = 100 * p1[c] / soma
        p1 = p1[p1.lula.notna() & p1.flavio.notna()]
    return p2, p1


def atualizar(html=None):
    DIR.mkdir(parents=True, exist_ok=True)
    html = html or baixar_html()
    p2, p1 = parse(html)
    p2.to_csv(DIR / "pesquisas_2t.csv", index=False)
    p1.to_csv(DIR / "pesquisas_1t.csv", index=False)
    return p2, p1


def carregar():
    p2 = pd.read_csv(DIR / "pesquisas_2t.csv", parse_dates=["inicio", "fim"])
    p1 = pd.read_csv(DIR / "pesquisas_1t.csv", parse_dates=["inicio", "fim"])
    man = DIR / "manuais_2t.csv"
    if man.exists():
        m = pd.read_csv(man, parse_dates=["inicio", "fim"])
        if len(m):
            # uma linha manual substitui a da Wikipédia com o mesmo instituto e
            # datas de campo (correção); se não houver, é acrescentada
            m["divulgada"] = m.lula.notna() & m.flavio.notna()
            m["flavio_validos"] = 100 * m.flavio / (m.flavio + m.lula)
            chave = ["instituto", "inicio", "fim"]
            p2 = p2.merge(m[chave], on=chave, how="left", indicator=True)
            p2 = p2[p2._merge == "left_only"].drop(columns="_merge")
            p2 = pd.concat([p2, m.drop(columns=["fonte"], errors="ignore")], ignore_index=True)
    return p2, p1


def _stats(x):
    x = pd.Series(x).dropna()
    if not len(x):
        return {}
    return {"n": int(len(x)), "media": float(x.mean()), "mediana": float(x.median()), "dp": float(x.std(ddof=1)) if len(x) > 1 else 0.0,
            "min": float(x.min()), "max": float(x.max())}


def resumo(dias_2t=7, dias_1t=7):
    """Tudo o que a aba de pesquisas do painel mostra."""
    p2, p1 = carregar()
    ini2 = pd.Timestamp(DATA_2T) - pd.Timedelta(days=dias_2t + 2)
    sem2 = p2[p2.fim >= ini2].sort_values("fim", ascending=False)
    pub = sem2[sem2.divulgada]
    ini1 = pd.Timestamp(DATA_1T) - pd.Timedelta(days=dias_1t + 1)
    sem1 = p1[(p1.fim >= ini1) & (p1.fim < pd.Timestamp(DATA_1T))].sort_values("fim", ascending=False).copy()
    for c in RESULTADO_1T:
        sem1["erro_" + c] = sem1[c + "_validos"] - RESULTADO_1T[c]
    sem1["erro_margem"] = (sem1.flavio_validos - sem1.lula_validos) - (RESULTADO_1T["flavio"] - RESULTADO_1T["lula"])
    # viés de cada instituto no 1º turno (margem Flávio − Lula) e 2º turno ajustado
    vies = sem1.groupby(sem1.instituto.str.replace(r"\s*\(.*\)$", "", regex=True)).erro_margem.mean()
    pub = pub.copy()
    chave = pub.instituto.str.replace(r"\s*\(.*\)$", "", regex=True)
    pub["vies_1t_margem"] = chave.map(vies)
    # erro de margem m no 1º turno => desloca a fatia bipartidária em -m/2
    pub["flavio_validos_ajustado"] = pub.flavio_validos - pub.vies_1t_margem / 2
    ultima = pub.sort_values("fim").groupby(chave).tail(1)

    def rec(df, cols):
        d = df[cols].copy()
        for c in d.columns:
            if pd.api.types.is_datetime64_any_dtype(d[c]):
                d[c] = d[c].dt.strftime("%d/%m")
        d = d.astype(object).where(d.notna(), None)
        return d.to_dict("records")

    return {
        "segundo_turno": {
            "janela": f"{ini2:%d/%m} a {DATA_2T:%d/%m}",
            "divulgadas": rec(pub, ["instituto", "inicio", "fim", "amostra", "margem", "flavio", "lula", "indecisos",
                                    "flavio_validos", "vies_1t_margem", "flavio_validos_ajustado"]),
            "pendentes": rec(sem2[~sem2.divulgada], ["instituto", "inicio", "fim", "amostra", "margem"]),
            "stats": _stats(pub.flavio_validos),
            "stats_ultima_por_instituto": _stats(ultima.flavio_validos),
            "stats_ajustado": _stats(ultima.flavio_validos_ajustado),
        },
        "primeiro_turno": {
            "janela": f"{ini1:%d/%m} a {pd.Timestamp(DATA_1T) - pd.Timedelta(days=1):%d/%m}",
            "resultado": RESULTADO_1T,
            "pesquisas": rec(sem1, ["instituto", "inicio", "fim", "amostra", "margem"] +
                             [c + "_validos" for c in RESULTADO_1T] + ["erro_flavio", "erro_lula", "erro_margem"]),
            "erro_medio": {c: float(sem1["erro_" + c].mean()) for c in RESULTADO_1T},
            "erro_abs_medio": {c: float(sem1["erro_" + c].abs().mean()) for c in RESULTADO_1T},
            "erro_margem_medio": float(sem1.erro_margem.mean()),
            "por_instituto": [{"instituto": k, "erro_margem": float(v)} for k, v in vies.sort_values().items()],
        },
    }


if __name__ == "__main__":
    p2, p1 = atualizar()
    print(f"2º turno: {len(p2)} pesquisas ({p2.divulgada.sum()} divulgadas); 1º turno: {len(p1)}")
    r = resumo()
    print(r["segundo_turno"]["stats"], r["segundo_turno"]["stats_ajustado"])
    print(r["primeiro_turno"]["erro_medio"], r["primeiro_turno"]["erro_margem_medio"])
