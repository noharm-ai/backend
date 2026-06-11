# scripts/

## validate_unit_conversion_inference.py

Valida a acurácia do prompt de `get_llm_conversion_suggestions` (em `services/admin/admin_unit_conversion_service.py`) contra fatores de conversão já validados de um schema NoHarm.

### Como funciona

1. Conecta ao banco (réplica) e busca pares `(medicamento, unidade, fator)` via CTE `conversoes_padrao` — a mesma lógica usada pelo pipeline de ML clássico.
2. Filtra apenas drogas de **Convenção A** (ver seção abaixo) e exclui fatores triviais (`fator = 1`).
3. Agrupa por medicamento — um medicamento pode ter várias unidades (ml, FR, gotas...) e todas vão numa única chamada ao modelo.
4. Chama **Claude Haiku 4.5** (Bedrock Converse API) com o mesmo prompt do serviço.
5. Compara o fator predito com o fator armazenado (tolerância de 5%).
6. Imprime relatório com acurácia por caso.

### Uso

```bash
# rodada padrão: 30 amostras, seed 42, schema padrão
env/bin/python3 scripts/validate_unit_conversion_inference.py

# parâmetros explícitos
env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema meu_schema \
    --samples 200 \
    --seed 42

# dry-run: mostra os prompts sem chamar Bedrock
env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema meu_schema --samples 10 --dry-run

# verbose: mostra resultado por unidade durante a execução
env/bin/python3 scripts/validate_unit_conversion_inference.py --verbose

# salva casos FALHOU e NULL em JSON para análise de falhas
env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema meu_schema --samples 200 --save-failures scripts/failures.json

# rodar 4 schemas em paralelo
for schema in meu_schema_a meu_schema_b meu_schema_c meu_schema_d; do
  env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema $schema --samples 200 --seed 42 --model haiku \
    --save-failures scripts/failures_${schema}.json \
    2>&1 | tee scripts/run_${schema}.log &
done
wait
```

### Variáveis de ambiente

Lidas do `.env` na raiz do projeto (ou do ambiente):

| Variável | Descrição |
|---|---|
| `DB_HOST` | Host do banco (réplica) |
| `DB_PORT` | Porta (padrão: 5432) |
| `DB_NAME` | Nome do banco |
| `DB_USER` | Usuário |
| `DB_PASSWORD` | Senha |

Credenciais AWS para Bedrock seguem a cadeia padrão do boto3 (`~/.aws/credentials`, variáveis de ambiente, IAM role).

### Modelos disponíveis (Bedrock inference profiles)

| Modelo | ID |
|---|---|
| Claude Haiku 4.5 | `global.anthropic.claude-haiku-4-5-20251001-v1:0` |
| Claude Sonnet 4.6 | `global.anthropic.claude-sonnet-4-6` |
| Claude Opus 4.8 | `global.anthropic.claude-opus-4-8` |

Trocar o modelo: use `--model <alias>` na linha de comando. Aliases disponíveis: `haiku`, `sonnet`, `opus`, `qwen3next`, `deepseekv32`, `kimik25`, `minimax21`, `minimax25`, `gptoss120b`.

### Convenção A vs Convenção B

Schemas NoHarm usam duas convenções para armazenar fatores de conversão:

| Convenção | Comportamento | Exemplo |
|---|---|---|
| **A** | `fator` = conteúdo farmacológico real | AZITROMICINA 500mg, COMPRIMIDO→mg: `fator=500` |
| **B** | `fator=1` para todos os containers | AZITROMICINA 500mg, COMPRIMIDO→mg: `fator=1` |

O script filtra automaticamente para Convenção A usando a CTE `conversoes_padrao`:
```sql
-- âncora Convenção A: unidade onde fator=1 E unidademedida_nh = unidadepadrao da substância
WHERE uc.fator = 1
  AND um.unidademedida_nh IS NOT NULL
  AND s.unidadepadrao = um.unidademedida_nh
```
Drogas sem âncora Convenção A são excluídas. O campo `unidademedida_nh` da tabela `{schema}.unidademedida` é o discriminador — schemas Convenção B têm `unidademedida_nh='unidade'` nos containers, nunca igual a `unidadepadrao` da substância.

Adicionalmente, fatores `= 1` são excluídos da validação porque:
- O serviço já retorna `prediction=1` para unidades âncora automaticamente (nunca chama o LLM)
- Incluí-los inflacionava a acurácia em até 71% (casos triviais)

### Benchmark multi-schema: prompt v6, seed=42, 200 amostras, apenas conversões não-triviais

| Schema | Acurácia | Errado | Null |
|---|---|---|---|
| schema1 | **91.0%** | 6.0% | 3.0% |
| schema2 | **90.5%** | 6.5% | 3.0% |
| schema3 | **88.0%** | 9.0% | 3.0% |
| schema4 | **87.0%** | 9.0% | 4.0% |
| schema5 | **85.0%** | 9.0% | 6.0% |
| schema6 | **79.0%** | 7.5% | 13.5% |
| schema7 | **78.5%** | 8.5% | 13.0% |
| schema8 | **77.0%** | 7.0% | 16.0% |
| **Média** | **~84.5%** | | |

Custo: ~$0.08/100 amostras com Haiku 4.5.

Resultados históricos (histórico comparativo com linha de base pós-filtro válida):

