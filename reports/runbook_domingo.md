# Roteiro de operação do painel publicado (para o Claude, na sessão do Claude Code)

Painel: https://claude.ai/artifact/46vTS3ce2ef6CMCagHDaTM
Banco do painel (ArtifactData, mesma URL):
  estado/atual        projeção (escrito pelo Claude a cada rodada)
  pesquisas/resumo    aba de pesquisas (escrito pelo Claude)
  controle/comando    {acao: "aguardando" | "iniciar" | "parar", em} (escrito pelo botão)
  estado/governadores 2º turno de governador (AC, AM, DF, ES, RN, TO), escrito junto com estado/atual
  controle/premissas  {transf: {cury, renan, caiado, zema, outros}, prior_A} (escrito pela aba Premissas)
Toda escrita num documento existente exige if_version (a versão retornada na última leitura/escrita).

## Preparar o ambiente (container pode ser novo)
    cd /home/user/BetoMazer && git pull origin claude/brazil-election-prediction-model-fqwgo7
    pip install -q -r requirements.txt
    mkdir -p data/live

## Atualizar pesquisas (sábado à noite / domingo)
    python -m eleicoes.pesquisas
    python -c "import json; from eleicoes.nuvem import payload_pesquisas; open('data/live/pesquisas_db.json','w').write(json.dumps(payload_pesquisas(), ensure_ascii=False))"
Depois: ArtifactData get pesquisas/resumo (versão) e set com file_path data/live/pesquisas_db.json e if_version.
Se a Wikipédia bloquear, usar WebFetch/WebSearch para as pesquisas novas e incluí-las em data/pesquisas/manuais_2t.csv.

## Domingo, 16h25 (Brasília): prontidão
1. Escrever estado/atual com status "prontidao":
       python -c "import json; from eleicoes.painel import Estado; from eleicoes.nuvem import payload; open('data/live/estado_db.json','w').write(json.dumps(payload(Estado(sims=1000), 'prontidao'), ensure_ascii=False))"
   e ArtifactData set estado/atual (file_path, if_version).
2. Monitor com tique a cada 45 s; a cada tique: ArtifactData list controle.
   - Se comando.acao == "iniciar" (ou se já passou de 17h05 sem clique): iniciar a coleta (passo 3).
   - A cada ~3 min sem início, reescrever estado/atual com status "prontidao" (mantém o selo "Claude de prontidão").

## Coleta ao vivo
3. Gravar data/live/controle.json = {"premissas": <controle/premissas sem o campo em>, "comando": <controle/comando>} e iniciar desacoplado:
       nohup python -m eleicoes.nuvem loop data/live/estado_db.json --intervalo 90 > data/live/loop.log 2>&1 &
   Monitor: tail -F data/live/loop.log | grep --line-buffered -E "RODADA|PARADO|APURACAO_COMPLETA|Traceback|Error"
4. A cada linha RODADA:
   - ArtifactData list controle -> regravar data/live/controle.json (premissas novas entram na rodada seguinte; acao "parar" encerra o loop).
   - ArtifactData batch: set estado/atual (data/live/estado_db.json) e set estado/governadores
     (data/live/estado_gov.json), cada um com o seu if_version.
5. Se o processo morrer: reiniciar o passo 3 (o histórico é recuperado de data/live/painel_historico_6258.csv).
6. Encerrar quando aparecer APURACAO_COMPLETA (fazer uma última escrita) ou PARADO, ou às 23h30.
