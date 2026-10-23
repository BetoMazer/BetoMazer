"""Transforma os CSVs do TSE em tabelas por zona eleitoral, município e seção.

Saídas em data/processed/:
  munzona_resumo.parquet  aptos, comparecimento, abstenção, brancos, nulos e válidos
                          por (ano, turno, UF, município, zona)
  munzona_votos.parquet   votos por candidato em formato longo
  candidatos.csv          resultado nacional por candidato
  munzona_{ano}_t{t}.csv  tabela larga (uma coluna por candidato), para Excel
  municipio.parquet       painel por município usado pelo modelo
  secao_{ano}.parquet     votos por seção (apenas para backtest)

Uso: python -m eleicoes.process [--secao]
"""
import argparse

import numpy as np
import pandas as pd

from .config import ANOS, FINALISTAS, PROCESSED, RAW, REGIAO, TERCEIROS

CHAVE = ["ano", "turno", "uf", "cd_mun", "zona"]


def _ler(path, cols):
    return pd.read_csv(path, sep=";", encoding="latin1", usecols=cols, dtype=str)


def ler_votos(ano):
    df = _ler(RAW / f"votacao_candidato_munzona_{ano}_BR.csv",
              ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA", "NR_CANDIDATO",
               "NM_URNA_CANDIDATO", "SG_PARTIDO", "QT_VOTOS_NOMINAIS_VALIDOS"])
    df = pd.DataFrame({
        "ano": ano,
        "turno": df.NR_TURNO.astype(int),
        "uf": df.SG_UF,
        "cd_mun": df.CD_MUNICIPIO.astype(int),
        "nm_mun": df.NM_MUNICIPIO,
        "zona": df.NR_ZONA.astype(int),
        "nr": df.NR_CANDIDATO.astype(int),
        "nome": df.NM_URNA_CANDIDATO,
        "partido": df.SG_PARTIDO,
        "votos": df.QT_VOTOS_NOMINAIS_VALIDOS.astype(int),
    })
    return df


