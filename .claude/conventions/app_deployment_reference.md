# App Deployment Reference Convention

Applies to **application repos** whose deployed instance is owned by a separate
deployment repo. Defines the contract an app repo must publish so the deployment repo
can adapt it without guessing.

## Division of responsibility

An app repo owns:
- Its source code, tests, and CI/CD — building and publishing its own image.
- A **deployment reference**: an accurate, minimal description of what its image needs
  to run. Nothing more.

An app repo does **not** own:
- Where or how it's actually deployed.
- Host-level bootstrapping (dedicated service users, directory ownership/permissions).
- Live secret values, or the deployment repo's own conventions (folder layout,
  secrets-split, container naming).

The deployment repo reads the app repo's deployment reference and adapts it into its
own conventions. Changes flow one direction: app repo → deployment repo. The deployment
repo's adapted copy is derived, not independently maintained — don't let it drift into
a second source of truth.

## Required files (repo root, unless there's a reason to nest them)

- **`docker-compose.deploy.yml`** — a real, valid Compose file: image reference (pinned
  appropriately per your own tagging convention), ports, volumes (bind mount vs. named
  volume, stated plainly), restart policy. This must stay an actual, parseable compose
  file — `docker compose -f docker-compose.deploy.yml config` should always succeed —
  not degrade into prose. A deployment repo's sync process (or a human) reads this file
  directly; it can't reliably parse a paragraph.
- **`.env.example`** — every env var the deploy file references, with a placeholder and
  a one-line comment. Non-secret vars can have a sensible default inline; secret vars
  should be left blank with a comment explaining where the value comes from. The file
  split in the deployment repo (`.env` vs `.secrets.env`) is the deployment repo's
  concern — the app repo just needs to document what's needed.

## Example

```yaml
# docker-compose.deploy.yml
services:
  my-app:
    image: ghcr.io/owner/my-app:latest
    pull_policy: always
    ports:
      - "${HOST_PORT:-8080}:8080"
    volumes:
      - app_data:/app/.cache
    restart: unless-stopped
volumes:
  app_data:
```

```
# .env.example
HOST_PORT=8080        # port the app is exposed on
SOME_API_KEY=         # from provider's dashboard — required at runtime
```

## Change signal

When `docker-compose.deploy.yml` or `.env.example` changes, that is the signal the
deployment repo's adapted copy may need re-syncing. Note this in the PR description
so the deployment repo maintainer knows to update their copy.
