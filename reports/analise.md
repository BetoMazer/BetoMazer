# Eleições presidenciais 2018, 2022 e 1º turno 2026 — análise por zona e região

Fonte: TSE, arquivos `votacao_candidato_munzona` e `detalhe_votacao_munzona`
(recorte Presidente). Unidade mínima: município × zona eleitoral — 6.240
unidades em 2018, 6.283 em 2022 e 6.292 em 2026 (≈2.640 zonas, várias
abrangendo mais de um município). Tabelas completas em `reports/tabelas/` e os
dados por zona em `data/processed/munzona_{ano}_t{turno}.csv`.

## Resultado nacional

| eleição | candidato A | % válidos | candidato B | % válidos | abstenção | brancos | nulos |
|---|---|---|---|---|---|---|---|
| 2018 1º t | Bolsonaro | 46,03 | Haddad | 29,28 | 20,33% | 2,65% | 6,14% |
| 2018 2º t | Bolsonaro | **55,13** | Haddad | 44,87 | 21,30% | 2,14% | 7,43% |
| 2022 1º t | Bolsonaro | 43,20 | Lula | 48,43 | 20,95% | 1,59% | 2,82% |
| 2022 2º t | Bolsonaro | 49,10 | Lula | **50,90** | 20,58% | 1,42% | 3,16% |
| 2026 1º t | Flávio Bolsonaro | **47,03** | Lula | 45,16 | 21,08% | 1,84% | 2,93% |

Brancos e nulos em % do comparecimento. Em 2026 os demais candidatos somaram
7,81% dos válidos: Augusto Cury (Avante) 2,89%, Renan Santos (Missão) 2,24%,
Ronaldo Caiado (PSD) 2,18%, Zema (Novo) 0,27% e o restante 0,21%.

## Regiões

O mapa é estável entre as três eleições: Nordeste vermelho, Sul e
Centro-Oeste azuis, Sudeste e Norte decidindo. O que muda em 2026 é a
intensidade. No 1º turno Flávio teve 60,1% no Sul (Bolsonaro 54,6% em 2022),
56,5% no Centro-Oeste, 51,4% no Sudeste e 49,2% no Norte; Lula caiu no seu
reduto, de 66,8% para 63,8% no Nordeste, e de 42,6% para 39,7% no Sudeste.
Em 26 das 27 UFs a fatia de Flávio no 1º turno superou a de Bolsonaro no
1º turno de 2022 (a exceção é o DF, 51,7→51,3, onde Caiado teve 4,8%); nas de maior peso o ganho foi de 4 a 7 p.p. (SP 47,7→51,9;
MG 43,6→48,2; RS 48,9→55,6; PR 55,3→59,9). Peso no eleitorado de 2026:
Sudeste 41,8%, Nordeste 27,4%, Sul 14,4%, Norte 8,3%, Centro-Oeste 7,6%,
exterior 0,6%.

Os terceiros de 2026 têm geografia própria, o que importa para o 2º turno:
Caiado fez 12,3% em Goiás e 4,8% no DF (6,8% no Centro-Oeste), enquanto Cury e
Renan cresceram no Sul/Sudeste (≈3% cada) e ficaram mais fracos no Nordeste.
Ou seja, o voto "em disputa" está concentrado justamente onde Flávio já é
mais forte.

Por zona, Flávio venceu em 3.307 das 6.292 unidades e Lula em 2.941; Lula tem
mais zonas acima de 60% (1.908 contra 1.473), o padrão típico de voto mais
concentrado no Nordeste.

## Comparecimento entre turnos

A abstenção oscila pouco entre turnos (≈±1 p.p.), mas não de forma uniforme.
Em 2018 o comparecimento caiu em todas as regiões no 2º turno (−4,4% no
Norte); em 2022 subiu ≈0,9% no Sul, Sudeste e Centro-Oeste, ficou estável no
Nordeste e caiu 2,5% no Norte. Diferencial de comparecimento de 1% entre
regiões vale ≈0,1–0,2 p.p. no resultado nacional — por isso o modelo projeta
o comparecimento separadamente.

## Transferência de votos entre turnos

Regressão ecológica por município (NNLS, destino no 2º turno de cada
categoria do 1º turno). É inferência ecológica — os números individuais são
ruidosos (ex.: brancos "indo" para Bolsonaro em 2022 é artefato), mas o
padrão agregado é informativo:

* **2022**: eleitores de Tebet ≈66% Bolsonaro / 6% Lula / 28% branco-nulo;
  de Ciro ≈15% Bolsonaro / 80% Lula. Somados, os terceiros foram ≈70/30 para
  Bolsonaro — mesmo sendo candidaturas de centro e centro-esquerda.
* **2018**: Ciro ≈8% Bolsonaro / 86% Haddad; Alckmin e Amoêdo ≈60% Bolsonaro
  com 35–40% para branco/nulo.

O swing entre turnos (logit da fatia bipartidária) foi muito homogêneo entre
UFs em 2022 (desvio-padrão 0,023) e muito heterogêneo em 2018 (0,213), por
causa da concentração regional do voto em Ciro. A correlação do swing
municipal entre 2018 e 2022 é baixa (0,31): o comportamento entre turnos
depende mais de quem são os terceiros do que de uma "personalidade" fixa do
município. Isso justifica o desenho do modelo: o principal preditor do swing
é a composição do voto nos terceiros, e o histórico entra só como feature
secundária.

## O que o 1º turno de 2026 implica para o 2º

