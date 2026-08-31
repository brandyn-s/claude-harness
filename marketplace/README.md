# marketplace/ — GENERATED. Do not edit.

Every file under this directory is assembled by
[`scripts/build-marketplace.py`](../scripts/build-marketplace.py) from the
sources in `skills/`, `hooks/`, `agents/` and `bin/`. Editing anything here is
lost on the next build.

**Reviewing this repository? Read `skills/`, `hooks/` and `rules/` instead.**
This tree is a packaging artifact and roughly doubles the file count.

## Why it is duplicated at all

Not sloppiness — a constraint of the plugin format. From the Claude Code docs:

> when users install a plugin, Claude Code copies the plugin directory to a cache
> location... Copied plugins can't reference files outside their directory using
> paths like `../shared-utils`, because those files won't be copied.

So each plugin **must be self-contained**. One source of truth plus generated
self-contained bundles is the only shape that satisfies both.

## Why it is committed rather than gitignored

`/plugin marketplace add <owner>/<repo>` fetches the plugin sources at the paths
named in `.claude-plugin/marketplace.json`. If this tree is not in the
repository, installing from GitHub cannot work.

`.gitattributes` marks it `linguist-generated`, so GitHub collapses it in diffs
and excludes it from language statistics.

## Rebuilding

```bash
git fetch origin main          # the version ledger lives in origin/main
python3 scripts/build-marketplace.py
```

The build refuses to run without that ledger. That is deliberate: a release build
must not invent version numbers with no evidence of what was published before.
CI re-runs the build and fails if the result differs from what is committed.
