# Docker Guidelines

## Images

### Keep images small
- Use the smallest appropriate base image: prefer `alpine` or distroless variants when
  the runtime supports them. Only use full `debian`/`ubuntu` bases when you have a
  specific dependency that requires them.
- Remove build-time tools and caches in the same layer they are created to avoid
  bloating intermediate layers:
  ```dockerfile
  RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
   && make /app \
   && apt-get purge -y build-essential \
   && rm -rf /var/lib/apt/lists/*
  ```

### Use multi-stage builds for compiled languages
Separate the build environment from the runtime image. The final image should contain
only the compiled output and its runtime dependencies, not build tools, source code,
or test artifacts:

```dockerfile
FROM sdk-image AS build
COPY . .
RUN build-command

FROM runtime-image
COPY --from=build /app/output /app
```

### Layer ordering
Put layers that change infrequently early in the Dockerfile. Dependency installation
(e.g., `npm install`, `pip install`) should come before copying application source,
so the dependency layer is cached across routine code changes.

## Secrets

**Never embed secrets in images.**

- Do not use `ARG` or `ENV` for secrets — they are visible in `docker inspect` and
  image history.
- Do not `COPY` files containing secrets (`.env`, credential files, certificates with
  private keys) into an image.
- Pass secrets at runtime via environment variables, Docker secrets (`--secret`), or
  a secrets management service. In compose, use `secrets:` and `environment:` rather
  than baking values into the image.

### Env file split for Compose projects

Split config from secrets across three files per stack:

- **`<name>.env`** — non-secret config (tracked). Safe to version-control.
- **`<name>.secrets.env`** — secret values only (gitignored). Never committed.
- **`<name>.secrets.env.example`** — documents every secret var with a placeholder
  and a one-line comment explaining where the value comes from:

```
# <name>.secrets.env.example
API_KEY=        # from provider's dashboard
DB_PASSWORD=    # set during host bootstrap
```

Add `*.secrets.env` to `.gitignore` and commit only the `.example` file.

## Security

- **Run as a non-root user.** Create a dedicated user in the Dockerfile and switch to
  it before the final `CMD`/`ENTRYPOINT`:
  ```dockerfile
  RUN addgroup --system app && adduser --system --ingroup app app
  USER app
  ```
- Drop unnecessary Linux capabilities. Avoid `--privileged` in production.
- Pin base image tags to a digest or at least a minor version — `FROM node:20.11-alpine`
  not `FROM node:latest`.

## Health Checks

Define a `HEALTHCHECK` instruction so orchestrators know when a container is ready and
when it has degraded:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8080/health || exit 1
```

For non-HTTP services, use a language-appropriate probe (e.g., a database ping command).

## Graceful Shutdown

Ensure the main process handles `SIGTERM` and shuts down cleanly within the orchestrator's
termination grace period. Use `CMD ["executable", "arg"]` (exec form) rather than
`CMD executable arg` (shell form) — shell form wraps the process in a shell that will
not forward signals.

## .dockerignore

Always include a `.dockerignore`. At minimum, exclude:
- `.git/`
- Local build outputs (`bin/`, `obj/`, `dist/`, `node_modules/`, `__pycache__/`)
- Local environment files (`.env`, `*.local`)
- IDE and OS metadata (`.vscode/`, `.DS_Store`)
- Test results and coverage reports

## Local Development

Use `docker compose` (or `docker-compose`) for local development rather than bare
`docker run` chains. Keep a `compose.yaml` (or `docker-compose.yml`) in the repo root
with the local development configuration.

- Use named volumes for data that should persist across container restarts.
- Use bind mounts for source directories you want to edit live during development.
- Define a separate override file (`compose.override.yaml`) for developer-specific
  settings rather than committing them to the base compose file.

## Validation

For declarative Compose repos with no build step, `docker compose config` is the
minimum static check before treating a change as done:

```bash
docker compose -f <stack>-compose.yaml config
```

This catches YAML syntax errors, undefined variables, and invalid Compose keys before
anything touches a running environment. It does not replace a live smoke test — verify
the stack actually comes up healthy after any structural change.

## Image Tagging

- Never rely solely on `latest` in production deployments — it is mutable and makes
  rollback ambiguous.
- Tag images with at minimum the git commit SHA. Semantic version tags are also useful
  for release images.
- Convention: `<registry>/<image>:<semver>` for releases, `<image>:<sha>` for CI builds.
