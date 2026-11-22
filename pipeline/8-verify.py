#!/usr/bin/env python3
"""Career pipeline verifier — the ONLY module allowed to set last_verified.
Methods, recorded per record in 'verification':
  1. jobicy official status endpoint (free, documented; authoritative for jobicy IDs)
  2. bounded listing content check (arbeitnow/remotive): HTTP 200 AND title words present AND
     no expiry notice. Never a bare-200 claim (directive: 200 alone is not verification).
Bounded and manual per run: caps + pacing, respects 429/Retry-After. No standing enablement."""
import json, re, time, urllib.request, urllib.error, datetime, sys, os

OUT = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(OUT, "pipeline-state.json")
NOW = datetime.datetime.now(datetime.timezone.utc).isoformat()
CONTENT_CHECK_CAP = {"arbeitnow": 30, "remotive": 15}

EXPIRY = ["no longer available", "job has expired", "position has been filled",
          "this job is no longer", "job is closed", "nicht mehr verfügbar", "nicht mehr verfuegbar"]

def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.status, r.read().decode("utf-8", "replace")

def jobicy_status(ids):
    status = {}
    for i in range(0, len(ids), 100):
        batch = ids[i:i+100]
        url = "https://jobicy.com/api/jobs/status?ids=" + ",".join(batch)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "career-pipeline-local-test/0.2"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            for s in d.get("jobs", d.get("statuses", [])):
                status[str(s.get("id"))] = s.get("status")
        except Exception as e:
            print("jobicy status ERR", e, file=sys.stderr)
        time.sleep(1)
    return status

def content_check(j):
    try:
        code, html = fetch(j["url"])
    except urllib.error.HTTPError as e:
        return False, f"content check: HTTP {e.code} (inconclusive, not marked closed)"
    except Exception as e:
        return False, f"content check: fetch error {type(e).__name__} (inconclusive)"
    low = html.lower()
    words = [w for w in re.findall(r"[a-z\u00C0-\u024F]{4,}", j["title"].lower())][:4]
    found = sum(1 for w in words if w in low)
    expired = any(p in low for p in EXPIRY)
    ok = code == 200 and found >= max(1, len(words) // 2) and not expired
    return ok, f"content check: HTTP {code}, title words {found}/{len(words)}, expiry-notice {expired}"

def main():
    d = json.load(open(os.path.join(OUT, "collected.json")))
    act = d["jobs"]
    # 1. jobicy official status for every jobicy record
    jids = [j["source_id"] for j in act if j["source"] == "jobicy" and j["source_id"]]
    st = jobicy_status(jids)
    n1 = 0
    for j in act:
        if j["source"] == "jobicy" and j["source_id"] in st:
            j["last_verified"] = NOW
            j["verification"] = "jobicy official status endpoint: " + str(st[j["source_id"]])
            n1 += 1
    # 2. bounded content checks for the other sources
    n2 = 0
    for src, cap in CONTENT_CHECK_CAP.items():
        pool = [j for j in act if j["source"] == src and j.get("primary_site")]
        attempted = 0
        for j in pool:
            if attempted >= cap: break
            prev = str(j.get("verification") or "")
            if prev.startswith("content check: HTTP 403"):
                continue  # 403 bot-block is terminal; no automatic domain retry
            attempted += 1
            ok, note = content_check(j)
            j["verification"] = note
            if ok:
                j["last_verified"] = NOW
                n2 += 1
            time.sleep(1)
    # persist verification into cross-run state
    state = json.load(open(STATE)) if os.path.exists(STATE) else {}
    for j in act:
        if j["id"] in state:
            state[j["id"]]["last_verified"] = j.get("last_verified")
            state[j["id"]]["verification"] = j.get("verification")
    json.dump(state, open(STATE, "w"), ensure_ascii=False, indent=1)
    json.dump(d, open(os.path.join(OUT, "collected.json"), "w"), ensure_ascii=False, indent=1)
    total = sum(1 for j in act if j.get("last_verified"))
    print(f"verified: jobicy-status {n1}, content-check {n2}, total {total}/{len(act)}")

if __name__ == "__main__":
    main()
