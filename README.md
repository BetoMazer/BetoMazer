# Projeção do 2º turno presidencial 2026 com apuração parcial

Modelo que projeta o resultado final do 2º turno (Flávio Bolsonaro × Lula) a
partir de uma fração pequena das urnas apuradas, usando o vetor de votação de
cada município/zona no 1º turno de 2026 e o comportamento entre turnos em 2018
e 2022. Todos os dados vêm do TSE.

## Como rodar no domingo

```bash
pip install -r requirements.txt
python -m eleicoes.download          # baixa os arquivos do TSE (~1,4 GB, só presidente é extraído)
python -m eleicoes.process           # gera data/processed/ (por zona e município)
python -m eleicoes.live              # coleta o feed do TSE a cada 120 s e projeta
```

Opções do `live`:

| opção | efeito |
|---|---|
| `--intervalo 60` | segundos entre rodadas (uma rodada completa leva ~40 s) |
| `--uma-vez` | roda uma vez e sai |
| `--prior-A 50` | calibra a linha de base pré-apuração para 50% de Flávio (ex.: pesquisas). Só pesa antes de ~1–2% apurado |
| `--eleicao 6257` | teste com o 1º turno (já 100% apurado) para validar a coleta |

Saídas em `data/live/`: `historico_6258.csv` (projeção a cada rodada),
`projecao_uf_6258.csv`, `projecao_municipios_6258.csv`,
`projecao_zonas_6258.csv` (projeção por zona eleitoral) e
`apuracao_municipios_6258.csv` (o dado bruto coletado).

## Dados

* `votacao_candidato_munzona_{2018,2022,2026}` e `detalhe_votacao_munzona_*`
  (dadosabertos.tse.jus.br): votos por candidato, aptos, comparecimento,
  abstenção, brancos e nulos por município × zona, 1º e 2º turnos.
* `votacao_secao_{2018,2022}`: votos por seção, usados para reapurar 2018 e
  2022 seção a seção no backtest.
* Feed ao vivo: `resultados.tse.jus.br/oficial/ele2026/6258/dados/{uf}/{uf}{mun}-c0001-e006258-u.json`
  (eleição 6258 = 2º turno presidente; lista de municípios em `config/mun-e006258-cm.json`).

**Limitação importante:** durante a apuração o TSE divulga resultado por
município, UF e Brasil — não por zona. Zona só aparece nos arquivos
consolidados depois. Por isso a observação ao vivo é municipal (5.757
unidades, incluindo cidades no exterior); a projeção por zona é obtida
aplicando o desvio estimado do município ao vetor de 1º turno de cada zona.
Para 5.567 dos 5.757 municípios há uma única zona, então município = zona; a
diferença só existe nas 190 cidades com várias zonas. Os arquivos de boletim de
urna (`arquivo-urna/.../cs.json`) têm horário por seção, mas é horário de
publicação em lote (MG inteiro às 12h55 do dia seguinte), não de totalização —
não servem para reconstruir a ordem de apuração.

## Modelo (resumo; detalhes em `eleicoes/model.py`)

1. **Linha de base** por município: `s0 = (Flávio₁ + Σ aₖ·Terceiroₖ) / (Flávio₁ + Lula₁ + Σ Terceiroₖ)`,
   com prior de transferência `aₖ` (Cury 55%, Renan 75%, Caiado 75%, Zema 80%,
   demais 35% para Flávio) em `config.PRIOR_TRANSFERENCIA`.
2. **Desvio observado** em cada município com urnas apuradas:
   `r = logit(Flávio/(Flávio+Lula) apurado) − logit(s0)`.
3. **Vetor de desvio**: regressão bayesiana do desvio contra o perfil do
   município (fatia de cada terceiro, força de Flávio no 1º turno, brancos/nulos,
   abstenção, swing entre turnos de 2022, tendência 2022→2026, tamanho, região,
   UF). Priors encolhem tudo para zero: com pouca apuração o swing é quase
   uniforme; conforme entram dados ele se diferencia por perfil. Se as zonas
   apuradas repetem o 1º turno o desvio é ~0; se votam diferente, o desvio
   aprendido é aplicado às não apuradas de perfil parecido. As features das
   não apuradas são truncadas à faixa já observada (não extrapola).
4. **Municípios parcialmente apurados**: o desvio próprio é combinado com o do
   modelo conforme o volume apurado (shrinkage), com penalidade por a parte
   apurada não ser uma amostra aleatória do município.
5. **Comparecimento**: mesmo mecanismo para a razão válidos-2º-turno / válidos-1º-turno,
   que dá o peso de cada município ainda não apurado.
6. **Incerteza**: Monte Carlo (3.000 simulações) com incerteza dos
   coeficientes, ruído por município e um viés sistemático comum a todo o voto
   não apurado.

## Backtest

`python -m eleicoes.backtest` reapura os 2º turnos de 2022 e 2018 seção a
seção em quatro ordens de chegada (aleatória, regional, favorável a A primeiro,
favorável a B primeiro), com prior de transferência **neutro (50/50)** para não
usar informação do resultado. Resultados em `reports/tabelas/backtest_resumo.csv`
e discussão em `reports/analise.md`.

## Estrutura

```
eleicoes/config.py     URLs, códigos de eleição, priors, regiões
eleicoes/download.py   download do portal de dados abertos
eleicoes/process.py    tabelas por zona, município e seção
eleicoes/analysis.py   análise descritiva (reports/tabelas/)
eleicoes/model.py      modelo de projeção
eleicoes/live.py       coleta ao vivo + projeção
eleicoes/backtest.py   reapuração simulada de 2018 e 2022
data/processed/        dados por zona (CSV por eleição/turno) e painel municipal
reports/               análise e tabelas
```
