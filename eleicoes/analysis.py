"""Análise descritiva das eleições presidenciais 2018, 2022 e 1º turno de 2026.

Gera reports/tabelas/*.csv e imprime os números usados em reports/analise.md.
Uso: python -m eleicoes.analysis
"""
import numpy as np
import pandas as pd
from scipy.optimize import nnls

from .config import FINALISTAS, PROCESSED, REPORTS, TERCEIROS

TAB = REPORTS / "tabelas"


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def carregar():
    resumo = pd.read_parquet(PROCESSED / "munzona_resumo.parquet")
    votos = pd.read_parquet(PROCESSED / "munzona_votos.parquet")
    mun = pd.read_parquet(PROCESSED / "municipio.parquet")
    return resumo, votos, mun


def tabela_regional(resumo, votos):
    """Comparecimento, abstenção, brancos, nulos e votos dos finalistas por região."""
    linhas = []
    for (ano, turno), r in resumo.groupby(["ano", "turno"]):
        fin = FINALISTAS[ano]
        v = votos[(votos.ano == ano) & (votos.turno == turno)]
        va = v[v.nr == fin["A"]].groupby(["uf", "cd_mun", "zona"]).votos.sum()
        vb = v[v.nr == fin["B"]].groupby(["uf", "cd_mun", "zona"]).votos.sum()
        r = r.set_index(["uf", "cd_mun", "zona"]).assign(A=va, B=vb).fillna({"A": 0, "B": 0})
        for reg, g in list(r.groupby("regiao")) + [("Brasil", r)]:
            s = g[["aptos", "comparecimento", "abstencoes", "brancos", "nulos", "validos", "A", "B"]].sum()
            linhas.append({
                "ano": ano, "turno": turno, "regiao": reg, "aptos": int(s.aptos),
                "comparecimento_pct": 100 * s.comparecimento / s.aptos,
                "abstencao_pct": 100 * s.abstencoes / s.aptos,
                "brancos_pct": 100 * s.brancos / s.comparecimento,
                "nulos_pct": 100 * s.nulos / s.comparecimento,
                "A": fin["nome_A"], "A_pct_validos": 100 * s.A / s.validos,
                "B": fin["nome_B"], "B_pct_validos": 100 * s.B / s.validos,
                "peso_eleitorado_pct": np.nan,
            })
    t = pd.DataFrame(linhas)
    tot = t[t.regiao == "Brasil"].set_index(["ano", "turno"]).aptos
    t["peso_eleitorado_pct"] = 100 * t.aptos / t.set_index(["ano", "turno"]).index.map(tot)
    return t


def transferencia(mun, ano):
    """Regressão ecológica (NNLS) por município: destino no 2º turno de cada
    categoria do 1º turno. Retorna matriz origem x destino (fração dos eleitores)."""
    t1, t2 = f"{ano}t1_", f"{ano}t2_"
    origens = ["A", "B"] + list(TERCEIROS[ano].values()) + ["outros", "brancos", "nulos", "abst"]
    m = mun.dropna(subset=[t1 + "aptos", t2 + "aptos"])
    m = m[(m[t1 + "aptos"] > 0) & (m[t2 + "aptos"] > 0)].fillna(0).copy()
    m[t1 + "abst"] = m[t1 + "aptos"] - m[t1 + "comparecimento"]
    m[t2 + "abst"] = m[t2 + "aptos"] - m[t2 + "comparecimento"]
    m[t2 + "bn"] = m[t2 + "brancos"] + m[t2 + "nulos"]
    # normaliza pelo eleitorado do 2º turno para tornar as unidades comparáveis
    X = m[[t1 + o for o in origens]].to_numpy(float) / m[[t1 + "aptos"]].to_numpy(float)
    res = {}
    for dest in ["A", "B", "bn", "abst"]:
        y = m[t2 + dest].to_numpy(float) / m[t2 + "aptos"].to_numpy(float)
        w = np.sqrt(m[t2 + "aptos"].to_numpy(float))
        coef, _ = nnls(X * w[:, None], y * w)
        res[dest] = coef
    M = pd.DataFrame(res, index=origens)
    M = M.div(M.sum(axis=1), axis=0)  # cada origem distribui 100% dos seus eleitores
    return M


def swing_uf(mun, ano):
    """Variação, por UF, da fatia de A entre 1º e 2º turno (votos A/(A+B))."""
    t1, t2 = f"{ano}t1_", f"{ano}t2_"
    g = mun.groupby("uf")[[t1 + "A", t1 + "B", t1 + "validos", t2 + "A", t2 + "B"]].sum()
    s1 = g[t1 + "A"] / (g[t1 + "A"] + g[t1 + "B"])
    s2 = g[t2 + "A"] / (g[t2 + "A"] + g[t2 + "B"])
    terc = 1 - (g[t1 + "A"] + g[t1 + "B"]) / g[t1 + "validos"]
    return pd.DataFrame({"A_2t_pct": 100 * s2, "A_1t_2partidos_pct": 100 * s1,
                         "terceiros_1t_pct": 100 * terc, "swing_logit": _logit(s2) - _logit(s1)})


