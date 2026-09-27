# Security Policy

## Supported Versions

Only the **latest release** receives security fixes. If you self-host, upgrade to the latest
release before reporting, and check whether the issue still reproduces there.

## Reporting a Vulnerability

**Do not report security vulnerabilities through public issues, pull requests or discussions.**

Report them privately through GitHub's private vulnerability reporting: open this repository's
**Security** tab and choose **Report a vulnerability**. Only the maintainer can see the report.

Please include:

- the affected component (backend API, MCP server, frontend, an integration worker, or a
  published container image) and the release or commit you tested;
- a description of the vulnerability and its impact;
- steps to reproduce, or a proof of concept;
- any known mitigation or suggested fix.

Please do not access, change or delete other people's data, and give us reasonable time to fix
the issue before you disclose it.

## What to Expect

This project has a single maintainer, so these times are best effort:

- **Acknowledgement** within **7 days**.
- **Initial assessment** within **14 days**: whether the report is accepted and how severe it is.
- **Fix and disclosure:** agreed with you, based on severity. Accepted reports are fixed in a
  new release and published as a GitHub security advisory, crediting you unless you prefer
  otherwise.

## Scope

In scope:

- the code in this repository;
- the container images published from it.

Out of scope:

- vulnerabilities in a particular self-hosted deployment's configuration or infrastructure;
- third-party services the app integrates with (for example Google, Strava, Immich or Snipe-IT);
- issues in dependencies that are already publicly known and tracked upstream. You are still
  welcome to report if this project needs to act.
