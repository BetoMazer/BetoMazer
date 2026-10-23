"""Caminhos, URLs e metadados das eleições usadas no modelo."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
LIVE = DATA / "live"
REPORTS = ROOT / "reports"

CDN = "https://cdn.tse.jus.br/estatistica/sead/odsele"
RESULTADOS = "https://resultados.tse.jus.br/oficial"

ANOS = (2018, 2022, 2026)

# Eleição/cargo do 2º turno presidencial de 2026 no sistema de divulgação do TSE
# (descobertos em /oficial/comum/config/ele-c.json).
CICLO_2026 = "ele2026"
ELEICAO_T1_2026 = "6257"
ELEICAO_T2_2026 = "6258"
CARGO_PRESIDENTE = "0001"

# Finalistas de cada eleição: (número "direita", número "esquerda").
# O modelo projeta a participação do primeiro (A) no total A+B de votos válidos.
FINALISTAS = {
    2018: {"A": 17, "B": 13, "nome_A": "Jair Bolsonaro", "nome_B": "Fernando Haddad"},
    2022: {"A": 22, "B": 13, "nome_A": "Jair Bolsonaro", "nome_B": "Lula"},
    2026: {"A": 22, "B": 13, "nome_A": "Flávio Bolsonaro", "nome_B": "Lula"},
}

# Candidatos eliminados no 1º turno com peso relevante, usados como features do
# modelo (o voto deles é o que "se redistribui" no 2º turno).
TERCEIROS = {
    2018: {12: "ciro", 45: "alckmin", 30: "amoedo"},
    2022: {15: "tebet", 12: "ciro"},
    2026: {70: "cury", 14: "renan", 55: "caiado", 30: "zema"},
}

# Fração dos eleitores de cada terceiro (que escolhem um finalista) que vai
# para o candidato A no 2º turno. É o ponto de partida do modelo; durante a
# apuração o desvio em relação a essa divisão é aprendido com os votos
# apurados. Os valores de 2026 são a premissa conservadora definida pelo
# usuário (Cury 50/50, Renan 50/50, Caiado 70/30, Zema 80/20) e podem ser
# alterados no painel ou com --transf. "outros" = demais candidatos (UP, PSTU,
# PCB, PCO, DC, Democrata).
PRIOR_TRANSFERENCIA = {
    2018: {"ciro": 0.5, "alckmin": 0.5, "amoedo": 0.5, "outros": 0.5},
    2022: {"tebet": 0.5, "ciro": 0.5, "outros": 0.5},
    2026: {"cury": 0.50, "renan": 0.50, "caiado": 0.70, "zema": 0.80, "outros": 0.35},
}

REGIAO = {
    "AC": "Norte", "AM": "Norte", "AP": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste",
    "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MS": "Centro-Oeste", "MT": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
    "ZZ": "Exterior",
}
