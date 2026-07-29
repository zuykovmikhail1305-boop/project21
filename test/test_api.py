from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps as deps_module
from app.api.v1.endpoints import artifacts as artifacts_module
from app.api.v1.endpoints import auth as auth_module
from app.api.v1.endpoints import documents as documents_module
from app.api.v1.endpoints import users as users_module
from app.core.config import get_db
from app.models.artifact import ArtifactStatus
from app.models.document import DocumentStatus


def make_user(
    user_id: int = 1,
    email: str = "user@example.com",
    username: str = "user",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=user_id,
        email=email,
        username=username,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def make_artifact(
    artifact_id: int = 1,
    user_id: int = 1,
    status: ArtifactStatus | str = ArtifactStatus.READY,
    storage_path: str = "C:/tmp/artifact.pdf",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=artifact_id,
        session_id=10,
        user_id=user_id,
        artifact_type="pdf",
        title="Quarterly Report",
        status=status,
        file_size=1024,
        error_message=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        storage_path=storage_path,
    )


def make_document(
    document_id: int = 1,
    status: DocumentStatus | str = DocumentStatus.READY,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=document_id,
        filename="report.pdf",
        mime_type="application/pdf",
        file_size=2048,
        status=status.value if isinstance(status, DocumentStatus) else status,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        chunks=[],
    )


class FakeArtifactQuery:
    def __init__(self, artifacts: list[SimpleNamespace]):
        self._artifacts = artifacts

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def count(self):
        return len(self._artifacts)

    def all(self):
        return self._artifacts


class FakeArtifactDB:
    def __init__(self, artifacts: list[SimpleNamespace]):
        self._artifacts = artifacts
        self.deleted = None
        self.committed = False

    def query(self, model):
        return FakeArtifactQuery(self._artifacts)

    def delete(self, artifact):
        self.deleted = artifact

    def commit(self):
        self.committed = True


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(auth_module.router)
    app.include_router(documents_module.router)
    app.include_router(users_module.router)
    app.include_router(artifacts_module.router)

    @app.get("/")
    async def root():
        return {"message": "CorpAI Intelligence API", "status": "running"}

    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    return app


@pytest.fixture
def app():
    application = build_test_app()
    regular_user = make_user()
    admin_user = make_user(user_id=2, email="admin@example.com", username="admin")
    dummy_db = object()

    application.dependency_overrides[get_db] = lambda: dummy_db
    application.dependency_overrides[deps_module.get_current_user] = lambda: regular_user
    application.dependency_overrides[deps_module.get_current_admin_user] = lambda: admin_user

    yield application

    application.dependency_overrides.clear()


@pytest.fixture
def client(app):
    return TestClient(app)


def test_root_and_health_endpoints(client):
    root_response = client.get("/")
    health_response = client.get("/health")

    assert root_response.status_code == 200
    assert root_response.json() == {"message": "CorpAI Intelligence API", "status": "running"}
    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}


def test_auth_register_success_and_conflict(client, monkeypatch):
    created_user = make_user(user_id=100, email="new@example.com", username="new-user")

    class SuccessUserService:
        def __init__(self, db):
            self.db = db

        async def register(self, email, username, password):
            assert email == "new@example.com"
            assert username == "new-user"
            assert password == "secret123"
            return created_user

    monkeypatch.setattr(auth_module, "UserService", SuccessUserService)

    response = client.post(
        "/auth/register",
        json={"email": "new@example.com", "username": "new-user", "password": "secret123"},
    )

    assert response.status_code == 201
    assert response.json()["email"] == "new@example.com"
    assert response.json()["username"] == "new-user"

    class FailingUserService:
        def __init__(self, db):
            self.db = db

        async def register(self, email, username, password):
            raise ValueError("email already exists")

    monkeypatch.setattr(auth_module, "UserService", FailingUserService)

    conflict_response = client.post(
        "/auth/register",
        json={"email": "new@example.com", "username": "new-user", "password": "secret123"},
    )

    assert conflict_response.status_code == 400
    assert conflict_response.json()["detail"] == "email already exists"