def main():
    TAB.mkdir(parents=True, exist_ok=True)
    resumo, votos, mun = carregar()
    pd.set_option("display.width", 200, "display.max_columns", 30)

    reg = tabela_regional(resumo, votos)
    reg.to_csv(TAB / "regional.csv", index=False)
    print(reg.drop(columns=["A", "B"]).round(2).to_string(index=False))

    for ano in (2018, 2022):
        M = transferencia(mun, ano)
        M.to_csv(TAB / f"transferencia_{ano}.csv")
        print(f"\nTransferência 1º→2º turno {ano} (linhas = voto no 1º turno):")
        print((100 * M).round(1).to_string())
        su = swing_uf(mun, ano)
        su.to_csv(TAB / f"swing_uf_{ano}.csv")
        print(f"swing logit UF {ano}: média {su.swing_logit.mean():.3f}, dp {su.swing_logit.std():.3f}")

    # zonas: quem venceu em cada zona e distribuição
    z = votos.merge(resumo[["ano", "turno", "uf", "cd_mun", "zona", "validos", "regiao"]],
                    on=["ano", "turno", "uf", "cd_mun", "zona"])
    linhas = []
    for (ano, turno), g in z.groupby(["ano", "turno"]):
        fin = FINALISTAS[ano]
        w = g.pivot_table(index=["uf", "cd_mun", "zona", "regiao"], columns="nr", values="votos", fill_value=0)
        a, b = w[fin["A"]], w[fin["B"]]
        linhas.append({"ano": ano, "turno": turno, "zonas": len(w),
                       "zonas_A_vence": int((a > b).sum()), "zonas_B_vence": int((b > a).sum()),
                       "zonas_A_>60%": int((a / w.sum(axis=1) > .6).sum()),
                       "zonas_B_>60%": int((b / w.sum(axis=1) > .6).sum())})
    zt = pd.DataFrame(linhas)
    zt.to_csv(TAB / "zonas_vencedor.csv", index=False)
    print("\n", zt.to_string(index=False))

    # 2026 vs 2022: deslocamento por UF no 1º turno
    g = mun.groupby(["regiao", "uf"])[["2022t1_A", "2022t1_B", "2022t1_validos", "2022t2_A", "2022t2_B",
                                        "2026t1_A", "2026t1_B", "2026t1_validos"]].sum()
    comp = pd.DataFrame({
        "bolsonaro_2022t1": 100 * g["2022t1_A"] / g["2022t1_validos"],
        "flavio_2026t1": 100 * g["2026t1_A"] / g["2026t1_validos"],
        "lula_2022t1": 100 * g["2022t1_B"] / g["2022t1_validos"],
        "lula_2026t1": 100 * g["2026t1_B"] / g["2026t1_validos"],
        "bolsonaro_2022t2": 100 * g["2022t2_A"] / (g["2022t2_A"] + g["2022t2_B"]),
        "terceiros_2026t1": 100 * (1 - (g["2026t1_A"] + g["2026t1_B"]) / g["2026t1_validos"]),
    })
    comp.to_csv(TAB / "uf_2022_2026.csv")
    print("\n", comp.round(1).to_string())

    # terceiros 2026 por região
    cols = [f"2026t1_{c}" for c in list(TERCEIROS[2026].values()) + ["outros"]]
    t = mun.groupby("regiao")[cols + ["2026t1_validos"]].sum()
    t = 100 * t[cols].div(t["2026t1_validos"], axis=0)
    t.to_csv(TAB / "terceiros_2026_regiao.csv")
    print("\n", t.round(2).to_string())

    # correlação entre swings municipais 2018 e 2022 (persistência do comportamento)
    s = {}
    for ano in (2018, 2022):
        a1, b1 = mun[f"{ano}t1_A"], mun[f"{ano}t1_B"]
        a2, b2 = mun[f"{ano}t2_A"], mun[f"{ano}t2_B"]
        s[ano] = _logit(a2 / (a2 + b2)) - _logit(a1 / (a1 + b1))
    ok = mun["2018t1_validos"].notna() & mun["2022t1_validos"].notna() & (mun.uf != "ZZ")
    print("\ncorrelação swing municipal 2018 x 2022:", np.corrcoef(s[2018][ok], s[2022][ok])[0, 1].round(3))


if __name__ == "__main__":
    main()
