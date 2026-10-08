---
name: complexidade-pr
description: >
  Classifica a complexidade de um Pull Request em BAIXA, MÉDIA ou ALTA e indica os
  três pontos onde o revisor deve focar, para o tech lead decidir em segundos se o
  PR precisa de review detalhado. Avalia tamanho, abrangência (camadas tocadas),
  zonas de risco NoHarm (lógica clínica, multi-tenant/X-Schema, RBAC, migrations,
  infra/Lambda, dependências), densidade lógica, cobertura de testes e
  reversibilidade. Use sempre que estiver revisando um PR ou diff, ao ser pedido
  code review, triagem de PR, "esse PR é grande?", "vale review detalhado?", ou ao
  abrir/atualizar PRs em repositórios NoHarm. Não julga estilo, correção ou
  qualidade do código — apenas quanto esforço e atenção o review exige.
---

# Triagem: Complexidade do PR

Você classifica quanta atenção humana este PR exige. O leitor é o tech lead,
que vai bater o olho no seu comentário e decidir: aprovo rápido, reviso com calma,
ou chamo alguém com contexto. Sua saída precisa ser lida em menos de 30 segundos.

Esta é uma triagem, não um review. NÃO aponte bugs, não sugira refatorações,
não comente estilo. Se algo parecer errado no código, isso pesa na complexidade
(vira ponto de foco), mas você não corrige — quem revisa corrige.

Sua entrega é sempre um comentário no PR. Concluir "é simples" sem registrar não
encerra a tarefa. Veja "Publicar o resultado" no fim.

## Como avaliar

Leia o diff completo e o título/descrição do PR. Depois pontue as seis dimensões
abaixo. Cada uma recebe 🟢, 🟡 ou 🔴. Os critérios são guias, não fórmulas —
use julgamento, e quando um sinal for ambíguo, prefira o nível mais alto.

**1. Tamanho**
Conte só o que exige leitura: ignore lockfiles, arquivos gerados, snapshots,
migrations auto-geradas sem lógica manual, e renomeações puras.
- 🟢 até ~150 linhas ou até 5 arquivos
- 🟡 ~150–500 linhas ou 6–15 arquivos
- 🔴 acima disso, ou muitos arquivos pequenos espalhados sem coesão

**2. Abrangência**
Quantas camadas/superfícies o PR atravessa: modelo/DB, migration, service,
router/API contract, frontend, infra (SAM/template.yaml, workflows), jobs/Lambda,
NiFi/Prefect, prompts de LLM.
- 🟢 uma camada
- 🟡 duas ou três camadas coesas (ex.: model + service + router de uma feature)
- 🔴 quatro ou mais, ou mistura de repositórios/superfícies sem relação direta

**3. Zonas de risco**
Toca algo onde um erro sai caro? Em ordem de gravidade:
- Lógica clínica: cálculo de dose, conversão de unidade, interações, alertas,
  escores, regras de prescrição — erro aqui chega ao paciente.
- Multi-tenant: qualquer coisa com `X-Schema`, `search_path`, schema dinâmico,
  queries que atravessam tenants — erro aqui vaza dado de um hospital para outro.
- Autenticação/RBAC: permissões, roles, gating de rota, JWT.
- Migration destrutiva: DROP, ALTER TYPE, renomear coluna, backfill em tabela grande.
- Infra/Lambda/CI: template SAM, IAM, workflows, variáveis de ambiente.
- Dependências: pacote novo ou major bump.
- Integrações externas: Bedrock, APIs de terceiros, filas.
- 🟢 nenhuma
- 🟡 uma zona, mudança contida
- 🔴 lógica clínica ou multi-tenant, ou duas ou mais zonas

**4. Densidade lógica**
Quanto raciocínio a mudança exige para ser entendida.
- 🟢 CRUD, config, texto, mudança mecânica e repetitiva
- 🟡 condicionais novos, nova função com regra de negócio, nova query com joins
- 🔴 algoritmo, regra com muitos ramos, nova abstração/padrão, concorrência,
  ou refatoração misturada com mudança de comportamento (o pior caso: não dá
  para separar o que mudou de propósito do que mudou de forma)

**5. Cobertura de testes**
Compare a mudança de lógica com a mudança em testes.
- 🟢 lógica nova/alterada tem teste correspondente, ou não há lógica a testar
- 🟡 testes parciais, ou só o caminho feliz
- 🔴 lógica nova ou alterada sem nenhum teste, ou testes existentes removidos/
  desativados (`skip`, `xfail`, asserts comentados)

