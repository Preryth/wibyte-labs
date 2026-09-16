# VPS deployment and operations

## Service control

systemctl status wibyte-backend nginx --no-pager
systemctl restart wibyte-backend
journalctl -u wibyte-backend -f

The wibyte-frontend preview service is disabled.
Nginx serves the frontend build directly.

## Deploy backend changes

cd /root/wibyte-labs
systemctl restart wibyte-backend
curl --fail --retry 5 --retry-connrefused --retry-delay 2 http://127.0.0.1:8000/health
curl --fail https://labs.wibyte.in/api/health

## Build and publish frontend changes

cd /root/wibyte-labs/frontend
VITE_API_URL=https://labs.wibyte.in/api npm run build &&
cp -a dist/. /var/www/wibyte-labs/ &&
chmod -R a+rX /var/www/wibyte-labs

Refresh browser tabs after deploying.
A build alone does not publish files to Nginx.

## Rebuild the student image

docker build -t wpl-student:dev /root/wibyte-labs/container

Only newly created containers use the rebuilt image.

## Configuration outside Git

- /etc/nginx/sites-available/wibyte-labs
- /etc/systemd/system/wibyte-backend.service
- /etc/systemd/system/wibyte-backend.service.d/listen-local.conf
- /etc/letsencrypt/
- Backend environment secrets and frontend environment files
- Supabase, Resend, GitHub App, and WordPress DNS settings
- Application database: /root/wibyte-labs/wpl.db

These must be backed up separately. Do not commit secrets, certificate
private keys, or the live database.

## Authentication configuration

- Supabase Site URL: https://labs.wibyte.in
- GitHub callback: https://labs.wibyte.in/api/github/callback
- Sender: WiByte Labs <noreply@labs.wibyte.in>
- Supabase email sending limit currently configured: 30/hour
- Resend account quotas also apply.

## Certificates

certbot renew --dry-run

Automatic renewal is configured and its simulation passed.
During ownership transfer, update the Certbot contact email to the new
WiByte account:

certbot update_account --email NEW_WIBYTE_EMAIL

## Final checks

- Signup, confirmation, resend, password reset, and approval/login
- GitHub authorization, token refresh, and repository push
- Terminal input, Python input(), Run and Stop
- HTTPS GUI; unauthenticated GUI access returns 403
- Idle lab removal after approximately 30–31 minutes
- Backend restart without socket cleanup warnings
