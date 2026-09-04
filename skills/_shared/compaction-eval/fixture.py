#!/usr/bin/env python3
"""Deterministic synthetic engineering session with planted facts and a QA key.

The A/B in run_live.py needs a transcript whose ground truth is known exactly,
so recall can be graded by string and number match with no model in the loop.
Everything here is hand-authored and static: building the fixture twice yields
identical bytes, and `fixture_sha()` pins the version a results.json was scored
against.

The session: a flaky integration test in a Python/Postgres service
("ledger-api"). It plants, and the key asks back:

  identifiers  6   two ticket ids, two commit shas, two port numbers
  errors       4   verbatim error lines
  questions    3   user questions, two of which are never answered
  root_causes  3   confirmed root causes with file:line
  hypotheses   2   hypotheses that were tested and ruled out
  decisions    3   A-vs-B decisions with the stated reason
  subagent     1   a number that appears only in a subagent report

Tool results are rendered at realistic size (full file reads, install logs, a
diff) so the summarizer actually has to cut; distractors are planted too (a
neighbouring ticket, the default Postgres port, CI run ids, other counts) so a
summary has to keep the RIGHT digits, not just some digits. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zlib
from pathlib import Path

# ---- planted facts (the QA key references these constants) -------------------

TICKET_MAIN = "PLAT-4821"
TICKET_SEC = "SEC-1207"
TICKET_DISTRACTOR = "PLAT-4819"
SHA_REGRESSION = "a3f9c2e1b7d4"
SHA_FIX = "0d77be41c9a2"
PORT_TEST_PG = "5433"
PORT_METRICS = "18080"

ERR_POOL = "E0412 connection pool exhausted (max_size=8, waiting=13)"
ERR_TXN = ("sqlalchemy.exc.InvalidRequestError: Can't reconnect until invalid "
           "transaction is rolled back")
ERR_MOD = "ModuleNotFoundError: No module named 'ledger.migrations.v0042_backfill'"
ERR_DOCKER = ('ERROR: failed to solve: process "/bin/sh -c uv sync --frozen" did not '
              'complete successfully: exit code: 2')

Q_ANSWERED = "Which pool size are we running in prod right now?"
Q_UNANSWERED_1 = "Do we need to bump max_connections on the staging RDS too, or only prod?"
Q_UNANSWERED_2 = "Can you also confirm whether the nightly backfill job uses the same pool?"

RC_POOL = "ledger/db/pool.py:47"
RC_TXN = "ledger/api/handlers/transfer.py:118"
RC_PKG = "pyproject.toml:31"

HYP_PGBOUNCER = "pgbouncer transaction pooling is dropping prepared statements"
HYP_XDIST = "parallel pytest-xdist workers share one database"

SUBAGENT_COUNT = "214"          # test modules scanned; the main thread never repeats it

# ---- bulk tool results --------------------------------------------------------

_CI_RUNS = [
    ("19347712088", "failure", SHA_REGRESSION), ("19347701140", "success", SHA_REGRESSION),
    ("19347688912", "failure", SHA_REGRESSION), ("19347650277", "success", SHA_REGRESSION),
    ("19347602341", "success", SHA_REGRESSION), ("19347598810", "failure", SHA_REGRESSION),
    ("19347540196", "success", "7c1e0b9d3a55"), ("19347501822", "success", "7c1e0b9d3a55"),
    ("19347466015", "success", "5be2f8a0c113"), ("19347430907", "success", "5be2f8a0c113"),
    ("19347399254", "success", "5be2f8a0c113"), ("19347361780", "success", "e94d1a72f068"),
]

_TEST_NAMES = [
    "test_transfer_single", "test_transfer_concurrent", "test_transfer_rollback_on_fx_error",
    "test_reconcile_daily", "test_reconcile_gap", "test_export_csv_headers",
    "test_export_csv_utf8", "test_ledger_balance_snapshot", "test_ledger_balance_negative",
    "test_fx_rate_cache", "test_fx_rate_stale", "test_smoke_health", "test_smoke_metrics",
    "test_tenant_routing_header", "test_tenant_routing_default", "test_audit_log_written",
]

_PACKAGES = [
    ("annotated-types", "0.7.0"), ("anyio", "4.4.0"), ("certifi", "2024.7.4"), ("click", "8.1.7"),
    ("dnspython", "2.6.1"), ("email-validator", "2.2.0"), ("fastapi", "0.115.0"),
    ("fastapi-cli", "0.0.5"), ("greenlet", "3.0.3"), ("h11", "0.14.0"), ("httpcore", "1.0.5"),
    ("httptools", "0.6.1"), ("httpx", "0.27.2"), ("idna", "3.8"), ("jinja2", "3.1.4"),
    ("markdown-it-py", "3.0.0"), ("markupsafe", "2.1.5"), ("mdurl", "0.1.2"),
    ("prometheus-client", "0.20.0"), ("psycopg", "3.2.1"), ("psycopg-binary", "3.2.1"),
    ("psycopg-pool", "3.2.2"), ("pydantic", "2.8.2"), ("pydantic-core", "2.20.1"),
    ("pygments", "2.18.0"), ("python-dotenv", "1.0.1"), ("python-multipart", "0.0.9"),
    ("pyyaml", "6.0.2"), ("rich", "13.8.0"), ("shellingham", "1.5.4"), ("sniffio", "1.3.1"),
    ("sqlalchemy", "2.0.31"), ("starlette", "0.38.4"), ("structlog", "24.4.0"), ("tenacity", "9.0.0"),
    ("typer", "0.12.5"), ("typing-extensions", "4.12.2"), ("uvicorn", "0.30.6"), ("uvloop", "0.20.0"),
    ("watchfiles", "0.24.0"), ("websockets", "13.0.1"),
]

_GIT_LOG = [
    ("b2d41e07c9f3", "ci: cache uv downloads between jobs"),
    ("f10a9c3e5d72", "docs: describe tenant routing header"),
    (SHA_REGRESSION, "refactor(db): build the engine per request for tenant routing"),
    ("7c1e0b9d3a55", "feat(api): X-Tenant header selects the database"),
    ("5be2f8a0c113", "chore: bump fastapi to 0.115"),
    ("e94d1a72f068", "fix(fx): retry quotes with jitter"),
    ("41cc8e2b9f10", "test: cover negative balances"),
    ("9d03fa61b2e8", "feat(export): csv export endpoint"),
    ("2f8b7c0e14da", "fix(reconcile): handle empty day"),
    ("c6e1d9a4f7b3", "chore: ruff 0.6"),
    ("8a4f2e6c0b1d", "feat(metrics): pool gauges"),
    ("d5b09c7e3a26", "fix(api): 422 on same-account transfer"),
    ("3e7c1a9d5f84", "docs: runbook for pool exhaustion alerts"),
    ("6b2e8f4a1c90", "chore: python 3.12"),
    ("0a9d3c5e7b21", "feat(audit): audit events table"),
    ("e1f4b7d2a693", "refactor(db): session factory helper"),
    ("74c2a8e0d1f5", "fix(smoke): wait for postgres healthcheck"),
    ("a8e0c3f5b972", "feat(fx): sandbox provider"),
    ("1d6f9b3e2c48", "initial ledger-api skeleton"),
]


def _ci_table() -> str:
    rows = ["databaseId    conclusion  headSha"]
    for run_id, conclusion, sha in _CI_RUNS:
        rows.append(f"{run_id}   {conclusion:<9}   {sha}")
    return "\n".join(rows)


def _numbered(lines: list[str], start: int = 1) -> str:
    """Render like the Read tool: right-aligned line number, tab, content."""
    return "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(lines, start=start))


def _ci_failure_log() -> str:
    lines = ["Run uv sync --frozen --all-extras",
             "Using CPython 3.12.4 interpreter at: /opt/hostedtoolcache/Python/3.12.4/x64/bin/python3",
             "Creating virtual environment at: .venv",
             "Resolved 41 packages in 3ms", "Prepared 41 packages in 2.14s", "Installed 41 packages in 131ms"]
    lines += [f" + {name}=={ver}" for name, ver in _PACKAGES]
    lines += ["Run docker compose -f docker-compose.test.yml up -d --wait",
              " Container ledger-api-postgres-1  Healthy", " Container ledger-api-redis-1  Healthy",
              "Run uv run pytest tests/integration -q -p xdist -n 4 --maxfail=1",
              "============================= test session starts =============================",
              "platform linux -- Python 3.12.4, pytest-8.3.2, pluggy-1.5.0",
              "rootdir: /home/runner/work/ledger-api/ledger-api, configfile: pyproject.toml",
              "plugins: asyncio-0.24.0, xdist-3.6.1, cov-5.0.0, repeat-0.9.3",
              "4 workers [16 items]", ""]
    for name in _TEST_NAMES:
        status = "FAILED" if name == "test_transfer_concurrent" else "PASSED"
        worker = zlib.crc32(name.encode("utf-8")) % 4   # stable across processes; hash() is salted
        lines.append(f"[gw{worker}] {status} tests/integration/test_ledger.py::{name}")
    lines += [
        "",
        "=================================== FAILURES ===================================",
        "__________________________ test_transfer_concurrent ___________________________",
        "[gw2] linux -- Python 3.12.4 /home/runner/work/ledger-api/ledger-api/.venv/bin/python3",
        "tests/integration/test_ledger.py:212: in test_transfer_concurrent",
        "    results = await asyncio.gather(*[post_transfer(c) for c in cases])",
        "ledger/api/handlers/transfer.py:108: in post_transfer",
        "    async with get_session(request) as session:",
        "ledger/db/pool.py:62: in get_session",
        "    conn = await _acquire(engine)",
        "ledger/db/pool.py:52: in _acquire",
        "    return await engine.connect()",
        "ledger/db/pool.py:55: in _acquire",
        "    raise PoolExhausted(f\"E0412 connection pool exhausted ({stats})\") from exc",
        f"E   ledger.db.pool.PoolExhausted: {ERR_POOL}",
        "------------------------------ Captured log call -------------------------------",
        "INFO     ledger.api:transfer.py:107 posting transfer ACC-00071 -> ACC-00088 amount=125.00 EUR",
        f"WARNING  ledger.db.pool:pool.py:50 {ERR_POOL}",
        f"ERROR    ledger.api:transfer.py:118 {ERR_TXN}",
        "WARNING  ledger.fx:client.py:71 quote retry 1/3 after 0.42s (sandbox 503)",
        "=========================== short test summary info ============================",
        f"FAILED tests/integration/test_ledger.py::test_transfer_concurrent - {ERR_POOL}",
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        "========================= 1 failed, 15 passed in 47.31s ========================",
        "Error: Process completed with exit code 1.",
    ]
    return "\n".join(lines)


def _pool_py_full() -> str:
    lines = [
        '"""Database engines and sessions for ledger-api."""',
        "from __future__ import annotations",
        "",
        "import asyncio",
        "import logging",
        "from contextlib import asynccontextmanager",
        "from typing import AsyncIterator",
        "",
        "from fastapi import Request",
        "from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine",
        "",
        "from ledger.config import settings",
        "from ledger.observability import metrics",
        "",
        "logger = logging.getLogger(__name__)",
        "",
        "",
        "class TenantUnknown(LookupError):",
        '    """Raised when a request names a tenant with no configured database."""',
        "",
        "",
        "class PoolExhausted(RuntimeError):",
        '    """Raised when no connection could be acquired within pool_timeout."""',
        "",
        "",
        "class UnsupportedDriver(ValueError):",
        '    """Raised when a DATABASE_URL does not use the supported driver."""',
        "",
        "",
        "_SESSION_FACTORIES: dict[str, async_sessionmaker[AsyncSession]] = {}",
        "",
        "",
        "def _tenant_from(request: Request) -> str:",
        '    return request.headers.get("X-Tenant", "default")',
        "",
        "",
        "# -- engine resolution ---------------------------------------------------------",
        "def get_engine(request: Request) -> AsyncEngine:",
        '    """Return the engine for the tenant on this request."""',
        '    tenant = request.headers.get("X-Tenant", "default")',
        "    url = settings.database_url_for(tenant)",
        f"    # NOTE({SHA_REGRESSION}): per-tenant routing needs a URL per request;",
        "    # the engine used to live at module scope.",
        "    if url is None:",
        "        raise TenantUnknown(tenant)",
        '    logger.debug("engine for %s", tenant)',
        "    engine = create_async_engine(url, pool_size=8, max_overflow=0, pool_timeout=5)",
        "    return engine",
        "",
        "async def _acquire(engine: AsyncEngine):",
        "    try:",
        "        return await engine.connect()",
        "    except TimeoutError as exc:",
        "        stats = engine.pool.status()",
        '        raise PoolExhausted(f"E0412 connection pool exhausted ({stats})") from exc',
        "",
        "",
        "@asynccontextmanager",
        "async def get_session(request: Request) -> AsyncIterator[AsyncSession]:",
        "    engine = get_engine(request)",
        "    metrics.db_checkout_attempts.inc()",
        "    conn = await _acquire(engine)",
        "    factory = _SESSION_FACTORIES.setdefault(str(engine.url), async_sessionmaker(engine, expire_on_commit=False))",
        "    session = factory(bind=conn)",
        "    try:",
        "        yield session",
        "    finally:",
        "        await session.close()",
        "        await conn.close()",
        "",
        "",
        "async def dispose_all() -> None:",
        '    """Dispose every engine created so far (used by tests and shutdown)."""',
        "    for factory in list(_SESSION_FACTORIES.values()):",
        '        engine = factory.kw["bind"]',
        "        await engine.dispose()",
        "    _SESSION_FACTORIES.clear()",
        "",
        "",
        "async def ping(engine: AsyncEngine, timeout: float = 2.0) -> bool:",
        "    try:",
        "        async with asyncio.timeout(timeout):",
        "            async with engine.connect() as conn:",
        '                await conn.exec_driver_sql("SELECT 1")',
        "        return True",
        "    except Exception:  # noqa: BLE001 - health probe",
        '        logger.warning("database ping failed", exc_info=True)',
        "        return False",
        "",
        "",
        "def pool_status(engine: AsyncEngine) -> dict[str, int]:",
        "    pool = engine.pool",
        '    return {"size": pool.size(), "checked_out": pool.checkedout(), "overflow": pool.overflow()}',
        "",
        "",
        '__all__ = ["get_engine", "get_session", "dispose_all", "ping", "pool_status", "PoolExhausted"]',
    ]
    assert lines[46].startswith("    engine = create_async_engine("), "RC_POOL must be line 47"
    return _numbered(lines)


def _transfer_py_full() -> str:
    lines = [
        '"""Transfer endpoints."""',
        "from __future__ import annotations",
        "",
        "import logging",
        "from decimal import Decimal",
        "",
        "from fastapi import APIRouter, HTTPException, Request",
        "from pydantic import BaseModel, Field",
        "from sqlalchemy import insert, select, update",
        "",
        "from ledger.db.models import Account, AuditEvent, Transfer",
        "from ledger.db.pool import get_session",
        "from ledger.fx import FxUnavailable, fx",
        "from ledger.observability import metrics",
        "",
        'logger = logging.getLogger("ledger.api")',
        'router = APIRouter(prefix="/transfers", tags=["transfers"])',
        "",
        "class TransferIn(BaseModel):",
        "    source_account: str = Field(min_length=8, max_length=34)",
        "    target_account: str = Field(min_length=8, max_length=34)",
        "    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)",
        '    currency: str = Field(pattern=r"^[A-Z]{3}$")',
        "    reference: str | None = Field(default=None, max_length=140)",
        "",
        "class TransferOut(BaseModel):",
        "    id: int",
        "    status: str",
        "    rate: Decimal | None",
        "",
        "",
        "def _debit(payload: TransferIn):",
        "    return (",
        "        update(Account)",
        "        .where(Account.number == payload.source_account, Account.balance >= payload.amount)",
        "        .values(balance=Account.balance - payload.amount)",
        "        .returning(Account.id)",
        "    )",
        "",
        "",
        "def _credit(payload: TransferIn):",
        "    return (",
        "        update(Account)",
        "        .where(Account.number == payload.target_account)",
        "        .values(balance=Account.balance + payload.amount)",
        "        .returning(Account.id)",
        "    )",
        "",
        "",
        "def _audit(rate: Decimal | None):",
        '    return insert(AuditEvent).values(kind="transfer", rate=rate)',
        "",
        "",
        "async def _load_transfer(session, transfer_id: int) -> Transfer | None:",
        "    result = await session.execute(select(Transfer).where(Transfer.id == transfer_id))",
        "    return result.scalar_one_or_none()",
        "",
        "",
        '@router.get("/{transfer_id}", response_model=TransferOut)',
        "async def get_transfer(transfer_id: int, request: Request) -> TransferOut:",
        "    async with get_session(request) as session:",
        "        row = await _load_transfer(session, transfer_id)",
        "    if row is None:",
        '        raise HTTPException(status_code=404, detail="transfer not found")',
        "    return TransferOut(id=row.id, status=row.status, rate=row.rate)",
        "",
        "",
        '@router.get("", response_model=list[TransferOut])',
        "async def list_transfers(request: Request, limit: int = 50, offset: int = 0) -> list[TransferOut]:",
        "    if limit > 500:",
        '        raise HTTPException(status_code=422, detail="limit must be <= 500")',
        "    async with get_session(request) as session:",
        "        result = await session.execute(",
        "            select(Transfer).order_by(Transfer.id.desc()).limit(limit).offset(offset)",
        "        )",
        "        rows = result.scalars().all()",
        "    return [TransferOut(id=r.id, status=r.status, rate=r.rate) for r in rows]",
        "",
        "",
        "def _validate(payload: TransferIn) -> None:",
        "    if payload.source_account == payload.target_account:",
        '        raise HTTPException(status_code=422, detail="source and target must differ")',
        "    if payload.currency not in fx.supported():",
        '        raise HTTPException(status_code=422, detail=f"unsupported currency {payload.currency}")',
        "",
        "",
        "async def _record(session, payload: TransferIn, rate: Decimal) -> int:",
        "    result = await session.execute(",
        "        insert(Transfer)",
        "        .values(",
        "            source=payload.source_account,",
        "            target=payload.target_account,",
        "            amount=payload.amount,",
        "            currency=payload.currency,",
        "            rate=rate,",
        '            status="posted",',
        "        )",
        "        .returning(Transfer.id)",
        "    )",
        "    return int(result.scalar_one())",
        "",
        "",
        '@router.post("", response_model=TransferOut, status_code=201)',
        "async def post_transfer(payload: TransferIn, request: Request) -> TransferOut:",
        "    _validate(payload)",
        "    debit_stmt, credit_stmt = _debit(payload), _credit(payload)",
        '    logger.info("posting transfer %s -> %s amount=%s %s", payload.source_account, payload.target_account, payload.amount, payload.currency)',
        "    async with get_session(request) as session:",
        "        try:",
        "            debit = await session.execute(debit_stmt)",
        "            credit = await session.execute(credit_stmt)",
        "            rate = await fx.quote(payload.currency, timeout=2.0)",
        "            await session.execute(_audit(rate))",
        "            await session.commit()",
        "        except FxUnavailable as exc:",
        '            logger.error("fx quote failed: %s", exc)',
        "            metrics.transfer_failed.inc()",
        '            raise HTTPException(status_code=503, detail="fx unavailable") from exc',
        "        except Exception:",
        "            await session.rollback()",
        "            raise",
        "        if debit.scalar_one_or_none() is None or credit.scalar_one_or_none() is None:",
        '            raise HTTPException(status_code=409, detail="insufficient funds or unknown account")',
        "        transfer_id = await _record(session, payload, rate)",
        "        await session.commit()",
        "    metrics.transfer_posted.inc()",
        '    return TransferOut(id=transfer_id, status="posted", rate=rate)',
        "",
        "",
        '@router.post("/{transfer_id}/reverse", response_model=TransferOut)',
        "async def reverse_transfer(transfer_id: int, request: Request) -> TransferOut:",
        "    async with get_session(request) as session:",
        "        row = await _load_transfer(session, transfer_id)",
        "        if row is None:",
        '            raise HTTPException(status_code=404, detail="transfer not found")',
        '        if row.status != "posted":',
        '            raise HTTPException(status_code=409, detail=f"cannot reverse a {row.status} transfer")',
        '        await session.execute(update(Transfer).where(Transfer.id == transfer_id).values(status="reversed"))',
        "        await session.commit()",
        "    metrics.transfer_reversed.inc()",
        '    return TransferOut(id=transfer_id, status="reversed", rate=row.rate)',
    ]
    assert lines[117].strip().startswith('raise HTTPException(status_code=503'), "RC_TXN must be line 118"
    return _numbered(lines)


def _pyproject_full() -> str:
    lines = [
        "[project]", 'name = "ledger-api"', 'version = "2026.8.4"',
        'description = "Ledger service: transfers, balances, reconciliation"', 'readme = "README.md"',
        'requires-python = ">=3.12"', 'license = { text = "Proprietary" }', "dependencies = [",
        '    "fastapi>=0.115",', '    "uvicorn[standard]>=0.30",', '    "sqlalchemy[asyncio]>=2.0.35",',
        '    "psycopg[binary,pool]>=3.2",', '    "pydantic>=2.8",', '    "prometheus-client>=0.20",',
        '    "structlog>=24.4",', '    "httpx>=0.27",', '    "tenacity>=9.0",', "]", "",
        "[build-system]", 'requires = ["setuptools>=70", "wheel"]', 'build-backend = "setuptools.build_meta"', "",
        "[tool.setuptools]", "include-package-data = true", "",
        "[tool.setuptools.package-data]", '"ledger" = ["py.typed"]', "",
        "[tool.setuptools.packages]",
        'find = { include = ["ledger", "ledger.api*", "ledger.db*", "ledger.fx*"] }', "",
        "[tool.uv]",
        'dev-dependencies = ["pytest>=8", "pytest-asyncio>=0.24", "pytest-xdist>=3.6", "pytest-repeat>=0.9"]', "",
        "[tool.pytest.ini_options]", 'asyncio_mode = "auto"', 'testpaths = ["tests"]',
        'addopts = "-p no:cacheprovider"', 'markers = ["integration: needs the compose database"]', "",
        "[tool.ruff]", "line-length = 110", 'target-version = "py312"',
    ]
    assert lines[30].startswith("find = {"), "RC_PKG must be line 31"
    return _numbered(lines)


def _git_log_and_show() -> str:
    lines = [f"{sha[:7]} {msg}" for sha, msg in _GIT_LOG]
    lines += ["", f"commit {SHA_REGRESSION}", "Author: Priya Natarajan <priya@example.com>",
              "Date:   Tue Aug 26 14:02:11 2026 -0400", "",
              "    refactor(db): build the engine per request for tenant routing", "",
              "    Each tenant may have its own database URL, so the engine is now resolved",
              "    from the request instead of module scope.", "",
              "diff --git a/ledger/db/pool.py b/ledger/db/pool.py", "index 3f1c9a2..8be7d40 100644",
              "--- a/ledger/db/pool.py", "+++ b/ledger/db/pool.py", "@@ -30,22 +30,26 @@",
              "-_ENGINE: AsyncEngine | None = None",
              "-",
              "-",
              "-def get_engine() -> AsyncEngine:",
              '-    """Return the process-wide engine, creating it on first use."""',
              "-    global _ENGINE",
              "-    if _ENGINE is None:",
              "-        _ENGINE = create_async_engine(settings.database_url, pool_size=8, max_overflow=0, pool_timeout=5)",
              "-    return _ENGINE",
              "+_SESSION_FACTORIES: dict[str, async_sessionmaker[AsyncSession]] = {}",
              "+",
              "+",
              "+def _tenant_from(request: Request) -> str:",
              '+    return request.headers.get("X-Tenant", "default")',
              "+",
              "+",
              "+# -- engine resolution ---------------------------------------------------------",
              "+def get_engine(request: Request) -> AsyncEngine:",
              '+    """Return the engine for the tenant on this request."""',
              '+    tenant = request.headers.get("X-Tenant", "default")',
              "+    url = settings.database_url_for(tenant)",
              f"+    # NOTE({SHA_REGRESSION}): per-tenant routing needs a URL per request;",
              "+    # the engine used to live at module scope.",
              "+    if url is None:",
              "+        raise TenantUnknown(tenant)",
              '+    logger.debug("engine for %s", tenant)',
              "+    engine = create_async_engine(url, pool_size=8, max_overflow=0, pool_timeout=5)",
              "+    return engine",
              "@@ -58,7 +62,7 @@ async def _acquire(engine: AsyncEngine):",
              " @asynccontextmanager",
              "-async def get_session() -> AsyncIterator[AsyncSession]:",
              "-    engine = get_engine()",
              "+async def get_session(request: Request) -> AsyncIterator[AsyncSession]:",
              "+    engine = get_engine(request)",
              "     metrics.db_checkout_attempts.inc()",
              "     conn = await _acquire(engine)",
              "diff --git a/ledger/api/deps.py b/ledger/api/deps.py", "index 91ab2c0..77d3e1f 100644",
              "--- a/ledger/api/deps.py", "+++ b/ledger/api/deps.py", "@@ -4,12 +4,14 @@",
              "-from ledger.db.pool import get_session",
              "+from fastapi import Request",
              "+from ledger.db.pool import get_session",
              " ",
              "-async def session():",
              "-    async with get_session() as s:",
              "+async def session(request: Request):",
              "+    async with get_session(request) as s:",
              "         yield s",
              " ledger/db/pool.py        | 31 ++++++++++++-------",
              " ledger/api/deps.py       | 12 ++++---",
              " tests/integration/test_ledger.py |  4 +-",
              " 3 files changed, 30 insertions(+), 17 deletions(-)"]
    return "\n".join(lines)


def _helm_values() -> str:
    return "\n".join([
        "replicaCount: 12", "image:", "  repository: ghcr.io/example/ledger-api", "  tag: 2026.08.4",
        "  pullPolicy: IfNotPresent", "env:", '  DB_POOL_SIZE: "8"', '  DB_POOL_TIMEOUT: "5"',
        f'  METRICS_PORT: "{PORT_METRICS}"', "  LOG_LEVEL: info", '  FX_PROVIDER: "openexchange"',
        '  FX_TIMEOUT_SECONDS: "2"', "envFrom:", "  - secretRef:", "      name: ledger-api-db",
        "service:", "  type: ClusterIP", "  port: 8000", "resources:", "  requests:", "    cpu: 500m",
        "    memory: 512Mi", "  limits:", '    cpu: "2"', "    memory: 1Gi", "livenessProbe:",
        "  httpGet:", "    path: /healthz", "    port: 8000", "  initialDelaySeconds: 10",
        "readinessProbe:", "  httpGet:", "    path: /readyz", "    port: 8000", "  periodSeconds: 5",
        "autoscaling:", "  enabled: true", "  minReplicas: 12", "  maxReplicas: 24",
        "  targetCPUUtilizationPercentage: 70", "podDisruptionBudget:", "  minAvailable: 9",
    ])


def _compose_file() -> str:
    return "\n".join([
        "services:", "  postgres:", "    image: postgres:16.3", "    ports:",
        f'      - "{PORT_TEST_PG}:5432"', "    environment:", "      POSTGRES_DB: ledger_test",
        "      POSTGRES_USER: ledger", "      POSTGRES_PASSWORD: ledger",
        "    command: postgres -c max_connections=60 -c log_min_duration_statement=250",
        "    healthcheck:", '      test: ["CMD-SHELL", "pg_isready -U ledger -d ledger_test"]',
        "      interval: 2s", "      timeout: 2s", "      retries: 15", "  redis:", "    image: redis:7.2-alpine",
        "    ports:", '      - "6380:6379"', "    healthcheck:", '      test: ["CMD", "redis-cli", "ping"]',
        "      interval: 2s", "      retries: 10", "  api:", "    build: .", "    depends_on:",
        "      postgres:", "        condition: service_healthy", "      redis:",
        "        condition: service_healthy", "    environment:",
        "      DATABASE_URL: postgresql+psycopg://ledger:ledger@postgres:5432/ledger_test",
        "      REDIS_URL: redis://redis:6379/0", f'      METRICS_PORT: "{PORT_METRICS}"',
        '      DB_POOL_SIZE: "8"', "    ports:", '      - "8000:8000"', f'      - "{PORT_METRICS}:{PORT_METRICS}"',
    ])


def _docker_log() -> str:
    lines = ['#0 building with "default" instance using docker driver',
             "#1 [internal] load build definition from Dockerfile", "#1 transferring dockerfile: 1.02kB done",
             "#2 [internal] load metadata for ghcr.io/astral-sh/uv:python3.12-bookworm-slim",
             "#3 [internal] load .dockerignore", "#3 transferring context: 214B done" .replace("214B", "198B"),
             "#4 [ 1/7] FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:3c0f1e8d2b6a94f7c1e0d5b8a2f4c6e8d0b2a4c6e8f0a2c4e6b8d0f2a4c6e8b0",
             "#5 [internal] load build context", "#5 transferring context: 1.94MB 0.1s done",
             "#6 [ 2/7] WORKDIR /app", "#6 CACHED",
             "#7 [ 3/7] COPY pyproject.toml uv.lock ./", "#7 DONE 0.0s",
             "#8 [ 4/7] RUN uv sync --frozen --no-dev",
             "#8 0.412 Using CPython 3.12.4 interpreter at: /usr/local/bin/python3",
             "#8 0.418 Creating virtual environment at: .venv",
             "#8 1.207 error: The lockfile at `uv.lock` needs to be updated, but `--frozen` was provided.",
             "#8 1.207   To update the lockfile, run `uv lock`.",
             "#8 1.209   Dependency `sqlalchemy` was pinned to 2.0.31 in the lockfile but pyproject.toml now requires >=2.0.35",
             '#8 ERROR: process "/bin/sh -c uv sync --frozen --no-dev" did not complete successfully: exit code: 2',
             "------", " > [ 4/7] RUN uv sync --frozen --no-dev:", "------", "Dockerfile:23",
             "--------------------", "  21 |     COPY pyproject.toml uv.lock ./", "  22 |     ",
             "  23 | >>> RUN uv sync --frozen --no-dev", "  24 |     COPY src/ ./src/",
             "  25 |     RUN uv sync --frozen --no-dev --no-editable", "--------------------",
             ERR_DOCKER, "Error: Process completed with exit code 1."]
    return "\n".join(lines)


def _metrics_output() -> str:
    lines = [
        "# HELP ledger_db_pool_size Configured pool size", "# TYPE ledger_db_pool_size gauge",
        'ledger_db_pool_size{tenant="default"} 8',
        "# HELP ledger_db_pool_checked_out Connections currently checked out",
        "# TYPE ledger_db_pool_checked_out gauge", 'ledger_db_pool_checked_out{tenant="default"} 8',
        "# HELP ledger_db_pool_waiters Requests waiting for a connection",
        "# TYPE ledger_db_pool_waiters gauge", 'ledger_db_pool_waiters{tenant="default"} 13',
        "# HELP ledger_db_engines_created_total Engines created since start",
        "# TYPE ledger_db_engines_created_total counter", "ledger_db_engines_created_total 1862",
        "# HELP ledger_db_checkout_attempts_total Checkout attempts",
        "# TYPE ledger_db_checkout_attempts_total counter", "ledger_db_checkout_attempts_total 1862",
        "# HELP ledger_transfer_failed_total Transfers that failed",
        "# TYPE ledger_transfer_failed_total counter", "ledger_transfer_failed_total 41",
        "# HELP ledger_transfer_posted_total Transfers posted", "# TYPE ledger_transfer_posted_total counter",
        "ledger_transfer_posted_total 1798",
        "# HELP ledger_http_request_duration_seconds Request latency",
        "# TYPE ledger_http_request_duration_seconds histogram",
    ]
    buckets = [("0.005", 302), ("0.01", 611), ("0.025", 1104), ("0.05", 1420), ("0.1", 1633),
               ("0.25", 1745), ("0.5", 1781), ("1", 1802), ("2.5", 1811), ("5", 1849), ("10", 1862), ("+Inf", 1862)]
    lines += [f'ledger_http_request_duration_seconds_bucket{{path="/transfers",le="{le}"}} {n}' for le, n in buckets]
    lines += ['ledger_http_request_duration_seconds_sum{path="/transfers"} 412.7',
              'ledger_http_request_duration_seconds_count{path="/transfers"} 1862',
              "# HELP process_open_fds Number of open file descriptors", "# TYPE process_open_fds gauge",
              "process_open_fds 1907"]
    return "\n".join(lines)


def _uv_lock_output() -> str:
    lines = ["Resolved 41 packages in 1.86s", "Updated sqlalchemy v2.0.31 -> v2.0.35",
             "Updated psycopg v3.2.1 -> v3.2.3", "Updated psycopg-binary v3.2.1 -> v3.2.3",
             "Updated psycopg-pool v3.2.2 -> v3.2.3", "Updated greenlet v3.0.3 -> v3.1.0",
             "Updated typing-extensions v4.12.2 -> v4.12.2 (no change)"]
    lines += ["[fix/PLAT-4821-pool-lifespan b81c3aa] chore: regenerate uv.lock for sqlalchemy 2.0.35",
              " 1 file changed, 38 insertions(+), 38 deletions(-)",
              "Enumerating objects: 5, done.", "Counting objects: 100% (5/5), done.",
              "Delta compression using up to 8 threads", "Compressing objects: 100% (3/3), done.",
              "Writing objects: 100% (3/3), 1.21 KiB | 1.21 MiB/s, done.",
              "To github.com:example/ledger-api.git",
              "   0d77be4..b81c3aa  fix/PLAT-4821-pool-lifespan -> fix/PLAT-4821-pool-lifespan"]
    return "\n".join(lines)


def _subagent_report() -> str:
    return "\n".join([
        "Explore agent report (read-only scan of tests/):",
        f"- Scanned {SUBAGENT_COUNT} test modules under tests/ (unit, integration, e2e).",
        "- 3 modules open a database connection outside the shared fixtures:",
        "    tests/integration/test_reconcile.py:41   (asyncpg.connect(...) directly)",
        "    tests/integration/test_export_csv.py:19  (create_async_engine at import time)",
        "    tests/e2e/test_smoke.py:77               (psycopg.connect for a health probe)",
        "- Every other module reaches the database through the `engine` / `session` fixtures in",
        "  tests/conftest.py, which build one engine per test session from DATABASE_URL.",
        "- test_transfer_concurrent: p95 wall time 4.8s over the last 50 CI runs, p50 1.9s;",
        "  every failure in that window coincides with pool_timeout=5 being exceeded.",
        "- No test module references pgbouncer; all connect to 127.0.0.1:5433 via",
        "  docker-compose.test.yml.",
        "- The nightly backfill job (jobs/backfill.py) was not inspected; it lives outside tests/.",
    ])


def _jobs_rg() -> str:
    return "\n".join([
        "jobs/backfill.py:12:from ledger.db.pool import get_engine",
        "jobs/backfill.py:58:    engine = get_engine(request=None)",
        "jobs/backfill.py:59:    # TODO: backfill runs with its own DATABASE_URL from the cron env",
        "jobs/export_snapshot.py:9:from ledger.db.pool import get_engine",
        "jobs/export_snapshot.py:33:    engine = get_engine(request=None)",
        "jobs/reconcile_nightly.py:14:from ledger.db.pool import get_session",
    ])


def _conftest_full() -> str:
    lines = [
        '"""Shared fixtures: one engine per test session, one connection per test."""',
        "from __future__ import annotations", "", "import asyncio", "import os", "",
        "import pytest", "import pytest_asyncio",
        "from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine", "",
        "from ledger.config import settings", "",
        'DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://ledger:ledger@127.0.0.1:5433/ledger_test")',
        "", "",
        '@pytest.fixture(scope="session")', "def event_loop():", "    loop = asyncio.new_event_loop()",
        "    yield loop", "    loop.close()", "", "",
        '@pytest_asyncio.fixture(scope="session")', "async def engine():",
        "    eng = create_async_engine(DATABASE_URL, pool_size=8, max_overflow=0, pool_timeout=5)",
        "    async with eng.begin() as conn:", '        await conn.exec_driver_sql("SELECT 1")',
        "    yield eng", "    await eng.dispose()", "", "",
        "@pytest_asyncio.fixture", "async def session(engine) -> AsyncSession:",
        "    factory = async_sessionmaker(engine, expire_on_commit=False)",
        "    async with factory() as s:", "        yield s", "        await s.rollback()", "", "",
        "@pytest_asyncio.fixture", "async def client(engine):",
        "    from httpx import ASGITransport, AsyncClient", "    from ledger.api.app import create_app", "",
        "    app = create_app(engine=engine)",
        '    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:',
        "        yield c", "", "",
        '@pytest.fixture(scope="session", autouse=True)', "def _settings_for_tests():",
        '    settings.fx_provider = "sandbox"', "    settings.fx_timeout_seconds = 2.0", "    yield", "", "",
        "@pytest.fixture", "def accounts(session):", "    return [f\"ACC-{n:05d}\" for n in range(70, 90)]",
    ]
    return _numbered(lines)


# ---- transcript ---------------------------------------------------------------

def build_transcript() -> list[dict]:
    """~60 alternating turns. Tool calls are rendered as text inside the turn that
    made them; tool results are user turns, as in a real Claude Code session."""
    u, a = "user", "assistant"
    T: list[tuple[str, str]] = []

    T.append((u, f"We have a flaky integration test in ledger-api, tracked as {TICKET_MAIN}. CI fails "
                 f"roughly one run in four on test_transfer_concurrent and nobody can reproduce it "
                 f"locally. Can you dig in? Repo is at ~/code/ledger-api. There is an older timeout "
                 f"ticket, {TICKET_DISTRACTOR}, that is unrelated; ignore it."))
    T.append((a, "I'll start with the recent CI history to see when the flake began.\n\n"
                 "[tool_use: Bash] gh run list --workflow ci.yml --limit 12 --json databaseId,conclusion,headSha"))
    T.append((u, "[tool_result]\n" + _ci_table()))
    T.append((a, f"Three failures in the last twelve runs, and all three are on {SHA_REGRESSION}; the "
                 f"runs on 7c1e0b9d3a55 and earlier are green. Let me read the failing log.\n\n"
                 "[tool_use: Bash] gh run view 19347712088 --log-failed | tail -80"))
    T.append((u, "[tool_result]\n" + _ci_failure_log()))
    T.append((a, f"The failing test dies on `{ERR_POOL}`: eight connections checked out, thirteen "
                 f"requests waiting. Two things stand out. First, the pool is exhausted with only "
                 f"sixteen concurrent transfers in the test. Second, the captured log also shows "
                 f"`{ERR_TXN}` from transfer.py:118, which looks like a separate bug. My first "
                 f"hypothesis is that {HYP_PGBOUNCER}, since pgbouncer in transaction mode would "
                 "explain both symptoms. Let me check its config.\n\n[tool_use: Read] deploy/pgbouncer.ini"))
    T.append((u, "[tool_result]\n" + _numbered([
        "[databases]",
        "ledger = host=ledger-prod.cluster-abc123.us-east-1.rds.amazonaws.com port=5432 dbname=ledger",
        "", "[pgbouncer]", "listen_addr = 0.0.0.0", "listen_port = 6432", "auth_type = scram-sha-256",
        "auth_file = /etc/pgbouncer/userlist.txt", "pool_mode = session", "max_client_conn = 400",
        "default_pool_size = 40", "reserve_pool_size = 5", "server_reset_query = DISCARD ALL",
        "server_idle_timeout = 600", "log_connections = 0", "log_disconnections = 0",
        "; NOTE: pgbouncer fronts prod only. Tests and docker-compose connect to postgres directly."])))
    T.append((a, f"That rules the pgbouncer hypothesis out: prod runs pool_mode = session (prepared "
                 f"statements survive), and the test path does not go through pgbouncer at all, it "
                 f"connects straight to postgres. Ruled out: {HYP_PGBOUNCER}. Next I want to see "
                 f"what {SHA_REGRESSION} changed.\n\n[tool_use: Bash] git log --oneline -19 && "
                 f"git show --stat {SHA_REGRESSION}"))
    T.append((u, "[tool_result]\n" + _git_log_and_show()))
    T.append((a, "The engine is now built per request. If that means a new pool per request, the "
                 "eight-connection ceiling is per pool and the process can open hundreds of connections. "
                 "Let me read the whole module.\n\n[tool_use: Read] ledger/db/pool.py"))
    T.append((u, "[tool_result]\n" + _pool_py_full()))
    T.append((a, f"Confirmed root cause for the pool exhaustion: {RC_POOL}. `create_async_engine` runs "
                 f"inside `get_engine(request)`, so every request creates a fresh engine and pool "
                 f"(pool_size=8, max_overflow=0, pool_timeout=5). Under sixteen concurrent transfers "
                 f"the process opens sixteen pools, postgres runs out of slots, and the acquire times "
                 f"out after five seconds, which is exactly the p95 the flake shows. The tenant "
                 f"routing itself is fine; the engine just needs to be cached per URL.\n\n"
                 "Let me confirm the connection count from the metrics endpoint on a local run.\n\n"
                 f"[tool_use: Bash] docker compose -f docker-compose.test.yml up -d --wait && "
                 f"uv run pytest tests/integration -q -x >/dev/null; curl -s localhost:{PORT_METRICS}/metrics "
                 "| grep -E 'ledger_|process_open_fds'"))
    T.append((u, "[tool_result]\n" + _metrics_output()))
    T.append((a, f"`ledger_db_engines_created_total 1862` after one test run confirms it: one engine "
                 f"per request, and 1907 open file descriptors to go with it. (/metrics is served on "
                 f"{PORT_METRICS}, separate from the API port, which is why the dashboard panel was "
                 "empty; the panel scrapes 8000.)\n\n"
                 "There are two reasonable fixes:\n"
                 "  A. a module-level singleton dict keyed by URL, created lazily on first use;\n"
                 "  B. a FastAPI lifespan handler that builds the engines at startup and disposes "
                 "them at shutdown, exposed through a dependency.\n"
                 "I recommend B: lifespan shutdown drains the pool explicitly, whereas the old "
                 "singleton leaked connections across test sessions, which is how this flake hid "
                 "behind the earlier timeout ticket. Which do you prefer?"))
    T.append((u, "B, the lifespan approach. The singleton leaking across test sessions is exactly the "
                 "kind of thing I don't want to debug again. " + Q_ANSWERED))
    T.append((a, "Lifespan it is. On the pool size: prod runs pool_size 8 per pod, from "
                 "deploy/helm/values-prod.yaml (DB_POOL_SIZE: \"8\"), with 12 pods, so 96 connections "
                 "against an RDS max_connections of 200. Let me confirm the values file.\n\n"
                 "[tool_use: Read] deploy/helm/values-prod.yaml"))
    T.append((u, "[tool_result]\n" + _numbered(_helm_values().splitlines())))
    T.append((a, "Confirmed: DB_POOL_SIZE is 8 in prod, DB_POOL_TIMEOUT 5, and the HPA can take the "
                 "deployment to 24 pods, so the ceiling is 192 of the 200 RDS connections. That is "
                 "tight but not the flake. I'll now write the lifespan handler and the dependency.\n\n"
                 "[tool_use: Edit] ledger/db/pool.py (replace get_engine with an EngineRegistry built in "
                 "lifespan; dispose on shutdown)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/ledger/db/pool.py has been updated."))
    T.append((a, "[tool_use: Edit] ledger/api/app.py (add lifespan=engine_lifespan to FastAPI(); "
                 "register the registry on app.state)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/ledger/api/app.py has been updated."))
    T.append((a, "Now the second error from the log. `transfer.py:118` raised HTTPException from "
                 "inside a failed transaction without rolling back, so the session is returned to the "
                 "pool in an invalid state and the next borrower gets the InvalidRequestError. "
                 "Let me read the handler.\n\n[tool_use: Read] ledger/api/handlers/transfer.py"))
    T.append((u, "[tool_result]\n" + _transfer_py_full()))
    T.append((a, f"Confirmed root cause for the invalid-transaction error: {RC_TXN}. The FxUnavailable "
                 f"branch re-raises as a 503 but skips `await session.rollback()`, which only the "
                 f"generic `except Exception` branch does. The session goes back to the pool mid-"
                 f"transaction and the next request on that connection fails with "
                 f"`{ERR_TXN}`. Fix: roll back in the FxUnavailable branch too, or restructure so the "
                 "rollback happens in a finally.\n\n[tool_use: Edit] ledger/api/handlers/transfer.py "
                 "(add `await session.rollback()` before the raise at line 118)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/ledger/api/handlers/transfer.py "
                 "has been updated."))
    T.append((u, Q_UNANSWERED_1))
    T.append((a, "Good question. RDS parameter groups differ between the two environments, so I want "
                 "to check staging's max_connections before answering; let me finish verifying the "
                 "pool fix first and come back to it.\n\n[tool_use: Bash] uv run pytest "
                 "tests/integration/test_ledger.py -q -p no:xdist -x"))
    T.append((u, "[tool_result]\n................                                                   [100%]\n"
                 "16 passed in 39.88s"))
    T.append((a, "Green with the fix on a single worker. Before I trust that, I want to know whether "
                 f"the flake was ever about workers: a second hypothesis is that {HYP_XDIST}. "
                 "I'll stash the fix temporarily and run the original code without xdist, twenty times.\n\n"
                 "[tool_use: Bash] git stash && uv run pytest tests/integration/test_ledger.py -q "
                 "-p no:xdist -k test_transfer_concurrent --count 20 2>&1 | tail -5; git stash pop"))
    T.append((u, "[tool_result]\ntests/integration/test_ledger.py::test_transfer_concurrent[14-20] FAILED\n"
                 f"E   ledger.db.pool.PoolExhausted: {ERR_POOL}\n"
                 "5 failed, 15 passed in 118.02s\nSaved working directory and index state WIP on "
                 "fix/PLAT-4821-pool-lifespan: 7c1e0b9 refactor(db): build the engine per request\n"
                 "Dropped refs/stash@{0} (2a9f0e4c1b7d6e3f5a8c9b0d1e2f3a4b5c6d7e8f)"))
    T.append((a, f"Five failures in twenty on a single worker with the original code, so the xdist "
                 f"hypothesis is ruled out as well: {HYP_XDIST} is not what causes the flake. It is "
                 "the per-request engine, full stop. Fix restored.\n\nLet me get an independent read "
                 "on how many tests touch a real connection outside the fixtures, since those would "
                 "also be affected by the registry change.\n\n[tool_use: Agent] Explore: scan tests/ "
                 "and report every test module that opens a database connection outside the shared "
                 "fixtures, plus the recent CI timing for test_transfer_concurrent. Read-only."))
    T.append((u, "[tool_result]\n" + _subagent_report()))
    T.append((a, "Useful. Three modules bypass the fixtures (test_reconcile.py, test_export_csv.py "
                 "and test_smoke.py); test_export_csv.py creating an engine at import time is the "
                 "one that will break with the registry. Let me see what the shared fixtures "
                 "provide before routing it through them.\n\n[tool_use: Read] tests/conftest.py"))
    T.append((u, "[tool_result]\n" + _conftest_full()))
    T.append((a, "The session-scoped `engine` fixture already builds one engine with the same pool "
                 "settings, so test_export_csv.py just needs to take it as a parameter. The "
                 "timing matches the pool_timeout theory.\n\n[tool_use: Edit] "
                 "tests/integration/test_export_csv.py (use the `engine` fixture instead of "
                 "create_async_engine at import)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/tests/integration/test_export_csv.py "
                 "has been updated."))
    T.append((u, "While you're in there: we have gone back and forth for weeks between asyncpg and "
                 "psycopg3 as the async driver. Pick one so the registry only has to support one URL "
                 "scheme."))
    T.append((a, "I'd pick psycopg3. Reason: SQLAlchemy 2.0's async support is first-class for "
                 "psycopg3, and we keep one driver for the sync scripts in jobs/ as well, so there "
                 "is a single connection-string scheme (postgresql+psycopg://) and one set of "
                 "server-side-cursor semantics to reason about. asyncpg is a little faster on bulk "
                 "fetches, but nothing in ledger-api is bulk-fetch bound."))
    T.append((u, "psycopg3 it is. Make the registry reject any other scheme so nobody sneaks asyncpg "
                 "back in."))
    T.append((a, "[tool_use: Edit] ledger/db/pool.py (EngineRegistry.__init__ raises "
                 "UnsupportedDriver unless the URL scheme is postgresql+psycopg)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/ledger/db/pool.py has been updated."))
    T.append((a, "Running the whole suite now, with xdist back on.\n\n[tool_use: Bash] uv run pytest -q"))
    T.append((u, "[tool_result]\n...........................F....................................\n"
                 "=================================== FAILURES ===================================\n"
                 "______________________ test_backfill_v0042_is_idempotent _______________________\n"
                 "tests/unit/test_migrations.py:14: in <module>\n"
                 "    from ledger.migrations import v0042_backfill\n"
                 f"E   {ERR_MOD}\n"
                 "=========================== short test summary info ============================\n"
                 f"FAILED tests/unit/test_migrations.py::test_backfill_v0042_is_idempotent - {ERR_MOD}\n"
                 "1 failed, 63 passed in 52.10s"))
    T.append((a, "A different failure, and it is not related to the pool: the migrations package "
                 "cannot be imported from the installed wheel. Let me look at the packaging config.\n\n"
                 "[tool_use: Read] pyproject.toml"))
    T.append((u, "[tool_result]\n" + _pyproject_full()))
    T.append((a, f"Confirmed root cause: {RC_PKG}. The `find.include` list names ledger.api*, "
                 f"ledger.db* and ledger.fx* but not ledger.migrations*, so the wheel that CI installs "
                 f"omits the migrations package and the import fails with `{ERR_MOD}`. Locally the "
                 "editable install hides it, which is why nobody saw it. Adding the package.\n\n"
                 "[tool_use: Edit] pyproject.toml (line 31: add \"ledger.migrations*\" to include)"))
    T.append((u, "[tool_result] The file /Users/dev/code/ledger-api/pyproject.toml has been updated."))
    T.append((a, "Committing the three fixes together on the branch.\n\n[tool_use: Bash] git add -A && "
                 "git commit -q -m \"fix(db): build engines once in lifespan; roll back on fx failure; "
                 f"package migrations ({TICKET_MAIN})\" && git rev-parse HEAD"))
    T.append((u, f"[tool_result]\n{SHA_FIX}"))
    T.append((a, f"Committed as {SHA_FIX} on fix/PLAT-4821-pool-lifespan. Pushing and opening the PR "
                 "so CI runs the Docker build too.\n\n[tool_use: Bash] git push -u origin "
                 "fix/PLAT-4821-pool-lifespan && gh pr create --fill"))
    T.append((u, "[tool_result]\nEnumerating objects: 23, done.\nCounting objects: 100% (23/23), done.\n"
                 "Delta compression using up to 8 threads\nCompressing objects: 100% (12/12), done.\n"
                 "Writing objects: 100% (12/12), 4.87 KiB | 4.87 MiB/s, done.\nremote: \n"
                 "remote: Create a pull request for 'fix/PLAT-4821-pool-lifespan' on GitHub by visiting:\n"
                 "remote:      https://github.com/example/ledger-api/pull/new/fix/PLAT-4821-pool-lifespan\n"
                 "To github.com:example/ledger-api.git\n * [new branch]      fix/PLAT-4821-pool-lifespan -> "
                 "fix/PLAT-4821-pool-lifespan\nhttps://github.com/example/ledger-api/pull/1418"))
    T.append((a, "PR #1418 is open. Watching the CI run.\n\n[tool_use: Bash] gh pr checks 1418 --watch"))
    T.append((u, "[tool_result]\nlint        pass   41s\nunit        pass   1m12s\nintegration pass   "
                 "2m03s\ndocker-build fail   1m48s   https://github.com/example/ledger-api/actions/runs/19348102277"))
    T.append((a, "Tests are green but the Docker build failed. Reading that log.\n\n[tool_use: Bash] "
                 "gh run view 19348102277 --log-failed | tail -40"))
    T.append((u, "[tool_result]\n" + _docker_log()))
    T.append((a, f"`{ERR_DOCKER}`. uv refuses to install because uv.lock is stale: pyproject.toml now "
                 "requires sqlalchemy>=2.0.35 (bumped with the psycopg3 change) while the lock still "
                 "pins 2.0.31. Two options:\n"
                 "  A. drop --frozen from the Dockerfile so uv re-resolves during the build;\n"
                 "  B. keep --frozen and regenerate uv.lock in the PR.\n"
                 "I recommend B: builds stay reproducible, and the lockfile drift was the actual bug; "
                 "dropping --frozen would hide the next one too."))
    T.append((u, "Agreed, keep --frozen and regenerate the lock. I do not want builds that resolve "
                 "differently from what was reviewed."))
    T.append((a, "[tool_use: Bash] uv lock && git add uv.lock && git commit -q -m \"chore: regenerate "
                 "uv.lock for sqlalchemy 2.0.35\" && git push"))
    T.append((u, "[tool_result]\n" + _uv_lock_output()))
    T.append((a, "Lock regenerated and pushed (b81c3aa). One more thing from the CI output: gitleaks "
                 f"flagged a key in tests/fixtures/fx_sandbox.json; that is tracked separately as "
                 f"{TICKET_SEC} and is out of scope here, but do not paste that value into the PR "
                 "description. Re-watching checks.\n\n[tool_use: Bash] gh pr checks 1418 --watch"))
    T.append((u, "[tool_result]\nlint        pass   40s\nunit        pass   1m09s\nintegration pass   "
                 "1m58s\ndocker-build pass   2m21s"))
    T.append((a, "All four checks pass. Summary of the state: the flake was the per-request engine "
                 f"({RC_POOL}), fixed with a lifespan-owned EngineRegistry; the invalid-transaction "
                 f"error came from the missing rollback at {RC_TXN}; the migrations import failure "
                 f"came from the packaging include list at {RC_PKG}. PR #1418 is ready for review."))
    T.append((u, "Great. " + Q_UNANSWERED_2 + " And leave the RDS question for after review, we can "
                 "look at the parameter groups together."))
    T.append((a, "I have not looked at jobs/backfill.py yet; it lives outside tests/ so the scan did "
                 "not cover it. I'll check how it builds its engine next. First, let me make sure the "
                 "test database port in docker-compose matches what the fixtures expect, since the "
                 "integration job now runs the registry code.\n\n[tool_use: Read] docker-compose.test.yml"))
    T.append((u, "[tool_result]\n" + _numbered(_compose_file().splitlines())))
    T.append((a, f"The test postgres is published on host port {PORT_TEST_PG} (not the default 5432, "
                 "which a local postgres usually occupies), and the compose file caps max_connections "
                 "at 60, which is why the old per-request engines hit the wall so quickly in CI. "
                 "The fixtures read the same DATABASE_URL, so nothing to change there.\n\n"
                 "[tool_use: Bash] rg -n \"create_async_engine|get_engine|get_session\" jobs/"))
    T.append((u, "[tool_result]\n" + _jobs_rg()))
    T.append((a, "jobs/backfill.py and jobs/export_snapshot.py both import get_engine, which no longer "
                 "exists after the registry change, so both jobs need updating before this merges. "
                 "Let me look at how backfill uses it."))

    turns = [{"role": r, "content": c} for r, c in T]
    for i in range(1, len(turns)):
        if turns[i]["role"] == turns[i - 1]["role"]:
            # merge consecutive same-role turns (a user question following a tool result)
            turns[i - 1]["content"] += "\n\n" + turns[i]["content"]
            turns[i]["content"] = None
    return [t for t in turns if t["content"] is not None]


# ---- QA key -------------------------------------------------------------------

def build_questions() -> list[dict]:
    return [
        {"id": "id1", "category": "identifiers", "match": "contains",
         "q": "What is the ticket id of the flaky-test investigation the user asked for?",
         "answers": [TICKET_MAIN]},
        {"id": "id2", "category": "identifiers", "match": "contains",
         "q": "What ticket id tracks the gitleaks secret-scanning finding?",
         "answers": [TICKET_SEC]},
        {"id": "id3", "category": "identifiers", "match": "sha",
         "q": "Which commit sha introduced the regression (the per-request engine)?",
         "answers": [SHA_REGRESSION]},
        {"id": "id4", "category": "identifiers", "match": "sha",
         "q": "Which commit sha contains the three fixes (pool lifespan, rollback, packaging)?",
         "answers": [SHA_FIX]},
        {"id": "id5", "category": "identifiers", "match": "number",
         "q": "On which host TCP port does the test Postgres from docker-compose.test.yml listen?",
         "answers": [PORT_TEST_PG]},
        {"id": "id6", "category": "identifiers", "match": "number",
         "q": "On which TCP port is the /metrics endpoint served?",
         "answers": [PORT_METRICS]},
        {"id": "err1", "category": "errors", "match": "verbatim",
         "q": "Quote the exact pool-exhaustion error line (the E0412 message).",
         "answers": [ERR_POOL]},
        {"id": "err2", "category": "errors", "match": "verbatim",
         "q": "Quote the exact SQLAlchemy invalid-transaction error line.",
         "answers": [ERR_TXN]},
        {"id": "err3", "category": "errors", "match": "verbatim",
         "q": "Quote the exact ModuleNotFoundError line from the unit test run.",
         "answers": [ERR_MOD]},
        {"id": "err4", "category": "errors", "match": "verbatim",
         "q": "Quote the exact final ERROR line of the failed Docker build.",
         "answers": [ERR_DOCKER]},
        {"id": "uq1", "category": "questions", "match": "label",
         "q": f'Was the user\'s question "{Q_ANSWERED}" answered during the session? '
              "Reply with exactly one of ANSWERED, UNANSWERED, UNKNOWN.",
         "answers": ["ANSWERED"], "labels": ["ANSWERED", "UNANSWERED", "UNKNOWN"]},
        {"id": "uq2", "category": "questions", "match": "label",
         "q": f'Was the user\'s question "{Q_UNANSWERED_1}" answered during the session? '
              "Reply with exactly one of ANSWERED, UNANSWERED, UNKNOWN.",
         "answers": ["UNANSWERED"], "labels": ["ANSWERED", "UNANSWERED", "UNKNOWN"]},
        {"id": "uq3", "category": "questions", "match": "label",
         "q": f'Was the user\'s question "{Q_UNANSWERED_2}" answered during the session? '
              "Reply with exactly one of ANSWERED, UNANSWERED, UNKNOWN.",
         "answers": ["UNANSWERED"], "labels": ["ANSWERED", "UNANSWERED", "UNKNOWN"]},
        {"id": "rc1", "category": "root_causes", "match": "fileline",
         "q": "At which file:line was the pool-exhaustion root cause confirmed?",
         "answers": [RC_POOL]},
        {"id": "rc2", "category": "root_causes", "match": "fileline",
         "q": "At which file:line was the invalid-transaction (missing rollback) root cause confirmed?",
         "answers": [RC_TXN]},
        {"id": "rc3", "category": "root_causes", "match": "fileline",
         "q": "At which file:line was the migrations packaging root cause confirmed?",
         "answers": [RC_PKG]},
        {"id": "hyp1", "category": "hypotheses", "match": "label",
         "q": f'Was the hypothesis "{HYP_PGBOUNCER}" CONFIRMED, RULED_OUT, NOT_TESTED, or UNKNOWN? '
              "Reply with exactly one label.",
         "answers": ["RULED_OUT"], "labels": ["CONFIRMED", "RULED_OUT", "NOT_TESTED", "UNKNOWN"]},
        {"id": "hyp2", "category": "hypotheses", "match": "label",
         "q": f'Was the hypothesis "{HYP_XDIST}" CONFIRMED, RULED_OUT, NOT_TESTED, or UNKNOWN? '
              "Reply with exactly one label.",
         "answers": ["RULED_OUT"], "labels": ["CONFIRMED", "RULED_OUT", "NOT_TESTED", "UNKNOWN"]},
        {"id": "dec1", "category": "decisions", "match": "decision",
         "q": "Which async database driver was chosen, asyncpg or psycopg3, and for what reason?",
         "answers": ["psycopg3", "psycopg 3"],
         "reject": ["chose asyncpg", "asyncpg was chosen", "went with asyncpg", "picked asyncpg",
                    "selected asyncpg"],
         "reason_any": ["sqlalchemy", "one driver", "single driver", "sync scripts", "one connection-string",
                        "single connection-string", "one url scheme", "single url scheme"]},
        {"id": "dec2", "category": "decisions", "match": "decision",
         "q": "For caching the database engine, was a module-level singleton or a FastAPI lifespan "
              "handler chosen, and why?",
         "answers": ["lifespan"],
         "reject": ["chose the singleton", "singleton was chosen", "went with the singleton",
                    "chose a singleton", "chose a module-level singleton"],
         "reason_any": ["shutdown", "drain", "dispose", "leak"]},
        {"id": "dec3", "category": "decisions", "match": "decision",
         "q": "For the Docker build failure, was --frozen dropped from the Dockerfile or kept with "
              "uv.lock regenerated, and why?",
         "answers": ["regenerat", "kept --frozen", "keep --frozen", "keeping --frozen", "kept `--frozen`",
                     "keep `--frozen`"],
         "reject": ["dropped --frozen", "drop --frozen", "removed --frozen", "remove --frozen",
                    "without --frozen"],
         "reason_any": ["reproducib", "drift", "stale", "reviewed"]},
        {"id": "sub1", "category": "subagent", "match": "number",
         "q": "How many test modules did the Explore subagent report scanning?",
         "answers": [SUBAGENT_COUNT]},
    ]


CATEGORIES = ("identifiers", "errors", "questions", "root_causes", "hypotheses", "decisions", "subagent")


def build_fixture() -> dict:
    transcript = build_transcript()
    questions = build_questions()
    return {
        "_about": "Synthetic engineering session with planted facts for the compaction A/B "
                  "(skills/_shared/compaction-eval). Deterministic; see fixture.py.",
        "transcript": transcript,
        "questions": questions,
        "planted": {
            "identifiers": [TICKET_MAIN, TICKET_SEC, SHA_REGRESSION, SHA_FIX, PORT_TEST_PG, PORT_METRICS],
            "errors": [ERR_POOL, ERR_TXN, ERR_MOD, ERR_DOCKER],
            "questions": {"answered": [Q_ANSWERED], "unanswered": [Q_UNANSWERED_1, Q_UNANSWERED_2]},
            "root_causes": [RC_POOL, RC_TXN, RC_PKG],
            "ruled_out": [HYP_PGBOUNCER, HYP_XDIST],
            "decisions": [
                {"a": "asyncpg", "b": "psycopg3", "chosen": "psycopg3"},
                {"a": "module-level singleton", "b": "FastAPI lifespan", "chosen": "FastAPI lifespan"},
                {"a": "drop --frozen", "b": "keep --frozen and regenerate uv.lock",
                 "chosen": "keep --frozen and regenerate uv.lock"},
            ],
            "subagent_only_number": SUBAGENT_COUNT,
        },
    }


def transcript_text(fixture: dict) -> str:
    return "\n\n".join(f"[{t['role']}]\n{t['content']}" for t in fixture["transcript"])


def fixture_sha(fixture: dict) -> str:
    raw = json.dumps(fixture, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="write the compaction-eval fixture as JSON")
    ap.add_argument("--write", type=Path, help="destination path (default: stdout)")
    args = ap.parse_args(argv)
    fx = build_fixture()
    text = json.dumps(fx, indent=2, ensure_ascii=False)
    if args.write:
        args.write.write_text(text + "\n", encoding="utf-8")
        print(f"wrote {args.write} ({len(fx['transcript'])} turns, {len(fx['questions'])} questions, "
              f"sha {fixture_sha(fx)})")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
