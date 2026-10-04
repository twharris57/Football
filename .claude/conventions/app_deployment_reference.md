# App Deployment Reference

The app repo publishes what its image needs; a separate deployment repo adapts it.
Changes flow one way: app repo → deployment repo.

**The app repo owns:** source, tests, CI, image publishing, and a deployment reference.
**It doesn't own:** where it runs, host setup, live secrets, or the deployment repo's layout.

## Required files (repo root)

Same config/secrets split as `docker_guidelines.md`, so the deployment repo can copy the
templates straight across:

- **`docker-compose.deploy.yml`** — a real, parseable compose file: image, ports,
  volumes, restart policy. `docker compose -f docker-compose.deploy.yml config` must pass.
- **`.env.example`** — non-secret config only, each var with a one-line comment.
- **`<name>.secrets.env.example`** — every secret, blank, each with a comment on where it
  comes from. The real `<name>.secrets.env` is gitignored.

```yaml
services:
  my-app:
    image: ghcr.io/owner/my-app:latest
    pull_policy: always
    ports: ["${HOST_PORT:-8080}:8080"]
    env_file:
      - path: ./my-app.secrets.env
        required: false  # only if every secret is optional
    volumes: [app_data:/app/.cache]
    restart: unless-stopped
volumes:
  app_data:
```

When any of these files change, say so in the PR so the deployment repo gets re-synced.
