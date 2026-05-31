# scripts/

## validate_unit_conversion_inference.py

Valida a acurácia do prompt de `get_llm_conversion_suggestions` (em `services/admin/admin_unit_conversion_service.py`) contra fatores de conversão já validados de um schema NoHarm.

### Como funciona

1. Conecta ao banco (réplica) e busca pares `(medicamento, unidade, fator)` do schema informado via `unidadeconverte`.
2. Agrupa por medicamento — um medicamento pode ter várias unidades (ml, FR, gotas...) e todas vão numa única chamada ao modelo.
3. Chama **Claude Opus 4.8** (Bedrock, `global.anthropic.claude-opus-4-8`) com o mesmo prompt do serviço, incluindo o campo `curadoria` da substância como contexto clínico.
4. Compara o fator predito com o fator armazenado (tolerância de 5%).
5. Imprime relatório com acurácia por caso.

### Uso

```bash
# rodada padrão: 30 amostras, seed 42, schema padrão
env/bin/python3 scripts/validate_unit_conversion_inference.py

# parâmetros explícitos
env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema meu_schema \
    --samples 50 \
    --seed 123

# dry-run: mostra os prompts sem chamar Bedrock
env/bin/python3 scripts/validate_unit_conversion_inference.py \
    --schema meu_schema --samples 10 --dry-run

# verbose: mostra resultado por unidade durante a execução
env/bin/python3 scripts/validate_unit_conversion_inference.py --verbose
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
| Claude Opus 4.8 | `global.anthropic.claude-opus-4-8` |

Trocar o modelo: use `--model <alias>` na linha de comando. Aliases disponíveis: `haiku`, `sonnet`, `opus`, `qwen3next`, `deepseekv32`, `kimik25`, `minimax21`, `minimax25`, `gptoss120b`.

Resultados com **prompt few-shot + CoT**, seed=42, 100 amostras, apenas drogas com substância vinculada:

| Modelo | Acurácia | Errado | Null | Input tok | Output tok | Custo/100 |
|---|---|---|---|---|---|---|
| **Kimi K2.5** | **88%** | 3% | 9% | 61,578 | 1,204 | $0.0406 |
| **GPT-OSS 120B** | **87%** | 1% | 5% | 59,864 | 19,866 | $0.0209 |
| **Haiku 4.5** | **91%** | 4% | 5% | 73,023 | 2,239 | $0.0842 |
| DeepSeek V3.2 | 82% | 8% | 10% | 60,766 | 1,712 | $0.0408 |
| Qwen3 Next 80B | 75% | 19% | 6% | 64,853 | 1,225 | $0.0112 |
| MiniMax M2.1 | 47% | 0% | 1% | 29,507 | 13,999 | $0.0257 |
| MiniMax M2.5 | 45% | 0% | 1% | 27,954 | 15,825 | $0.0274 |

Resultados com **prompt original** (sem few-shot), seed=42, 100 amostras:

| Modelo | Acurácia | Errado | Null | Input tok | Output tok | Custo/100 |
|---|---|---|---|---|---|---|
| Haiku 4.5 | 80% | 5% | 15% | 14,320 | 2,441 | $0.0265 |

Preços: perfil global sa-east-1 (São Paulo). MiniMax M2.1/M2.5 são reasoning models — output tokens muito maiores por causa do CoT interno.

### Interpretando os resultados

| Status | Significado |
|---|---|
| `OK` | Fator predito dentro de 5% do valor armazenado |
| `FALHOU` | Fator predito fora da tolerância — pode ser erro do prompt ou dado inconsistente no banco |
| `NULL` | Modelo não retornou fator para aquela unidade — informação insuficiente no nome do medicamento |
| `ERRO` | Falha na chamada ao Bedrock |

**Atenção:** fatores `FALHOU` nem sempre indicam erro do LLM. Alguns schemas armazenam o fator como "conteúdo total da embalagem" (ex: 600mg de ativo por bisnaga) em vez de "fração de embalagem" (ex: 0.0333 = 1/30g). Nesses casos o ground truth é inconsistente.

### Amostragem

A amostragem é por **medicamento** (não por par medicamento-unidade), garantindo diversidade de drogas. Com a mesma `--seed` o resultado é sempre reproduzível.
