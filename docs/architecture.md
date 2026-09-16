# WiByte Labs architecture

## Current deployment

- Hostinger VPS: 200.234.44.47
- Application: https://labs.wibyte.in
- Repository checkout: /root/wibyte-labs
- Frontend: React/Vite build served by Nginx from /var/www/wibyte-labs
- Backend: FastAPI, managed by wibyte-backend.service
- Backend listener: 127.0.0.1:8000
- Nginx forwards /api/ requests and terminal WebSockets to the backend.
- Student labs run as Docker containers using wpl-student:dev.
- GUI ports bind to 127.0.0.1 and are accessed through an authenticated
  HTTPS proxy at /gui/<lab-id>/.
- Supabase provides student authentication and approval checks.
- Resend provides SMTP for Supabase authentication emails.
- GitHub stores student repositories.
- Local application metadata is stored in /root/wibyte-labs/wpl.db.

## Lab lifecycle

Labs are temporary. The inactivity worker checks every 60 seconds and
removes labs after 30 minutes without recorded user activity.
Editor/browser interaction, terminal actions, and GUI input contribute
to activity tracking.

Deleting a lab removes its container workspace, including unpushed work.
Students must push work to GitHub to preserve it beyond the lab lifecycle.

## Authentication and transport

Public application access uses HTTPS.
Terminal authentication is sent in the first WebSocket message.
GUI access uses a signed, scoped cookie and lab ownership checks.
The old Vite preview service is disabled.

## Infrastructure

This deployment uses Docker directly on the VPS.
Google Cloud and Kubernetes are not part of the current deployment.
