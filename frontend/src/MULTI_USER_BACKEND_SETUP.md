# WiByte Labs multi-user backend setup

This update makes protected frontend-to-backend requests carry the signed-in Supabase access token. The backend verifies the token with Supabase, checks that the profile is approved, and uses the verified Supabase user ID as the owner of Labs and GitHub connections.

## 1. Add Supabase settings to `backend/.env`

Add these values from the same Supabase project used by the frontend:

```env
SUPABASE_URL=https://YOUR-PROJECT-ID.supabase.co
SUPABASE_PUBLISHABLE_KEY=YOUR_SUPABASE_PUBLISHABLE_KEY
```

Use the project URL without `/rest/v1/`. Do not put a Supabase service-role key in the frontend.

## 2. Restart the backend

The backend now reads `.env` automatically at startup. Stop the server completely and start it again after adding the values.

## 3. Existing development data

The old development student and old Labs can remain in the local `wpl.db`. New authenticated users get their own local student record whose ID is the verified Supabase user ID. Old records are not used for authenticated requests.

## 4. GitHub reconnect

Because GitHub connections are now tied to the authenticated Supabase user, connect GitHub while signed in to the intended email/password account. The OAuth callback keeps using the signed OAuth state to finish the connection.

## Security model

- The browser does not tell the backend which user it is acting as.
- The browser sends a Supabase access token.
- The backend verifies that token with Supabase.
- Only profiles whose `approval_status` is `approved` are allowed through.
- Lab lookup checks that the authenticated user owns the requested Lab.
- GitHub connections and repositories are looked up using that same verified user ID.

## Development note

The existing GUI/noVNC connection still exposes a Docker port directly, as it did before this update. The main API, workspace, terminal WebSocket, GitHub operations, and Lab lifecycle are authenticated/owner-scoped. When the project is deployed, the GUI connection should be moved behind authenticated infrastructure rather than relying on a directly exposed container port.
