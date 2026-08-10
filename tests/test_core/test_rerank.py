"""MMR reranking — five copies of one fact is not five facts.

The regression these guard against is subtle: a pure-relevance top-k can
return the same document five times, which the model reads as
corroboration rather than as repetition.
"""

from __future__ import annotations

from core.rerank import dedupe_near_identical, jaccard, mmr_rerank

_CLUSTER = [
    {
        "content": "The deploy failed because the migration was not applied",
        "score": 9.0,
    },
    {
        "content": "Deploy failed since the migration was not applied first",
        "score": 8.9,
    },
    {"content": "The deploy failed as migration was not applied at all", "score": 8.8},
    {"content": "Rate limits on the X API are 300 posts per 3 hours", "score": 6.0},
    {"content": "Vault password is required before browser login flows", "score": 5.0},
]


class TestJaccard:
    def test_identical_token_sets_are_one(self) -> None:
        assert jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0

    def test_disjoint_sets_are_zero(self) -> None:
        assert jaccard(frozenset({"a"}), frozenset({"b"})) == 0.0

    def test_empty_sets_are_zero(self) -> None:
        assert jaccard(frozenset(), frozenset({"a"})) == 0.0


class TestDedupe:
    def test_verbatim_duplicates_are_dropped(self) -> None:
        items = [
            {"content": "the migration was not applied before the deploy ran"},
            {"content": "the migration was not applied before the deploy ran"},
            {"content": "something entirely different about rate limits"},
        ]
        assert len(dedupe_near_identical(items)) == 2

    def test_distinct_content_survives(self) -> None:
        items = [
            {"content": "alpha beta gamma delta"},
            {"content": "epsilon zeta eta theta"},
        ]
        assert len(dedupe_near_identical(items)) == 2


class TestMMR:
    def test_top_result_is_still_the_most_relevant(self) -> None:
        out = mmr_rerank(_CLUSTER, limit=3)
        assert out[0]["content"] == _CLUSTER[0]["content"]

    def test_diversity_beats_a_third_near_duplicate(self) -> None:
        out = mmr_rerank(_CLUSTER, limit=3)
        deploy_hits = sum(1 for item in out if "deploy failed" in item["content"])
        assert deploy_hits < 3, "MMR should not return three copies of one fact"

    def test_lambda_one_is_pure_relevance(self) -> None:
        out = mmr_rerank(_CLUSTER, limit=3, lambda_=1.0)
        assert [i["content"] for i in out] == [i["content"] for i in _CLUSTER[:3]]

    def test_respects_the_limit(self) -> None:
        assert len(mmr_rerank(_CLUSTER, limit=2)) == 2

    def test_empty_and_degenerate_inputs(self) -> None:
        assert mmr_rerank([], limit=5) == []
        assert mmr_rerank(_CLUSTER, limit=0) == []
        single = [{"content": "one", "score": 1.0}]
        assert mmr_rerank(single, limit=5) == single

    def test_zero_scores_do_not_divide_by_zero(self) -> None:
        items = [{"content": f"item {i}", "score": 0.0} for i in range(4)]
        assert len(mmr_rerank(items, limit=2)) == 2

    def test_every_returned_item_came_from_the_input(self) -> None:
        out = mmr_rerank(_CLUSTER, limit=5)
        originals = {i["content"] for i in _CLUSTER}
        assert all(item["content"] in originals for item in out)
        assert len({id(i) for i in out}) == len(out), "no duplicates in output"
