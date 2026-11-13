import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import api from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.me();
      setUser(me);
      setWorkspaces(await api.workspaces());
    } catch {
      setUser(null);
      setWorkspaces([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async (email, password) => { await api.login({ email, password }); await refresh(); };
  const loginDemo = async (role) => { await api.loginDemo(role); await refresh(); };
  const signup = async (d) => { await api.signup(d); await refresh(); };
  const logout = async () => { await api.logout(); setUser(null); setWorkspaces([]); };

  const workspace = workspaces[0] || null; // first workspace is active
  const isAdmin = workspace?.role === 'admin';

  return (
    <AuthContext.Provider value={{ user, workspaces, workspace, isAdmin, loading, login, loginDemo, signup, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
