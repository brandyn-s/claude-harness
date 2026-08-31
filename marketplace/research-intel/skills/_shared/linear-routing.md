# Issue-tracker routing — TEMPLATE (fill in your own)

Maps a repository to the tracker project that its work belongs to, so a skill
posting a status update does not have to ask.

**This ships empty on purpose.** The original contained one workspace's project
identifiers. Replace the example row with your own.

| Repo | Project / team | Identifier | Notes |
|---|---|---|---|
| `example-repo` | Example Project | `<project-id>` | default target for status updates |

## Column contract

- **Repo** — matches the Repo column in `repo-map.md`.
- **Project / team** — the human-readable name, for the update text.
- **Identifier** — whatever your tracker's API needs (a UUID for Linear, a key
  like `PROJ` for Jira). Treat it as opaque.
- **Notes** — routing caveats: an initiative rather than a project, a repo whose
  work is split across two targets, a repo that should be skipped.

## Unmapped repos

A skill that cannot resolve a repo here should say so and stop, not guess. An
update posted to the wrong project is worse than no update, because someone has
to notice it before it can be corrected.
