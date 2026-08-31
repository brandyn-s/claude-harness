"""Modal Sandbox template — run untrusted / LLM-generated code in an isolated container.

Run:  modal run sandbox_runner.py

Use for: executing model-generated exploits/PoCs, running an untrusted repo's
test suite, any code you don't want touching your machine.

PERIMETER: code and inputs must be egress-safe (public / synthetic / OSS). Never
run anything carrying sensitive Example data or real secrets in a Modal Sandbox.
"""
import modal

app = modal.App("sandbox-runner")

# Runtime image for the untrusted code; add whatever dependencies it needs.
image = modal.Image.debian_slim().pip_install("pytest")


@app.local_entrypoint()
def main():
    # Example: a snippet a model produced that you want to run in isolation.
    generated_code = "print(sum(i * i for i in range(10)))"

    sb = modal.Sandbox.create(image=image, app=app, timeout=120)  # 2-min cap
    try:
        p = sb.exec("python", "-c", generated_code)
        stdout = p.stdout.read()
        p.wait()
        print("returncode:", p.returncode)
        print("stdout:", stdout)
    finally:
        sb.terminate()
        sb.detach()
