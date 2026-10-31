"""Probe which models each provider key can reach. Never prints keys."""
import json
import urllib.request
import urllib.error
from dotenv import dotenv_values

env = {k.strip().lower(): (v or "").strip() for k, v in dotenv_values(".env").items()}


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, str(e)[:300]


print("== HF model", env["hf_model_id"])
s, d = get(f"https://huggingface.co/api/models/{env['hf_model_id']}?expand[]=inferenceProviderMapping&expand[]=pipeline_tag&expand[]=gated")
print(s, d if s != 200 else {k: d.get(k) for k in ("pipeline_tag", "gated", "inferenceProviderMapping")})

print("== HF whoami")
s, d = get("https://huggingface.co/api/whoami-v2", {"Authorization": f"Bearer {env['hf_token']}"})
print(s, (d.get("name"), d.get("type")) if s == 200 else d)

print("== Gemini models")
for hdr in ({"x-goog-api-key": env["gemini_api_key"]}, {"Authorization": f"Bearer {env['gemini_api_key']}"}):
    s, d = get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=100", hdr)
    print(list(hdr)[0], s)
    if s == 200:
        for m in d["models"]:
            if "generateContent" in m.get("supportedGenerationMethods", []):
                print("  ", m["name"])
        break
    else:
        print(d)

print("== Sarvam")
for path in ("https://api.sarvam.ai/v1/models",):
    for hdr in ({"api-subscription-key": env["sarvam_api_key"]}, {"Authorization": f"Bearer {env['sarvam_api_key']}"}):
        s, d = get(path, hdr)
        print(list(hdr)[0], s, d if s != 200 else [m.get("id") for m in d.get("data", d)])
