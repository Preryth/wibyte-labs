# Configurable single-host setup

This toolkit runs the current application on a local Linux Docker Engine. It
recreates the deployment features from c23dea5 after development restarted from
Preryth main, while retaining the newer GUI, editor/autosave, combined Commit &
Push, and inactivity save-before-close behavior.

It does not restore the abandoned next-system architecture or change an existing
VPS, provider account, DNS, SMTP settings, or cloud infrastructure.

## Requirements

- Linux, Bash, Python 3.10+, Docker Engine and Docker Compose v2.
- Access to the local `/var/run/docker.sock`. This backend architecture controls
  the local Docker daemon and therefore has host-administration capabilities.
- Available backend port 8000 and web port 8080, unless the web port is configured
  differently. One `wpl` application project per Docker Engine is supported.
- Your Supabase project and GitHub App credentials, configured through their
  normal provider interfaces. The wizard does not create those resources.

Host Node/npm or a host Python virtual environment is not required for Compose.
Docker Desktop, remote Docker engines and distributed execution are outside this
single-host setup.

## Fresh installation

Clone the Wibytelabs repository, enter it and run `./wpl setup`.

The wizard asks for the public website URL, Supabase project URL/public/backend
keys, and GitHub App Client ID/client secret. Secret entry is hidden. It generates
the signing key once and saves `backend/.env` with permissions 0600 after you
confirm the displayed provider settings. Cancellation does not save partial keys.

It then builds the student, backend and frontend images from repository source
and ordinary base images. It does not require the old `wpl-*-baseline` images or
anything in `/home/wibyte/wpl-baseline-runtime-*`. The backend applies existing
SQLite Alembic migrations before starting; readiness checks verify both services.

Default browser URL: `http://localhost:8080`. Use the exact configured public
origin rather than switching interchangeably between localhost and an IP.

## Existing installation

`./wpl setup --check` validates prerequisites, saved configuration, frontend/backend
agreement, Compose ownership and ports. It does not write, build, restart, apply
migrations or contact external identity/email/GitHub services.

`./wpl urls` prints the required public origin and callback addresses without
revealing credentials. Running `./wpl setup` again reuses the existing environment
file and signing key; it does not rotate secrets or reset the database.

Setup refuses a database without its matching private configuration. It also
refuses to silently use an obsolete root `wpl.db` instead of `data/wpl.db`.
The API, migrations and inactivity code share the configured database location.

### Adopting the temporary external deployment

The restart baseline currently uses an external Compose wrapper. To inspect
adoption without changing it:

```bash
./wpl setup --check --adopt-existing /home/wibyte/wpl-baseline-runtime-2ad4c06/compose.json
```

After saving and closing all labs in the UI, the same command without `--check`
builds and recreates the known backend/web services under this checkout:

```bash
./wpl setup --adopt-existing /home/wibyte/wpl-baseline-runtime-2ad4c06/compose.json
```

This is an explicit exception to the normal foreign-checkout refusal. Adoption
requires matching credentials/public origin, exact Compose ownership labels and
the preserved database bind mount. A recorded lab prevents adoption before any
build/restart, with a second check before cutover. It does not delete lab records,
student containers, databases, volumes, providers or the old wrapper.

Back up the existing SQLite database consistently and preserve its private keys
before cutover. The external wrapper remains a rollback artifact, not the active
source of configuration after successful adoption. Recreating the application
disconnects browser/API transports; save and close labs first.

## Daily commands

```bash
./wpl start                 # Build changed application images and start
./wpl stop                  # Stop backend/web; do not delete data or lab containers
./wpl restart               # Rebuild/recreate backend/web
./wpl status
./wpl logs --follow
./wpl urls
```

`start` and `restart` first perform setup checks. Use `setup` to rebuild the
student image after changing `container/Dockerfile`; existing labs retain their
current image. Changing code does not update an existing container until rebuilt.
Database model changes still require proper Alembic migrations.

## Configuration

`backend/.env` is the source for Compose credentials and public build settings.
It is excluded from Git and Docker build contexts. Do not print a full resolved
Compose configuration in a report: it contains secrets.

