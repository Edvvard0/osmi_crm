async def test_unhandled_error_is_hidden(client):
    r = await client.get("/_boom")
    assert r.status_code == 500
    body = r.json()["error"]
    assert body["code"] == "internal_error"
    assert body["request_id"] and r.headers["x-request-id"] == body["request_id"]
    text = r.text
    assert "hunter2" not in text and "Traceback" not in text and "RuntimeError" not in text


async def test_db_integrity_error_does_not_leak(client):
    r = await client.get("/_integrity")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "unique_violation"
    assert "uq_customers_phone" not in r.text and "INSERT" not in r.text


async def test_validation_error_has_no_input_echo(client):
    r = await client.post("/_echo", json={"a": "<script>alert(1)</script>"})
    assert r.status_code == 422
    assert "script" not in r.text and "alert" not in r.text
    assert r.json()["error"]["code"] == "validation_error"
    assert "a" in r.json()["error"]["fields"]


async def test_404_uses_common_format(client):
    r = await client.get("/api/v1/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_body_limit(client):
    r = await client.post(
        "/_echo", content=b"x" * 2_000_000, headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "payload_too_large"


async def test_request_id_from_client_is_sanitized(client):
    r = await client.get("/api/v1/nope", headers={"x-request-id": "bad\r\nvalue"})
    assert "\n" not in r.headers["x-request-id"]


async def test_docs_available_in_dev(client):
    assert (await client.get("/api/docs")).status_code == 200


async def test_docs_disabled_in_prod(prod_client):
    for path in ("/api/docs", "/api/redoc", "/openapi.json"):
        assert (await prod_client.get(path)).status_code == 404


async def test_no_server_headers(prod_client):
    r = await prod_client.get("/api/v1/nope")
    assert "server" not in r.headers and "x-powered-by" not in r.headers
