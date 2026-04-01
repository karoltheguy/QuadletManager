# QuadletManager Development Plan

## Objective
Build a self-hosted, agentless web dashboard to manage Podman Quadlets on multiple remote Linux servers via Systemd.

## 1 through 8 are implemented.

## 9. Future Work (Not Required for MVP)
* Maintenance & Hardening
  * Security audit — review for edge cases (input sanitization, SSH key handling, session management)
  * Dependency updates — ensure all packages are up to date
  * Error handling — verify graceful recovery in all failure scenarios (SSH drops, DB corruption, etc.)
* New Features
  * Multi-user sessions — allow concurrent editors with conflict resolution
  * Audit log — track who changed what, and when
  * Backup & restore — snapshot quadlet configs before edits
  * Dark/light theme toggle — if not already implemented
  * Notification preferences — Slack/email alerts on file changes or service failures
  * Quadlet dependency visualization — graph relationship between containers, volumes, networks, and pods
* DevOps & Deployment
  * Containerize QuadletManager itself — ship as a Docker/Podman image for easy deployment
  * CI/CD pipeline — automated testing and deployment on push
  * Helm chart or Compose file — one-command deployment
* Documentation
  * User guide / walkthrough — beyond the setup guide, a full usage tutorial
  * API documentation — auto-generated OpenAPI/Swagger docs from FastAPI