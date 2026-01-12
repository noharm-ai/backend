"""Utils for SQL queries validation."""

import re

from exception.validation_error import ValidationError
from utils import status


def validate_sql_query(sql: str):
    """
    Validate SQL query to prevent destructive operations.
    Only SELECT queries are allowed.
    """
    if not sql or not sql.strip():
        raise ValidationError(
            "Query SQL não pode estar vazia",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    # Remove comments and normalize whitespace
    sql_clean = re.sub(r"--[^\n]*", "", sql)  # Remove single-line comments
    sql_clean = re.sub(
        r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL
    )  # Remove multi-line comments
    sql_clean = sql_clean.lower().strip()

    # List of forbidden SQL keywords/operations
    forbidden_keywords = [
        r"\bdelete\b",
        r"\bdrop\b",
        r"\btruncate\b",
        r"\binsert\b",
        r"\bupdate\b",
        r"\balter\b",
        r"\bcreate\b",
        r"\breplace\b",
        r"\bmerge\b",
        r"\bgrant\b",
        r"\brevoke\b",
        r"\bexec\b",
        r"\bexecute\b",
        r"\bcall\b",
        r"\binto\s+outfile\b",
        r"\bload\s+data\b",
        r"\bload_file\b",
        r"\bcopy\b",
        r"\bimport\b",
        r"\bset\s+",
        r"\bdeclare\b",
        r"\bprepare\b",
        r"\bshutdown\b",
        r"\bkill\b",
    ]

    # Check for forbidden keywords
    for keyword_pattern in forbidden_keywords:
        if re.search(keyword_pattern, sql_clean):
            raise ValidationError(
                "Query SQL contém operação não permitida. Apenas SELECT é permitido.",
                "errors.invalidSQL",
                status.HTTP_400_BAD_REQUEST,
            )

    # Ensure query starts with SELECT or WITH
    if not re.match(r"^\s*(select|with)\b", sql_clean):
        raise ValidationError(
            "Query SQL deve começar com SELECT",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    # Check for semicolons (potential SQL injection with multiple statements)
    if ";" in sql_clean.rstrip(";"):  # Allow trailing semicolon
        raise ValidationError(
            "Query SQL não pode conter múltiplos comandos (;)",
            "errors.invalidSQL",
            status.HTTP_400_BAD_REQUEST,
        )

    return True


def validate_schema_access(sql: str, user_schema: str):
    """
    Validate that the query only accesses tables from the user's schema
    or specific whitelisted tables from the public schema.

    Allowed public tables: classe, descricao_enum, substancia, usuario
    """
    # Whitelisted public schema tables
    ALLOWED_PUBLIC_TABLES = {"classe", "descricao_enum", "substancia", "usuario"}

    # Pattern to extract schema-qualified table references in FROM/JOIN clauses
    # This matches schema.table only when it appears after FROM or JOIN keywords
    # at the table reference position (not inside function calls like EXTRACT(epoch FROM ...))
    # Matches patterns like: FROM schema.table, JOIN schema.table AS alias
    qualified_table_pattern = (
        r"\b(?:from|join)\s+(?:(?:inner|left|right|full|cross)\s+(?:outer\s+)?join\s+)?"
        r'([a-z_][a-z0-9_]*|"[^"]+")\.([a-z_][a-z0-9_]*|"[^"]+")'
        r"(?:\s+(?:as\s+)?[a-z_][a-z0-9_]*)?"
    )

    # Find all schema-qualified table references in FROM/JOIN clauses
    all_matches = re.findall(qualified_table_pattern, sql)

    # Filter out matches that are inside function calls (e.g., EXTRACT(... FROM ...))
    # by checking if they appear after function names followed by opening parenthesis
    qualified_matches = []
    for match in all_matches:
        # Reconstruct the full match pattern to find its position
        schema_part, table_part = match
        full_pattern = f"{schema_part}.{table_part}"

        # Find all occurrences of this schema.table pattern
        for m in re.finditer(re.escape(full_pattern), sql):
            pos = m.start()
            # Look backwards to see if this is inside a function call
            # Check for function patterns like: function_name(... FROM schema.table
            preceding_text = sql[max(0, pos - 100) : pos]

            # If we find a function name + opening paren before FROM, skip this match
            # Common functions that use FROM: EXTRACT, SUBSTRING, TRIM, OVERLAY
            if re.search(
                r"\b(?:extract|substring|trim|overlay)\s*\([^)]*$",
                preceding_text,
                re.IGNORECASE,
            ):
                continue

            # Otherwise, this is a valid table reference
            qualified_matches.append(match)
            break  # Only process first occurrence of each pattern

    for schema_part, table_part in qualified_matches:
        # Remove quotes if present
        schema_name = schema_part.strip('"').lower()
        table_name = table_part.strip('"').lower()

        # Check if schema is allowed
        if schema_name == "public":
            if table_name not in ALLOWED_PUBLIC_TABLES:
                raise ValidationError(
                    f"Acesso negado à tabela public.{table_name}. "
                    f"Apenas as seguintes tabelas públicas são permitidas: {', '.join(sorted(ALLOWED_PUBLIC_TABLES))}",
                    "errors.unauthorizedSchemaAccess",
                    status.HTTP_400_BAD_REQUEST,
                )
        elif schema_name != user_schema.lower():
            raise ValidationError(
                f"Acesso negado ao schema '{schema_name}'. "
                f"Apenas o schema '{user_schema}' e tabelas específicas do schema 'public' são permitidos.",
                "errors.unauthorizedSchemaAccess",
                status.HTTP_400_BAD_REQUEST,
            )

    # Pattern to detect unqualified table references that might be targeting other schemas
    # Look for FROM/JOIN clauses to extract table names
    table_reference_pattern = r'\b(?:from|join)\s+([a-z_][a-z0-9_]*|"[^"]+")\b'
    unqualified_matches = re.findall(table_reference_pattern, sql)

    # Check if there are suspicious patterns that might indicate schema manipulation
    # Detect information_schema or pg_catalog access attempts
    forbidden_schemas = ["information_schema", "pg_catalog", "pg_temp"]
    for forbidden_schema in forbidden_schemas:
        if forbidden_schema in sql:
            raise ValidationError(
                f"Acesso ao schema '{forbidden_schema}' não é permitido",
                "errors.unauthorizedSchemaAccess",
                status.HTTP_400_BAD_REQUEST,
            )

    # Warn if there are many unqualified table references (potential risk)
    # This is a soft check - the database will use the search_path which should be set to user's schema
    if len(unqualified_matches) > 0:
        # Extract unique table names
        unqualified_tables = {match.strip('"').lower() for match in unqualified_matches}

        # Check if any unqualified tables match forbidden public table patterns
        # (tables that exist in public but aren't whitelisted)
        potentially_dangerous = {
            "user",
            "users",
            "schema",
            "schemas",
            "config",
            "configuration",
        }
        dangerous_tables = unqualified_tables.intersection(potentially_dangerous)

        if dangerous_tables:
            raise ValidationError(
                f"Tabelas suspeitas detectadas: {', '.join(dangerous_tables)}. "
                f"Use qualificação explícita de schema (ex: {user_schema}.tabela ou public.classe)",
                "errors.suspiciousTableAccess",
                status.HTTP_400_BAD_REQUEST,
            )

    return True
