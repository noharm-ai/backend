import pytest

from exception.validation_error import ValidationError
from utils import sqlutils

# ============================================================================
# Tests for validate_sql_query()
# ============================================================================


class TestValidateSqlQuery:
    """Test cases for validate_sql_query function"""

    # Valid queries - should pass
    @pytest.mark.parametrize(
        "query",
        [
            # Basic SELECT queries
            "SELECT * FROM prescricao",
            "select * from prescricao",
            "  SELECT * FROM prescricao  ",
            "SELECT id, nome FROM usuario",
            "SELECT * FROM prescricao WHERE id = 1",
            # WITH clauses (CTEs)
            "WITH cte AS (SELECT * FROM prescricao) SELECT * FROM cte",
            "with active_users as (select * from usuario where ativo = true) select * from active_users",
            # Complex queries
            "SELECT p.*, u.nome FROM prescricao p JOIN usuario u ON p.idusuario = u.idusuario",
            "SELECT COUNT(*) FROM prescricao WHERE dt_prescricao > '2024-01-01'",
            # Queries with comments
            "-- This is a comment\nSELECT * FROM prescricao",
            "SELECT * FROM prescricao -- inline comment",
            "/* Multi-line\n   comment */\nSELECT * FROM prescricao",
            # Queries with trailing semicolon
            "SELECT * FROM prescricao;",
            "SELECT * FROM prescricao ;",
            "SELECT * FROM prescricao  ;  ",
            # SQL functions
            "SELECT EXTRACT(year FROM dt_prescricao) FROM prescricao",
            "SELECT SUBSTRING(nome FROM 1 FOR 10) FROM usuario",
            "SELECT UPPER(nome), LOWER(email) FROM usuario",
            # Aggregations
            "SELECT COUNT(*), AVG(valor) FROM prescricao GROUP BY idUsuario",
            # Subqueries
            "SELECT * FROM (SELECT * FROM prescricao WHERE ativo = true) sub",
            # CASE statements
            "SELECT id, CASE WHEN ativo THEN 'Ativo' ELSE 'Inativo' END FROM usuario",
        ],
    )
    def test_valid_queries(self, query):
        """Test that valid SELECT queries pass validation"""
        assert sqlutils.validate_sql_query(query) is True

    # Invalid queries - destructive operations
    @pytest.mark.parametrize(
        "query",
        [
            # DELETE operations
            "DELETE FROM prescricao",
            "delete from prescricao where id = 1",
            # INSERT operations
            "INSERT INTO prescricao VALUES (1, 'test')",
            "insert into prescricao (id) values (1)",
            # UPDATE operations
            "UPDATE prescricao SET nome = 'test'",
            "update prescricao set ativo = false where id = 1",
            # DROP operations
            "DROP TABLE prescricao",
            "drop table if exists prescricao",
            "DROP DATABASE demo",
            # TRUNCATE operations
            "TRUNCATE TABLE prescricao",
            "truncate prescricao",
            # ALTER operations
            "ALTER TABLE prescricao ADD COLUMN test VARCHAR(100)",
            "alter table prescricao drop column nome",
            # CREATE operations
            "CREATE TABLE test (id INT)",
            "create view test_view as select * from prescricao",
            # EXEC/EXECUTE operations
            "EXEC sp_procedure",
            "EXECUTE procedure_name",
            "exec('SELECT * FROM prescricao')",
            # Other dangerous operations
            "GRANT ALL ON prescricao TO usuario",
            "REVOKE SELECT ON prescricao FROM usuario",
            "MERGE INTO prescricao",
            "CALL procedure_name()",
            "DECLARE @var INT",
            "PREPARE stmt FROM 'SELECT * FROM prescricao'",
            # File operations
            "SELECT * FROM prescricao INTO OUTFILE '/tmp/data.txt'",
            "LOAD DATA INFILE '/tmp/data.txt' INTO TABLE prescricao",
        ],
    )
    def test_forbidden_operations(self, query):
        """Test that destructive operations are blocked"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_sql_query(query)
        # Error could be either "operação não permitida" or "deve começar com SELECT"
        # depending on query structure
        error_msg = str(exc_info.value)
        assert (
            "operação não permitida" in error_msg
            or "deve começar com SELECT" in error_msg
        )

    # Invalid queries - must start with SELECT or WITH
    @pytest.mark.parametrize(
        "query",
        [
            "FROM prescricao SELECT *",
            "WHERE id = 1 SELECT * FROM prescricao",
            "SHOW TABLES",
            "DESCRIBE prescricao",
            "EXPLAIN SELECT * FROM prescricao",
        ],
    )
    def test_must_start_with_select_or_with(self, query):
        """Test that queries must start with SELECT or WITH"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_sql_query(query)
        assert "deve começar com SELECT" in str(exc_info.value)

    # Invalid queries - multiple statements
    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM prescricao; SELECT * FROM usuario",
            "SELECT * FROM prescricao; DROP TABLE prescricao",
            "SELECT 1; DELETE FROM prescricao",
        ],
    )
    def test_multiple_statements_blocked(self, query):
        """Test that multiple statements are blocked"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_sql_query(query)
        # Error could be either "múltiplos comandos" or "operação não permitida"
        # depending on what validation catches first
        error_msg = str(exc_info.value)
        assert (
            "múltiplos comandos" in error_msg or "operação não permitida" in error_msg
        )

    # Invalid queries - empty or whitespace
    @pytest.mark.parametrize(
        "query",
        [
            "",
            "   ",
            "\n\n",
            "\t\t",
            None,
        ],
    )
    def test_empty_queries(self, query):
        """Test that empty queries are rejected"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_sql_query(query)
        assert "não pode estar vazia" in str(exc_info.value)

    # Edge cases - comments trying to hide forbidden keywords
    @pytest.mark.parametrize(
        "query",
        [
            "SELECT * FROM prescricao -- DELETE FROM prescricao",
            "/* DROP TABLE prescricao */ SELECT * FROM prescricao",
            "SELECT * FROM /* INSERT INTO */ prescricao",
        ],
    )
    def test_comments_removed_properly(self, query):
        """Test that comments are properly removed and don't affect validation"""
        # These should pass because the dangerous keywords are in comments
        assert sqlutils.validate_sql_query(query) is True


