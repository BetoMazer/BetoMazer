# Projeção do 2º turno presidencial 2026 com apuração parcial

Modelo e painel ao vivo que projetam o resultado final do 2º turno (Flávio
Bolsonaro × Lula) a partir de uma fração pequena das urnas apuradas, usando o
vetor de votação de cada município/zona no 1º turno de 2026 e o comportamento
entre turnos em 2018 e 2022. Dados do TSE; pesquisas da Wikipédia (que
consolida os registros do TSE).

## Domingo, passo a passo

**Uma vez, antes (sábado ou domingo de manhã):**

1. Instale o Python 3.10 ou mais novo (python.org; no Windows marque
   *"Add Python to PATH"* na instalação).
2. Baixe este repositório: botão **Code → Download ZIP** no GitHub (branch
   `claude/brazil-election-prediction-model-fqwgo7`) e descompacte, ou
   `git clone` + `git checkout claude/brazil-election-prediction-model-fqwgo7`.
3. Ensaie com a apuração simulada:
   * Windows: abra o Prompt de Comando na pasta e rode `iniciar_painel.bat --demo`
   * macOS/Linux: `./iniciar_painel.sh --demo`

   O navegador abre em http://localhost:8050 com uma apuração fictícia
   correndo (≈3 min). Feche com Ctrl+C.

Os dados processados do TSE já estão no repositório (`data/processed/`); não
é preciso baixar os arquivos brutos.

**No domingo (urnas fecham às 17h de Brasília em todo o país):**

1. Por volta das 16h30, rode `iniciar_painel.bat` (Windows) ou
   `./iniciar_painel.sh` (macOS/Linux) — **sem** `--demo`.
2. Deixe a janela aberta. O painel fica em *"aguardando apuração"* mostrando a
   linha de base; quando o TSE começar a divulgar (a partir das 17h) ele passa
   a *AO VIVO*, coleta os 5.757 municípios a cada 60 s e reprojeta.
3. Se o computador dormir ou o programa fechar, é só rodar de novo: o
   histórico da noite é recuperado de `data/live/`.

Opções: `--intervalo 90` (segundos entre coletas), `--porta 8060`.
Alternativa sem navegador: `python -m eleicoes.live` imprime a projeção no
terminal (`--transf cury=50,renan=50,caiado=70,zema=80` e `--prior-A 50`).

## O painel

**Apuração ao vivo** — projeção final de cada candidato com IC 90%/95%,
probabilidade de vitória, % de seções totalizadas e parcial do TSE; curva da
projeção × parcial ao longo da apuração; *vetor de desvio por UF* (quanto cada
UF está votando acima/abaixo da linha de base do 1º turno); tabelas por região
e UF; municípios que mais se afastam da base em cada direção.

**Premissas** — divisão dos eleitores de Cury, Renan Santos, Caiado, Zema e
demais entre Flávio e Lula (padrão conservador: Cury 50/50, Renan 50/50,
Caiado 70/30, Zema 80/20, demais 35/65) e, opcionalmente, um ponto de partida
fixo para antes da primeira urna (ex.: média das pesquisas). "Aplicar"
reprojeta na hora, inclusive no meio da apuração. As premissas definem a
linha de base; o desvio real em relação a ela é aprendido com as urnas — por
isso elas pesam muito até ~2% apurado e quase nada depois de ~5%.

**Pesquisas** — todas as pesquisas de 2º turno da última semana (fatia de
Flávio nos válidos, média, mediana, desvio-padrão, amplitude, última de cada
instituto), as registradas e ainda não divulgadas, e a comparação das
pesquisas da semana final do 1º turno com o resultado das urnas, por
candidato e por instituto. Inclui uma leitura "ajustada" que desloca cada
pesquisa pelo erro que o mesmo instituto teve no 1º turno. Atualiza da
Wikipédia a cada 30 min; pesquisas ausentes podem ser incluídas em
`data/pesquisas/manuais_2t.csv` (colunas instituto, inicio, fim, amostra,
margem, flavio, lula, indecisos).

