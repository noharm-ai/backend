---
name: "dados-sensiveis-hardcoded"
description: >
  Revisa um Pull Request procurando dados sensíveis (dados pessoais, identificadores como CPF/CNS/CRM, dados clínicos vinculados a pessoa identificável, infraestrutura interna como IPs/hostnames/ARNs/connection strings, identificação de clientes/hospitais, e credenciais em texto claro) escritos diretamente no código — tanto no diff final quanto em cada commit do histórico da branch, incluindo valores que foram adicionados e depois removidos e mensagens de commit. Use sempre que estiver revisando um PR, um diff, uma branch ou for solicitado um code review, especialmente em repositórios NoHarm que lidam com dados de pacientes e infraestrutura multi-tenant. Não cobre estilo, performance, arquitetura ou lógica de negócio, apenas dados sensíveis hard coded.
---

# Review: Dados Sensíveis Hard Coded

Você revisa as linhas ADICIONADAS em cada commit da branch deste PR — não só
no diff final — e as mensagens desses commits, procurando dados sensíveis
escritos diretamente.

Esta é sua única tarefa. NÃO comente sobre estilo, performance, arquitetura,
nomes de variáveis, testes ausentes ou lógica de negócio. Se não houver
achado de dado sensível, o review passa — mesmo que o código tenha outros problemas.

Sua entrega é sempre um comentário no PR, com achados ou sem. Ler o diff e
concluir "está limpo" não encerra a tarefa: o registro dessa conclusão é o
produto do trabalho. Veja "Publicar o resultado" no fim.

## Escopo: diff final e histórico da branch

Um valor adicionado num commit e removido em outro não aparece no diff final
do PR, mas continua existindo: no histórico que vai para a branch alvo (em
merge commit ou rebase-merge), nas refs do PR no GitHub (`refs/pull/<n>/head`,
mesmo com squash merge) e em qualquer clone ou fork já feito. Por isso o
escopo é o histórico inteiro da branch.

### Como obter o escopo

Use a branch alvo como referência, não só o merge-base, para que commits da
base trazidos por merge para dentro da branch não entrem no escopo:

```
git fetch origin <branch-alvo>
git log --reverse --cc -p origin/<branch-alvo>..HEAD
```

- `--reverse` percorre do commit mais antigo ao mais novo, para você saber
  em qual commit cada valor entrou.
- `--cc` mostra, em merge commits, apenas o que foi introduzido na
  resolução de conflito — conteúdo novo que não está em nenhum dos pais.
- Compare com o diff final (`git diff origin/<branch-alvo>...HEAD`) para
  saber se cada achado ainda está no HEAD.

### O que revisar em cada commit

- **Linhas adicionadas** (`+`) de cada commit, com as mesmas categorias e
  exclusões de sempre.
- **Mensagem do commit** (título e corpo). Mensagens também ficam no
  histórico e às vezes carregam nome de cliente, IP ou ID de paciente.
- **Linhas removidas continuam fora de escopo.** Se foram adicionadas na
  própria branch, você já as viu no commit que as adicionou. Se vieram da
  base, são pré-existentes e não pertencem a este PR.

### Se o histórico não estiver disponível

Checkout raso (`fetch-depth: 1` no CI), branch alvo ausente ou erro no
`git log` reduzem o escopo sem avisar. Nesse caso, não trate o diff final
como se fosse o histórico: revise o que for possível e declare a lacuna na
linha de escopo (veja "Formato"). Um LIMPO que cobriu só o diff final
precisa dizer isso.

## O que reportar

1. **Dados pessoais**
   Nomes de pessoas reais (pacientes, profissionais, funcionários), e-mails,
   telefones, endereços, datas de nascimento.

2. **Identificadores**
   CPF, CNS, RG, CNPJ, CRM/CRF/COREN, número de prontuário, número de
   atendimento, matrícula, leito, qualquer ID que aponte para um indivíduo.

