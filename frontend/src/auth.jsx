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
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
