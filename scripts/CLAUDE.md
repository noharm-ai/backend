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

### Benchmark multi-schema: prompt v3, seed=42, 200 amostras, apenas conversões não-triviais

| Schema | Acurácia | Errado | Null |
|---|---|---|---|
| dasa_chn | **87.0%** | 10.5% | 2.5% |
| unimedbh | **85.5%** | 11.5% | 3.0% |
| beneficienciaportuguesa | **84.0%** | 6.5% | 9.5% |
| santacasasjc | **76.0%** | 16.5% | 7.5% |
| clinicaspoa | **76.0%** | 8.0% | 16.0% |
| azambuja | **75.5%** | 12.0% | 12.5% |
| fghsaude | **74.5%** | 13.5% | 12.0% |
| primavera | **69.5%** | 6.0% | 24.5% |
| **Média** | **~78%** | | |

Custo: ~$0.08/100 amostras com Haiku 4.5.

Resultados anteriores (histórico comparativo):

| Setup | Acurácia | Observação |
|---|---|---|
| prompt original sem few-shot, 100 amostras | 80% | inflado por fator=1 triviais |
| prompt few-shot + CoT v1, 500 amostras | 90% | inflado por fator=1 triviais |
| prompt v3, fator≠1, 8 schemas, 200 amostras | **~78%** | benchmark real, sem triviais |

Os 90% anteriores eram inflados — ~50% dos casos corretos eram âncoras triviais (`fator=1`) que o serviço já resolve sem LLM.

### Histórico de versões do prompt

| Versão | Mudança | Resultado |
|---|---|---|
| v1 | Prompt original sem few-shot | 80% (com triviais) |
| v2 | + few-shot + CoT (5 exemplos) | 90% (com triviais) |
| v3 | + exemplo 2b (UNIDADE como container, Xmg/YmL total content) | +3% fghsaude, +5% unimedbh vs v2 em amostras equivalentes |
| v4 | + regra X% + regra G dimensional | **Revertido** — regra G causou NULL em comprimidos simples (-7.5% azambuja) |
| v5 | + só regra X% (sem G) | **Revertido** — X% em Rule 2 ainda causava NULL excessivo (-7.5% azambuja) |

**Lição**: adicionar regras explícitas ao prompt de forma incremental é arriscado — regras longas tornam o modelo mais cauteloso em geral e causam NULL em casos simples. Exemplos few-shot são mais seguros do que regras textuais.

### Padrões de falha conhecidos (não resolvidos)

| Padrão | Exemplo | Causa |
|---|---|---|
| Soluções percentuais | NaCl 20% → pred=200mg/mL, exp=2000mg/10mL | Modelo lê `20%` como `20mg/mL` em vez de `200mg/mL` |
| Unidade `G` dimensional | Ceftriaxona 1g [G→mg]: pred=1, exp=1000 | Modelo não aplica 1g=1000mg |
| `MG/ML` como nome de unidade | Dexmedetomidina [MG/ML→mcg]: pred=1 | Schema usa `MG/ML` como nome de unidade; modelo não reconhece |
| Combo drugs | AMPICILINA+SULBACTAM 1G+500MG: pred=1500, exp=1000 | Modelo soma ambos os componentes |
| PT-BR número | "10.000 UI" → pred=10 | Modelo lê `.000` como decimal, não milhar |

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
Schemas maiores testados: `fghsaude` (5k drogas), `beneficienciaportuguesa` (2.4k), `primavera` (1.4k).