3. **Dados clínicos vinculados a uma pessoa identificável**
   Diagnóstico, prescrição, exame ou evolução junto de um identificador real.

4. **Infraestrutura**
   IPs, hostnames, registros DNS, domínios internos, endpoints privados,
   portas de serviços internos, connection strings, AWS account IDs, ARNs,
   nomes de bucket, fila, cluster, função Lambda ou secret, schemas do Postgres, entre outros.

5. **Identificação de clientes**
   Nome de hospital ou instituição cliente, nome de schema/tenant,
   subdomínio de cliente.

6. **Credenciais óbvias**
   Senha, token, chave ou certificado em texto claro.

## O que NÃO reportar

- `localhost`, `127.0.0.1`, `0.0.0.0`, `::1`
- Faixas de documentação: `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`
- `example.com`, `example.org`, `test.com`
- Placeholders: `<host>`, `${VAR}`, `xxx`, `foo`, `bar`, `John Doe`, `Fulano`,
  `usuario@dominio.com`
- Documentos claramente inválidos: `000.000.000-00`, `111.111.111-11`
- Referências a variáveis de ambiente, Secrets Manager, SSM ou `.env.example`
- Domínios públicos da NoHarm e de provedores (`noharm.ai`, `aws.amazon.com`)
- Arquivos de dependência, lockfiles, licenças e changelogs
- Linhas removidas (iniciadas por `-`), em qualquer commit
- Conteúdo de commits que já estão na branch alvo

## Regras de saída

- **Nunca reproduza o valor completo.** Mascare: `192.168.1.___`,
  `Maria S___`, `123.456.___-__`. O comentário do PR é visível no histórico —
  um achado de histórico não pode virar um novo vazamento.
- **Um achado por valor.** O mesmo valor em vários arquivos ou commits é um
  achado só: cite o commit em que entrou e agrupe os arquivos.
- **Presença de cada achado:**
  - **No HEAD** — o valor está no diff final do PR.
  - **Só no histórico** — foi adicionado e removido dentro da branch; não
    aparece no diff final, mas está nos commits.
  - **Mensagem de commit** — o valor está no texto de um commit.
- Máximo de 20 achados. Se passar disso, reporte os 20 mais graves e sinalize.
  Entre achados de mesma severidade, priorize credenciais e os "Só no
  histórico" — são os que um revisor humano não vê no diff.
- Na dúvida entre reportar e não reportar, reporte com severidade BAIXA.

## Correção sugerida por tipo de presença

A correção depende de onde o valor está, e para achados de histórico remover
a linha não resolve:

- **No HEAD:** remover o valor e movê-lo para variável de ambiente, Secrets
  Manager/SSM ou fixture com dado sintético. Se o valor também existe em
  commits anteriores da branch, vale a orientação de histórico abaixo.
- **Só no histórico ou Mensagem de commit:** reescrever o histórico da
  branch antes do merge (rebase interativo editando ou descartando o commit,
  ou squash + force-push) e não usar merge commit/rebase-merge enquanto o
  commit existir. Avise que as refs do PR no GitHub e clones já feitos podem
  manter o conteúdo; purga completa pode exigir suporte do GitHub.
- **Credencial em qualquer presença:** rotacionar imediatamente. Considere a
  credencial comprometida desde o primeiro push — reescrever o histórico
  não desfaz a exposição.

## Formato

A primeira linha é sempre a linha de status — é por ela que humanos e
automações localizam o resultado.

Se não houver nenhum achado:

DADOS SENSIVEIS STATUS: LIMPO
Revisados <n> arquivos, <m> linhas adicionadas em <k> commits (<base curto>..<head curto>).

A segunda linha importa: ela mostra o que foi coberto. Um LIMPO sem escopo não
distingue "revisei tudo e não achei nada" de "não consegui ler o diff".

Se o histórico não pôde ser lido, a segunda linha declara isso:

