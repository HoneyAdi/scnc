import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, type UserInfo } from "./api";

interface AuthState {
  user: UserInfo | null;
  loading: boolean;
  error: string | null;
  can: (perm: string) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false));
  }, []);

  async function login(username: string, password: string) {
    setError(null);
    try {
      const res = await api.login(username, password);
      setUser(res.user);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed.");
      throw e;
    }
  }

  async function logout() {
    await api.logout().catch(() => undefined);
    setUser(null);
  }

  const can = (perm: string) => user?.permissions.includes(perm) ?? false;
  return (
    <AuthContext.Provider value={{ user, loading, error, can, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside provider");
  return ctx;
}
