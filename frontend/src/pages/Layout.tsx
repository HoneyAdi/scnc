import { useEffect, useState } from "react";
import { Link, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";

export default function Layout() {
  const { user, loading, can, logout } = useAuth();
  const navigate = useNavigate();
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    if (!loading && !user) navigate("/login", { replace: true });
  }, [loading, user, navigate]);

  useEffect(() => {
    fetch("http://127.0.0.1:8000/health")
      .then((r) => (r.ok ? "reachable" : "error"))
      .then(setHealth)
      .catch(() => setHealth("unreachable"));
  }, []);

  if (loading) return <p>Loading…</p>;
  if (!user) return null;

  return (
    <div style={{ fontFamily: "sans-serif" }}>
      <header
        style={{ display: "flex", gap: 16, alignItems: "center", borderBottom: "1px solid #ccc" }}
      >
        <strong>SCN Accounting</strong>
        <nav style={{ display: "flex", gap: 12 }}>
          <Link to="/">Dashboard</Link>
          {can("users.view") && <Link to="/users">Users</Link>}
          {can("roles.view") && <Link to="/roles">Roles</Link>}
          {can("audit.view") && <Link to="/audit">Audit log</Link>}
        </nav>
        <span style={{ marginLeft: "auto" }}>
          {user.username} <button onClick={() => logout().then(() => navigate("/login"))}>Log out</button>
        </span>
      </header>
      <p style={{ fontSize: 12, color: "#555" }}>
        API status: {health} · Signed in as {user.username}
      </p>
      <main>
        <Outlet />
      </main>
    </div>
  );
}

export function Dashboard() {
  const [db, setDb] = useState<string>("checking…");
  useEffect(() => {
    api
      .get("/health/db")
      .then(() => setDb("reachable"))
      .catch(() => setDb("unreachable"));
  }, []);
  return (
    <section>
      <h2>Dashboard</h2>
      <p>System status at a glance. Financial modules arrive in later phases.</p>
      <ul>
        <li>API: reachable (you are reading this page)</li>
        <li>Database: {db}</li>
        <li>Fee collection, vouchers, reports: not yet implemented</li>
      </ul>
    </section>
  );
}