| Setup | Acurácia | Observação |
|---|---|---|
| prompt original sem few-shot, 100 amostras | 80% | inflado por fator=1 triviais |
| prompt few-shot + CoT v1, 500 amostras | 90% | inflado por fator=1 triviais |
| prompt v3, fator≠1, 4 schemas, 200 amostras | **~76.9%** | baseline pós-filtro real (beneficienciaportuguesa 83%, fghsaude 72.5%, primavera 67%, unimedbh 85%) |
| prompt v6, fator≠1, 8 schemas, 200 amostras | **~84.5%** | +6.4% vs v3 nos 4 schemas com baseline válido |

Os 90% anteriores eram inflados — ~50% dos casos corretos eram âncoras triviais (`fator=1`) que o serviço já resolve sem LLM.

### Histórico de versões do prompt

| Versão | Mudança | Resultado |
|---|---|---|
| v1 | Prompt original sem few-shot | 80% (com triviais) |
| v2 | + few-shot + CoT (5 exemplos) | 90% (com triviais) |
| v3 | + exemplo 2b (UNIDADE como container, Xmg/YmL total content) | +3% schema7, +5% schema2 vs v2 em amostras equivalentes |
| v4 | + regra X% + regra G dimensional | **Revertido** — regra G causou NULL em comprimidos simples (-7.5% schema6) |
| v5 | + só regra X% (sem G) | **Revertido** — X% em Rule 2 ainda causava NULL excessivo (-7.5% schema6) |
| v6 | + exemplos 6 (BOLSA/FA/UNIDADE como container c/ volume explícito), 7 (prefixo NP/NAO PADRAO), 8 (AMPOLA YmL confirma total) + FA/BOLSA/AMPOLA na Rule 1 | **+6.4% médio** — validação cruzada em 4 schemas, sem regressões |

**Lição**: adicionar regras explícitas ao prompt de forma incremental é arriscado — regras longas tornam o modelo mais cauteloso em geral e causam NULL em casos simples. Exemplos few-shot são mais seguros do que regras textuais.

**Abordagem de validação cruzada**: para cada novo exemplo, rodar baseline v3 no mesmo pool filtrado (seed=42, 200 amostras) antes de comparar. Pools pré-filtro e pós-filtro geram amostras diferentes (diferença de até 25% nos schemas com muitas âncoras), invalidando a comparação direta.

### Padrões de falha conhecidos (não resolvidos)

| Padrão | Exemplo | Causa |
|---|---|---|
| Soluções percentuais | NaCl 20% → pred=200mg/mL, exp=2000mg/10mL | Modelo lê `20%` como `20mg/mL` em vez de `200mg/mL` |
| Unidade `G` dimensional | Ceftriaxona 1g [G→mg]: pred=1, exp=1000 | Modelo não aplica 1g=1000mg |
| `MG/ML` como nome de unidade | Dexmedetomidina [MG/ML→mcg]: pred=1 | Schema usa `MG/ML` como nome de unidade; modelo não reconhece |
| Combo drugs | AMPICILINA+SULBACTAM 1G+500MG: pred=1500, exp=1000 | Modelo soma ambos os componentes |
| PT-BR número | "10.000 UI" → pred=10 | Modelo lê `.000` como decimal, não milhar |
| NP sem dose explícita | NP: AC VALPROICO 500 → pred=50 | Nome sem "MG" — modelo incerto sobre a unidade do número |

### Padrões resolvidos em v6

| Padrão | Solução |
|---|---|
| BOLSA/FA → NULL (volume explícito no nome) | Exemplo 6: LEVOFLOXACINO 5MG/ML BOLSA 100ML → FA/BOLSA=500 |
| UNIDADE → NULL (container c/ concentração×volume) | Exemplo 6 + FA/BOLSA adicionados à Rule 1 |
| NP:/NAO PADRAO → F=1 em comprimidos | Exemplo 7: NP: BUSPIRONA 10MG → UNIDADE=10 |
| AMPOLA 5ML → F=1250 (trata como /mL) | Exemplo 8: 250MG/5ML AMPOLA 5ML → F=250 (total), não 1250 |

### Interpretando os resultados

| Status | Significado |
|---|---|
| `OK` | Fator predito dentro de 5% do valor armazenado |
| `FALHOU` | Fator predito fora da tolerância — pode ser erro do prompt ou dado inconsistente no banco |
| `NULL` | Modelo não retornou fator para aquela unidade — informação insuficiente no nome do medicamento |
| `ERRO` | Falha na chamada ao Bedrock |

`FALHOU` nem sempre indica erro do LLM — alguns schemas têm ground truth inconsistente. `NULL` é comportamento correto quando o nome não tem informação suficiente.

### Amostragem

A amostragem é por **medicamento** (não por par medicamento-unidade), garantindo diversidade de drogas. Com a mesma `--seed` o resultado é sempre reproduzível.

Para encontrar schemas com mais medicamentos em Convenção A:
```sql
SELECT sc.schema_name, COUNT(DISTINCT uc.fkmedicamento) AS drugs_conv_a
FROM public.schema_config sc
-- JOIN com a query CTE por schema para contar drogas elegíveis
WHERE sc.status = 1
  AND sc.schema_name NOT LIKE 'pec_%'
  AND sc.schema_name NOT LIKE 'ebserh%'
ORDER BY drugs_conv_a DESC;
```
Schemas maiores testados tiveram entre 1.4k e 5k drogas em Convenção A.
