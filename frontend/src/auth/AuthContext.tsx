import React from 'react';

import {
  isSupabaseAuthConfigured,
  supabase,
  type AuthSession,
  type AuthUser,
} from './supabaseClient';

type AuthContextValue = {
  accessToken: string | null;
  error: string | null;
  isConfigured: boolean;
  isLoading: boolean;
  session: AuthSession | null;
  signInWithGoogle: () => Promise<void>;
  signOut: () => Promise<void>;
  user: AuthUser | null;
};

const AuthContext = React.createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = React.useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = React.useState(isSupabaseAuthConfigured);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let isMounted = true;
    if (!supabase) {
      setIsLoading(false);
      return () => {
        isMounted = false;
      };
    }

    supabase.auth
      .getSession()
      .then(({ data, error: sessionError }) => {
        if (!isMounted) {
          return;
        }
        if (sessionError) {
          setError(sessionError.message);
        }
        setSession(data.session ?? null);
      })
      .finally(() => {
        if (isMounted) {
          setIsLoading(false);
        }
      });

    const { data } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setError(null);
    });

    return () => {
      isMounted = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = React.useCallback(async () => {
    if (!supabase) {
      setError('Supabase 登录尚未配置');
      return;
    }
    setError(null);
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    });
    if (signInError) {
      setError(signInError.message);
    }
  }, []);

  const signOut = React.useCallback(async () => {
    if (!supabase) {
      return;
    }
    setError(null);
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) {
      setError(signOutError.message);
    }
  }, []);

  const value = React.useMemo<AuthContextValue>(
    () => ({
      accessToken: session?.access_token ?? null,
      error,
      isConfigured: isSupabaseAuthConfigured,
      isLoading,
      session,
      signInWithGoogle,
      signOut,
      user: session?.user ?? null,
    }),
    [error, isLoading, session, signInWithGoogle, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = React.useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return value;
}
