import pytest


async def test_health_degraded_when_db_down(client):
    r = await client.get("/api/v1/health")
    # без доступной БД — 503 и никаких адресов/DSN в ответе
    if r.status_code == 503:
        assert r.json() == {"status": "degraded", "db": False}
        assert "postgresql" not in r.text and "localhost" not in r.text


@pytest.mark.integration
async def test_health_ok_with_real_db(client):
    r = await client.get("/api/v1/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": True}
