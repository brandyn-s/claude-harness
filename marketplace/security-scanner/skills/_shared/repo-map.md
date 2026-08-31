# Repo map — TEMPLATE (fill in your own)

Maps a repository name to where it lives locally and anything a skill needs to
know to operate on it. `/pr-fix` and its references read this file rather than
hard-coding paths, so that adding a repo is a data change, not a code change.

**This ships empty on purpose.** The original was an inventory of one person's
repositories. Add your own rows; the columns are the contract.

| Repo | Local path | Writable remote | Notes |
|---|---|---|---|
| `example-repo` | `$HOME/code/example-repo` | `origin` | Fork: pass `--repo owner/example-repo` to every `gh pr` command |

## Column contract

- **Repo** — the bare repository name, as `gh` reports it.
- **Local path** — absolute, `$HOME`-relative. Skills resolve from here; never
  hard-code a path in a skill.
- **Writable remote** — `origin` for a direct clone. For a fork, the remote that
  accepts your pushes, which is why the Notes column carries `--repo`: `gh pr`
  guesses wrong on forks and will target upstream.
- **Notes** — anything a skill must pass explicitly. Fork targeting, a protected
  branch, a required review, a non-default branch name.

## Why a file and not a constant

The map changes far more often than the skills that consume it, and it is the
only place that knows about your environment. Keeping it separate is what lets
the surrounding skills be portable.
