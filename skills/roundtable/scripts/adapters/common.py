"""Common adapter primitives — HTTP retry, error classification."""
import json
import time
import urllib.request
import urllib.error


class AdapterResult(dict):
    """Standardized adapter return shape.

    Keys: ok (bool), text, input_tokens, output_tokens, elapsed_s,
          model, error (if not ok), retried (bool)
    """


def http_post_json(url: str, payload: dict, headers: dict,
                   timeout: int = 900,
                   retry_on_transient: bool = True) -> dict:
    """POST a JSON payload, return parsed JSON response.

    Retries once on transient errors (5xx, timeouts, ConnectionResetError).
    Does NOT retry on 4xx (auth, bad request, etc.).

    Returns dict with: response (parsed JSON if ok), error (str if not),
                        status_code (int), retried (bool), elapsed_s (float)
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    t0 = time.time()
    retried = False

    for attempt in range(2 if retry_on_transient else 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {
                "response": data,
                "status_code": 200,
                "retried": retried,
                "elapsed_s": round(time.time() - t0, 1),
            }
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code >= 500 and attempt == 0 and retry_on_transient:
                retried = True
                time.sleep(5)
                continue
            return {
                "error": f"HTTP {e.code}: {body[:500]}",
                "status_code": e.code,
                "retried": retried,
                "elapsed_s": round(time.time() - t0, 1),
            }
        except (urllib.error.URLError, ConnectionResetError, OSError) as e:
            err_msg = str(e)
            if attempt == 0 and retry_on_transient:
                retried = True
                time.sleep(5)
                continue
            return {
                "error": f"transport: {err_msg[:500]}",
                "status_code": -1,
                "retried": retried,
                "elapsed_s": round(time.time() - t0, 1),
            }

    return {
        "error": "exhausted retries",
        "status_code": -1,
        "retried": retried,
        "elapsed_s": round(time.time() - t0, 1),
    }
