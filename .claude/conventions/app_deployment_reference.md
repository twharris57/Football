# App Deployment Reference

The app repo publishes what its image needs; a separate deployment repo adapts it.
Changes flow one way: app repo → deployment repo.

**The app repo owns:** source, tests, CI, image publishing, and a deployment reference.
**It doesn't own:** where it runs, host setup, live secrets, or the deployment repo's layout.

## Required files (repo root)

- **`docker-compose.deploy.yml`** — a real, parseable compose file: image, ports,
  volumes, restart policy. `docker compose -f docker-compose.deploy.yml config` must pass.
- **`.env.example`** — every var the deploy file uses, each with a one-line comment.
  Secrets blank, with their source.

```yaml
services:
  my-app:
    image: ghcr.io/owner/my-app:latest
    pull_policy: always
    ports: ["${HOST_PORT:-8080}:8080"]
    volumes: [app_data:/app/.cache]
    restart: unless-stopped
volumes:
  app_data:
```

When either file changes, say so in the PR so the deployment repo gets re-synced.
