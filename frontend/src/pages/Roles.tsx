import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

export default function RolesPage() {
  const { can } = useAuth();
  const [roles, setRoles] = useState<{ id: number; name: string; permissions: string[] }[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get("/api/v1/admin/roles")
      .then(setRoles)
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed."));
  }, []);

  if (!can("roles.view")) return <p>Not authorized to view roles.</p>;

  return (
    <section>
      <h2>Roles</h2>
      {error && (
        <p role="alert" style={{ color: "darkred" }}>
          {error}
        </p>
      )}
      {roles.length === 0 ? (
        <p>No roles found.</p>
      ) : (
        <ul>
          {roles.map((r) => (
            <li key={r.id}>
              <strong>{r.name}</strong> — {r.permissions.join(", ") || "no permissions"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AuditPage() {
  const { can } = useAuth();
  const [items, setItems] = useState<
    { id: number; created_at: string; actor_id: number | null; action: string; entity: string }[]
  >([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get("/api/v1/admin/audit-log?limit=100")
      .then((r) => setItems(r.items))
      .catch((e) => setError(e instanceof Error ? e.message : "Load failed."));
  }, []);

  if (!can("audit.view")) return <p>Not authorized to view the audit log.</p>;

  return (
    <section>
      <h2>Audit log</h2>
      {error && (
        <p role="alert" style={{ color: "darkred" }}>
          {error}
        </p>
      )}
      {items.length === 0 ? (
        <p>No audit events yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Time</th>
              <th>Actor</th>
              <th>Action</th>
              <th>Entity</th>
            </tr>
          </thead>
          <tbody>
            {items.map((a) => (
              <tr key={a.id}>
                <td>{a.id}</td>
                <td>{a.created_at}</td>
                <td>{a.actor_id ?? "system"}</td>
                <td>{a.action}</td>
                <td>{a.entity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
