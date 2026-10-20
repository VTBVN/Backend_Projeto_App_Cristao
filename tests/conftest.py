import json

import pytest
import requests

from app import create_app


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Os testes não devem acessar a rede.")
    monkeypatch.setattr(requests, "get", forbidden)


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "APP_ENV": "testing", "MONGODB_URI": "",
                       "CACHE_SQLITE_PATH": tmp_path / "cache.sqlite3"})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def provider(monkeypatch):
    calls = []

    def install(status=200, payload=None, raw=None):
        data = payload if payload is not None else {
            "reference": "John 3:16", "text": "Texto de teste.", "translation_id": "almeida"
        }

        class Response:
            status_code = status

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def iter_content(self, chunk_size):
                yield raw if raw is not None else json.dumps(data).encode()

        def get(*args, **kwargs):
            calls.append((args, kwargs))
            return Response()

        monkeypatch.setattr(requests, "get", get)
        return calls

    return install
