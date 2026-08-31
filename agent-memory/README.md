# agent-memory/ — convention, not content

This directory is **intentionally empty** in the public copy.

In the original it holds `topics/*.md`: one file per system the agent operates,
carrying the vendor gotchas, API quirks, and hard-won operational detail that
sessions accumulate. That content is specific to one organisation's
infrastructure and is not published. The **convention** is the transferable
part, so it is documented here.

## The idea

Rules encode *how to work*. Topic files encode *what is true about a specific
system*, and they are loaded on demand rather than always — so the ambient
context stays small while the detail stays reachable.

```
agent-memory/
  topics/
    <system>.md      # one file per system: aws.md, github.md, slack.md, ...
```

A topic file is worth writing when a fact is:

- **durable** — it will still be true next month;
- **costly to rediscover** — it took a failed attempt or a doc dive to learn;
- **not derivable from the code** — the repo cannot tell you the API silently
  caps a page at 500, or that a filter with an unknown field returns everything
  instead of erroring.

Anti-pattern: restating what the code already says. If `git log` or the source
answers it, a topic file adds drift risk and nothing else.

## Routing

`rules/agent-delegation.md` maps task keywords to the topic files a subagent
should be handed. Keep that table in sync with whatever files you create here;
a topic file nothing routes to will never be read.

## Getting started

Create `topics/` and add files as you hit facts worth keeping. Start from a real
surprise rather than trying to document a system up front — the first entry in
most of these files was a bug.
