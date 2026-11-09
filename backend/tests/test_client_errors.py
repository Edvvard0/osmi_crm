from app.api.v1 import client_errors


async def test_client_error_logged_204(client):
    client_errors.limiter.reset()
    r = await client.post("/api/v1/client-errors", json={"message": "boom", "kind": "onerror"})
    assert r.status_code == 204 and r.content == b""


async def test_client_error_rejects_extra_and_markup(client):
    r = await client.post("/api/v1/client-errors", json={"message": "x", "evil": 1})
    assert r.status_code == 422
    r = await client.post("/api/v1/client-errors", json={"message": "<script>x</script>"})
    assert r.status_code == 422


async def test_client_error_message_too_long(client):
    r = await client.post("/api/v1/client-errors", json={"message": "a" * 501})
    assert r.status_code == 422


async def test_client_error_rate_limit(client):
    client_errors.limiter.reset()
    codes = [
        (await client.post("/api/v1/client-errors", json={"message": "m"})).status_code
        for _ in range(25)
    ]
    assert codes.count(204) == 20 and codes[-1] == 429
    client_errors.limiter.reset()


async def test_markup_error_code_is_specific_and_not_echoed(client):
    r = await client.post("/api/v1/client-errors", json={"message": "<img src=x onerror=alert(1)>"})
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"message": "markup_not_allowed"}
    assert "onerror" not in r.text and "img" not in r.text