**6. Reversibilidade**
Se der errado em produção, quanto custa voltar?
- 🟢 revert do PR resolve
- 🟡 precisa de revert + limpeza (cache, feature flag, reprocessamento)
- 🔴 migration irreversível, alteração de dado histórico, mudança de contrato
  que clientes externos já podem estar consumindo, ou evento disparado que não
  volta (e-mail, notificação, cobrança)

## Do sinal ao nível

- **ALTA** — qualquer 🔴 em Zonas de risco, ou dois ou mais 🔴 em qualquer dimensão
- **MÉDIA** — um 🔴 (fora de Zonas de risco), ou três ou mais 🟡
- **BAIXA** — o resto

A regra assimétrica é intencional: um PR pequeno e bem testado que muda cálculo
de dose ainda é ALTA, porque o custo do erro não depende do tamanho do diff.

Recomendação por nível (uma linha, adapte ao contexto):
- **BAIXA** → "Review rápido; aprovar se o CI passar."
- **MÉDIA** → "Review com atenção nos pontos de foco; ~20–30 min."
- **ALTA** → "Review detalhado" + quem chamar quando a zona exigir: contexto
  clínico (farmacêutico/produto), quem conhece o multi-tenant, quem cuida da
  infra. Se o PR mistura refatoração com feature, sugira dividir.

## Pontos de foco

Liste exatamente três (menos só se o PR for tão pequeno que não existam três
coisas dignas de nota — aí liste as que houver). Cada ponto:

- Aponta arquivo e, quando possível, função/trecho.
- Diz **por que** merece atenção em uma frase — o que pode dar errado ali.
- É onde o revisor deve gastar tempo, não um resumo do PR.

Ordene do mais crítico ao menos. Zonas de risco vêm antes de densidade; densidade
antes de tamanho. Um teste ausente para uma regra clínica é ponto de foco; um
arquivo grande de CRUD não é.

## Formato

A primeira linha é sempre a linha de status — é por ela que humanos e
automações localizam o resultado.

```
COMPLEXIDADE PR: ALTA
Recomendação: review detalhado; envolver alguém com contexto clínico. Considere separar a refatoração do `DoseService` em PR próprio.

| Dimensão | Sinal | Motivo |
|---|---|---|
| Tamanho | 🟡 | 340 linhas em 9 arquivos |
| Abrangência | 🟡 | model + service + router |
| Zonas de risco | 🔴 | altera cálculo de dose máxima diária |
| Densidade lógica | 🔴 | refatoração misturada com mudança de regra |
| Cobertura | 🟡 | testa caminho feliz, não testa unidade desconhecida |
| Reversibilidade | 🟢 | revert resolve |

Onde focar:
1. `services/dose.py:calc_max_daily` — a regra de arredondamento mudou junto com a refatoração; confirmar se foi intencional.
2. `services/dose.py:_normalize_unit` — retorna `None` para unidade desconhecida; quem chama trata isso?
3. `tests/test_dose.py` — não cobre mcg→mg nem unidade ausente.

Revisados 9 arquivos, 340 linhas, no commit a1b2c3d.
```

Regras do formato:

- O `Motivo` da tabela tem no máximo uma frase curta. A tabela é para bater o
  olho; a explicação vai em "Onde focar".
- A última linha registra o escopo (arquivos, linhas, sha curto). Sem ela, não dá
  para saber se a triagem viu o commit atual.
- Sem preâmbulo, sem resumo do que o PR faz (o tech lead lê o título), sem elogio.
- Se não conseguir ler o diff inteiro (truncado, binário, muito grande), diga na
  linha de escopo o que ficou de fora e classifique como ALTA — o que não pôde
  ser lido não pode ser considerado simples.

## Publicar o resultado

Publique o resultado como comentário no PR **em todos os casos**, inclusive
BAIXA. Um PR sem o comentário é indistinguível de um PR que a triagem não rodou,
e o tech lead volta a ter que abrir o diff para decidir — exatamente o trabalho
que esta skill existe para poupar.

- **Um comentário por PR.** Se já existir um comentário seu começando com
  `COMPLEXIDADE PR:`, edite-o. O comentário reflete sempre o commit mais recente;
  um PR que começou BAIXA pode virar ALTA depois de mais pushes.
- **Mantenha BAIXA curto.** Linha de status, recomendação, tabela e escopo.
  Pontos de foco só se houver algo que valha o olhar.
- **Não repita a skill de dados sensíveis.** Se ela rodar no mesmo PR, o achado
  dela não vira ponto de foco aqui — cada skill tem seu comentário.

Se você não tiver ferramenta para comentar no PR, devolva o bloco de resultado
na sua resposta, começando pela linha de status, e diga explicitamente que o
comentário não pôde ser publicado.
