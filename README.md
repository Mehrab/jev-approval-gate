# jev-approval-gate

A tiny smart approval gate for AI agents, built on TypeSafe's Jev (a System One decision model).

The agent proposes a tool call. Jev answers typed questions about it with probabilities. Plain policy code turns those numbers into ALLOW, ASK, or DENY.

**LLM generates, Jev decides, code executes.**

One Python file, standard library only. No `pip install`.

## Run it

```bash
# 1. No key: canned answers so you can see the flow
python3 jev_gate.py --mock

# 2. Live, with a TypeSafe key
export TYPESAFE_API_KEY=your-key
python3 jev_gate.py

# ...or live through OpenRouter (same model, billed to OpenRouter credits)
export OPENROUTER_API_KEY=sk-or-...
python3 jev_gate.py --provider openrouter

# 3. Same inputs, stricter policy - watch a verdict flip
python3 jev_gate.py --allow-threshold 0.9

# 4. Try your own action
python3 jev_gate.py --action "tool=gmail.send to=all-staff@corp.com body='Office closed Friday'"

# Raw Jev answers for each call
python3 jev_gate.py --json
```

Provider: `--provider auto` (default) uses TypeSafe if `TYPESAFE_API_KEY` is set, otherwise OpenRouter.

## What it asks Jev (one API call per action)

| id | type | question |
|---|---|---|
| `decision` | Choice | allow / ask / deny, with a description of each |
| `irreversible` | Noul | Would this be hard to undo? |
| `external` | Noul | Does it reach people outside the team? |
| `on_goal` | Noul | Does it serve the user's stated goal? |
| `risk` | Score | 0 none - 3 severe, if it was a mistake |

The state is `{user_goal, proposed_tool_call}`.

## The policy (plain code, tunable)

1. deny probability >= `--deny-threshold` (0.50) -> DENY
2. on_goal < 0.2 -> DENY
3. external and irreversible both >= 0.5 -> ASK
4. allow probability >= `--allow-threshold` (0.60) -> ALLOW
5. anything else -> ASK

Jev never "decides" on its own. It gives calibrated numbers; your thresholds decide. Change one number and the same input routes differently.

## APIs

- TypeSafe: `POST https://api.typesafe.ai/v1/systemone`, `Authorization: Bearer $TYPESAFE_API_KEY`, `model: jev-latest` ([quick start](https://docs.typesafe.ai/introduction/quickstart))
- OpenRouter: `POST https://openrouter.ai/api/alpha/decisions`, `Authorization: Bearer $OPENROUTER_API_KEY`, `model: typesafe/jev-1.13` ([tutorial](https://openrouter.ai/docs/guides/community/jev-tutorial))

Same request body (`state`, `model`, `questions`) and same `answers` shape on both.

## Cost

Input tokens only, output is free. A full run (5 actions) is a few thousand input tokens, well under a cent. OpenRouter responses include `usage.cost`, and the script prints the total.

## Caveats

- "Can't hallucinate" means Jev can't return something outside your answer space. It doesn't mean the judgment is right.
- Option wording and order in a Choice can move the answer. Tune thresholds on labeled examples, not round numbers.
- Mock numbers are made up for the demo. Live numbers will differ.

## 60-90 second demo script

> Quick one on Jev. Jev isn't a chat model. You give it a state and a few typed questions, and it gives back probabilities. No prose.
>
> So I built the simplest thing I could: an approval gate for an agent. The agent's goal here is prepping for a client demo. It proposes five tool calls: book a prep meeting, delete an old build, wipe the home folder, email the client, and tweet about it.
>
> *(run `python3 jev_gate.py`)*
>
> One Jev call per action, five questions each: allow, ask or deny, is it reversible, does it reach outsiders, is it on goal, and how bad would a mistake be. Each call comes back in well under a second, and the whole run costs a fraction of a cent.
>
> Look at the results. Meeting: allowed. Wipe the home folder: denied. Email to the client: goes to a human, because it's external and you can't unsend it. The tweet: blocked, it has nothing to do with the goal.
>
> Here's the part I like. Jev doesn't make the call, my code does. *(run with `--allow-threshold 0.9`)* Same inputs, one number changed, and deleting the old build now asks me first. That's the governed-harness idea: the LLM proposes, Jev scores, policy decides, and every decision is a number you can log and replay.
>
> Where I want to take it: not just tool calls. Plan steps, delegating to subagents, memory writes, when to interrupt a human. Those are all decisions.
