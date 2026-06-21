"""Verify mandatory SQL scope predicates and bounded RRF behavior."""

import pytest
from cortex.errors import InputValidationError
from cortex.services.retrieval import (
    LEXICAL_RETRIEVAL_SQL,
    VECTOR_RETRIEVAL_SQL,
    RankedCandidate,
    fuseReciprocalRanks,
)


def testRetrievalSqlContainsScopeAndActiveVersionPredicates() -> None:
    """Both rankings must filter enterprise, ACL principals, and inactive versions in SQL."""
    for retrievalSql in (LEXICAL_RETRIEVAL_SQL, VECTOR_RETRIEVAL_SQL):
        assert "c.enterprise_id = :enterprise_id" in retrievalSql
        assert "ca.principal_id = ANY" in retrievalSql
        assert "dv.status = 'active'" in retrievalSql


def testRrfTruncatesBeforeReranking() -> None:
    """RRF may merge broad lists but must return no more than the cross-encoder boundary."""
    lexicalCandidates = [
        RankedCandidate(str(index), f"lexical {index}", 1.0) for index in range(100)
    ]
    vectorCandidates = [
        RankedCandidate(str(index), f"vector {index}", 1.0) for index in range(50, 150)
    ]

    fusedCandidates = fuseReciprocalRanks(lexicalCandidates, vectorCandidates, rerankTopK=40)

    assert len(fusedCandidates) == 40


def testRrfRejectsUnsafeCandidateLimit() -> None:
    """A pipeline cannot accidentally send hundreds of chunks to a local reranker."""
    with pytest.raises(InputValidationError, match="30-50"):
        fuseReciprocalRanks([], [], rerankTopK=200)
