import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface UserRow {
  id: number;
  username: string;
  is_active: boolean;
}

export default function UsersPage() {
  const { can } = useAuth();
  const [items, setItems] = useState<UserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ username: "", password: "", roles: "" });

  async function refresh() {
    try {
      const res = await api.get("/api/v1/admin/users");
      setItems(res.items);
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Load failed.");
    }
  }

  useEffect(() => {
    refresh().catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    try {
      await api.post("/api/v1/admin/users", {
        username: form.username,
        password: form.password,
        roles: form.roles
          .split(",")
          .map((r) => r.trim())
          .filter(Boolean),
      });
      setForm({ username: "", password: "", roles: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  }

  async function deactivate(id: number) {
    try {
      await api.post(`/api/v1/admin/users/${id}/deactivate`, {});
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Deactivate failed.");
    }
  }

  if (!can("users.view")) return <p>Not authorized to view users.</p>;

  return (
    <section>
      <h2>Users ({total})</h2>
      {error && (
        <p role="alert" style={{ color: "darkred" }}>
          {error}
        </p>
      )}
      {items.length === 0 ? (
        <p>No users found.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Username</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id}>
                <td>{u.id}</td>
                <td>{u.username}</td>
                <td>{u.is_active ? "yes" : "no"}</td>
                <td>
                  {u.is_active && can("users.deactivate") && (
                    <button onClick={() => deactivate(u.id)}>Deactivate</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {can("users.create") && (
        <form onSubmit={create}>
          <h3>Create user</h3>
          <input
            placeholder="username"
            value={form.username}
            onChange={(e) => setForm({ ...form, username: e.target.value })}
            required
          />
          <input
            placeholder="password (min 12 chars)"
            type="password"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            required
          />
          <input
            placeholder="roles, comma separated"
            value={form.roles}
            onChange={(e) => setForm({ ...form, roles: e.target.value })}
          />
          <button type="submit">Create</button>
        </form>
      )}
    </section>
  );
}
