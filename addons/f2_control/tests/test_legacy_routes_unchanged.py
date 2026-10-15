"""The retired Jev routes send exactly what 3.11.1 sent: the TypeSafe and Cloudflare request bodies for a judge's ask
byte-match fixtures captured from that release's code (haiku-brain-design section 12). The Claude route's extra
variant keys (the bare phrasing and its doctrine topics) never reach them.

Regenerate the fixture only on purpose: F2_REGEN_LEGACY_PAYLOADS=1 pytest this file."""
import json
import os
import pathlib

import jev_kit as K
from jev import client, council
from jev.judges.dusk import DuskJudge
from jev.judges.probe import ProbeJudge

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legacy_payloads.json"


class Recorder:
    def __init__(self):
        self.sent = []

    def post(self, url, json=None, headers=None, timeout=None):  # noqa: A002 - requests' own keyword
        self.sent.append({"url": url, "headers": headers, "body": json})
        return type("R", (), {"status_code": 500, "text": "test"})()


def _payloads(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(client, "requests", rec)
    out = {}
    for judge, ctx in ((DuskJudge(), K.ctx("P2")), (ProbeJudge(), K.ctx("P2"))):
        state, questions = judge.evidence(ctx), council.expand(judge.questions)
        client.call_typesafe("typesafe", "ts-key", state, questions)
        client.call("acct", "cf-token", state, questions, gateway="gw")
        out[judge.name] = {"typesafe": rec.sent[-2], "cloudflare": rec.sent[-1]}
    return out


def test_the_legacy_request_bodies_are_byte_identical(monkeypatch):
    got = json.dumps(_payloads(monkeypatch), sort_keys=True, indent=1)
    if os.environ.get("F2_REGEN_LEGACY_PAYLOADS"):
        FIXTURE.write_text(got + "\n", encoding="utf-8")
    assert got + "\n" == FIXTURE.read_text(encoding="utf-8")
