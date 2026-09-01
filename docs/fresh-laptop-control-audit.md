# Fresh-laptop control audit

The redesign tests one hypothesis: the original harness remained effective but
accumulated ambient cost, version-specific compensations, and overlapping
controls that could work against one another.

## Verdict

| Hypothesis | Verdict | Evidence | Design response |
|---|---|---|---|
| The harness became bloated | Confirmed | 97,380 measured ambient tokens; roughly 109,000 in a typical coding session after path rescoping | Fresh default is 2 rules and 3 hooks; everything else is opt-in |
| Older-Claude lessons remain ambient | Confirmed in part | `never-stop-early` enforces session persistence; `validate-to-improve` says every passing validation must produce more work | Retained as historical source, removed from the installable rule set |
| Controls can fight each other | Confirmed for one concrete path | `promise-checker.py` blocks phrases such as “let's wrap up” without checking whether the requested outcome is complete, while `outcome-over-verification` requires stopping once decisive evidence passes | Stop hook demoted; the outcome contract owns termination |
| Rules can fight each other | Confirmed | `validate-to-improve` prohibits stopping at PASS; `outcome-over-verification` requires stopping when decisive evidence passes | `validate-to-improve` demoted from installation |
| Low friction requires blanket authority | Refuted | Claude Code can auto-approve sandbox-contained Bash independently of permission mode | Use `acceptEdits` + sandbox auto-allow; unsandboxed commands return to permission review |

This does not imply every old rule or hook is obsolete. It means historical
presence is no longer enough to earn ambient or blocking status.

## Control ownership

The fresh-laptop core has one owner per concern:

| Concern | Owner | Why it remains custom |
|---|---|---|
| Filesystem and process containment | Claude Code sandbox | Native OS-enforced boundary |
| Fast local edit flow | `acceptEdits` + sandbox auto-allow | Native behavior, no custom classifier or hook needed |
| Credential paths and destructive shapes | native denies + `bash-security-guard.py` | Native paths cover files; the hook covers semantic command shapes |
| Harness config integrity | `config-guard.py` | Cross-file harness invariants are not expressible as permission rules |
| Untrusted MCP result instructions | `result-injection-guard.py` | Content-level trust check is outside the sandbox's scope |
| Work/verification stopping condition | `outcome-over-verification.md` | One bounded decision contract; no competing Stop hook |
| Harness authoring quality | `claude-md-quality.md` | Small ambient routing contract for configuration work |

## Promotion gate

A component joins the daily core only if all are true:

1. A measured failure or durable safety requirement exists.
2. Native permissions, sandboxing, or an on-demand skill cannot cover it.
3. It has a direct behavior test and a named failure mode.
4. Its token or runtime cost is bounded.
5. It has one owner and does not contradict an existing control.

Failing any item means the component stays on-demand, author-profile-only, or
historical. This is the operational meaning of **simple, fast, correct**.

## Personal operator layer

The portable core is the kernel, not the complete owner workstation. The
`brandyn-operator` overlay promotes a bounded middle set whose failure modes are
specific to the owner's work:

- `delivery` policy inside the existing Bash hook process;
- explicit review for Terraform, AWS, destructive Git-history, and mutating MCP
  operations;
- one compact diagnostic/change-history/negative-search rule;
- non-blocking repeated-failure detection; and
- prompt and tool-output secret protection.

Portability policy is selected only on affected hosts, and workflow preferences
remain opt-in. The phrase-based `promise-checker` and the contradictory
`validate-to-improve`/`never-stop-early` contracts remain demoted.

## Re-evaluation loop

Do not bulk-promote the author mirror after installing a new laptop. Use the
small core for real work, record concrete friction or escaped failures, and
promote one component at a time through the gate. Re-run the context report and
the direct test for that component; do not require a new meta-harness.
