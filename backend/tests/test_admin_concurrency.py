"""Admin/role lifecycle regression tests: atomicity, system-role protection, gates."""
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.main import create_app
from app.models.auth import (
    AuditLog,
    Role,
    Session as DbSession,
    SystemSetting,
    User,
    UserRole,
)


def _wipe_live(engine) -> None:
    # Order respects FK RESTRICT guards (audit/sessions reference users).
    with Session(engine) as s:
        s.execute(delete(AuditLog))
        s.execute(delete(DbSession))
        s.execute(delete(UserRole))
        s.execute(delete(User))
        s.execute(delete(SystemSetting))
        s.commit()


def _live_engine():
    url = os.environ["TEST_DATABASE_URL"]
    assert "/scnc_test" in url
    return create_engine(url)


def test_concurrent_last_admin_deactivation():
    """Two admins racing to deactivate each other: exactly one succeeds.

    Real commits on the disposable test DB (rollback isolation cannot observe
    cross-connection races); everything created is deleted in `finally`.
    """
    engine = _live_engine()
    try:
        _wipe_live(engine)
        with Session(engine) as s:
            role_id = s.execute(
                select(Role.id).where(Role.name == "Super Admin")
            ).scalar_one()
            ids = []
            for name in ("concA", "concB"):
                u = User(username=name, password_hash=hash_password("ConcPass123456!"))
                s.add(u)
                s.flush()
                s.add(UserRole(user_id=u.id, role_id=role_id))
                ids.append(u.id)
            s.commit()

        def attempt(me: str, target: int) -> int:
            c = TestClient(create_app(), base_url="http://testserver")
            try:
                r = c.post(
                    "/api/v1/auth/login",
                    json={"username": me, "password": "ConcPass123456!"},
                )
                assert r.status_code == 200, r.text
                return c.post(f"/api/v1/admin/users/{target}/deactivate").status_code
            finally:
                c.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(attempt, "concA", ids[1])
            f2 = pool.submit(attempt, "concB", ids[0])
            codes = sorted([f1.result(), f2.result()])
        assert codes == [200, 400], codes
    finally:
        _wipe_live(engine)
        engine.dispose()
