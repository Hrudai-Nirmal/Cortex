"""Verify access scope remains a hard SQL boundary in the live retrieval path."""

from cortex.services.retrieval import LEXICAL_RETRIEVAL_SQL, VECTOR_RETRIEVAL_SQL


def testScopePredicatePrecedesRankingInAllRetrievalSql() -> None:
    """Authorization must remain inside the lexical/vector SQL rather than app memory."""
    for retrievalSql in (LEXICAL_RETRIEVAL_SQL, VECTOR_RETRIEVAL_SQL):
        assert "c.enterprise_id = :enterprise_id" in retrievalSql
        assert "ca.principal_id = ANY" in retrievalSql
        assert "dv.status = 'active'" in retrievalSql
        assert "JOIN document AS d" in retrievalSql