def test_auth_login_refresh_logout_and_me(client, monkeypatch):
    current_user = make_user()

    class SuccessUserService:
        def __init__(self, db):
            self.db = db

        async def authenticate(self, email, password):
            assert email == "user@example.com"
            assert password == "secret123"
            return current_user

    class SuccessTokenService:
        def __init__(self, db):
            self.db = db

        async def create_tokens(self, user_id):
            assert user_id == current_user.id
            return {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_type": "bearer",
            }

        async def refresh_tokens(self, refresh_token):
            assert refresh_token == "refresh-token"
            return {
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "bearer",
            }

        async def revoke_refresh_token(self, refresh_token):
            assert refresh_token == "refresh-token"
            return True

    monkeypatch.setattr(auth_module, "UserService", SuccessUserService)
    monkeypatch.setattr(auth_module, "TokenService", SuccessTokenService)

    login_response = client.post(
        "/auth/login",
        json={"email": "user@example.com", "password": "secret123"},
    )

    assert login_response.status_code == 200
    assert login_response.json()["access_token"] == "access-token"
    assert login_response.cookies.get("access_token") == "access-token"

    refresh_response = client.post("/auth/refresh", json={"refresh_token": "refresh-token"})
    assert refresh_response.status_code == 200
    assert refresh_response.json()["access_token"] == "new-access-token"

    logout_response = client.post("/auth/logout", json={"refresh_token": "refresh-token"})
    assert logout_response.status_code == 200
    assert logout_response.json() == {"message": "Logged out successfully"}

    me_response = client.get("/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"


def test_documents_list_detail_delete_and_validation(client, monkeypatch):
    fake_document = make_document()
    captured = {}

    def fake_list_documents(db, folder_id=None, status=None, skip=0, limit=100):
        captured["folder_id"] = folder_id
        captured["status"] = status
        captured["skip"] = skip
        captured["limit"] = limit
        return [fake_document]

    monkeypatch.setattr(documents_module, "list_documents", fake_list_documents)
    monkeypatch.setattr(documents_module, "get_document", lambda db, document_id: fake_document)
    monkeypatch.setattr(documents_module, "delete_document", lambda db, document_id: True)

    list_response = client.get("/documents/?status=ready&skip=2&limit=5")
    assert list_response.status_code == 200
    assert list_response.json()[0]["filename"] == "report.pdf"
    assert captured["status"] == DocumentStatus.READY
    assert captured["skip"] == 2
    assert captured["limit"] == 5

    detail_response = client.get("/documents/1")
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == 1

    delete_response = client.delete("/documents/1")
    assert delete_response.status_code == 204

    invalid_status_response = client.get("/documents/?status=broken")
    assert invalid_status_response.status_code == 400
    assert "Invalid status" in invalid_status_response.json()["detail"]


def test_users_me_and_admin_routes(client, monkeypatch):
    current_user = make_user()
    admin_user = make_user(user_id=2, email="admin@example.com", username="admin")
    another_user = make_user(user_id=3, email="other@example.com", username="other")

    monkeypatch.setattr(users_module, "get_users", lambda db, skip=0, limit=100: [current_user, another_user])
    monkeypatch.setattr(users_module, "get_user_by_id", lambda db, user_id: another_user if user_id == 3 else None)

    update_capture = {}

    def fake_update_user(db, user_id, **kwargs):
        update_capture["user_id"] = user_id
        update_capture["kwargs"] = kwargs
        return another_user

    monkeypatch.setattr(users_module, "update_user", fake_update_user)
    monkeypatch.setattr(users_module, "delete_user", lambda db, user_id: True)

    me_response = client.get("/users/me")
    assert me_response.status_code == 200
    assert me_response.json()["email"] == "user@example.com"

    list_response = client.get("/users/?skip=1&limit=2")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 2

    get_response = client.get("/users/3")
    assert get_response.status_code == 200
    assert get_response.json()["email"] == "other@example.com"

    patch_response = client.patch(
        "/users/3",
        json={"username": "renamed", "is_active": False, "ignored": "value"},
    )
    assert patch_response.status_code == 200
    assert update_capture["user_id"] == 3
    assert update_capture["kwargs"] == {"username": "renamed", "is_active": False}

    delete_response = client.delete("/users/3")
    assert delete_response.status_code == 204


def test_artifacts_routes(client, monkeypatch):
    current_user = make_user()
    artifact = make_artifact()
    fake_db = FakeArtifactDB([artifact])

    client.app.dependency_overrides[get_db] = lambda: fake_db
    client.app.dependency_overrides[deps_module.get_current_user] = lambda: current_user

    monkeypatch.setattr(artifacts_module, "_get_user_artifact", lambda artifact_id, user_id, db: artifact)

    list_response = client.get("/artifacts/")
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert list_response.json()["artifacts"][0]["title"] == "Quarterly Report"

    get_response = client.get("/artifacts/1")
    assert get_response.status_code == 200
    assert get_response.json()["artifact_type"] == "pdf"

    with tempfile.NamedTemporaryFile(delete=False) as tmp_file:
        tmp_file.write(b"artifact content")
        tmp_path = tmp_file.name

    try:
        file_artifact = make_artifact(storage_path=tmp_path)
        monkeypatch.setattr(artifacts_module, "_get_user_artifact", lambda artifact_id, user_id, db: file_artifact)

        download_response = client.get("/artifacts/1/download")
        assert download_response.status_code == 200
        assert download_response.headers["content-type"].startswith("application/pdf")

        monkeypatch.setattr(artifacts_module, "_get_user_artifact", lambda artifact_id, user_id, db: file_artifact)
        delete_response = client.delete("/artifacts/1")
        assert delete_response.status_code == 204
        assert not Path(tmp_path).exists()
        assert fake_db.deleted is file_artifact
        assert fake_db.committed is True
    finally:
        Path(tmp_path).unlink(missing_ok=True)
