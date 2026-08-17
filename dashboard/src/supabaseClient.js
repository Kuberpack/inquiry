import { createClient } from '@supabase/supabase-js'

// Uses the publishable/anon key — safe to expose in browser code, unlike the
// service_role key used by the backend ingestion scripts. Access is governed
// by the RLS policies set up in inquiry-dashboard-schema-update.sql.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

if (!supabaseUrl || !supabaseAnonKey) {
  console.error(
    'Missing VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY — check your .env file.'
  )
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
