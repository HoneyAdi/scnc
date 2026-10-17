import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface Period {
  id: number;
  code: string;
  name: string;
  starts_on: string;
  ends_on: string;
  status: string;
  closed_by: number | null;
  closed_at: string | null;
}

export default function PeriodsPage() {
  const { can } = useAuth();
  const [items, setItems] = useState<Period[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ code: "", name: "", starts_on: "", ends_on: "" });

  async function refresh() {
    try {
      setItems(await api.get("/api/v1/periods"));
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
      await api.post("/api/v1/periods", form);
      setForm({ code: "", name: "", starts_on: "", ends_on: "" });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Create failed.");
    }
  }

  async function close(id: number) {
    try {
      await api.post(`/api/v1/periods/${id}/close`, {});
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Close failed.");
    }
  }

  if (!can("periods.view")) return <p>Not authorized to view financial periods.</p>;

  return (
    <section>
      <h2>Financial periods</h2>
      {error && (
        <p role="alert" style={{ color: "darkred" }}>
          {error}
        </p>
      )}
      {items.length === 0 ? (
        <p>No financial periods defined yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Code</th>
              <th>Name</th>
              <th>Start</th>
              <th>End</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {items.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td>
                <td>{p.name}</td>
                <td>{p.starts_on}</td>
                <td>{p.ends_on}</td>
                <td>{p.status}</td>
                <td>
                  {p.status === "open" && can("periods.configure") && (
                    <button onClick={() => close(p.id)}>Close</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {can("periods.configure") && (
        <form onSubmit={create}>
          <h3>Create period</h3>
          <input
            placeholder="code, e.g. FY26-27"
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
          <input
            type="date"
            aria-label="starts on"
            value={form.starts_on}
            onChange={(e) => setForm({ ...form, starts_on: e.target.value })}
            required
          />
          <input
            type="date"
            aria-label="ends on"
            value={form.ends_on}
            onChange={(e) => setForm({ ...form, ends_on: e.target.value })}
            required
          />
          <button type="submit">Create</button>
        </form>
      )}
    </section>
  );
}
