"""Dev tool: send the WhatsApp webhook a signed, Meta-shaped text message, as Meta would.

Needs the api running with WA_APP_SECRET set, and the same WA_APP_SECRET in this shell.
Text only (media needs the Graph API). Replies are log-only without a token: see
`docker compose logs worker` (start it with `docker compose start worker`).

    WA_APP_SECRET=dev-secret python scripts/wa_fake.py --from +919000000001 --text "LINK 123456"
"""

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
p.add_argument("--from", dest="sender", required=True, help="sender number, E.164 (+91...)")
p.add_argument("--text", required=True)
p.add_argument("--to", default="dev-alpha", help="business phone_number_id (lab-alpha's seed)")
p.add_argument("--url", default="http://localhost:8000")
a = p.parse_args()

secret = os.environ.get("WA_APP_SECRET", "")
if not secret:
    sys.exit("WA_APP_SECRET is not set: export the same value the api runs with.")

message = {"from": a.sender.lstrip("+"), "id": f"wamid.{uuid.uuid4().hex}", "type": "text",
           "text": {"body": a.text}}
payload = {"object": "whatsapp_business_account", "entry": [{"id": "1", "changes": [{"value": {
    "messaging_product": "whatsapp", "metadata": {"phone_number_id": a.to},
    "messages": [message]}}]}]}
body = json.dumps(payload).encode()
sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    a.url + "/api/whatsapp/webhook", data=body,
    headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    sys.exit(f"{e.code} {e.read().decode()}")
except urllib.error.URLError as e:
    sys.exit(f"cannot reach {a.url}: {e.reason}")