## Dados

* `votacao_candidato_munzona_{2018,2022,2026}` e `detalhe_votacao_munzona_*`
  (dadosabertos.tse.jus.br): votos por candidato, aptos, comparecimento,
  abstenção, brancos e nulos por município × zona, 1º e 2º turnos.
* `votacao_secao_{2018,2022}`: votos por seção, usados para reapurar 2018 e
  2022 seção a seção no backtest.
* Feed ao vivo: `resultados.tse.jus.br/oficial/ele2026/6258/dados/{uf}/{uf}{mun}-c0001-e006258-u.json`
  (eleição 6258 = 2º turno presidente; lista de municípios em `config/mun-e006258-cm.json`).

Para refazer o processamento a partir do TSE: `python -m eleicoes.download --secao`
e `python -m eleicoes.process --secao` (≈2 GB de download).

**Limitação importante:** durante a apuração o TSE divulga resultado por
município, UF e Brasil — não por zona. Por isso a observação ao vivo é
municipal (5.757 unidades, incluindo cidades no exterior); a projeção por
zona (`data/live/projecao_zonas_6258.csv`) aplica o desvio estimado do
município ao vetor de 1º turno de cada zona. 5.567 dos 5.757 municípios têm
uma única zona; a diferença só existe nas 190 cidades com várias zonas.

## Modelo (detalhes em `eleicoes/model.py`)

1. **Linha de base** por município: `s0 = (Flávio₁ + Σ aₖ·Terceiroₖ) / (Flávio₁ + Lula₁ + Σ Terceiroₖ)`,
   com `aₖ` = premissas acima.
2. **Desvio observado** em cada município com urnas:
   `r = logit(Flávio/(Flávio+Lula) apurado) − logit(s0)`.
3. **Vetor de desvio**: regressão bayesiana do desvio contra o perfil do
   município (fatia de cada terceiro, força de Flávio no 1º turno, brancos/nulos,
   abstenção, swing entre turnos de 2022, tendência 2022→2026, tamanho, região,
   UF). Com pouca apuração o swing é quase uniforme; com mais dados ele se
   diferencia por perfil e o desvio aprendido é aplicado às zonas não
   apuradas de perfil parecido (sem extrapolar além da faixa já observada).
4. **Municípios parcialmente apurados**: o desvio próprio é combinado com o
   do modelo conforme o volume apurado, com penalidade por a parte apurada não
   ser uma amostra aleatória do município.
5. **Comparecimento**: mesmo mecanismo para a razão válidos-2º-turno / válidos-1º-turno.
6. **Incerteza**: Monte Carlo com incerteza dos coeficientes, ruído por
   município e viés sistemático comum ao voto não apurado.

## Backtest

`python -m eleicoes.backtest` reapura os 2º turnos de 2022 e 2018 seção a
seção em quatro ordens de chegada, com premissa neutra (50/50). Com 1% das
seções o erro médio foi 0,6 p.p. (2022) e 0,9 p.p. (2018); com 5%, 0,2 e 0,6;
em 360 pontos testados o modelo nunca deu > 90% de chance ao lado errado.
Detalhes em `reports/analise.md`.

## Estrutura

```
eleicoes/config.py     URLs, códigos de eleição, premissas padrão, regiões
eleicoes/download.py   download do portal de dados abertos
eleicoes/process.py    tabelas por zona, município e seção
eleicoes/analysis.py   análise descritiva (reports/tabelas/)
eleicoes/model.py      modelo de projeção
eleicoes/live.py       coletor do TSE + projeção no terminal
eleicoes/painel.py     servidor do painel (http://localhost:8050)
eleicoes/web/          página do painel
eleicoes/pesquisas.py  pesquisas (Wikipédia), dispersão, erro do 1º turno
eleicoes/backtest.py   reapuração simulada de 2018 e 2022
data/processed/        dados por zona (CSV por eleição/turno) e painel municipal
data/pesquisas/        pesquisas consolidadas (+ manuais_2t.csv opcional)
reports/               análise e tabelas
```