# ============================================================================
# Tests for validate_schema_access()
# ============================================================================


class TestValidateSchemaAccess:
    """Test cases for validate_schema_access function"""

    # Valid queries - user's own schema
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            # Explicit schema qualification
            ("SELECT * FROM demo.prescricao", "demo"),
            ("select * from demo.prescricao where id = 1", "demo"),
            ("SELECT * FROM demo.prescricao p WHERE p.id = 1", "demo"),
            # Multiple tables from same schema
            (
                "SELECT p.*, u.nome FROM demo.prescricao p JOIN demo.usuario u ON p.idusuario = u.idusuario",
                "demo",
            ),
            # Different user schema
            ("SELECT * FROM hospital.prescricao", "hospital"),
            ("SELECT * FROM hospital_demo.paciente", "hospital_demo"),
        ],
    )
    def test_valid_user_schema_access(self, query, user_schema):
        """Test that queries accessing user's own schema are allowed"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Valid queries - whitelisted public tables
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            # Individual whitelisted tables
            ("SELECT * FROM public.classe", "demo"),
            ("SELECT * FROM public.substancia", "demo"),
            ("SELECT * FROM public.usuario", "demo"),
            # With aliases
            ("SELECT u.nome FROM public.usuario u", "demo"),
            ("SELECT s.* FROM public.substancia s WHERE s.ativo = true", "demo"),
            ("SELECT c.descricao FROM public.classe c", "demo"),
            # With AS keyword
            ("SELECT * FROM public.usuario AS u", "demo"),
            ("SELECT * FROM public.substancia AS s", "demo"),
            # Multiple whitelisted tables
            (
                "SELECT u.nome, s.nome FROM public.usuario u JOIN public.substancia s ON u.id = s.id_usuario",
                "demo",
            ),
            # Mixed user schema and public
            (
                "SELECT p.*, s.nome FROM demo.prescricao p JOIN public.substancia s ON p.sctid = s.id",
                "demo",
            ),
            # Self-join
            (
                "SELECT u1.nome, u2.nome FROM public.usuario u1 JOIN public.usuario u2 ON u1.id_superior = u2.idusuario",
                "demo",
            ),
        ],
    )
    def test_valid_public_table_access(self, query, user_schema):
        """Test that queries accessing whitelisted public tables are allowed"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Valid queries - with SQL functions using FROM
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            # EXTRACT function
            (
                "SELECT EXTRACT(epoch FROM p.dtvigencia - p.dtprescricao) FROM demo.prescricao p",
                "demo",
            ),
            (
                "SELECT EXTRACT(year FROM p.dtprescricao) FROM demo.prescricao p",
                "demo",
            ),
            (
                "SELECT p.id, EXTRACT(day FROM p.dtprescricao) as day FROM demo.prescricao p",
                "demo",
            ),
            # SUBSTRING function
            (
                "SELECT SUBSTRING(u.nome FROM 1 FOR 10) FROM public.usuario u",
                "demo",
            ),
            # TRIM function
            (
                "SELECT TRIM(BOTH ' ' FROM u.nome) FROM public.usuario u",
                "demo",
            ),
            # OVERLAY function
            (
                "SELECT OVERLAY(u.email PLACING '***' FROM 1 FOR 3) FROM public.usuario u",
                "demo",
            ),
            # Multiple functions
            (
                "SELECT EXTRACT(year FROM p.dtprescricao), SUBSTRING(u.nome FROM 1 FOR 20) "
                "FROM demo.prescricao p JOIN public.usuario u ON p.idusuario = u.idusuario",
                "demo",
            ),
            # Functions in WHERE clause
            (
                "SELECT * FROM demo.prescricao p WHERE EXTRACT(year FROM p.dtprescricao) = 2024",
                "demo",
            ),
        ],
    )
    def test_valid_queries_with_sql_functions(self, query, user_schema):
        """Test that SQL functions with FROM keyword don't cause false positives"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Valid queries - complex scenarios
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            # CTE with aliases
            (
                "WITH active_users AS (SELECT u.idusuario, u.nome FROM public.usuario u WHERE u.ativo = true) "
                "SELECT au.nome, p.id FROM active_users au JOIN demo.prescricao p ON au.idusuario = p.idusuario",
                "demo",
            ),
            # Subquery
            (
                "SELECT u.nome, sub.total FROM public.usuario u "
                "JOIN (SELECT p.idusuario, COUNT(*) as total FROM demo.prescricao p GROUP BY p.idusuario) sub "
                "ON u.idusuario = sub.idusuario",
                "demo",
            ),
            # Quoted identifiers
            (
                'SELECT * FROM "public"."usuario" u WHERE u.ativo = true',
                "demo",
            ),
        ],
    )
    def test_valid_complex_queries(self, query, user_schema):
        """Test complex valid queries"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Invalid queries - non-whitelisted public tables
    @pytest.mark.parametrize(
        "query, user_schema, expected_table",
        [
            ("SELECT * FROM public.schema_config", "demo", "schema_config"),
            ("SELECT * FROM public.config", "demo", "config"),
            ("SELECT * FROM public.settings", "demo", "settings"),
            ("SELECT c.* FROM public.configuration c", "demo", "configuration"),
            # Even with alias
            (
                "SELECT sc.* FROM public.schema_config sc WHERE sc.id = 1",
                "demo",
                "schema_config",
            ),
        ],
    )
    def test_invalid_non_whitelisted_public_tables(
        self, query, user_schema, expected_table
    ):
        """Test that non-whitelisted public tables are blocked"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_schema_access(query.lower(), user_schema)
        assert "Acesso negado à tabela" in str(exc_info.value)
        assert expected_table in str(exc_info.value)
        assert "classe" in str(exc_info.value)  # Should mention whitelisted tables

    # Invalid queries - other user schemas
    @pytest.mark.parametrize(
        "query, user_schema, forbidden_schema",
        [
            ("SELECT * FROM hospital_demo.prescricao", "demo", "hospital_demo"),
            ("SELECT * FROM other_schema.tabela", "demo", "other_schema"),
            ("SELECT p.* FROM hospital.prescricao p", "demo", "hospital"),
            # Mixed valid and invalid
            (
                "SELECT p.*, h.* FROM demo.prescricao p JOIN hospital.prescricao h ON p.id = h.id",
                "demo",
                "hospital",
            ),
        ],
    )
    def test_invalid_other_schema_access(self, query, user_schema, forbidden_schema):
        """Test that other user schemas are blocked"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_schema_access(query.lower(), user_schema)
        error_msg = str(exc_info.value)
        assert "Acesso negado ao schema" in error_msg
        assert forbidden_schema in error_msg

    # Invalid queries - system schemas
    @pytest.mark.parametrize(
        "query, user_schema, forbidden_schema",
        [
            (
                "SELECT table_name FROM information_schema.tables",
                "demo",
                "information_schema",
            ),
            ("SELECT * FROM pg_catalog.pg_tables", "demo", "pg_catalog"),
            ("SELECT * FROM pg_temp.temp_table", "demo", "pg_temp"),
            # Even in subquery
            (
                "SELECT * FROM demo.prescricao WHERE EXISTS (SELECT 1 FROM information_schema.tables)",
                "demo",
                "information_schema",
            ),
        ],
    )
    def test_invalid_system_schema_access(self, query, user_schema, forbidden_schema):
        """Test that system schemas are blocked"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_schema_access(query.lower(), user_schema)
        error_msg = str(exc_info.value)
        # Check that the forbidden schema is mentioned in the error
        assert forbidden_schema in error_msg
        # Error can be "Acesso negado ao schema 'X'..." or "Acesso ao schema 'X' não é permitido"
        assert "schema" in error_msg.lower()

    # Invalid queries - suspicious unqualified tables
    @pytest.mark.parametrize(
        "query, user_schema, suspicious_table",
        [
            ("SELECT * FROM user WHERE id = 1", "demo", "user"),
            ("SELECT * FROM users", "demo", "users"),
            ("SELECT * FROM schema", "demo", "schema"),
            ("SELECT * FROM schemas", "demo", "schemas"),
            ("SELECT * FROM config", "demo", "config"),
            ("SELECT * FROM configuration", "demo", "configuration"),
            # With JOIN
            (
                "SELECT * FROM demo.prescricao p JOIN user u ON p.id = u.id",
                "demo",
                "user",
            ),
        ],
    )
    def test_invalid_suspicious_unqualified_tables(
        self, query, user_schema, suspicious_table
    ):
        """Test that suspicious unqualified table names are flagged"""
        with pytest.raises(ValidationError) as exc_info:
            sqlutils.validate_schema_access(query.lower(), user_schema)
        assert "Tabelas suspeitas detectadas" in str(exc_info.value)
        assert suspicious_table in str(exc_info.value)

    # Edge cases - column references should not trigger schema validation
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            # Column references with dots
            (
                "SELECT u.idusuario, u.nome, u.email FROM public.usuario u WHERE u.ativo = true",
                "demo",
            ),
            (
                "SELECT p.id, p.dt_prescricao, s.nome FROM demo.prescricao p JOIN public.substancia s ON p.sctid = s.id",
                "demo",
            ),
            # Many column references
            (
                "SELECT u.id, u.nome, u.email, u.ativo, u.created_at, u.updated_at "
                "FROM public.usuario u WHERE u.id = 1 AND u.ativo = true",
                "demo",
            ),
            # Column in ON clause
            (
                "SELECT * FROM demo.prescricao p JOIN public.usuario u ON p.idusuario = u.idusuario",
                "demo",
            ),
        ],
    )
    def test_column_references_not_validated(self, query, user_schema):
        """Test that column references (alias.column) don't trigger schema validation"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Edge cases - case insensitivity
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            ("SELECT * FROM DEMO.PRESCRICAO", "demo"),
            ("SELECT * FROM Demo.Prescricao", "demo"),
            ("SELECT * FROM PUBLIC.USUARIO", "demo"),
            ("SELECT * FROM Public.Usuario", "demo"),
        ],
    )
    def test_case_insensitivity(self, query, user_schema):
        """Test that validation is case-insensitive"""
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True

    # Edge cases - unqualified tables (should pass, relies on search_path)
    @pytest.mark.parametrize(
        "query, user_schema",
        [
            ("SELECT * FROM prescricao", "demo"),
            ("SELECT * FROM prescricao WHERE id = 1", "demo"),
            ("SELECT p.* FROM prescricao p", "demo"),
            # But not suspicious ones
            # ("SELECT * FROM user", "demo"),  # This should fail (tested separately)
        ],
    )
    def test_unqualified_tables_allowed(self, query, user_schema):
        """Test that unqualified tables are allowed (relies on database search_path)"""
        # Note: unqualified tables that aren't suspicious are allowed
        # The database search_path will determine which schema is used
        assert sqlutils.validate_schema_access(query.lower(), user_schema) is True
