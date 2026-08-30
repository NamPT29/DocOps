import pytest
from fakeredis import FakeRedis

from server.services.template_cache_service import TemplateArtifactCache


def test_shared_cache_hits_across_workers_and_invalidates_by_revision():
    redis = FakeRedis(decode_responses=True)
    first_worker = TemplateArtifactCache(redis_client=redis, ttl_seconds=60)
    second_worker = TemplateArtifactCache(redis_client=redis, ttl_seconds=60)
    calls = []

    value = first_worker.get_or_compute(
        "schema",
        7,
        "100-2048",
        lambda: calls.append("load") or {"status": "ok", "data": ["field"]},
    )
    shared = second_worker.get("schema", 7, "100-2048")

    assert shared == value
    assert calls == ["load"]
    assert first_worker.metrics()["misses"] == 1
    assert second_worker.metrics()["hits"] == 1

    first_worker.invalidate(7)

    assert second_worker.get("schema", 7, "100-2048") is None
    assert second_worker.metrics()["misses"] == 1


def test_local_fallback_is_versioned_and_only_caches_successful_values():
    cache = TemplateArtifactCache(ttl_seconds=60)
    attempts = []

    def fail_once():
        attempts.append("failed")
        raise RuntimeError("loader failed")

    with pytest.raises(RuntimeError, match="loader failed"):
        cache.get_or_compute("maxa_mapping", 3, "v1", fail_once)

    loaded = cache.get_or_compute(
        "maxa_mapping",
        3,
        "v1",
        lambda: attempts.append("loaded") or {"mapping_3_cap": {}},
    )

    assert cache.get("maxa_mapping", 3, "v1") is loaded
    assert cache.get("maxa_mapping", 3, "v2") is None
    assert attempts == ["failed", "loaded"]
    assert cache.metrics() == {
        "hits": 1,
        "misses": 3,
        "writes": 1,
        "invalidations": 0,
        "backend_errors": 0,
    }


def test_cache_rejects_namespaces_that_could_hold_user_or_auth_data():
    cache = TemplateArtifactCache(ttl_seconds=60)

    with pytest.raises(ValueError, match="Unsupported template cache namespace"):
        cache.set("user", 1, "v1", {"token": "secret"})
