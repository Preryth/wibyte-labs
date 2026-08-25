# WiByte Labs authentication setup

## 1. Supabase Dashboard settings

Authentication -> Providers -> Email:
- Enable Email provider.
- Keep Google disabled.
- For development, choose whether email confirmation is required. The frontend supports both behaviours.

Authentication -> URL Configuration:
- Site URL: `http://localhost:5173`
- Add `http://localhost:5173/**` to Redirect URLs if your dashboard supports wildcard redirect entries.

## 2. Run the database setup

Open Supabase Dashboard -> SQL Editor and run:

`supabase/001_profiles_and_access.sql`

This creates a `profiles` table and automatically gives every new signup a `pending` status.

## 3. Create and approve the first administrator

Sign up through WiByte Labs. Then open Supabase Dashboard -> Table Editor -> `profiles`.

Find your account and set:
- `approval_status` = `approved`
- `role` = `admin`

The current application does not yet expose a custom WiByte admin dashboard. Until that is built, approve or decline students directly in the Supabase Table Editor by changing `approval_status`.

## 4. Email delivery

Supabase can be used for development email confirmation and password-reset testing. Before production, configure a production SMTP provider in Supabase so password-reset and confirmation emails are reliably delivered.

## Security note

This update blocks pending/declined users in the frontend. The existing Docker/Lab backend still uses its pre-existing development-student model and has not yet been converted to per-user JWT authorization. Before public deployment, backend endpoints must be tied to the authenticated Supabase user and must enforce approval status server-side. Do not expose the current development backend publicly as a multi-user service.
