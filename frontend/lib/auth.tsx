"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, TOKEN_KEY } from "./api";

export type Me = { id: number; player_no: number | null; nickname: string; is_club_creator: boolean; is_moderator: boolean; role: "player" | "admin"; providers: string[];
  is_publisher?: boolean; publisher_consent?: boolean };

type Ctx = {
  me: Me | null;
  ready: boolean;
  signIn: (token: string) => Promise<void>;
  signOut: () => void;
  reload: () => Promise<void>;
};

const AuthContext = createContext<Ctx>({
  me: null, ready: false, signIn: async () => {}, signOut: () => {}, reload: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    try {
      setMe(await api<Me>("/auth/me"));
    } catch {
      setMe(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const signIn = useCallback(async (token: string) => {
    try { window.localStorage.setItem(TOKEN_KEY, token); } catch {}
    await reload();
  }, [reload]);

  const signOut = useCallback(() => {
    try { window.localStorage.removeItem(TOKEN_KEY); } catch {}
    setMe(null);
  }, []);

  return <AuthContext.Provider value={{ me, ready, signIn, signOut, reload }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
