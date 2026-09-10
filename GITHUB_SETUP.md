# GitHub production setup

These repository settings accompany the committed workflows and cannot be
expressed completely as files in the repository.

## `main` ruleset

Create a branch ruleset targeting `main`:

- require a pull request before merge;
- require the `test` status check;
- require the branch to be up to date before merge;
- block force pushes and branch deletion;
- allow repository administrators to perform an emergency bypass, with the
  bypass recorded in GitHub.

## `production` environment

Create an environment named `production` and add:

- `VPS_HOST`;
- `VPS_USER`;
- `DEPLOY_KEY`.

Restrict deployment branches to `main`. The current workflow deploys
automatically after its checks; add required reviewers only if a manual gate is
desired later.

## Actions and repository security

- Set the default workflow token permission to read-only contents.
- Allow GitHub-authored actions plus the pinned `appleboy/scp-action` and
  `appleboy/ssh-action` commits used by the deploy workflow.
- Enable Dependabot alerts and security updates.
- Enable secret scanning and push protection when available for the repository.
- Keep `.env`, private keys and production state outside Git. Rotate a credential
  immediately if secret scanning ever reports it in history.

## Visibility

The repository is currently public. Keep it public only if publishing the bot
source is intentional. Changing visibility is an owner decision; secrets must
remain external in either case.
