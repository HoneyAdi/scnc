"""Admin/role lifecycle regression tests: atomicity, system-role protection, gates."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.main import create_app
from app.models.auth import Role, User, UserRole
from tests.conftest import (
    assert_connected_test_db,
    assert_no_unexpected_users,
    delete_user_graph,
    live_engine,
)

# Per-run unique suffix: concurrent or crashed-and-rerun suites never share rows.
RID = f"{os.getpid()}{uuid.uuid4().hex[:6]}"

# The two admins each test creates; cleanup is scoped to exactly these.
NAMES = ("concA_" + RID, "concB_" + RID)


def _make_admins(s, role_id, names):
    ids = {}
    for name in names:
        u = User(username=name, password_hash=hash_password("ConcPass123456!"))
        s.add(u)
        s.flush()
        s.add(UserRole(user_id=u.id, role_id=role_id))
        ids[name] = u.id
    s.commit()
    return ids


def _login_token(name: str) -> str:
    c = TestClient(create_app(), base_url="http://testserver")
    try:
        r = c.post(
            "/api/v1/auth/login",
            json={"username": name, "password": "ConcPass123456!"},
        )
        assert r.status_code == 200, r.text
        return r.cookies["scnc_session"]
    finally:
        c.close()


def _deactivate(target: int, token: str) -> int:
    c = TestClient(create_app(), base_url="http://testserver")
    try:
        return c.post(
            f"/api/v1/admin/users/{target}/deactivate",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
    finally:
        c.close()


def test_concurrent_last_admin_deactivation():
    """Same target raced twice by a stable actor: exactly one succeeds.

    Without serialization both requests could observe two active admins and
    both deactivate; the membership advisory lock makes the count check and
    the write atomic, so the second deterministically sees the last admin.
    Real commits on the disposable test DB; cleanup is scoped to the two users
    this test creates (never a blanket table wipe).
    """
    engine = live_engine()
    assert_connected_test_db(engine)
    delete_user_graph(engine, NAMES)  # idempotent pre-clean for crashed reruns
    try:
        assert_no_unexpected_users(engine)
        with Session(engine) as s:
            role_id = s.execute(
                select(Role.id).where(Role.name == "Super Admin")
            ).scalar_one()
            ids = _make_admins(s, role_id, NAMES)

        token1 = _login_token(NAMES[0])
        token2 = _login_token(NAMES[0])
        target = ids[NAMES[1]]
        with ThreadPoolExecutor(max_workers=2) as pool:
            codes = sorted([
                pool.submit(_deactivate, target, token1).result(),
                pool.submit(_deactivate, target, token2).result(),
            ])
        assert codes == [200, 400], codes
        with Session(engine) as s:
            assert (
                s.execute(select(func.count(User.id)).where(User.is_active.is_(True))).scalar()
                == 1
            )
    finally:
        delete_user_graph(engine, NAMES)
        engine.dispose()


def test_mutual_deactivation_leaves_one_survivor():
    """Two admins racing to deactivate each other: exactly one stays active.

    Either interleaving is safe ([200,400] via the guard, or [200,401] because
    the loser acts after their own deactivation); what must always hold is a
    single surviving active Super Admin and no silent double removal.
    """
    engine = live_engine()
    assert_connected_test_db(engine)
    delete_user_graph(engine, NAMES)  # idempotent pre-clean for crashed reruns
    try:
        assert_no_unexpected_users(engine)
        with Session(engine) as s:
            role_id = s.execute(
                select(Role.id).where(Role.name == "Super Admin")
            ).scalar_one()
            ids = _make_admins(s, role_id, NAMES)

        token_a = _login_token(NAMES[0])
        token_b = _login_token(NAMES[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_deactivate, ids[NAMES[1]], token_a)
            f2 = pool.submit(_deactivate, ids[NAMES[0]], token_b)
            codes = sorted([f1.result(), f2.result()])
        assert codes in ([200, 400], [200, 401]), codes
        with Session(engine) as s:
            active = s.execute(
                select(User.username).where(User.is_active.is_(True))
            ).scalars().all()
            assert len(active) == 1, active
            assert s.execute(
                select(func.count(User.id))
                .select_from(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(User.is_active.is_(True), Role.name == "Super Admin")
            ).scalar() == 1
    finally:
        delete_user_graph(engine, NAMES)
        engine.dispose()
