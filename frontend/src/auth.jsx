import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, session, setUnauthorizedHandler } from "./api";
import { resetAskHistory } from "./ask/store";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (session.token() ? session.user() : null));

  const logout = useCallback(() => {
    session.clear();
    resetAskHistory();   // answers can hold bank figures: never left for the next person at this browser
                         // (they stay saved on the server for this user and come back at the next login)
    setUser(null);
  }, []);

  // A session saved before roles came with the user (specs/user-roles.md) is topped up from /auth/me.
  useEffect(() => {
    if (!user || user.access) return;
    api.me()
      .then((me) => {
        const next = { ...user, ...me };
        session.save(session.token(), next);
        setUser(next);
      })
      .catch(() => {});
  }, [user]);

  // Any 401 from the API (expired or invalid token) signs the user out.
  useEffect(() => {
    setUnauthorizedHandler(logout);
    return () => setUnauthorizedHandler(() => {});
  }, [logout]);

  const login = useCallback(async (email, password) => {
    const result = await api.login(email, password);
    resetAskHistory();
    session.save(result.access_token, result.user);
    setUser(result.user);
    return result.user;
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