def ler_detalhe(ano):
    num = ["QT_APTOS", "QT_COMPARECIMENTO", "QT_ABSTENCOES", "QT_VOTOS_BRANCOS",
           "QT_TOTAL_VOTOS_NULOS", "QT_TOTAL_VOTOS_VALIDOS", "QT_TOTAL_VOTOS_ANULADOS"]
    df = _ler(RAW / f"detalhe_votacao_munzona_{ano}_BR.csv",
              ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NM_MUNICIPIO", "NR_ZONA"] + num)
    out = pd.DataFrame({
        "ano": ano,
        "turno": df.NR_TURNO.astype(int),
        "uf": df.SG_UF,
        "cd_mun": df.CD_MUNICIPIO.astype(int),
        "nm_mun": df.NM_MUNICIPIO,
        "zona": df.NR_ZONA.astype(int),
    })
    nomes = ["aptos", "comparecimento", "abstencoes", "brancos", "nulos", "validos", "anulados"]
    for c, n in zip(num, nomes):
        out[n] = df[c].astype(int)
    out["nulos"] += out.pop("anulados")
    # linhas separadas para voto em trânsito são somadas na zona
    return out.groupby(CHAVE + ["nm_mun"], as_index=False).sum(numeric_only=True)


def processar_munzona():
    PROCESSED.mkdir(parents=True, exist_ok=True)
    resumos, votos = [], []
    for ano in ANOS:
        resumos.append(ler_detalhe(ano))
        votos.append(ler_votos(ano))
    resumo = pd.concat(resumos, ignore_index=True)
    resumo["regiao"] = resumo.uf.map(REGIAO)
    v = pd.concat(votos, ignore_index=True)
    cand = (v.groupby(["ano", "turno", "nr", "nome", "partido"], as_index=False).votos.sum()
            .sort_values(["ano", "turno", "votos"], ascending=[True, True, False]))
    cand["pct_validos"] = 100 * cand.votos / cand.groupby(["ano", "turno"]).votos.transform("sum")
    cand.to_csv(PROCESSED / "candidatos.csv", index=False)
    vz = v.groupby(CHAVE + ["nr"], as_index=False).votos.sum()

    # checagem: soma dos votos nominais = válidos do arquivo de detalhe
    chk = vz.groupby(CHAVE).votos.sum().rename("soma").to_frame().join(resumo.set_index(CHAVE).validos)
    dif = (chk.soma - chk.validos).abs().sum()
    print(f"diferença total votos nominais x válidos: {dif}")

    resumo.to_parquet(PROCESSED / "munzona_resumo.parquet", index=False)
    vz.to_parquet(PROCESSED / "munzona_votos.parquet", index=False)

    nomes = cand.drop_duplicates(["ano", "nr"]).set_index(["ano", "nr"]).nome
    for (ano, turno), g in vz.groupby(["ano", "turno"]):
        w = g.pivot_table(index=CHAVE, columns="nr", values="votos", fill_value=0)
        w.columns = [f"{nomes[(ano, c)]} ({c})" for c in w.columns]
        r = resumo[(resumo.ano == ano) & (resumo.turno == turno)].set_index(CHAVE)
        out = r.join(w).reset_index()
        out.to_csv(PROCESSED / f"munzona_{ano}_t{turno}.csv", index=False)
    return resumo, vz


def painel_municipio(resumo, vz):
    """Uma linha por município, colunas por eleição: base de features do modelo."""
    mun = resumo.groupby(["ano", "turno", "uf", "cd_mun"], as_index=False).agg(
        nm_mun=("nm_mun", "first"), regiao=("regiao", "first"), n_zonas=("zona", "nunique"),
        aptos=("aptos", "sum"), comparecimento=("comparecimento", "sum"),
        brancos=("brancos", "sum"), nulos=("nulos", "sum"), validos=("validos", "sum"))
    vm = vz.groupby(["ano", "turno", "uf", "cd_mun", "nr"]).votos.sum().unstack("nr", fill_value=0)
    partes = []
    for ano in ANOS:
        fin = FINALISTAS[ano]
        terc = TERCEIROS[ano]
        for turno in (1, 2):
            m = mun[(mun.ano == ano) & (mun.turno == turno)].set_index(["uf", "cd_mun"])
            if m.empty:
                continue
            vv = vm.loc[(ano, turno)]
            p = f"{ano}t{turno}_"
            d = pd.DataFrame(index=m.index)
            for c in ["aptos", "comparecimento", "brancos", "nulos", "validos"]:
                d[p + c] = m[c]
            d[p + "A"] = vv.get(fin["A"], 0)
            d[p + "B"] = vv.get(fin["B"], 0)
            if turno == 1:
                usados = {fin["A"], fin["B"]}
                for nr, nome in terc.items():
                    d[p + nome] = vv.get(nr, 0)
                    usados.add(nr)
                outros = [c for c in vv.columns if c not in usados]
                d[p + "outros"] = vv[outros].sum(axis=1)
            partes.append(d)
    painel = pd.concat(partes, axis=1)
    meta = (mun.sort_values("ano").groupby(["uf", "cd_mun"])[["nm_mun", "regiao", "n_zonas"]].last())
    painel = meta.join(painel).reset_index()
    painel.to_parquet(PROCESSED / "municipio.parquet", index=False)
    print(f"painel municipal: {len(painel)} municípios")
    return painel


def processar_secao(ano):
    """Votos por seção nos dois turnos (para o backtest com apuração parcial)."""
    fin, terc = FINALISTAS[ano], TERCEIROS[ano]
    cols = ["NR_TURNO", "SG_UF", "CD_MUNICIPIO", "NR_ZONA", "NR_SECAO", "NR_VOTAVEL", "QT_VOTOS"]
    partes = []
    for ch in pd.read_csv(RAW / f"votacao_secao_{ano}_BR.csv", sep=";", encoding="latin1",
                          usecols=cols, dtype=str, chunksize=4_000_000):
        nr = ch.NR_VOTAVEL.astype(int)
        cat = np.where(nr == fin["A"], "A", np.where(nr == fin["B"], "B",
                       np.where(nr == 95, "brancos", np.where(nr >= 96, "nulos", "outros"))))
        cat = pd.Series(cat, index=ch.index)
        for n, nome in terc.items():
            cat[nr == n] = nome
        g = pd.DataFrame({
            "turno": ch.NR_TURNO.astype(np.int8), "uf": ch.SG_UF, "cd_mun": ch.CD_MUNICIPIO.astype(int),
            "zona": ch.NR_ZONA.astype(np.int16), "secao": ch.NR_SECAO.astype(np.int16),
            "cat": cat, "votos": ch.QT_VOTOS.astype(np.int32)})
        partes.append(g.groupby(["turno", "uf", "cd_mun", "zona", "secao", "cat"]).votos.sum())
    s = pd.concat(partes).groupby(level=[0, 1, 2, 3, 4, 5]).sum().unstack("cat", fill_value=0).reset_index()
    s.columns.name = None
    s.to_parquet(PROCESSED / f"secao_{ano}.parquet", index=False)
    print(f"seções {ano}: {len(s)} linhas")
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--secao", action="store_true")
    a = ap.parse_args()
    resumo, vz = processar_munzona()
    painel_municipio(resumo, vz)
    if a.secao:
        for ano in (2018, 2022, 2026):
            processar_secao(ano)
