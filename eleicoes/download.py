"""Baixa os arquivos de resultados do portal de dados abertos do TSE.

Arquivos usados (apenas o recorte BR = cargo Presidente):
  votacao_candidato_munzona_{ano}.zip -> votos por candidato, município x zona
  detalhe_votacao_munzona_{ano}.zip   -> aptos, comparecimento, abstenção, brancos, nulos
  votacao_secao_{ano}_BR.zip          -> votos por seção (usado no backtest de 2022)

Uso: python -m eleicoes.download [--secao]
"""
import argparse
import shutil
import zipfile

import requests

from .config import ANOS, CDN, RAW


def _baixar(url, destino):
    if destino.exists():
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".part")
    print(f"baixando {url}")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            shutil.copyfileobj(r.raw, f, length=1 << 20)
    tmp.rename(destino)
    return destino


def _extrair(zip_path, membro):
    alvo = RAW / membro
    if not alvo.exists():
        with zipfile.ZipFile(zip_path) as z:
            z.extract(membro, RAW)
    return alvo


def baixar_munzona():
    for ano in ANOS:
        for base in ("votacao_candidato_munzona", "detalhe_votacao_munzona"):
            z = _baixar(f"{CDN}/{base}/{base}_{ano}.zip", RAW / f"{base}_{ano}.zip")
            _extrair(z, f"{base}_{ano}_BR.csv")


def baixar_secao(anos=(2018, 2022, 2026)):
    for ano in anos:
        z = _baixar(f"{CDN}/votacao_secao/votacao_secao_{ano}_BR.zip", RAW / f"votacao_secao_{ano}_BR.zip")
        _extrair(z, f"votacao_secao_{ano}_BR.csv")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--secao", action="store_true", help="baixa também os dados por seção (≈430 MB)")
    a = ap.parse_args()
    baixar_munzona()
    if a.secao:
        baixar_secao()
