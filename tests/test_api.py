"""HTTP API smoke tests through the Flask test client."""

from __future__ import annotations


def test_health_and_overview(client):
    health = client.get("/api/health").get_json()["data"]
    assert health["ready"] is False
    assert health["missing"]

    overview = client.get("/api/overview").get_json()["data"]
    assert overview["datasets"] == 0
    assert client.get("/").status_code == 200


def test_about_and_open_allowlist(client):
    about = client.get("/api/about").get_json()["data"]
    assert about["stage"] == "beta"
    assert about["repo"] == "https://github.com/jasonjimnz/minics"
    assert about["docs"].startswith("https://jasonjimnz.github.io/")

    # Only project-owned https hosts may be opened in the system browser.
    blocked = client.post("/api/about/open", json={"url": "https://evil.example.com"})
    assert blocked.status_code == 403
    assert client.post("/api/about/open", json={"url": "http://github.com/jasonjimnz/minics"}).status_code == 403


def test_dataset_and_entry_endpoints(client):
    created = client.post("/api/datasets", json={"name": "Support QA"}).get_json()["data"]
    dataset_ref = created["public_id"]
    assert created["slug"] == "support-qa"

    assert client.get("/api/datasets").get_json()["data"]["total"] == 1

    entry = client.post(
        "/api/entries",
        json={"dataset": dataset_ref, "system": "be nice", "user": "hi", "assistant": "hello"},
    ).get_json()["data"]
    entry_ref = entry["public_id"]
    assert entry["evaluation"] is None

    listing = client.get(f"/api/entries?dataset={dataset_ref}").get_json()["data"]
    assert listing["total"] == 1

    detail = client.get(f"/api/entries/{entry_ref}").get_json()["data"]
    assert detail["validation"]["valid"] is True

    updated = client.patch(
        f"/api/entries/{entry_ref}", json={"status": "approved"}
    ).get_json()["data"]
    assert updated["status"] == "approved"

    assert client.get(f"/api/datasets/{dataset_ref}/stats").get_json()["data"]["approved"] == 1
    assert client.get("/api/entries/nope").status_code == 404

    assert client.delete(f"/api/entries/{entry_ref}").get_json()["data"]["deleted"] is True
    assert client.delete(f"/api/datasets/{dataset_ref}").get_json()["data"]["deleted"] is True


def test_collection_export_endpoint(client):
    dataset = client.post("/api/datasets", json={"name": "FAQ"}).get_json()["data"]
    entry = client.post(
        "/api/entries",
        json={"dataset": dataset["public_id"], "user": "2+2?", "assistant": "4."},
    ).get_json()["data"]
    collection = client.post(
        "/api/collections", json={"name": "Set", "entry_ids": [entry["id"]]}
    ).get_json()["data"]

    response = client.get(f"/api/collections/{collection['public_id']}/export?format=alpaca")
    assert response.status_code == 200
    assert '"output": "4."' in response.get_data(as_text=True)

    assert client.get("/api/collections").get_json()["data"]["formats"]


def test_document_endpoints(client):
    response = client.post(
        "/api/documents",
        json={"title": "Note", "markdown": "# Note\n\nSome content.", "index": False},
    )
    assert response.status_code == 202
    document = response.get_json()["data"]["document"]
    assert document["status"] == "ready"

    fetched = client.get(f"/api/documents/{document['public_id']}").get_json()["data"]
    assert "Some content" in fetched["markdown"]

    saved = client.put(
        f"/api/documents/{document['public_id']}/markdown",
        json={"markdown": "# Note\n\nUpdated.", "reindex": False},
    ).get_json()["data"]
    assert saved["document"]["public_id"] == document["public_id"]
    assert client.get("/api/documents/supported").get_json()["data"]["extensions"]


def test_jobs_and_events(client):
    jobs = client.get("/api/jobs").get_json()["data"]
    assert jobs["active"] == 0

    events = client.get("/api/events/history").get_json()["data"]
    assert isinstance(events["items"], list)


def test_config_endpoints(client):
    config = client.get("/api/config").get_json()["data"]
    assert config["ready"] is False

    updated = client.put(
        "/api/config",
        json={"llm": {"base_url": "http://127.0.0.1:9/v1", "model": "local"}},
    ).get_json()["data"]
    assert updated["llm"]["model"] == "local"
    assert "Embedding model" in updated["missing_requirements"]

    assert client.get("/api/config/models").status_code == 502


def test_models_endpoint_uses_supplied_endpoint(client, monkeypatch):
    from minics.llm.client import ModelInfo

    captured = {}

    def fake_list_models(*, base_url, api_key="", timeout=30.0, client=None):
        captured["base_url"] = base_url
        return [ModelInfo(id="nomic-embed-text"), ModelInfo(id="llama3")]

    monkeypatch.setattr("minics.server.api.system.list_models", fake_list_models)

    # The UI can list models before saving by passing the typed URL.
    data = client.get(
        "/api/config/models?kind=embedding&base_url=http://192.168.1.130:11434/v1"
    ).get_json()["data"]
    assert captured["base_url"] == "http://192.168.1.130:11434/v1"
    assert data["embedding"] == ["nomic-embed-text"]
    assert data["chat"] == ["llama3"]

    # Without an override the embedding endpoint falls back to the LLM URL.
    client.put("/api/config", json={"llm": {"base_url": "http://192.168.1.135:8000/v1"}})
    client.get("/api/config/models?kind=embedding").get_json()
    assert captured["base_url"] == "http://192.168.1.135:8000/v1"
