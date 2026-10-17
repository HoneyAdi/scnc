import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface Account {
  id: number;
  code: string;
  name: string;
  type: string;
  parent_id: number | null;
  is_active: boolean;
  is_system: boolean;
}

const TYPES = ["asset", "liability", "equity", "income", "expense"];

export default function AccountsPage() {
  const { can } = useAuth();
  const [items, setItems] = useState<Account[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", type: "asset", parent_id: "" });

  async function refresh() {
    try {
      const res = await api.get("/api/v1/accounts");
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
      await api.post("/api/v1/accounts", {
        code: form.code,
        name: form.name,
        type: form.type,
        parent_id: form.parent_id === "" ? null : Number(form.parent_id),
      });
      setForm({ code: "", name: "", type: "asset", parent_id: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  }

  async function setActive(id: number, is_active: boolean) {
    try {
      await api.patch(`/api/v1/accounts/${id}`, { is_active });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed.");
    }
  }

  if (!can("accounts.view")) return <p>Not authorized to view the chart of accounts.</p>;

  return (
    <section>
      <h2>Chart of accounts ({total})</h2>
      {error && (
        <p role="alert" style={{ color: "darkred" }}>
          {error}
        </p>
      )}
      {items.length === 0 ? (
        <p>No accounts defined yet. The chart starts empty; the college configures it.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Type</th>
              <th>Parent</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>{a.code}</td>
                <td>{a.name}</td>
                <td>{a.type}</td>
                <td>{a.parent_id ?? "—"}</td>
                <td>{a.is_active ? "yes" : "no"}</td>
                <td>
                  {can("accounts.configure") && (
                    <button onClick={() => setActive(a.id, !a.is_active)}>
                      {a.is_active ? "Deactivate" : "Activate"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {can("accounts.configure") && (
        <form onSubmit={create}>
          <h3>Create account</h3>
          <input
            placeholder="code, e.g. 1000"
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            required
          />
          <input
            placeholder="name"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
          <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <input
            placeholder="parent id (optional)"
            value={form.parent_id}
            onChange={(e) => setForm({ ...form, parent_id: e.target.value })}
          />
          <button type="submit">Create</button>
        </form>
      )}
    </section>
  );
}
