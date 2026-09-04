#!/usr/bin/env python3
"""Deterministic synthetic INCIDENT-RESPONSE session with planted facts and a QA key.

Second fixture for the compaction A/B (run_live.py --fixture incident). Same
planted-fact classes and counts as fixture.py so the two fixtures score on one
grader and one questionnaire shape, but a different domain: an on-call engineer
working a production 5xx incident in a Kubernetes/Istio/Helm/Redis stack rather
than a developer fixing a flaky test. Everything is hand-authored and static:
building the fixture twice yields identical bytes, and `fixture_sha()` pins the
version a results file was scored against.

The session: checkout-gateway (namespace `payments`, cluster prod-us-east-1)
starts returning 12% 5xx minutes after a Helm release that raised gunicorn
workers from 4 to 16; the Redis session store hits `maxclients 256`. It plants,
and the key asks back:

  identifiers  6   two ticket ids, two commit shas, two port numbers
  errors       4   verbatim error lines
  questions    3   user questions, two of which are never answered
  root_causes  3   confirmed root causes with file:line
  hypotheses   2   hypotheses that were tested and ruled out
  decisions    3   A-vs-B decisions with the stated reason
  subagent     1   a number that appears only in a subagent report

Tool results are rendered at realistic size (pod tables, a log tail, Helm
history, a git diff, full manifest reads, Prometheus JSON, an Envoy cluster
dump) so the summarizer actually has to cut; distractors are planted too (an
earlier unrelated incident id, the default Redis port, other shas in the Helm
history, other counts) so a summary has to keep the RIGHT digits. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

# ---- planted facts (the QA key references these constants) -------------------

TICKET_MAIN = "INC-2417"            # the PagerDuty incident being worked
TICKET_SEC = "SRE-3308"             # follow-up ticket the user files near the end
TICKET_DISTRACTOR = "INC-2409"      # last week's unrelated session-store failover
SHA_DEPLOY = "e7c41d09b3f2"         # the release that raised workers 4 -> 16
SHA_FIX = "5a8e21f7c0d3"            # the forward fix (pool cap + DestinationRule)
PORT_SESSION_STORE = "6390"         # Service port for Redis (container listens on 6379)
PORT_ENVOY_ADMIN = "15000"          # istio-proxy admin port used to dump /clusters

ERR_REDIS = "redis.exceptions.ConnectionError: max number of clients reached"
ERR_ENVOY = ("upstream connect error or disconnect/reset before headers. reset reason: "
             "connection failure, transport failure reason: delayed connect error: 111")
ERR_HELM = "Error: UPGRADE FAILED: another operation (install/upgrade/rollback) is in progress"
ERR_RBAC = ('Error from server (Forbidden): pods "session-store-0" is forbidden: User '
            '"oncall-ro@example.com" cannot get resource "pods/log" in API group "" in the '
            'namespace "payments"')

Q_ANSWERED = "What was the error-budget burn rate when the page fired?"
Q_UNANSWERED_1 = ("Do we need to tell the payments vendor about the retry storm, or will they "
                  "see it on their side?")
Q_UNANSWERED_2 = "Can you also check whether the EU cluster runs the same worker count?"

RC_WORKERS = "deploy/helm/checkout-gateway/values-prod.yaml:95"
RC_MAXCLIENTS = "deploy/helm/session-store/templates/configmap.yaml:31"
RC_READINESS = "services/checkout/api/health.py:26"

HYP_AUTOSCALER = "the cluster autoscaler was draining nodes during the rollout"
HYP_STALE = "the ingress gateway was still routing to pod IPs from the previous ReplicaSet"

SUBAGENT_COUNT = "1731"             # distinct customer sessions with a 5xx; only the subagent says it

# ---- bulk tool results --------------------------------------------------------

_NODES = ["ip-10-42-11-201.ec2.internal", "ip-10-42-12-87.ec2.internal", "ip-10-42-13-144.ec2.internal",
          "ip-10-42-14-9.ec2.internal", "ip-10-42-15-233.ec2.internal", "ip-10-42-16-56.ec2.internal"]

_GATEWAY_PODS = [
    ("checkout-gateway-7d9f6b8c4-2kq8p", "10.42.11.34"), ("checkout-gateway-7d9f6b8c4-4zvtn", "10.42.12.91"),
    ("checkout-gateway-7d9f6b8c4-6xw2d", "10.42.13.150"), ("checkout-gateway-7d9f6b8c4-8rj5m", "10.42.14.12"),
    ("checkout-gateway-7d9f6b8c4-b7ct9", "10.42.15.240"), ("checkout-gateway-7d9f6b8c4-c9lhz", "10.42.16.61"),
    ("checkout-gateway-7d9f6b8c4-dm4qs", "10.42.11.37"), ("checkout-gateway-7d9f6b8c4-f2n8w", "10.42.12.95"),
    ("checkout-gateway-7d9f6b8c4-hx6vb", "10.42.13.152"), ("checkout-gateway-7d9f6b8c4-k3pzr", "10.42.14.15"),
    ("checkout-gateway-7d9f6b8c4-m8tfy", "10.42.15.244"), ("checkout-gateway-7d9f6b8c4-x2k9p", "10.42.16.66"),
]

_OTHER_PODS = [
    ("session-store-0", "1/1", "10.42.11.20", 0), ("session-store-1", "1/1", "10.42.13.140", 0),
    ("session-store-2", "1/1", "10.42.15.230", 0),
    ("payments-api-5c8d7f9b6-7hq2n", "2/2", "10.42.12.80", 0), ("payments-api-5c8d7f9b6-9wxl4", "2/2", "10.42.14.4", 0),
    ("payments-api-5c8d7f9b6-kd3sm", "2/2", "10.42.16.50", 0),
    ("promo-engine-6f4b9c8d7-2ndqv", "2/2", "10.42.11.28", 1), ("promo-engine-6f4b9c8d7-pl9zt", "2/2", "10.42.13.146", 0),
    ("fraud-scorer-84c6d5b7f-8fjk2", "2/2", "10.42.12.88", 0), ("fraud-scorer-84c6d5b7f-tz5wq", "2/2", "10.42.15.236", 0),
    ("receipt-mailer-59b8f7c6d-6mv3x", "2/2", "10.42.14.7", 0),
    ("ledger-sync-cron-29174820-q7c2k", "0/2", "10.42.16.58", 0),
]

_HELM_HISTORY = [
    (36, "Mon Aug 11 09:14:02 2026", "superseded", "checkout-gateway-1.38.0", "2026.8.1", "Upgrade complete"),
    (37, "Tue Aug 12 16:40:51 2026", "superseded", "checkout-gateway-1.38.1", "2026.8.2", "Upgrade complete"),
    (38, "Thu Aug 14 11:02:19 2026", "superseded", "checkout-gateway-1.38.1", "2026.8.3", "Upgrade complete"),
    (39, "Mon Aug 18 10:27:44 2026", "superseded", "checkout-gateway-1.39.0", "2026.8.4", "Upgrade complete"),
    (40, "Tue Aug 19 15:55:08 2026", "superseded", "checkout-gateway-1.39.0", "2026.8.5", "Upgrade complete"),
    (41, "Wed Aug 20 09:31:37 2026", "superseded", "checkout-gateway-1.39.1", "2026.8.6", "Upgrade complete"),
    (42, "Thu Aug 21 14:12:55 2026", "superseded", "checkout-gateway-1.39.1", "2026.8.7", "Upgrade complete"),
    (43, "Mon Aug 25 10:48:20 2026", "superseded", "checkout-gateway-1.40.0", "2026.8.8", "Upgrade complete"),
    (44, "Tue Aug 26 17:03:41 2026", "superseded", "checkout-gateway-1.40.0", "2026.8.9", "Upgrade complete"),
    (45, "Thu Aug 28 09:58:13 2026", "superseded", "checkout-gateway-1.40.1", "2026.9.1", "Upgrade complete"),
    (46, "Tue Sep  2 15:21:36 2026", "superseded", "checkout-gateway-1.40.1", "2026.9.2", "Upgrade complete"),
    (47, "Thu Sep  4 14:07:12 2026", "deployed", "checkout-gateway-1.41.0", "2026.9.3", "Upgrade complete"),
]

_GIT_LOG = [
    (SHA_DEPLOY, "perf(gateway): raise gunicorn workers to 16 for the checkout surge"),
    ("9b0d4e2a7c15", "chore(helm): bump checkout-gateway chart to 1.41.0"),
    ("3f7a1c8e5b92", "feat(promo): stackable promo codes behind a flag"),
    ("c2e8d5f0a731", "fix(fraud): retry scorer with jitter"),
    ("71b6e9d3c4a8", "docs: on-call runbook for session-store failover"),
    ("d84c2f1b9e60", "chore: istio 1.24 sidecar images"),
    ("4a9e7b3d1f52", "feat(checkout): idempotency key on /confirm"),
    ("e6d0c4a8b217", "fix(session): refresh ttl on read"),
    ("b3f5a9c7d0e4", "chore(helm): hpa maxReplicas 12 for checkout-gateway"),
    ("0c7e2d9f4b18", "feat(receipts): pdf receipts"),
]


def _numbered(lines: list[str], start: int = 1) -> str:
    """Render like the Read tool: right-aligned line number, tab, content."""
    return "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(lines, start=start))


def _pods_table() -> str:
    rows = ["NAME                                  READY   STATUS      RESTARTS   AGE    IP             NODE"]
    for i, (name, ip) in enumerate(_GATEWAY_PODS):
        node = _NODES[i % len(_NODES)]
        rows.append(f"{name:<37} 2/2     Running     0          41m    {ip:<14} {node}")
    for i, (name, ready, ip, restarts) in enumerate(_OTHER_PODS):
        status = "Completed" if name.startswith("ledger-sync") else "Running"
        age = "9d" if name.startswith("session-store") else "3d"
        rows.append(f"{name:<37} {ready:<7} {status:<11} {restarts:<10} {age:<6} {ip:<14} {_NODES[(i + 2) % len(_NODES)]}")
    return "\n".join(rows)


def _helm_history() -> str:
    rows = ["REVISION  UPDATED                   STATUS      CHART                     APP VERSION  DESCRIPTION"]
    for rev, when, status, chart, app, desc in _HELM_HISTORY:
        rows.append(f"{rev:<9} {when:<25} {status:<11} {chart:<25} {app:<12} {desc}")
    return "\n".join(rows)


def _gateway_logs() -> str:
    base = '{"ts":"2026-09-04T14:%02d:%02d.%03dZ","level":"%s","logger":"%s","msg":%s%s}'
    lines = []
    reqs = [
        ("checkout.api", "INFO", '"POST /checkout/confirm 201 212ms"', ',"session":"s_9f2b7c","tenant":"web"'),
        ("checkout.api", "INFO", '"POST /cart/apply-promo 200 88ms"', ',"session":"s_41ac0e","tenant":"web"'),
        ("checkout.api", "INFO", '"GET /cart 200 31ms"', ',"session":"s_7d3e19","tenant":"ios"'),
        ("checkout.session", "ERROR", '"session load failed"', f',"error":"{ERR_REDIS}","session":"s_c08b52"'),
        ("checkout.api", "ERROR", '"POST /checkout/confirm 503 5012ms"', ',"session":"s_c08b52","tenant":"web"'),
        ("checkout.session", "ERROR", '"session load failed"', f',"error":"{ERR_REDIS}","session":"s_2ee71a"'),
        ("checkout.api", "ERROR", '"POST /cart/apply-promo 503 5009ms"', ',"session":"s_2ee71a","tenant":"android"'),
        ("gunicorn.error", "CRITICAL", '"WORKER TIMEOUT (pid:412)"', ''),
        ("gunicorn.error", "INFO", '"Booting worker with pid: 517"', ''),
        ("checkout.api", "INFO", '"POST /checkout/confirm 201 240ms"', ',"session":"s_b17f3d","tenant":"web"'),
        ("checkout.session", "ERROR", '"session load failed"', f',"error":"{ERR_REDIS}","session":"s_5a90ce"'),
        ("checkout.api", "ERROR", '"POST /checkout/confirm 503 5011ms"', ',"session":"s_5a90ce","tenant":"web"'),
        ("gunicorn.error", "CRITICAL", '"WORKER TIMEOUT (pid:389)"', ''),
        ("gunicorn.error", "INFO", '"Booting worker with pid: 521"', ''),
        ("checkout.api", "INFO", '"GET /healthz 200 1ms"', ''),
        ("checkout.api", "INFO", '"GET /readyz 200 1ms"', ''),
    ]
    minute, second = 31, 2
    for i in range(60):
        logger, level, msg, extra = reqs[i % len(reqs)]
        lines.append(base % (minute, second, (i * 137) % 1000, level, logger, msg, extra))
        second += 3 + (i % 4)
        if second >= 60:
            second -= 60
            minute += 1
    lines.append(f"[2026-09-04T14:34:51.221Z] \"POST /checkout/confirm HTTP/1.1\" 503 UF,URX {ERR_ENVOY} "
                 "- \"-\" 0 91 5004 - \"10.42.0.17\" \"okhttp/4.12.0\" outbound|8080||checkout-gateway.payments.svc.cluster.local")
    return "\n".join(lines)


def _events() -> str:
    lines = ["LAST SEEN   TYPE     REASON              OBJECT                                        MESSAGE"]
    for i, (name, _) in enumerate(_GATEWAY_PODS):
        age = 41 - (i % 3)
        lines += [
            f"{age}m         Normal   Scheduled           pod/{name}      Successfully assigned payments/{name} to {_NODES[i % len(_NODES)]}",
            f"{age}m         Normal   Pulled              pod/{name}      Container image \"ghcr.io/example/checkout-gateway:2026.9.3\" already present on machine",
            f"{age}m         Normal   Created             pod/{name}      Created container checkout-gateway",
            f"{age}m         Normal   Started             pod/{name}      Started container checkout-gateway",
        ]
    lines += [
        "41m         Normal   ScalingReplicaSet   deployment/checkout-gateway                   Scaled up replica set checkout-gateway-7d9f6b8c4 to 12",
        "40m         Normal   ScalingReplicaSet   deployment/checkout-gateway                   Scaled down replica set checkout-gateway-5b7c8d9e6 to 0",
        "40m         Normal   Killing             pod/checkout-gateway-5b7c8d9e6-9qp3l          Stopping container checkout-gateway",
        "40m         Normal   Killing             pod/checkout-gateway-5b7c8d9e6-z4wm7          Stopping container checkout-gateway",
        "19m         Normal   SuccessfulCreate    job/ledger-sync-cron-29174820                 Created pod: ledger-sync-cron-29174820-q7c2k",
        "17m         Normal   Completed           job/ledger-sync-cron-29174820                 Job completed",
        "6m          Warning  BackOff             pod/promo-engine-6f4b9c8d7-2ndqv              Back-off restarting failed container promo-engine",
    ]
    return "\n".join(lines)


def _git_show() -> str:
    lines = [f"{sha[:7]} {msg}" for sha, msg in _GIT_LOG]
    lines += ["", f"commit {SHA_DEPLOY}", "Author: Marcus Oyelaran <marcus@example.com>",
              "Date:   Thu Sep 4 13:52:40 2026 +0000", "",
              "    perf(gateway): raise gunicorn workers to 16 for the checkout surge", "",
              "    Load test on staging showed p95 dropping from 410ms to 190ms with 16 workers.",
              "    Also lifts the HPA ceiling so the surge can scale out.", "",
              " deploy/helm/checkout-gateway/values-prod.yaml | 4 ++--",
              " 1 file changed, 2 insertions(+), 2 deletions(-)", "",
              "diff --git a/deploy/helm/checkout-gateway/values-prod.yaml b/deploy/helm/checkout-gateway/values-prod.yaml",
              "index 4c1f9e2..a8d7b30 100644",
              "--- a/deploy/helm/checkout-gateway/values-prod.yaml", "+++ b/deploy/helm/checkout-gateway/values-prod.yaml",
              "@@ -92,7 +92,7 @@ gunicorn:", "   bind: 0.0.0.0:8080", "   timeout: 30", "   keepalive: 5",
              "-  workers: 4", "+  workers: 16", "   threads: 1", '   workerClass: "uvicorn.workers.UvicornWorker"',
              "   maxRequests: 5000", "@@ -108,4 +108,4 @@ autoscaling:", "   enabled: true", "   minReplicas: 12",
              "-  maxReplicas: 12", "+  maxReplicas: 20", "   targetCPUUtilizationPercentage: 65"]
    return "\n".join(lines)


def _values_prod_full() -> str:
    lines = [
        "# checkout-gateway production values (prod-us-east-1). Applied by Argo CD from main.",
        "replicaCount: 12",
        "image:", "  repository: ghcr.io/example/checkout-gateway", "  tag: 2026.9.3", "  pullPolicy: IfNotPresent",
        "imagePullSecrets:", "  - name: ghcr-pull", "",
        "serviceAccount:", "  create: true", "  name: checkout-gateway",
        "  annotations:", '    eks.amazonaws.com/role-arn: "arn:aws:iam::123456789012:role/checkout-gateway-prod"', "",
        "podAnnotations:", '  sidecar.istio.io/inject: "true"', '  prometheus.io/scrape: "true"',
        '  prometheus.io/port: "9090"', '  prometheus.io/path: "/metrics"', "",
        "podSecurityContext:", "  runAsNonRoot: true", "  runAsUser: 10001", "  fsGroup: 10001", "",
        "securityContext:", "  allowPrivilegeEscalation: false", "  readOnlyRootFilesystem: true",
        "  capabilities:", "    drop: [ALL]", "",
        "service:", "  type: ClusterIP", "  port: 8080", "  targetPort: 8080", "  metricsPort: 9090", "",
        "ingress:", "  enabled: false   # traffic arrives through the Istio ingress gateway (payments-gateway)", "",
        "env:", '  APP_ENV: "production"', '  LOG_LEVEL: "info"', '  LOG_FORMAT: "json"',
        f'  SESSION_STORE_URL: "redis://session-store.payments.svc.cluster.local:{PORT_SESSION_STORE}/0"',
        '  SESSION_TTL_SECONDS: "1800"', '  PAYMENTS_API_URL: "http://payments-api.payments.svc.cluster.local:8080"',
        '  PROMO_ENGINE_URL: "http://promo-engine.payments.svc.cluster.local:8080"',
        '  FRAUD_SCORER_URL: "http://fraud-scorer.payments.svc.cluster.local:8080"',
        '  VENDOR_RETRY_MAX: "3"', '  VENDOR_RETRY_BACKOFF_MS: "250"', '  OTEL_EXPORTER_OTLP_ENDPOINT: "http://otel-collector.observability:4317"',
        '  OTEL_SERVICE_NAME: "checkout-gateway"', "",
        "envFrom:", "  - secretRef:", "      name: checkout-gateway-secrets", "",
        "resources:", "  requests:", "    cpu: 500m", "    memory: 768Mi", "  limits:", '    cpu: "2"', "    memory: 1536Mi", "",
        "livenessProbe:", "  httpGet:", "    path: /healthz", "    port: 8080", "  initialDelaySeconds: 10",
        "  periodSeconds: 10", "  failureThreshold: 3", "",
        "readinessProbe:", "  httpGet:", "    path: /readyz", "    port: 8080", "  initialDelaySeconds: 5",
        "  periodSeconds: 5", "  failureThreshold: 3", "",
        "startupProbe:", "  httpGet:", "    path: /healthz", "    port: 8080", "  failureThreshold: 30", "  periodSeconds: 2", "",
        "gunicorn:", "  bind: 0.0.0.0:8080", "  timeout: 30", "  keepalive: 5",
        "  workers: 16", "  threads: 1", '  workerClass: "uvicorn.workers.UvicornWorker"', "  maxRequests: 5000",
        "  maxRequestsJitter: 500", "  gracefulTimeout: 20", "",
        "sessionStore:", "  poolMaxConnections: 20", "  socketTimeoutSeconds: 5", "  healthCheckIntervalSeconds: 30", "",
        "autoscaling:", "  enabled: true", "  minReplicas: 12", "  maxReplicas: 20", "  targetCPUUtilizationPercentage: 65", "",
        "podDisruptionBudget:", "  enabled: true", "  minAvailable: 9", "",
        "topologySpreadConstraints:", "  - maxSkew: 1", "    topologyKey: topology.kubernetes.io/zone",
        "    whenUnsatisfiable: ScheduleAnyway", "",
        "nodeSelector:", "  workload: general", "tolerations: []",
    ]
    assert lines[94] == "  workers: 16", "RC_WORKERS must be line 95"
    return _numbered(lines)


def _configmap_full() -> str:
    lines = [
        "apiVersion: v1", "kind: ConfigMap", "metadata:", "  name: {{ include \"session-store.fullname\" . }}-config",
        "  namespace: {{ .Release.Namespace }}", "  labels:", "    {{- include \"session-store.labels\" . | nindent 4 }}",
        "data:", "  redis.conf: |", "    # Session store for checkout-gateway. Three-member StatefulSet, one primary.",
        "    bind 0.0.0.0", "    port 6379", "    protected-mode yes", "    tcp-backlog 511", "    timeout 0",
        "    tcp-keepalive 300", "    daemonize no", "    supervised no", "    loglevel notice", "    databases 4",
        "    save 900 1", "    save 300 10", "    save 60 10000", "    stop-writes-on-bgsave-error yes",
        "    rdbcompression yes", "    dbfilename dump.rdb", "    dir /data", "    appendonly yes",
        "    appendfsync everysec", "    # Client limits. Sized for the original 4-worker gateway deployment.",
        "    maxclients 256", "    maxmemory 1536mb", "    maxmemory-policy volatile-lru", "    lazyfree-lazy-eviction yes",
        "    lazyfree-lazy-expire yes", "    slowlog-log-slower-than 10000", "    slowlog-max-len 256",
        "    latency-monitor-threshold 100", "    notify-keyspace-events \"\"", "    hash-max-listpack-entries 128",
        "    activerehashing yes", "    client-output-buffer-limit normal 0 0 0",
        "    client-output-buffer-limit replica 256mb 64mb 60", "    hz 10", "    dynamic-hz yes",
        "  sentinel.conf: |", "    sentinel monitor session-store session-store-0.session-store 6379 2",
        "    sentinel down-after-milliseconds session-store 5000", "    sentinel failover-timeout session-store 60000",
    ]
    assert lines[30] == "    maxclients 256", "RC_MAXCLIENTS must be line 31"
    return _numbered(lines)


def _health_py_full() -> str:
    lines = [
        '"""Liveness and readiness endpoints for checkout-gateway."""',
        "from __future__ import annotations", "", "import logging", "import time", "",
        "from fastapi import APIRouter, Response", "", "from checkout.config import settings",
        "from checkout.observability import metrics", "",
        'logger = logging.getLogger("checkout.health")', "router = APIRouter()", "_STARTED_AT = time.monotonic()", "", "",
        '@router.get("/healthz")', "async def healthz() -> dict:",
        '    """Process is up. Never touches a dependency: the liveness probe must not', '    restart a pod because Redis is slow."""',
        '    return {"status": "ok", "uptime_s": int(time.monotonic() - _STARTED_AT)}', "", "",
        '@router.get("/readyz")', "async def readyz() -> dict:",
        '    return {"status": "ok"}', "", "",
        '@router.get("/version")', "async def version() -> dict:",
        '    return {"version": settings.app_version, "commit": settings.git_sha}', "", "",
        '@router.get("/metrics")', "async def prometheus(response: Response) -> Response:",
        "    response.media_type = metrics.CONTENT_TYPE", "    return Response(content=metrics.render(), media_type=metrics.CONTENT_TYPE)",
        "", "", "async def dependency_report() -> dict:",
        '    """Diagnostic view used by the on-call runbook; NOT wired to any probe."""',
        "    from checkout.session.store import store", "    started = time.perf_counter()", "    try:",
        "        await store.ping(timeout=0.3)", '        session_store = "ok"',
        "    except Exception as exc:  # noqa: BLE001 - diagnostic", '        session_store = f"error: {exc}"',
        '    return {"session_store": session_store, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}',
    ]
    assert lines[25] == '    return {"status": "ok"}' and lines[24].startswith("async def readyz"), "RC_READINESS must be line 26"
    return _numbered(lines)


def _prom(query: str, rows: list[tuple[dict, str]]) -> str:
    result = [{"metric": m, "value": [1756997400 + i, v]} for i, (m, v) in enumerate(rows)]
    return json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}, indent=1)


def _prom_during() -> str:
    return "\n".join([
        _prom('redis_connected_clients{service="session-store"}',
              [({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-0"}, "256"),
               ({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-1"}, "3"),
               ({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-2"}, "3")]),
        _prom('increase(redis_rejected_connections_total{service="session-store"}[30m])',
              [({"service": "session-store", "pod": "session-store-0"}, "48913")]),
        _prom('redis_config_maxclients{service="session-store"}',
              [({"service": "session-store", "pod": "session-store-0"}, "256")]),
        _prom('sum(rate(http_requests_total{app="checkout-gateway",code=~"5.."}[5m])) / sum(rate(http_requests_total{app="checkout-gateway"}[5m]))',
              [({}, "0.1231")]),
        _prom('slo:burn_rate:1h{slo="checkout-gateway-availability"}', [({"slo": "checkout-gateway-availability"}, "14.6")]),
        _prom('slo:error_budget_remaining:30d{slo="checkout-gateway-availability"}', [({"slo": "checkout-gateway-availability"}, "0.72")]),
    ])


def _prom_after() -> str:
    return "\n".join([
        _prom('sum(rate(http_requests_total{app="checkout-gateway",code=~"5.."}[5m])) / sum(rate(http_requests_total{app="checkout-gateway"}[5m]))',
              [({}, "0.0041")]),
        _prom('redis_connected_clients{service="session-store"}',
              [({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-0"}, "148"),
               ({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-1"}, "3"),
               ({"__name__": "redis_connected_clients", "service": "session-store", "pod": "session-store-2"}, "3")]),
        _prom('histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{app="checkout-gateway"}[5m])) by (le))',
              [({}, "0.318")]),
    ])


def _endpoints_and_clusters() -> str:
    lines = ["NAME                      ADDRESSTYPE   PORTS   ENDPOINTS                                                    AGE",
             "checkout-gateway-8k2xz    IPv4          8080    " + ",".join(ip for _, ip in _GATEWAY_PODS[:6]) + " + 6 more...   41m",
             "", f"# istio-proxy admin, localhost:{PORT_ENVOY_ADMIN}/clusters (filtered)"]
    for _, ip in _GATEWAY_PODS:
        lines += [
            f"outbound|8080||checkout-gateway.payments.svc.cluster.local::{ip}:8080::cx_active::2",
            f"outbound|8080||checkout-gateway.payments.svc.cluster.local::{ip}:8080::cx_connect_fail::0",
            f"outbound|8080||checkout-gateway.payments.svc.cluster.local::{ip}:8080::rq_error::37",
            f"outbound|8080||checkout-gateway.payments.svc.cluster.local::{ip}:8080::health_flags::healthy",
            f"outbound|8080||checkout-gateway.payments.svc.cluster.local::{ip}:8080::region::us-east-1",
        ]
    lines += [f"outbound|{PORT_SESSION_STORE}||session-store.payments.svc.cluster.local::10.42.11.20:6379::cx_active::16",
              f"outbound|{PORT_SESSION_STORE}||session-store.payments.svc.cluster.local::10.42.11.20:6379::cx_connect_fail::0",
              f"outbound|{PORT_SESSION_STORE}||session-store.payments.svc.cluster.local::10.42.11.20:6379::health_flags::healthy",
              "", "# dig +short checkout-gateway.payments.svc.cluster.local", "172.20.114.203",
              "# dig +short session-store.payments.svc.cluster.local", "172.20.61.9"]
    return "\n".join(lines)


def _service_yaml() -> str:
    return _numbered([
        "apiVersion: v1", "kind: Service", "metadata:", "  name: session-store", "  namespace: payments",
        "  labels:", "    app.kubernetes.io/name: session-store", "    app.kubernetes.io/instance: session-store",
        "    app.kubernetes.io/managed-by: Helm", "  annotations:", "    meta.helm.sh/release-name: session-store",
        "    meta.helm.sh/release-namespace: payments", "spec:", "  type: ClusterIP", "  clusterIP: 172.20.61.9",
        "  clusterIPs:", "  - 172.20.61.9", "  ipFamilies:", "  - IPv4", "  ipFamilyPolicy: SingleStack",
        "  sessionAffinity: None", "  ports:", "  - name: tcp-redis", f"    port: {PORT_SESSION_STORE}",
        "    protocol: TCP", "    targetPort: 6379", "  - name: tcp-sentinel", "    port: 26379", "    protocol: TCP",
        "    targetPort: 26379", "  selector:", "    app.kubernetes.io/name: session-store",
        "    app.kubernetes.io/instance: session-store", "    role: primary", "status:", "  loadBalancer: {}",
    ])


def _subagent_report() -> str:
    return "\n".join([
        "Explore agent report (read-only Loki query, payments/checkout-gateway, 14:07-14:52 UTC):",
        f"- {SUBAGENT_COUNT} distinct customer sessions received at least one 5xx response in the window.",
        "- 61,204 failed requests in total; 41,880 were POST /checkout/confirm (68%), 11,017 POST /cart/apply-promo (18%),",
        "  8,307 spread over GET /cart, POST /cart/items and GET /checkout/summary.",
        "- Every failed request carries the same error class from the session layer; no other exception type appears.",
        "- p95 request latency in the window 4.9s against a 310ms baseline; p50 2.2s (workers block on the pool timeout).",
        "- 2,914 requests were retried by clients within 2s (User-Agent okhttp and the web SDK), i.e. a retry amplification",
        "  of roughly 1.05x; no evidence of a retry loop against the payments vendor from the gateway side.",
        "- Log lines contain session ids and tenant only; no card data or emails were observed.",
        "- The EU cluster (prod-eu-west-1) was not queried; its Loki tenant is separate.",
    ])


def _helm_history_pending() -> str:
    rows = _helm_history().splitlines()
    rows[-1] = rows[-1].replace("deployed  ", "superseded")
    rows.append(f"{48:<9} {'Thu Sep  4 14:31:05 2026':<25} {'pending-upgrade':<11} {'checkout-gateway-1.41.0':<25} "
                f"{'2026.9.3':<12} Preparing upgrade")
    return "\n".join(rows)


# ---- transcript ---------------------------------------------------------------

def build_transcript() -> list[dict]:
    """~60 alternating turns. Tool calls are rendered as text inside the turn that
    made them; tool results are user turns, as in a real Claude Code session."""
    u, a = "user", "assistant"
    T: list[tuple[str, str]] = []

    T.append((u, f"I'm on call and just got paged: {TICKET_MAIN}, CheckoutGateway5xxBudgetBurn, in "
                 f"prod-us-east-1 namespace payments. checkout-gateway is returning about 12% 5xx and it "
                 f"started a few minutes after a deploy at 14:07 UTC. Can you drive the investigation? "
                 f"My kube context is the read-only on-call one; helm and gh work. Last week's "
                 f"{TICKET_DISTRACTOR} was a session-store failover on a different team's service and is "
                 f"unrelated, so ignore it."))
    T.append((a, "Starting with the state of the namespace so we know whether pods are crashing or "
                 "serving errors while healthy.\n\n[tool_use: Bash] kubectl get pods -n payments -o wide"))
    T.append((u, "[tool_result]\n" + _pods_table()))
    T.append((a, "Twelve checkout-gateway pods, all Running, READY 2/2, zero restarts, 41 minutes old, "
                 "so the rollout replaced the fleet at 14:07 and whatever is failing is not tripping the "
                 "readiness probe. The promo-engine BackOff is a single pod and predates this. Let me "
                 "confirm which release that was.\n\n[tool_use: Bash] helm history checkout-gateway -n payments --max 12"))
    T.append((u, "[tool_result]\n" + _helm_history()))
    T.append((a, "Revision 47 deployed at 14:07:12 with chart 1.41.0 / app 2026.9.3; revision 46 from "
                 "Tuesday is the known-good one. Now the logs from the new pods.\n\n"
                 "[tool_use: Bash] kubectl logs deploy/checkout-gateway -n payments -c checkout-gateway "
                 "--since=20m --tail=60; kubectl logs -n istio-system deploy/payments-gateway --since=5m | grep 503 | tail -1"))
    T.append((u, "[tool_result]\n" + _gateway_logs()))
    T.append((a, f"The application error is `{ERR_REDIS}` on every failed request: the session store is "
                 f"refusing new clients, and each failing request holds a worker for the 5 s socket "
                 f"timeout, which is why the 503s take 5,0xx ms and why gunicorn logs WORKER TIMEOUT. The "
                 f"ingress gateway separately logs `{ERR_ENVOY}` for a slice of requests, which is a "
                 f"connection refused (errno 111) rather than a Redis error; I'll come back to that.\n\n"
                 f"Two candidate explanations for the client exhaustion. First, the platform team had a "
                 f"node-pool change scheduled for today, so one hypothesis is that {HYP_AUTOSCALER}, "
                 f"churning connections as pods moved. Second, the release itself changed connection "
                 f"behaviour. Events will settle the first one.\n\n"
                 "[tool_use: Bash] kubectl get events -n payments --sort-by=.lastTimestamp | tail -60; "
                 "kubectl get nodes -l workload=general --no-headers | awk '{print $2}' | sort | uniq -c"))
    T.append((u, "[tool_result]\n" + _events() + "\n\n   6 Ready"))
    T.append((a, f"No Evicted, no NodeNotReady, no drain or scale-down events in the window; the only "
                 f"activity is the ordinary ReplicaSet swap at 14:07 and all six general nodes are Ready. "
                 f"Ruled out: {HYP_AUTOSCALER}. So it is the release. Let me see what {SHA_DEPLOY} changed.\n\n"
                 f"[tool_use: Bash] git log --oneline -10 && git show {SHA_DEPLOY}"))
    T.append((u, "[tool_result]\n" + _git_show()))
    T.append((a, "Workers went from 4 to 16 per pod and the HPA ceiling from 12 to 20 replicas. Each "
                 "gunicorn worker owns its own Redis connection pool, so the connection budget just "
                 "quadrupled. I need the pool size and the store's client limit to do the arithmetic.\n\n"
                 "[tool_use: Read] deploy/helm/checkout-gateway/values-prod.yaml"))
    T.append((u, "[tool_result]\n" + _values_prod_full()))
    T.append((a, f"Confirmed root cause for the client exhaustion: {RC_WORKERS}. `workers: 16` with "
                 f"`sessionStore.poolMaxConnections: 20` and 12 replicas allows 16 x 20 x 12 = 3,840 client "
                 f"connections to the session store; the previous 4 workers allowed 960, and in practice "
                 f"the pools sat near 200 idle connections. The store's ceiling is set in its chart.\n\n"
                 "[tool_use: Read] deploy/helm/session-store/templates/configmap.yaml"))
    T.append((u, "[tool_result]\n" + _configmap_full()))
    T.append((a, f"Confirmed second root cause: {RC_MAXCLIENTS}. `maxclients 256` is hard-coded in the "
                 f"ConfigMap with a comment saying it was sized for the 4-worker deployment, so the limit "
                 f"was always one worker bump away from this incident. Let me confirm the store is pinned "
                 f"at the ceiling.\n\n[tool_use: Bash] for q in 'redis_connected_clients{{service=\"session-store\"}}' "
                 "'increase(redis_rejected_connections_total{service=\"session-store\"}[30m])' "
                 "'redis_config_maxclients{service=\"session-store\"}' '<5xx ratio>' '<burn rate 1h>' '<budget remaining 30d>'; "
                 "do curl -sG http://prometheus.monitoring.svc:9090/api/v1/query --data-urlencode \"query=$q\"; done"))
    T.append((u, "[tool_result]\n" + _prom_during()))
    T.append((a, "session-store-0 (the primary) reports exactly 256 connected clients and 48,913 rejected "
                 "connections in the last 30 minutes; the two replicas hold only their replication links. "
                 "5xx ratio 12.3%. That is the whole picture for the primary failure."))
    T.append((u, "Ok. Before we go further: " + Q_ANSWERED + " I need it for the incident channel."))
    T.append((a, "From the SLO recording rules just now: the 1-hour burn rate is 14.6x, against the "
                 "page threshold of 14.4x, and the 30-day error budget is down to 72% remaining, so about "
                 "28% of the budget went in roughly forty minutes.\n\n"
                 "Two ways to stop it:\n"
                 "  A. roll back to revision 46 now (Helm restores workers: 4 in one step, same image);\n"
                 "  B. forward-fix by lowering the pool or the worker count in a new release, which "
                 "means a commit, review, pipeline and a fresh rollout.\n"
                 "I recommend A: it restores service in about a minute and we can fix forward calmly "
                 "once the burn stops. Your call."))
    T.append((u, "Roll back. Getting customers unblocked comes first; we fix forward once it is green."))
    T.append((a, "Rolling back to 46.\n\n[tool_use: Bash] helm rollback checkout-gateway 46 -n payments --wait --timeout 5m"))
    T.append((u, f"[tool_result]\n{ERR_HELM}"))
    T.append((a, f"`{ERR_HELM}`: Helm will not act while a release record is pending. Checking the history "
                 "for what is pending.\n\n[tool_use: Bash] helm history checkout-gateway -n payments --max 13"))
    T.append((u, "[tool_result]\n" + _helm_history_pending()))
    T.append((a, "Revision 48 is stuck in pending-upgrade since 14:31:05: the deploy workflow was "
                 "re-run when the alert fired and its helm upgrade never finished (the pipeline runner "
                 "was killed at the 20-minute job limit). The release record is a Secret; removing the "
                 "pending record lets Helm proceed, and nothing was actually applied by 48 since the "
                 "pods are still from 47.\n\n[tool_use: Bash] kubectl -n payments get secret -l owner=helm,name=checkout-gateway "
                 "-o name | tail -3 && kubectl -n payments delete secret sh.helm.release.v1.checkout-gateway.v48"))
    T.append((u, "[tool_result]\nsecret/sh.helm.release.v1.checkout-gateway.v46\nsecret/sh.helm.release.v1.checkout-gateway.v47\n"
                 "secret/sh.helm.release.v1.checkout-gateway.v48\nsecret \"sh.helm.release.v1.checkout-gateway.v48\" deleted"))
    T.append((a, "Retrying the rollback.\n\n[tool_use: Bash] helm rollback checkout-gateway 46 -n payments --wait --timeout 5m"))
    T.append((u, "[tool_result]\nRollback was a success! Happy Helming!"))
    T.append((a, "Rolled back. Watching the error ratio and the client count for the next five minutes.\n\n"
                 "[tool_use: Bash] sleep 300; curl -sG http://prometheus.monitoring.svc:9090/api/v1/query "
                 "--data-urlencode 'query=<5xx ratio>'; ... '<connected clients>'; ... '<p95 latency>'"))
    T.append((u, "[tool_result]\n" + _prom_after()))
    T.append((a, f"5xx ratio 0.41%, which is the normal background of vendor declines; connected clients "
                 f"148 of 256; p95 back to 318 ms. The page will resolve on the next evaluation.\n\n"
                 f"Now the connection-refused 503s the ingress logged. My hypothesis was that "
                 f"{HYP_STALE}, which would show as endpoints in the gateway's cluster table that no longer "
                 f"exist. Let me compare the EndpointSlice, the sidecar's view on the admin port, and DNS.\n\n"
                 "[tool_use: Bash] kubectl get endpointslice -n payments -l kubernetes.io/service-name=checkout-gateway; "
                 f"kubectl -n payments exec checkout-gateway-7d9f6b8c4-2kq8p -c istio-proxy -- curl -s localhost:{PORT_ENVOY_ADMIN}/clusters "
                 "| grep -E 'checkout-gateway|session-store' | grep -E 'cx_active|cx_connect_fail|rq_error|health_flags|region'; "
                 "dig +short checkout-gateway.payments.svc.cluster.local; dig +short session-store.payments.svc.cluster.local"))
    T.append((u, "[tool_result]\n" + _endpoints_and_clusters()))
    T.append((a, f"The gateway's cluster table holds exactly the twelve live pod IPs from the EndpointSlice, "
                 f"every endpoint is healthy with cx_connect_fail 0, and both Service names resolve to their "
                 f"ClusterIPs. Ruled out: {HYP_STALE}. The errno 111 refusals line up instead with the "
                 f"gunicorn WORKER TIMEOUT lines: workers blocked on the pool timeout were killed by the "
                 f"arbiter and the listener was briefly closed while they rebooted, so the sidecar saw a "
                 f"refused connect. That stops on its own with the pool fix.\n\n"
                 "The remaining question is why twelve pods that could not complete a single checkout "
                 "stayed Ready for forty minutes.\n\n[tool_use: Read] services/checkout/api/health.py"))
    T.append((u, "[tool_result]\n" + _health_py_full()))
    T.append((a, f"Confirmed third root cause: {RC_READINESS}. `/readyz` returns ok unconditionally; it "
                 f"never touches the session store, so a pod that cannot serve checkout stays in the "
                 f"Service endpoints. There is even a `dependency_report()` helper that pings the store "
                 f"with a 300 ms timeout, but nothing wires it to a probe.\n\n"
                 "Two ways to get containment:\n"
                 "  A. add the session-store ping to /readyz (readiness fails, pod leaves the endpoints);\n"
                 "  B. an Istio DestinationRule with outlier detection on checkout-gateway (the mesh "
                 "ejects any pod that returns consecutive 5xx for 30 s, no code change).\n"
                 "I recommend B. Readiness on a shared dependency ejects the whole fleet at once when the "
                 "store blips, which is a cascading outage rather than containment; outlier detection ejects "
                 "only the pods actually failing and needs no code change. Which do you want?"))
    T.append((u, "B, the outlier detection. I do not want a Redis blip to take every pod out of rotation at once."))
    T.append((a, "[tool_use: Write] deploy/istio/checkout-gateway-destinationrule.yaml (outlierDetection: "
                 "consecutive5xxErrors 5, interval 10s, baseEjectionTime 30s, maxEjectionPercent 50; "
                 "connectionPool.http.http1MaxPendingRequests 256)"))
    T.append((u, "[tool_result] File created successfully at: /Users/oncall/code/payments-platform/deploy/istio/"
                 "checkout-gateway-destinationrule.yaml"))
    T.append((a, "Now the forward fix for the connection budget itself. Options:\n"
                 "  A. raise `maxclients` on the session store to 10000 and keep the 16 x 20 pools;\n"
                 "  B. cap the per-worker pool at 8 (16 x 8 x 20 max replicas = 2,560, still over 256, so "
                 "B also means lifting maxclients to 4096) and document the budget rule workers x pool x "
                 "maxReplicas < maxclients in the values file.\n"
                 "I recommend B: the cap bounds connections regardless of how far the HPA scales, and Redis "
                 "pays memory per client and is single-threaded, so an unbounded pool just moves the cliff."))
    T.append((u, "Cap the pool. We keep adding replicas and I do not want to rediscover this every time the "
                 "HPA scales. " + Q_UNANSWERED_1))
    T.append((a, "Capping it. On the vendor question: I want to see the gateway's outbound retry counters "
                 "toward the vendor before answering; let me land the fix first and come back to it.\n\n"
                 "[tool_use: Edit] services/checkout/config/redis.py (max_connections 20 -> 8 via "
                 "settings.session_pool_max; socket_connect_timeout 1.0; health_check_interval 30)"))
    T.append((u, "[tool_result] The file /Users/oncall/code/payments-platform/services/checkout/config/redis.py has been updated."))
    T.append((a, "[tool_use: Edit] deploy/helm/checkout-gateway/values-prod.yaml (sessionStore.poolMaxConnections: 8; "
                 "comment: workers x poolMaxConnections x autoscaling.maxReplicas must stay below the store's maxclients)"))
    T.append((u, "[tool_result] The file /Users/oncall/code/payments-platform/deploy/helm/checkout-gateway/values-prod.yaml has been updated."))
    T.append((a, "[tool_use: Edit] deploy/helm/session-store/templates/configmap.yaml (maxclients 256 -> 4096; "
                 "comment names the budget rule and this incident)"))
    T.append((u, "[tool_result] The file /Users/oncall/code/payments-platform/deploy/helm/session-store/templates/configmap.yaml has been updated."))
    T.append((a, "Running the gateway's unit tests and the chart lint before I commit.\n\n"
                 "[tool_use: Bash] uv run pytest services/checkout/tests -q && helm lint deploy/helm/checkout-gateway "
                 "-f deploy/helm/checkout-gateway/values-prod.yaml && helm lint deploy/helm/session-store"))
    T.append((u, "[tool_result]\n....................................................................................  [100%]\n"
                 "84 passed in 21.40s\n==> Linting deploy/helm/checkout-gateway\n[INFO] Chart.yaml: icon is recommended\n\n"
                 "1 chart(s) linted, 0 chart(s) failed\n==> Linting deploy/helm/session-store\n[INFO] Chart.yaml: icon is recommended\n\n"
                 "1 chart(s) linted, 0 chart(s) failed"))
    T.append((a, "Green. Before writing the customer-impact line I want an independent count rather than "
                 "eyeballing the log tail.\n\n[tool_use: Agent] Explore: query Loki for payments/checkout-gateway "
                 "between 14:07 and 14:52 UTC, count distinct customer sessions that received a 5xx, break "
                 "failures down by endpoint, and check for retry loops toward the vendor and for PII in the "
                 "log lines. Read-only."))
    T.append((u, "[tool_result]\n" + _subagent_report()))
    T.append((a, "Useful: the failures are all one error class, the retry amplification is small, and there "
                 "is no vendor retry loop from the gateway side, which is half the answer to your vendor "
                 "question, though I still want the vendor-facing counters before I say nobody needs "
                 "telling. I'll take the subagent's distinct-session count for the impact line in the "
                 "channel. Next, the store's own view of the rejections, from its log.\n\n"
                 "[tool_use: Bash] kubectl logs session-store-0 -n payments --since=1h | grep -i -E 'maxclients|max number' | tail -5"))
    T.append((u, f"[tool_result]\n{ERR_RBAC}"))
    T.append((a, f"`{ERR_RBAC}`: the read-only on-call role has pods/log for the gateway Deployment but not "
                 "for the session-store StatefulSet. That is a follow-up for the access review; the metrics "
                 "already show the rejections, so nothing is blocked. Committing the fix on a branch.\n\n"
                 f"[tool_use: Bash] git checkout -b fix/{TICKET_MAIN}-session-store-budget && git add -A && "
                 f"git commit -q -m \"fix(checkout): cap the session-store pool per worker; outlier detection for "
                 f"checkout-gateway ({TICKET_MAIN})\" && git rev-parse HEAD"))
    T.append((u, f"[tool_result]\n{SHA_FIX}"))
    T.append((a, f"Committed as {SHA_FIX} on fix/{TICKET_MAIN}-session-store-budget. Pushing and opening the "
                 "PR; Argo CD deploys the branch to staging automatically.\n\n"
                 f"[tool_use: Bash] git push -u origin fix/{TICKET_MAIN}-session-store-budget && gh pr create --fill"))
    T.append((u, "[tool_result]\nEnumerating objects: 19, done.\nCounting objects: 100% (19/19), done.\n"
                 "Delta compression using up to 8 threads\nCompressing objects: 100% (10/10), done.\n"
                 "Writing objects: 100% (10/10), 3.12 KiB | 3.12 MiB/s, done.\nremote: \n"
                 f"remote: Create a pull request for 'fix/{TICKET_MAIN}-session-store-budget' on GitHub by visiting:\n"
                 f"remote:      https://github.com/example/payments-platform/pull/new/fix/{TICKET_MAIN}-session-store-budget\n"
                 "To github.com:example/payments-platform.git\n"
                 f" * [new branch]      fix/{TICKET_MAIN}-session-store-budget -> fix/{TICKET_MAIN}-session-store-budget\n"
                 "https://github.com/example/payments-platform/pull/942"))
    T.append((u, f"I filed {TICKET_SEC} for the readiness gap and the on-call log access. " + Q_UNANSWERED_2
                 + " And park the vendor question for the postmortem, we will answer it there."))
    T.append((a, f"Noted: {TICKET_SEC} carries the readiness and RBAC follow-ups, and the vendor question "
                 "moves to the postmortem. I have not looked at the EU cluster yet; the subagent's Loki "
                 "tenant did not cover it either, so I'll check prod-eu-west-1's values file after the PR "
                 "checks. Meanwhile, the status-page update.\n\n"
                 f"[tool_use: Write] incident/{TICKET_MAIN}-status.md (Identified -> Monitoring: cause, rollback "
                 "time, next update in 30 minutes; no customer counts until the postmortem)"))
    T.append((u, f"[tool_result] File created successfully at: /Users/oncall/code/payments-platform/incident/{TICKET_MAIN}-status.md"))
    T.append((a, "One more check before the PR merges: the DestinationRule and the pool URL both name the "
                 "session-store port, so I want the Service definition rather than my memory of it.\n\n"
                 "[tool_use: Bash] kubectl get svc session-store -n payments -o yaml"))
    T.append((u, "[tool_result]\n" + _service_yaml()))
    T.append((a, f"The Service exposes Redis on port {PORT_SESSION_STORE} and forwards to the container's "
                 f"default 6379, so `SESSION_STORE_URL` in the values file is correct as written and the "
                 f"DestinationRule for the store must name {PORT_SESSION_STORE}, not 6379. Watching the PR checks.\n\n"
                 "[tool_use: Bash] gh pr checks 942 --watch"))
    T.append((u, "[tool_result]\nlint            pass   38s\nunit            pass   1m04s\nhelm-lint       pass   "
                 "22s\nstaging-deploy  pass   3m41s\nstaging-smoke   pass   1m12s"))
    T.append((a, f"All five checks pass and staging is serving on the new pool cap. State of the incident: "
                 f"the trigger was the worker bump at {RC_WORKERS} against the hard-coded client limit at "
                 f"{RC_MAXCLIENTS}; containment failed because of the unconditional readiness at "
                 f"{RC_READINESS}. Production is rolled back to revision 46 and healthy; PR #942 carries "
                 "the pool cap, the raised maxclients and the DestinationRule. Still open: the EU cluster "
                 "worker count, and the vendor notification question for the postmortem."))

    turns = [{"role": r, "content": c} for r, c in T]
    for i in range(1, len(turns)):
        if turns[i]["role"] == turns[i - 1]["role"]:
            turns[i - 1]["content"] += "\n\n" + turns[i]["content"]
            turns[i]["content"] = None
    return [t for t in turns if t["content"] is not None]


# ---- QA key -------------------------------------------------------------------

def build_questions() -> list[dict]:
    return [
        {"id": "id1", "category": "identifiers", "match": "contains",
         "q": "What is the PagerDuty incident id the user was paged for?",
         "answers": [TICKET_MAIN]},
        {"id": "id2", "category": "identifiers", "match": "contains",
         "q": "What ticket id did the user file for the readiness and log-access follow-ups?",
         "answers": [TICKET_SEC]},
        {"id": "id3", "category": "identifiers", "match": "sha",
         "q": "Which commit sha raised the gunicorn worker count (the release that caused the incident)?",
         "answers": [SHA_DEPLOY]},
        {"id": "id4", "category": "identifiers", "match": "sha",
         "q": "Which commit sha contains the forward fix (pool cap, maxclients, DestinationRule)?",
         "answers": [SHA_FIX]},
        {"id": "id5", "category": "identifiers", "match": "number",
         "q": "On which TCP port does the session-store Service expose Redis to clients?",
         "answers": [PORT_SESSION_STORE]},
        {"id": "id6", "category": "identifiers", "match": "number",
         "q": "On which TCP port was the istio-proxy admin interface queried for /clusters?",
         "answers": [PORT_ENVOY_ADMIN]},
        {"id": "err1", "category": "errors", "match": "verbatim",
         "q": "Quote the exact Redis error line the gateway logged on every failed request.",
         "answers": [ERR_REDIS]},
        {"id": "err2", "category": "errors", "match": "verbatim",
         "q": "Quote the exact upstream error text the ingress gateway logged for the 503 responses.",
         "answers": [ERR_ENVOY]},
        {"id": "err3", "category": "errors", "match": "verbatim",
         "q": "Quote the exact error line the first helm rollback attempt returned.",
         "answers": [ERR_HELM]},
        {"id": "err4", "category": "errors", "match": "verbatim",
         "q": "Quote the exact Forbidden error kubectl returned when reading the session-store pod log.",
         "answers": [ERR_RBAC]},
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
         "q": "At which file:line was the worker-count change confirmed as the trigger of the client exhaustion?",
         "answers": [RC_WORKERS]},
        {"id": "rc2", "category": "root_causes", "match": "fileline",
         "q": "At which file:line was the hard-coded session-store client limit (maxclients) confirmed as a root cause?",
         "answers": [RC_MAXCLIENTS]},
        {"id": "rc3", "category": "root_causes", "match": "fileline",
         "q": "At which file:line was the unconditional readiness endpoint confirmed as the reason failing pods stayed in rotation?",
         "answers": [RC_READINESS]},
        {"id": "hyp1", "category": "hypotheses", "match": "label",
         "q": f'Was the hypothesis "{HYP_AUTOSCALER}" CONFIRMED, RULED_OUT, NOT_TESTED, or UNKNOWN? '
              "Reply with exactly one label.",
         "answers": ["RULED_OUT"], "labels": ["CONFIRMED", "RULED_OUT", "NOT_TESTED", "UNKNOWN"]},
        {"id": "hyp2", "category": "hypotheses", "match": "label",
         "q": f'Was the hypothesis "{HYP_STALE}" CONFIRMED, RULED_OUT, NOT_TESTED, or UNKNOWN? '
              "Reply with exactly one label.",
         "answers": ["RULED_OUT"], "labels": ["CONFIRMED", "RULED_OUT", "NOT_TESTED", "UNKNOWN"]},
        {"id": "dec1", "category": "decisions", "match": "decision",
         "q": "To stop the 5xx, was a rollback to revision 46 or a forward fix chosen first, and for what reason?",
         "answers": ["roll back", "rollback", "rolled back", "revision 46"],
         "reject": ["chose the forward fix", "forward fix was chosen", "chose to forward-fix", "chose a forward fix",
                    "went with the forward fix", "decided to forward-fix", "forward-fix first"],
         "reason_any": ["restore", "unblock", "customers", "minute", "fast", "quick", "stop the burn", "bleeding",
                        "calmly", "first"]},
        {"id": "dec2", "category": "decisions", "match": "decision",
         "q": "For the connection budget, was raising maxclients alone or capping the per-worker pool chosen, and why?",
         "answers": ["cap", "capped", "capping", "pool max", "poolmaxconnections", "max_connections", "per-worker pool",
                     "pool size", "pool at 8", "pool to 8"],
         "reject": ["chose to raise maxclients alone", "raising maxclients alone was chosen", "chose raising maxclients",
                    "went with raising maxclients", "decided to raise maxclients alone", "chose option a",
                    "chose to only raise", "chose the maxclients increase"],
         "reason_any": ["bound", "regardless", "replica", "hpa", "scal", "rediscover", "single-thread", "memory per client",
                        "moves the cliff", "budget"]},
        {"id": "dec3", "category": "decisions", "match": "decision",
         "q": "For containment of failing pods, was a session-store check in /readyz or Istio outlier detection chosen, and why?",
         "answers": ["outlier", "destinationrule", "destination rule", "eject"],
         "reject": ["chose the readiness", "readiness check was chosen", "chose to add the session-store ping",
                    "went with readiness", "decided on the readiness", "chose the dependency check", "chose option a",
                    "readiness probe was chosen"],
         "reason_any": ["cascad", "whole fleet", "every pod", "all pods", "at once", "no code change", "without a code change",
                        "only the pods", "blip", "mesh"]},
        {"id": "sub1", "category": "subagent", "match": "number",
         "q": "How many distinct customer sessions did the Explore subagent report as having received a 5xx?",
         "answers": [SUBAGENT_COUNT]},
    ]


CATEGORIES = ("identifiers", "errors", "questions", "root_causes", "hypotheses", "decisions", "subagent")


def build_fixture() -> dict:
    transcript = build_transcript()
    questions = build_questions()
    return {
        "_about": "Synthetic incident-response session with planted facts for the compaction A/B "
                  "(skills/_shared/compaction-eval). Deterministic; see fixture_incident.py.",
        "transcript": transcript,
        "questions": questions,
        "planted": {
            "identifiers": [TICKET_MAIN, TICKET_SEC, SHA_DEPLOY, SHA_FIX, PORT_SESSION_STORE, PORT_ENVOY_ADMIN],
            "errors": [ERR_REDIS, ERR_ENVOY, ERR_HELM, ERR_RBAC],
            "questions": {"answered": [Q_ANSWERED], "unanswered": [Q_UNANSWERED_1, Q_UNANSWERED_2]},
            "root_causes": [RC_WORKERS, RC_MAXCLIENTS, RC_READINESS],
            "ruled_out": [HYP_AUTOSCALER, HYP_STALE],
            "decisions": [
                {"a": "roll back to revision 46", "b": "forward fix", "chosen": "roll back to revision 46"},
                {"a": "raise maxclients alone", "b": "cap the per-worker pool", "chosen": "cap the per-worker pool"},
                {"a": "session-store check in /readyz", "b": "Istio outlier detection",
                 "chosen": "Istio outlier detection"},
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
    ap = argparse.ArgumentParser(description="write the incident-response compaction-eval fixture as JSON")
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
