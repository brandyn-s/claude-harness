# Third-party notices

This project contains modified portions of the following permissively licensed
projects. The upstream copyright notices and MIT permission notice are retained
here; local files identify the adapted mechanism where practical.

| Project | Copyright | License | Used for |
|---|---|---|---|
| [flonat-research](https://github.com/flonat/flonat-research) | Copyright (c) 2026 Florian Burnat | MIT | selected hook concepts |
| [paceflow](https://github.com/paceaitian/paceflow) | Copyright (c) 2026 paceaitian | MIT | protected-config guard concept |
| [superpowers](https://github.com/obra/superpowers) | Copyright (c) 2025 Jesse Vincent | MIT | the four companion skills (`debugging-hypotheses`, `legacy-code-tdd`, `design-evidence-first`, `review-depth-by-risk`) were extracted from earlier forks of its planning, debugging, and TDD skills; the forks themselves were removed 2026-09-03 in favour of the installed plugin |
| [turbo](https://github.com/tobihagemann/turbo) | Copyright (c) 2026 Tobias Hagemann | MIT | selected planning, review, threat-model, and learning workflow patterns |
| [prompt-master](https://github.com/nidhinjs/prompt-master) | Copyright (c) 2026 Nidhin Joseph Nelson | MIT | prompt diagnostic reference patterns |
| [claude-pipeline](https://github.com/aaddrick/claude-pipeline) | Copyright (c) 2025 aaddrick | MIT | resolution-gate pattern in distill |
| [microsoft/skills](https://github.com/microsoft/skills) | Copyright (c) Microsoft Corporation | MIT | architecture-review template structure |
| [trailofbits/skills](https://github.com/trailofbits/skills) | Copyright (c) Trail of Bits | CC BY-SA 4.0 | `fp-check`, `semgrep`, `codeql`, `differential-review`, `semgrep-rule-creator`, `threat-model` skill structure and the `data-flow-analyzer`, `exploitability-verifier`, `poc-builder`, `semgrep-scanner` agents |

The Trail of Bits material is licensed CC BY-SA 4.0, not MIT: the files adapted
from it carry that attribution and remain available under the same
ShareAlike terms regardless of this repository's top-level LICENSE.

For each MIT entry, the MIT License grants permission, free of charge, to use,
copy, modify, merge, publish, distribute, sublicense, and sell copies of the
software, subject to inclusion of the copyright and permission notice. The
software is provided "as is", without warranty of any kind. See each linked
upstream repository for its complete license text and source history.

Material previously attributed to unavailable or unlicensed sources was not
carried forward into the public release: the affected completion-verification
skill, CLAUDE.md authoring rule, partial-read guard, and security signatures
were independently rewritten for this repository.
