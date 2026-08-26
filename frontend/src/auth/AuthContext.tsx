import React from 'react';
import { useDynamicTranslation, type TranslationKey } from '../i18n';
import {
  ApiError,
  localizeApiError,
  subscribeInvalidSession,
} from '../api/client';

import {
  isSupabaseAuthConfigured,
  supabase,
  type AuthSession,
  type AuthUser,
} from './supabaseClient';
import { verifyAuthSession } from './sessionApi';

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

/** 统一管理 Supabase 本地 session、Go 服务端确认状态及页面可见的当前用户。 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const tr = useDynamicTranslation();
  const [session, setSession] = React.useState<AuthSession | null>(null);
  const [isLoading, setIsLoading] = React.useState(isSupabaseAuthConfigured);
  const [authError, setAuthError] = React.useState<TranslationKey | ApiError | null>(null);
  const verificationGeneration = React.useRef(0);
  const error = authError instanceof ApiError
    ? localizeApiError(authError)
    : authError
      ? tr(authError)
      : null;

  const invalidateStoredSession = React.useCallback(() => {
    verificationGeneration.current += 1;
    setSession(null);
    setIsLoading(false);
    setAuthError('errors:auth.session_invalid');
    if (supabase) {
      // 服务端已明确拒绝当前 token；local scope 只清理本浏览器会话，不影响用户的其他设备。
      void supabase.auth.signOut({ scope: 'local' });
    }
  }, []);

  React.useEffect(() => {
    let isMounted = true;
    let activeVerificationToken: string | null = null;
    let currentAccessToken: string | null = null;
    let verifiedAccessToken: string | null = null;
    if (!supabase) {
      setIsLoading(false);
      return () => {
        isMounted = false;
      };
    }

    const verifyAndExposeSession = async (nextSession: AuthSession | null) => {
      if (!nextSession) {
        verificationGeneration.current += 1;
        activeVerificationToken = null;
        currentAccessToken = null;
        verifiedAccessToken = null;
        if (isMounted) {
          setSession(null);
          setIsLoading(false);
          setAuthError(null);
        }
        return;
      }

      if (activeVerificationToken === nextSession.access_token) {
        return;
      }
      if (verifiedAccessToken === nextSession.access_token) {
        setIsLoading(false);
        return;
      }
      const generation = verificationGeneration.current + 1;
      verificationGeneration.current = generation;
      activeVerificationToken = nextSession.access_token;
      currentAccessToken = nextSession.access_token;

      // 本地缓存只用于取得 token；Go 二次确认完成前不向 Header 暴露其中的旧用户信息。
      setSession(null);
      setIsLoading(true);
      setAuthError(null);
      try {
        const verifiedUser = await verifyAuthSession(nextSession.access_token);
        if (!isMounted || verificationGeneration.current !== generation) {
          if (activeVerificationToken === nextSession.access_token) {
            activeVerificationToken = null;
          }
          return;
        }
        if (verifiedUser.id !== nextSession.user.id) {
          activeVerificationToken = null;
          invalidateStoredSession();
          return;
        }
        const verifiedSession = verifiedUser.email
          ? { ...nextSession, user: { ...nextSession.user, email: verifiedUser.email } }
          : nextSession;
        verifiedAccessToken = nextSession.access_token;
        activeVerificationToken = null;
        setSession(verifiedSession);
        setIsLoading(false);
        setAuthError(null);
      } catch (verificationError) {
        if (!isMounted || verificationGeneration.current !== generation) {
          if (activeVerificationToken === nextSession.access_token) {
            activeVerificationToken = null;
          }
          return;
        }
        activeVerificationToken = null;
        if (
          verificationError instanceof ApiError
          && verificationError.status === 401
          && verificationError.code === 'auth.session_invalid'
        ) {
          invalidateStoredSession();
          return;
        }
        // 网络或 provider 暂不可用时不删除 Supabase 本地 session；下次刷新可重新确认。
        setSession(null);
        setIsLoading(false);
        setAuthError(
          verificationError instanceof ApiError
            ? verificationError
            : 'errors:auth.session_load_failed',
        );
      }
    };

    const { data } = supabase.auth.onAuthStateChange((event, nextSession) => {
      if (event === 'INITIAL_SESSION') {
        return;
      }
      if (event === 'SIGNED_OUT') {
        verificationGeneration.current += 1;
        activeVerificationToken = null;
        currentAccessToken = null;
        verifiedAccessToken = null;
        setSession(null);
        setIsLoading(false);
        return;
      }
      void verifyAndExposeSession(nextSession);
    });

    const unsubscribeInvalidSession = subscribeInvalidSession((rejectedAccessToken) => {
      if (rejectedAccessToken && rejectedAccessToken !== currentAccessToken) {
        return;
      }
      invalidateStoredSession();
    });

    void supabase.auth.getSession().then(({ data: sessionData, error: sessionError }) => {
      if (!isMounted) {
        return;
      }
      if (sessionError) {
        setSession(null);
        setIsLoading(false);
        setAuthError('errors:auth.session_load_failed');
        return;
      }
      void verifyAndExposeSession(sessionData.session ?? null);
    }).catch(() => {
      if (isMounted) {
        setSession(null);
        setIsLoading(false);
        setAuthError('errors:auth.session_load_failed');
      }
    });

    return () => {
      isMounted = false;
      verificationGeneration.current += 1;
      data.subscription.unsubscribe();
      unsubscribeInvalidSession();
    };
  }, [invalidateStoredSession]);

  const signInWithGoogle = React.useCallback(async () => {
    if (!supabase) {
      setAuthError('common:supabaseSignInIsNotConfigured');
      return;
    }
    setAuthError(null);
    const { error: signInError } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: {
        redirectTo: window.location.origin,
      },
    });
    if (signInError) {
      setAuthError('errors:auth.sign_in_failed');
    }
  }, []);

  const signOut = React.useCallback(async () => {
    if (!supabase) {
      return;
    }
    setAuthError(null);
    const { error: signOutError } = await supabase.auth.signOut();
    if (signOutError) {
      setAuthError('errors:auth.sign_out_failed');
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
