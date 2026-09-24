#!/usr/bin/env python3
"""
jev_mail_triage.py - tag email with TypeSafe's Jev. Report only, never touches a mailbox.

Same pattern as jev_gate.py: state + typed questions, one Jev call per email.
Jev returns probabilities; plain code decides whether a tag is confident enough
to apply or should go to a review queue.

Stdlib only (Python 3.8+).

  python3 jev_mail_triage.py --mock                     # no key, canned answers
  export TYPESAFE_API_KEY=...                           # or OPENROUTER_API_KEY=sk-or-...
  python3 jev_mail_triage.py                            # live, reads emails.json
  python3 jev_mail_triage.py --emails my_export.json    # your own emails
  python3 jev_mail_triage.py --min-confidence 0.8       # stricter auto-tag cutoff
  python3 jev_mail_triage.py --csv out.csv              # also write results to CSV

Input: a JSON list of {"from": ..., "subject": ..., "snippet": ...}.
Only the first 500 chars of each snippet are sent.

Questions per email (all in one call):
  tag          Choice  reply-needed / waiting-on / fyi / finance-receipt /
                       newsletter / community / personal / junk
  needs_reply  Noul    does this need a response within 3 days?
  urgency      Score   0 ignore, 1 someday, 2 this week, 3 today
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROUTES = {
    "typesafe": {
        "url": os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip("/") + "/v1/systemone",
        "key_env": "TYPESAFE_API_KEY",
        "model": os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest"),
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/alpha/decisions",
        "key_env": "OPENROUTER_API_KEY",
        "model": os.environ.get("OPENROUTER_JEV_MODEL", "typesafe/jev-1.13"),
    },
}

OWNER = "Mehrab (consultant, community volunteer)"

# Keep the tag list short. Criteria are decision rules, not topic descriptions.
# Tuned on a 50-email live sample: without the "never automated" rule, LinkedIn
# invitations and webinar invites came back as reply-needed, and retail promos
# split between newsletter and junk.
QUESTIONS = {
    "tag": {
        "type": "choice",
        "instructions": "Which single label fits this email best? Pick by what the sender wants from the reader, not by the topic.",
        "criteria": {
            "reply-needed": "A real person writing to the reader directly asks a question or for a decision, reply, or action. Automated or bulk senders are never reply-needed.",
            "waiting-on": "The reader asked for something earlier and this is progress or a holding reply; the ball is in the sender's court.",
            "fyi": "A person or service is informing the reader; nothing is asked of them.",
            "finance-receipt": "A receipt, invoice, bill, payment confirmation, or bank/card notice.",
            "newsletter": "Bulk content the reader subscribed to read: news digests, blogs, Substacks.",
            "community": "From a community, volunteer, religious, or meetup group the reader belongs to.",
            "personal": "From a friend or family member, one to one, not work.",
            "junk": "Promotions, sales, marketing, webinar or event pitches, cold outreach, or spam.",
        },
    },
    "needs_reply": {"type": "noul",
                    "instructions": "A real person is waiting for the reader to write back, and the reply should happen within 3 days."},
    "urgency": {"type": "score",
                "instructions": "How soon should the reader deal with this email?",
                "criteria": ["Ignore - no action ever needed",
                             "Someday - fine to leave for weeks",
                             "This week",
                             "Today"]},
}

# Illustrative canned answers for --mock, keyed by subject. Numbers are made up.
MOCK = {
    "Can you review the Q4 proposal by Friday?": ("reply-needed", 0.88, 0.93, 2.4),
    "Re: Venue for October meetup": ("waiting-on", 0.61, 0.35, 1.6),
    "Your receipt from Apple": ("finance-receipt", 0.97, 0.02, 0.1),
    "The Batch: this week in AI": ("newsletter", 0.94, 0.01, 0.2),
    "Volunteers needed Saturday - book drive": ("community", 0.72, 0.58, 1.9),
    "dinner sunday?": ("personal", 0.83, 0.86, 2.2),
    "Exclusive 70% off - today only!!": ("junk", 0.91, 0.0, 0.0),
    "Your package has shipped": ("fyi", 0.79, 0.03, 0.6),
}


def mock_answers(email):
    tag, conf, reply, urg = MOCK.get(email.get("subject"), ("fyi", 0.45, 0.3, 1.0))
    rest = (1 - conf) / (len(QUESTIONS["tag"]["criteria"]) - 1)
    probs = {k: (conf if k == tag else round(rest, 3)) for k in QUESTIONS["tag"]["criteria"]}
    return {
        "tag": {"type": "choice", "choice": tag, "confidence": conf, "probabilities": probs},
        "needs_reply": {"type": "noul", "noul": reply},
        "urgency": {"type": "score", "score": urg, "confidence": 0.8},
    }, {"input_tokens": 0}


def build_state(email):
    return {
        "mailbox_owner": OWNER,
        "from": email.get("from", ""),
        "subject": email.get("subject", ""),
        "body_first_500_chars": (email.get("snippet") or "")[:500],
    }


def ask_jev(state, api_key, route):
    body = json.dumps({"state": state, "model": route["model"], "questions": QUESTIONS}).encode()
    req = urllib.request.Request(
        route["url"], data=body, method="POST",
        headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        sys.exit("Jev API error %s: %s" % (e.code, e.read().decode()[:500]))
    except urllib.error.URLError as e:
        sys.exit("Could not reach %s: %s" % (route["url"], e.reason))
    return data["answers"], data.get("usage", {})


def route_email(a, min_confidence):
    """Plain code: apply the tag only when Jev is confident, else queue for review."""
    conf = a["tag"].get("confidence", 0)
    if conf >= min_confidence:
        return "APPLY"
    return "REVIEW"


def main():
    ap = argparse.ArgumentParser(description="Jev email triage demo (report only)")
    ap.add_argument("--emails", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "emails.json"))
    ap.add_argument("--mock", action="store_true", help="canned answers, no API key or network")
    ap.add_argument("--min-confidence", type=float, default=0.70, help="auto-tag cutoff (default 0.70)")
    ap.add_argument("--provider", choices=["auto", "typesafe", "openrouter"], default="auto")
    ap.add_argument("--csv", help="write results to this CSV file")
    ap.add_argument("--json", action="store_true", help="also print raw Jev answers")
    args = ap.parse_args()

    provider = args.provider
    if provider == "auto":
        provider = "typesafe" if os.environ.get("TYPESAFE_API_KEY") else "openrouter"
    route = ROUTES[provider]
    api_key = os.environ.get(route["key_env"], "")
    if not args.mock and not api_key:
        sys.exit("Set TYPESAFE_API_KEY or OPENROUTER_API_KEY (or run with --mock).")

    with open(args.emails) as f:
        emails = json.load(f)

    mode = "MOCK (illustrative numbers)" if args.mock else "LIVE %s via %s" % (route["model"], provider)
    print("Mode: %s | %d emails | auto-tag if confidence >= %.2f\n" % (mode, len(emails), args.min_confidence))
    print("%-24s %-34s %-15s %5s %6s %4s  %s" % ("from", "subject", "tag", "conf", "reply", "urg", "route"))
    print("-" * 100)

    rows, tokens, cost = [], 0, 0.0
    for e in emails:
        answers, usage = mock_answers(e) if args.mock else ask_jev(build_state(e), api_key, route)
        tokens += usage.get("input_tokens", 0) or 0
        cost += usage.get("cost", 0) or 0
        tag, conf = answers["tag"]["choice"], answers["tag"].get("confidence", 0)
        reply, urg = answers["needs_reply"]["noul"], answers["urgency"]["score"]
        route_to = route_email(answers, args.min_confidence)
        print("%-24s %-34s %-15s %5.2f %6.2f %4.1f  %s" % (
            e.get("from", "")[:24], e.get("subject", "")[:34], tag, conf, reply, urg, route_to))
        if args.json:
            print(json.dumps(answers, indent=2))
        rows.append({"from": e.get("from", ""), "subject": e.get("subject", ""), "tag": tag,
                     "confidence": round(conf, 3), "needs_reply": round(reply, 3),
                     "urgency": round(urg, 2), "route": route_to})

    applied = sum(r["route"] == "APPLY" for r in rows)
    print("\n%d auto-tagged, %d to review" % (applied, len(rows) - applied))
    if not args.mock:
        print("Input tokens used: %d" % tokens + (" | cost $%.6f" % cost if cost else ""))
    if args.csv:
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print("Wrote %s" % args.csv)


if __name__ == "__main__":
    main()

# Example (mock) run:
#   $ python3 jev_mail_triage.py --mock
#   from                     subject                            tag              conf  reply  urg  route
#   priya@clientco.com       Can you review the Q4 proposal by  reply-needed     0.88   0.93  2.4  APPLY
#   organizer@meetup-hous... Re: Venue for October meetup       waiting-on       0.61   0.35  1.6  REVIEW
#   no_reply@email.apple.com Your receipt from Apple            finance-receipt  0.97   0.02  0.1  APPLY
#   ...