Aritmética pura: Lula precisa de ≈62% dos eleitores de terceiros que
escolherem um finalista (45,16 + 0,62 × 7,81 ≈ 50) — sem contar diferencial
de comparecimento. Com a premissa padrão do modelo — conservadora: Cury
50/50, Renan 50/50, Caiado 70/30, Zema 80/20, demais 35/65 — a linha de base
dá **Flávio ≈51,4%**. Em 2022 Bolsonaro ganhou 5,9 p.p. entre turnos e Lula
2,5 p.p.; repetir algo parecido levaria Flávio a 52–53%.

## Pesquisas

Na semana final antes do 1º turno (26/09–03/10), as pesquisas registradas
erraram sistematicamente contra Flávio: em média ele apareceu 4,2 p.p. abaixo
do que teve nas urnas (votos válidos) e Lula 0,8 p.p. abaixo; a margem
Flávio − Lula saiu 3,5 p.p. melhor para Flávio do que as pesquisas
indicavam. O erro variou muito por instituto — de −7,8 p.p. na margem
(Indexa, CNT/MDA, Nexus/BTG) a praticamente zero (Palver, Gerp, Futura). Os
terceiros, em contrapartida, foram superestimados (Renan +1,5, Caiado +1,2).

Nas pesquisas de 2º turno da última semana (29 divulgadas entre 16 e 23/10),
Flávio tem em média 51,1% dos válidos, com desvio-padrão de 1,1 p.p. (de 48,7
a 52,7); considerando só a última de cada instituto, 50,9%. Se cada instituto
for corrigido pela metade do erro que teve na margem do 1º turno, a média
sobe para 52,9%.

Os dois lados desse ajuste: a favor, o padrão de 2022 se repetiu (pesquisas
subestimaram o bolsonarismo) e o erro de 2026 foi na mesma direção em quase
todos os institutos, o que sugere viés de método (amostragem, ponderação,
voto envergonhado), não ruído. Contra, parte do "erro" do 1º turno pode ter
sido movimento real de última hora — voto útil de eleitores de Renan e
Caiado migrando para Flávio no fim de semana, exatamente o que explicaria
terceiros superestimados e Flávio subestimado ao mesmo tempo. Esse movimento
já está contido nas pesquisas do 2º turno e não se repetiria. A verdade
provavelmente está entre 50,9% e 52,9%.

A linha de base do modelo (51,4%) está dentro dessa faixa. Os backtests
mostram que a partir de ~2% das seções apuradas a premissa deixa de importar.

## Backtest do modelo

Reapuração seção a seção dos 2º turnos de 2022 (real: Bolsonaro 49,10%) e
2018 (real: Bolsonaro 55,13%), 5 sorteios × 4 ordens de chegada (aleatória;
regional, com Nordeste por último; municípios mais bolsonaristas primeiro;
mais petistas primeiro), prior de transferência neutro 50/50. Erro em p.p. da
projeção de A; "parcial" é o erro de quem olha só o placar parcial.

| % seções apuradas | erro médio abs. 2022 | máx. 2022 | erro médio abs. 2018 | máx. 2018 | erro da parcial (média) | largura IC90 |
|---|---|---|---|---|---|---|
| 0,5% | 0,62 | 2,08 | 1,38 | 4,60 | ≈19 | ≈3,7 |
| 1% | 0,58 | 1,52 | 0,88 | 1,91 | ≈19 | ≈3,2 |
| 2% | 0,48 | 1,33 | 0,76 | 1,84 | ≈18 | ≈2,9 |
| 5% | 0,21 | 0,50 | 0,61 | 1,43 | ≈17 | ≈2,5 |
| 10% | 0,26 | 0,49 | 0,37 | 1,17 | ≈15 | ≈2,1 |
| 20% | 0,13 | 0,35 | 0,19 | 0,64 | ≈13 | ≈1,8 |
| 40% | 0,10 | 0,24 | 0,17 | 0,51 | ≈9 | ≈1,3 |

Leituras práticas:

* Com 1–2% das seções o modelo já erra, em média, ~0,5 p.p. em 2022 e
  ~0,8 p.p. em 2018. Com 5% fica em 0,2 (2022) e 0,6 (2018). Quem olha a
  parcial erra 15–20 p.p. nos cenários enviesados.
* 2018 é o caso difícil: o swing entre turnos foi fortemente regional
  (Ciro no Nordeste). Quando a apuração chega muito desbalanceada por
  região, o erro até 5% pode passar de 1 p.p. — por isso a regra de bolso é
  não "cravar" uma eleição com margem < 2 p.p. antes de ~10% apurado e de
  todas as regiões terem dados.
* Em nenhum dos 360 pontos o modelo deu probabilidade > 90% para o lado
  errado. Na disputa apertada de 2022 (margem de 1,8 p.p.) a probabilidade
  mediana de vitória de Lula foi 86% com 1% apurado, 88% com 5%, 92% com
  20% e > 99% com 60%.
* Intervalos de 90% cobriram o resultado real em 100% dos casos de 2022 e em
  75–100% dos de 2018 (abaixo do nominal só com ≤2% apurado) — levemente
  conservadores no caso típico, otimistas no caso de swing regional extremo
  com pouquíssimos dados.

Limitação do backtest: a ordem de chegada é simulada (o TSE não publica o
horário de totalização por seção), e a parte apurada de cada cidade grande é
um sorteio de seções/zonas — na vida real pode haver padrões (ex.: centro
antes de periferia) que o termo de viés de apuração parcial do modelo só
cobre parcialmente.