| Variable | Purpose/default |
| --- | --- |
| `WPL_PUBLIC_URL` | Public browser origin, default wizard choice `http://localhost:8080` |
| `WPL_LISTEN_ADDRESS` | Web listener, `127.0.0.1` by default |
| `WPL_HTTP_PORT` | Internal web port, 8080 locally; cannot overlap backend 8000 |
| `WPL_DATABASE_PATH` | Host paths resolve from repository root; Compose overrides to `/data/wpl.db` |
| `SUPABASE_URL` | Existing project's HTTPS origin |
| `SUPABASE_PUBLISHABLE_KEY` | Public browser/authentication key |
| `SUPABASE_SECRET_KEY` | Backend-only account lookup key |
| `WPL_GITHUB_CLIENT_ID`, `WPL_GITHUB_CLIENT_SECRET` | GitHub App OAuth credentials |
| `WPL_SECRET_KEY` | Preserved signing key for OAuth state and GUI cookies |
| `WPL_LAB_IMAGE` | `wpl-student:dev` |
| `WPL_LAB_MEMORY`, `WPL_LAB_CPUS`, `WPL_LAB_PIDS_LIMIT` | `1g`, `0.25`, `256` |
| `WPL_IDLE_MINUTES` | 30; current auto-save/push and failure preservation still apply |

The API URL, GUI URL, CORS origin and GitHub redirects derive from the public
origin. Optional standalone API/GUI overrides exist, but this Compose setup
requires the same public origin with `/api`. Backend process environment takes
precedence over the file. Compose checks reject mismatched frontend/backend
overrides rather than silently building against different projects.

The frontend gets only the API URL and Supabase public values as build arguments.
Rebuild it after changing those. `frontend/.env` is for standalone Vite development,
not the Compose configuration authority; use its example only for that workflow.

## Provider callbacks and HTTPS

For the chosen public origin, setup prints:

- Supabase confirmation destination: the origin itself.
- Password recovery: `<origin>/reset-password`.
- GitHub App OAuth callback: `<origin>/api/github/callback`.

These must be allowed at the existing providers. Do not replace a production
project's Site URL/callbacks blindly to test locally. Add supported development
redirects or use an appropriate development App when one cannot serve both.
This toolkit does not change provider settings or prove that email is delivered.
Preserve existing Resend/SMTP configuration and test it separately.

For a **fresh** Supabase project only, `supabase/001_profiles_and_access.sql`
provides the profiles/approval baseline. Do not rerun it on the existing project.
Existing schema/policies/accounts require inspection rather than replacement.
Approval is still enforced by the backend; the wizard does not approve users.

For HTTPS, configure a real certificate/TLS proxy separately and forward the
public origin to the loopback web listener, including WebSocket upgrades.
Setting an HTTPS URL does not issue a certificate or change DNS. GUI cookies are
Secure and noVNC requests encrypted WebSockets when the configured GUI URL is
HTTPS. Local HTTP uses non-Secure cookies and ordinary WebSockets. Nginx authenticates
GUI requests before forwarding to the registered loopback container port.
No JSON response rewriting or stripping Secure flags is needed.

## Data, portability and acceptance

Preserve `data/wpl.db` and the matching private environment/signing key when moving
machines. Student writable layers, unsaved browser buffers and live processes are
not SQLite backups. Normal stopping does not introduce durable named-workspace
storage; the current application's GitHub-backed persistence semantics remain.

The current inactivity service commits/pushes saved work and verifies the remote
before removing a lab. On save/push failure it keeps the lab and resumes programs.
This toolkit makes its timeout configurable; it does not replace that behavior.

Verification includes setup/adoption/secret-preservation tests, configuration and
HTTP/HTTPS GUI/OAuth checks, migrations against a temporary database, and mocked
inactivity success/failure regressions. Browser acceptance should cover signup/
approval/login, recovery email, new GitHub authorization, terminal/Python input and
Stop, files, combined Commit & Push, GUI background/settings and closure notices.
Use an explicitly approved disposable repository for real push/inactivity tests.
Basic health checks do not establish all authenticated/provider workflows.

No Google Cloud resources, paid services, account resets, database redesign,
dashboard features or automatic TLS/email provisioning are part of this toolkit.

## Recreation validation — 20 October 2026

The existing local deployment was adopted into this checkout after the user
saved and closed the last lab. Both application containers became healthy at
`http://localhost:8080`. Every SQLite row and both private environment files
matched the fresh pre-cutover backup; integrity passed and Alembic remained at
`7d8e63fb45c3`. The student image remained unchanged. The external baseline
wrapper/images and private backup remain available as recovery artifacts.

Validation passed: 15 setup/configuration/adoption tests, eight isolated backend
configuration/migration/route/inactivity tests, the frontend TypeScript/Vite
production build, and a disposable Docker/nginx startup and authentication-boundary
test. Live direct/proxied health checks and anonymous lab/GUI rejection passed.
No real provider email, GitHub consent or repository push was performed. The
browser acceptance workflows listed above still need a user-run check.

The frontend build reports three existing dependency audit findings (two moderate,
one high) and a large-bundle warning. Only the targeted brace-expansion lockfile
update is included here; this change is not a full dependency/security upgrade.
