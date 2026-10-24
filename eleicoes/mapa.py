"""Gera a geometria leve do mapa municipal usada no painel.

Entrada: malha municipal do IBGE em GeoJSON (ex.: geodata-br, geojs-100-mun.json)
e a lista de municípios do TSE (config/mun-e006258-cm.json), que traz o código
IBGE ("cdi") de cada código TSE.

Saída:
  eleicoes/web/mapa.json            polígonos simplificados e projetados (inteiros), UFs e ordem
  data/processed/mapa_municipios.csv  ordem dos municípios no mapa -> (uf, cd_mun TSE)

Uso: python -m eleicoes.mapa MALHA.geojson MUN_TSE.json
"""
import json
import math
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import shape
from shapely.ops import unary_union

from .config import PROCESSED

WEB = Path(__file__).resolve().parent / "web"
LARGURA = 1000          # unidades do sistema de coordenadas do mapa
TOL = 0.025             # simplificação (graus)
COS = math.cos(math.radians(15))


def main(malha, tse):
    cm = json.loads(Path(tse).read_text())
    ibge2tse = {m["cdi"]: (a["cd"].upper(), int(m["cd"])) for a in cm["abr"] if a["cd"] != "zz" for m in a["mu"]}
    feats = json.loads(Path(malha).read_text())["features"]
    geoms, linhas = [], []
    for f in feats:
        cod = str(f["properties"]["id"])
        if cod not in ibge2tse:
            continue
        g = shape(f["geometry"]).buffer(0)
        geoms.append((ibge2tse[cod], g))
    minx = min(g.bounds[0] for _, g in geoms); maxx = max(g.bounds[2] for _, g in geoms)
    miny = min(g.bounds[1] for _, g in geoms); maxy = max(g.bounds[3] for _, g in geoms)
    esc = LARGURA / ((maxx - minx) * COS)
    altura = round((maxy - miny) * esc)

    def proj(coords):
        out = []
        for x, y in coords:
            px, py = round((x - minx) * COS * esc), round((maxy - y) * esc)
            if not out or (px, py) != (out[-2], out[-1]):
                out += [px, py]
        return out

    def aneis(g):
        polys = [g] if g.geom_type == "Polygon" else list(getattr(g, "geoms", []))
        res = []
        for p in polys:
            s = p.simplify(TOL * (0.4 if p.area < 0.05 else 1), preserve_topology=True)
            if s.is_empty:
                continue
            for q in ([s] if s.geom_type == "Polygon" else list(s.geoms)):
                r = proj(q.exterior.coords)
                if len(r) >= 6:
                    res.append(r)
        return res

    muns = []
    for i, ((uf, cd), g) in enumerate(geoms):
        muns.append(aneis(g))
        linhas.append({"idx": i, "uf": uf, "cd_mun": cd})
    ufs = {}
    df = pd.DataFrame(linhas)
    for uf, sub in df.groupby("uf"):
        u = unary_union([geoms[i][1] for i in sub.idx]).buffer(0)
        ufs[uf] = aneis(u.simplify(TOL))
    nomes = pd.read_parquet(PROCESSED / "municipio.parquet", columns=["uf", "cd_mun", "nm_mun"]).set_index(["uf", "cd_mun"]).nm_mun
    out = {"w": LARGURA, "h": altura, "chaves": [f"{r['uf']}-{r['cd_mun']}" for r in linhas],
           "nomes": [str(nomes.get((r["uf"], r["cd_mun"]), "")).title() for r in linhas], "mun": muns, "uf": ufs}
    (WEB / "mapa.json").write_text(json.dumps(out, separators=(",", ":")))
    df.to_csv(PROCESSED / "mapa_municipios.csv", index=False)
    faltam = len(ibge2tse) - len(geoms)
    print(f"{len(geoms)} municípios no mapa ({faltam} do TSE sem geometria), {(WEB / 'mapa.json').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
