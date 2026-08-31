# Search Venues for Paradigm-Distance Scouting

Use Tavily, Exa, and Firecrawl as a complementary trio. Each surfaces different findings on the same query.

## Tool roles

| Tool | MCP fn | Best for |
|---|---|---|
| **arXiv** | `mcp__arxiv-mcp-server__search_papers` | Academic papers (preprints typically lead products by 1-2 years) |
| **Tavily** | `mcp__tavily__tavily_search` | Broad web, news, blog, time-range filtering |
| **Exa** | `mcp__exa__web_search_exa`, `mcp__exa__crawling_exa` | Semantic phrase queries, category filters (people/company), highlights |
| **Firecrawl** | `mcp__firecrawl__firecrawl_search`, `firecrawl_map`, `firecrawl_crawl`, `firecrawl_extract` | Deep crawl of a known site, structured extraction, mapping all linked pages on a domain |

**Fire Tavily and Exa in parallel** for each priority-1/2 query — they return different result sets. Use Firecrawl as a follow-up to deep-crawl high-signal sites surfaced by the first two (e.g., once a research lab homepage is found, `firecrawl_map` it for all linked papers).

## Priority order

### Priority 1 — Academic frontier

- **arXiv categories**: cs.SE (software engineering), cs.PL (programming languages), cs.LG (ML), cs.CR (security), cs.DB (databases), cs.AR (architecture), cs.DC (distributed)
- Search the **paradigm name explicitly**, not the incumbent's keywords. Examples:
  - bad: `"code knowledge graph"` → returns same-paradigm papers
  - good: `"learned call resolution graph neural network"` → finds GNN approach
  - good: `"datalog code analysis incremental"` → finds Glean-class systems
- **Conference proceedings**: ICSE, FSE, POPL, PLDI, OOPSLA/SPLASH, ASE, ECOOP, NeurIPS, ICML, ACL, MLSys, ICLR. Tavily query template: `"<VENUE> <YEAR>" <topic> proceedings`. Use Firecrawl on proceedings page once located.
- **Research blogs**: Anthropic, OpenAI, Google Research, Meta Research, MSR, Apple ML. Use Tavily with `include_domains: ["anthropic.com", "openai.com", ...]`.

### Priority 2 — Industrial state-of-the-art

Mature systems whose READMEs don't match incumbent's keywords. Search by **paradigm name**, not feature.

| System | Paradigm cue |
|---|---|
| Sourcegraph | "code search platform" / "Universal Code Search" |
| GitHub Stack Graphs | "scope graph stitching name resolution" |
| Glean (Meta) | "datalog code facts query" |
| CodeQL | "semantic code analysis dataflow" |
| LSIF / SCIP | "language server index format" |
| Semantic (GitHub) | "semantic source analysis" |
| ast-grep | "structural search rewrite ast" |

Run `gh search repos --owner github --owner sourcegraph --owner facebook` etc. for org-scoped discovery. Use Firecrawl on vendor docs sites for deep dive once located.

### Priority 3 — Adjacent-domain transfer

Cross-domain transfer is high-value. Exa is strongest here (semantic phrasing).

| Source domain | Paradigms to consider applying |
|---|---|
| Graph databases | property graphs (Neo4j model), RDF triples |
| Time-series / observability | event-sourced indexes, OTEL spans as graph edges |
| Compiler IR | SSA form, control-flow graphs, abstract domains |
| Network analysis | community detection variants, centrality, spectral methods |
| Document IR | inverted indexes, BM25-as-graph |
| Bioinformatics | sequence alignment for code clones, suffix arrays |
| Formal methods | model checking, theorem provers, SAT/SMT |

### Priority 4 — Community/practitioner

Last priority. /scout (via /gather-repos) and /gather-intel already cover GitHub keyword space and Reddit/HN/blogs. For frontier purposes:
- Conference talks (StrangeLoop, GopherCon, RustConf, Lambda Days)
- Podcast transcripts (last-resort signal)
- X/Twitter from known researchers

Skip GitHub trending — that's /scout's job.

### Priority 5 — Non-English venues (multilingual sweep)

English-only retrieval misses substantial frontier work in Chinese, Russian, Japanese, and Korean CS communities. arXiv:2602.19446 (Feb 2026) documented multi-decade growth in non-English open-source content; OpenRank (April 2025) reported China's open-source contributions grew 10× from 2015-2024.

**Caveat first:** top-tier CS venues (PLDI, POPL, OOPSLA, ICSE, FSE, VLDB, SIGMOD) remain predominantly English even from non-English researchers. Use multilingual sweep for **engineering practice and community signal**, not as a substitute for English peer-review search.

| Venue | Language | URL pattern | Best for |
|---|---|---|---|
| **Cyberleninka / КиберЛенинка** | Russian | cyberleninka.ru | Russian-language CS papers (call graph analysis, code analysis, ML for vulnerability detection) |
| **Habr.com** | Russian | habr.com/ru/companies | Russian engineering practice, AstraLinux-style technical articles |
| **eLibrary.ru** | Russian | elibrary.ru | 34M publications, Russia's largest scientific library |
| **Gitee** | Chinese | gitee.com | Chinese open-source projects (TuGraph, GraphScope, MindSpore, Aliyun work) |
| **CNKI** | Chinese | cnki.net | China National Knowledge Infrastructure — Chinese-language academic papers |
| **WanFang DB** | Chinese | wanfangdata.com.cn | Alternative Chinese academic database |
| **Aliyun research blogs** | Chinese | developer.aliyun.com | Industrial Chinese frontier (TuGraph performance, GraphScope Flex benchmarks) |
| **Habr Japan / Qiita** | Japanese | qiita.com | Japanese engineering practice |
| **OkkyConcepts / Korean CS blogs** | Korean | velog.io / brunch.co.kr | Korean engineering practice (Korean OSS grew +1706% per arXiv:2602.19446) |

**Search method:** use Exa (`mcp__exa__web_search_exa`) — its embedding model is multilingual, so a paradigm-name query in the target language returns relevant results without translate-then-search round-trips. Huang et al. EMNLP 2025 demonstrated direct cross-lingual semantic retrieval beats translate-then-search.

**Example queries (Chinese, for graph database scouting):**
- `图数据库 学习型 调用解析` (graph database / learned / call resolution)
- `知识图谱 增量构建` (knowledge graph / incremental construction)

**Example queries (Russian, for static analysis scouting):**
- `статический анализ графа вызовов` (static call graph analysis)
- `граф потока данных межпроцедурный` (interprocedural data flow graph)

**Skip condition:** if the incumbent is so domain-specific to English-language regulatory contexts (DoD, FedRAMP, GovCloud) that non-English contributions are unlikely to apply, document the skip in the report rather than running the sweep.

## Anti-patterns

- Searching the incumbent's keywords ("code knowledge graph mcp" returns peers)
- Filtering academic results by stars (research repos often have 0)
- Stopping at first paper that mentions topic — look for 3+ independent papers from different groups
- Treating preprints as production-ready
