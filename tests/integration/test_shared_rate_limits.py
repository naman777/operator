from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError

from operator_api.db import Base, RateLimitBucket, database
from operator_api.main import create_app
from operator_api.rate_limits import DatabaseWindowLimiter, Limit


def test_atomic_shared_windows_and_expired_cleanup(tmp_path):
    engine, _ = database(f"sqlite:///{tmp_path / 'buckets.db'}")
    Base.metadata.create_all(engine)
    clock = [120]
    first = DatabaseWindowLimiter(engine, clock=lambda: clock[0])
    second = DatabaseWindowLimiter(engine, clock=lambda: clock[0])
    limit = Limit("test", 5, 60)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: (first if i % 2 else second).check("hashed", limit), range(16)))
    assert sum(result[0] for result in results) == 5
    assert all(result[2] == 60 for result in results if not result[0])
    assert second.check("different", limit)[0]
    clock[0] = 180
    assert first.check("hashed", limit) == (True, 4, 0)
    with engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(RateLimitBucket)) == 1
    engine.dispose()


def test_two_api_instances_share_limits_and_ignore_spoofed_forwarding(tmp_path):
    url = f"sqlite:///{tmp_path / 'shared.db'}"
    with TestClient(create_app(url, {"guest": 1})) as first:
        assert first.post("/v1/guest-sessions").status_code == 201
        with TestClient(create_app(url, {"guest": 1})) as second:
            response = second.post("/v1/guest-sessions", headers={"X-Forwarded-For": "203.0.113.1"})
            assert response.status_code == 429
            assert int(response.headers["Retry-After"]) > 0


def test_costly_routes_are_limited_before_parsing_or_fetching(tmp_path):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'cost.db'}", {"upload": 1, "import": 1})) as client:
        token = client.post("/v1/guest-sessions").json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/v1/profile/documents", headers=headers, json={}).status_code == 422
        assert client.post("/v1/profile/documents/upload", headers=headers).status_code == 429
        assert client.post("/v1/opportunities/import", headers=headers, json={}).status_code == 422
        assert client.post("/v1/opportunities/import", headers=headers, json={}).status_code == 429
        assert client.get("/v1/profile", headers=headers).status_code == 200


def test_admission_storage_failure_is_closed_but_health_remains_available(tmp_path, monkeypatch):
    with TestClient(create_app(f"sqlite:///{tmp_path / 'failure.db'}")) as client:

        def fail(*args):
            raise OperationalError("private statement", {}, Exception("private credentials"))

        monkeypatch.setattr(DatabaseWindowLimiter, "check", fail)
        response = client.post("/v1/guest-sessions")
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "5"
        assert "private" not in response.text
        assert client.get("/health/ready").status_code == 200
