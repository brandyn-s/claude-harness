"""Shared spec dataclasses for vendor data-channel drift registries.

One definition of the contract, consumed by every vendor registry
(gather-claude-endpoints/scripts/channel_specs.py,
gather-openai-endpoints/scripts/openai_channel_specs.py) and by the engine
(diff_engine.py, same directory). Moved out of the Anthropic registry
2026-08-22 so registries are symmetrical consumers rather than one importing
its dataclasses from the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Extractor:
    """One normalized fact-set pulled from a channel's doc page.

    key          stable identifier; names the baseline file
    pattern      regex whose capture group(s) are the fact (see `kind`)
    min_expected floor below which extraction is treated as BLIND, not as removal
    kind         'set'  one group  -> the fact itself
                 'map'  two groups -> name=value, DEDUPED BY NAME (rate limits:
                        one name has one value, a second occurrence is a repeat)
                 'pair' two groups -> "G1 G2", every distinct COMBINATION kept
                        (verb+path: one path legitimately has several verbs, so
                        map's key-dedup would silently drop all but one)
    note         what a diff on this fact-set actually means operationally
    normalize    ((regex, replacement), ...) applied to every captured value
                 before dedup. Default () = no-op, so existing registries are
                 unaffected.

                 Added 2026-08-30. Some vendor pages declare no endpoint marker
                 at all -- every path appears only inside a `curl` example -- so
                 the fact IS whatever the example renders. When Anthropic
                 re-rendered its Admin API examples from `{workspace_id}` to a
                 concrete `wrkspc_01JwQvzr...`, three channels reported phantom
                 added/REMOVED pairs for an UNCHANGED endpoint set, and a
                 `--update-baseline` would have frozen a literal example ID into
                 the baseline -- guaranteeing the same churn on every future
                 rotation of that example. Canonicalizing the volatile segment
                 back to its placeholder makes the fact-set describe the ENDPOINT
                 rather than the vendor's choice of sample data.

                 Prefer a declaration marker where one exists (see
                 compliance-endpoint-paths); this is for pages that have none.
    """

    key: str
    pattern: str
    min_expected: int
    kind: str = "set"
    note: str = ""
    # For kind='map': a second group is the value. Pattern must have 2 groups.
    normalize: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ProseTrigger:
    """A machine-checkable Watching-table row, evaluated on the fetched page.

    expect='present': the pattern MUST match, or the trigger fires (something we
                      rely on — an exclusion sentence, a beta marker — changed).
    expect='absent':  the pattern must NOT match, or the trigger fires (a
                      capability appeared).

    A fired trigger is DRIFT-class for the exit code: it is a real state change
    on the vendor surface, not an instrument problem. A trigger's pattern must
    be INDEPENDENT of the channel's liveness marker — CHANNEL_DEAD short-circuits
    before triggers evaluate, so a trigger on the marker string is unreachable.
    """

    key: str
    pattern: str
    expect: str  # 'present' | 'absent'
    note: str = ""


@dataclass(frozen=True)
class ChannelSpec:
    """One vendor doc surface and the fact-sets extracted from it.

    local_path: when set, the channel is a MANUAL-EXPORT surface — the engine
    reads this file instead of fetching `url` (which then serves as the
    human-readable pointer to where the export comes from). Built for
    login-gated references (e.g. chatgpt.com/admin/api-reference) that cannot
    be fetched: an operator pastes/export-saves the page periodically. A
    missing file reports LOCAL_SOURCE_MISSING — a standing, non-exit-gating
    gap, never FETCH_FAILED — so an un-refreshed export cannot fail the run.
    """

    key: str
    title: str
    url: str
    marker: str
    surface: str  # e.g. 'claude.ai' | 'platform' | 'chatgpt-enterprise' | 'self-hosted'
    extractors: tuple[Extractor, ...] = field(default_factory=tuple)
    note: str = ""
    prose_triggers: tuple[ProseTrigger, ...] = field(default_factory=tuple)
    local_path: str = ""  # '~'-expandable; relative paths resolve against --kb; empty = ordinary fetched channel