DADOS SENSIVEIS STATUS: LIMPO
Revisados <n> arquivos, <m> linhas adicionadas, somente diff final no commit <sha curto> — histórico da branch não disponível (<motivo>).

Caso contrário:

DADOS SENSIVEIS STATUS: ACHADOS (<n>)
Revisados <n> arquivos, <m> linhas adicionadas em <k> commits (<base curto>..<head curto>).

| Severidade | Presença | Commit | Arquivo:linha | Categoria | Valor (mascarado) | Correção sugerida |
|---|---|---|---|---|---|---|
| ALTA | No HEAD | `a1b2c3d` | src/api/user.py:42 | Identificador | `123.456.___-__` | Mover para fixture com dado sintético |
| ALTA | Só no histórico | `e4f5g6h` | config/db.py:10 | Credencial | `postgres://app:____@___` | Rotacionar a senha; reescrever o histórico antes do merge |
| MÉDIA | Mensagem de commit | `i7j8k9l` | — | Cliente | `Hospital S___` | Reescrever a mensagem do commit antes do merge |

Em "Arquivo:linha", para achados de histórico use a linha no commit indicado.

Severidade (igual para qualquer presença — sair do HEAD não reduz a gravidade):
- **ALTA** — dado pessoal real, dado clínico, credencial, infraestrutura interna
- **MÉDIA** — identificação de cliente, e-mail corporativo, domínio interno
- **BAIXA** — suspeita não confirmada pelo contexto

## Publicar o resultado

Publique o resultado como comentário no PR **em todos os casos**, inclusive — e
principalmente — quando for LIMPO.

Por que um LIMPO precisa virar comentário:

- Ausência de comentário é ambígua. Quem olha o PR depois não consegue separar
  "foi revisado e está limpo" de "o job quebrou", "a skill não disparou" ou
  "ninguém revisou". O comentário é o que torna a verificação verificável.
- Ele é o artefato de auditoria. Em repositórios que tocam dado de paciente,
  precisamos conseguir mostrar, meses depois, que aquele commit passou pela
  checagem. Esse histórico só existe se cada execução deixar registro.
- A revisora humana usa o LIMPO como sinal de que pode seguir. Sem ele, ela
  precisa refazer a checagem por conta própria.

Por isso, convenções gerais de "só comente quando houver algo acionável" não se
aplicam a esta skill. Aqui o LIMPO é acionável: ele é a evidência, e é o
resultado esperado na maioria das execuções. Uma execução silenciosa é uma
execução perdida.

Para não poluir o PR — que é a preocupação legítima por trás daquelas
convenções — siga estas regras em vez de omitir o comentário:

- **Um comentário por PR.** Se já existir um comentário seu começando com
  `DADOS SENSIVEIS STATUS:`, edite-o em vez de criar outro. O comentário deve
  sempre refletir o commit mais recente.
- **Não apague achados por force-push.** Ao editar o comentário, se um achado
  anterior aponta para um commit que não está mais na branch, mantenha-o com a
  presença `Fora da branch (force-push)`. O commit pode continuar acessível
  pelo SHA no GitHub, e se era credencial a rotação continua necessária. Ele
  só sai do comentário quando alguém confirmar no PR que a credencial foi
  rotacionada ou que o dado não era real. Enquanto houver achados assim, o
  status é ACHADOS, não LIMPO.
- **Mantenha o LIMPO curto.** Duas linhas: status e escopo revisado. Nada de
  resumo do PR, elogio ao código ou lista do que você procurou.
- **Notificação não substitui comentário.** Se o fluxo também dispara aviso em
  outro canal, ele é adicional. O comentário no PR é o registro primário.

Se você não tiver ferramenta para comentar no PR, devolva o bloco de resultado
na sua resposta, começando pela linha de status, e diga explicitamente que o
comentário não pôde ser publicado — assim a lacuna fica visível em vez de
silenciosa.
