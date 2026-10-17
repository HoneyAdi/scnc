import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth";
import Layout, { Dashboard } from "./pages/Layout";
import LoginPage from "./pages/Login";
import UsersPage from "./pages/Users";
import RolesPage, { AuditPage } from "./pages/Roles";
import PeriodsPage from "./pages/Periods";
import AccountsPage from "./pages/Accounts";

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/users" element={<UsersPage />} />
            <Route path="/roles" element={<RolesPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="/periods" element={<PeriodsPage />} />
            <Route path="/accounts" element={<AccountsPage />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
