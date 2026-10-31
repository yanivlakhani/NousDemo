from fastapi.testclient import TestClient

from app import main


def test_cached_read_collapses_repeated_loads(monkeypatch):
    clock = iter((10.0, 10.0, 10.5, 13.0, 13.0, 13.0))
    monkeypatch.setattr(main, "monotonic", lambda: next(clock))
    main._read_cache.clear()
    calls = []

    def load():
        calls.append(True)
        return {"rows": [len(calls)]}

    first = main._cached_read("test", load, ttl=2.0)
    second = main._cached_read("test", load, ttl=2.0)
    third = main._cached_read("test", load, ttl=2.0)

    assert first == second == {"rows": [1]}
    assert third == {"rows": [2]}
    assert len(calls) == 2


def test_requests_report_application_timing():
    response = TestClient(main.app).get("/health")

    assert response.status_code == 200
    assert response.headers["server-timing"].startswith("app;dur=")
    assert float(response.headers["x-response-time-ms"]) >= 0
