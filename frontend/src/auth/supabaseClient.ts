import { createClient, type Session, type SupabaseClient, type User } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;

export type AuthSession = Session;
export type AuthUser = User;

export const isSupabaseAuthConfigured = Boolean(supabaseUrl && supabasePublishableKey);

export const supabase: SupabaseClient | null = isSupabaseAuthConfigured
  ? createClient(supabaseUrl!, supabasePublishableKey!)
  : null;

export async function currentAccessToken(): Promise<string | null> {
  if (!supabase) {
    return null;
  }
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}
