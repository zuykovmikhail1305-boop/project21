import asyncio

from app.core import config as config_module
import main


class DummyEngine:
    def _run_ddl_visitor(self, *args, **kwargs):
        return None


class DummySession:
    def close(self):
        return None


def test_lifespan_initializes_database_engine(monkeypatch):
    monkeypatch.setattr(config_module, "create_engine", lambda url: DummyEngine())
    monkeypatch.setattr(config_module, "sessionmaker", lambda **kwargs: lambda: DummySession())
    monkeypatch.setattr(main, "seed_groups", lambda db: None)

    async def run_lifespan():
        async with main.lifespan(main.fastapi_app):
            return None

    asyncio.run(run_lifespan())
