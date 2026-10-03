# Docker Guidelines

## Images

- Smallest base that works (alpine/distroless by default). Pin to a minor version or digest.
- Install dependencies before copying source so the layer caches.
- Clean build tools and caches in the same layer that created them; multi-stage builds
  for compiled languages.
- Run as a non-root user. No `--privileged`.
- Exec-form `CMD ["exe", "arg"]` so `SIGTERM` reaches the process.
- Add a `HEALTHCHECK` for long-running services.
- Always ship a `.dockerignore` (`.git/`, build output, `.env`, IDE files, test output).

## Secrets

Never in an image — not via `ARG`, `ENV`, or `COPY`. Pass at runtime.

Compose stacks split config from secrets:

| File | Tracked? |
|---|---|
| `<name>.env` | yes — non-secret config |
| `<name>.secrets.env` | no — gitignored |
| `<name>.secrets.env.example` | yes — each var blank, with a one-line source comment |

## Compose and tagging

- Local dev via `docker compose`; named volumes for persistent data.
- `docker compose -f <file> config` must pass before a change is done.
- Never deploy only `latest`; tag with the commit SHA and/or semver.
