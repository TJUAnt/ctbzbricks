import React from 'react';
import { useDynamicTranslation, type TranslationKey } from '../i18n';

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
  const tr = useDynamicTranslation();
  const [session, setSession] = React.useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = React.useState(isSupabaseAuthConfigured);
  const [errorKey, setErrorKey] = React.useState<TranslationKey | null>(null);
  const error = errorKey ? tr(errorKey) : null;

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
          setErrorKey('errors:auth.session_load_failed');
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
      setErrorKey(null);
    });

    return () => {
      isMounted = false;
      data.subscription.unsubscribe();
    };
  }, []);

  const signInWithGoogle = React.useCallback(async () => {
    if (!supabase) {
      setErrorKey('common:supabaseSignInIsNotConfigured');
      return;
    }
    setErrorKey(null);
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    });
    if (signInError) {
      setErrorKey('errors:auth.sign_in_failed');
    }
  }, [tr]);

  const signOut = React.useCallback(async () => {
    if (!supabase) {
      return;
    }
    setErrorKey(null);
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) {
      setErrorKey('errors:auth.sign_out_failed');
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
