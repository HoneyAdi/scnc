const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export interface UserInfo {
  id: number;
  username: string;
  is_active: boolean;
  permissions: string[];
}

async function request(path: string, init: RequestInit = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: "Request failed." }));
    throw new Error(typeof body.detail === "string" ? body.detail : "Request failed.");
  }
  return res.json();
}

export const api = {
  get: (path: string) => request(path),
  post: (path: string, body: unknown) =>
    request(path, { method: "POST", body: JSON.stringify(body) }),
  login: (username: string, password: string) =>
    request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }) as Promise<{ user: UserInfo; token: string }>,
  logout: () => request("/api/v1/auth/logout", { method: "POST", body: "{}" }),
  me: () => request("/api/v1/me") as Promise<UserInfo>,
};
