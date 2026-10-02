# Friday Afternoon Lab: Close the Leaks on AgentCore

## What this reinforces

This morning you watched an agent with a correctly configured guardrail. All of
that was plain Bedrock, on purpose: none of it is platform-specific.

This afternoon you put the same controls into an agent running on **AgentCore
Runtime**, the platform you have been working on all week.

**This lab gives you more step-by-step guidance than a normal assignment**,
because nobody has explicitly shown you this particular combination. The
guidance is in *how to set up* — the decisions about what to redact and where
are still yours, and they are what is being marked.

---

## Objective

A small agent, running on AgentCore, that handles a customer message
containing personal data and **closes two of the three leaks** — with a
written finding explaining what the third one would take.

Done looks like: a `grep` for the customer's email address across everything
your agent sends outward and everything it writes down returns nothing, while
the agent still answers the customer's question.

---

## Requirements

### Functional

1. **An AgentCore project** created with the `agentcore` CLI, with a
   `BedrockAgentCoreApp` entrypoint. It must run — either deployed to Runtime
   (`agentcore deploy`) or locally under `agentcore dev`. Either is fine;
   say which in your README.

2. **Two tools**, mirroring the two directions from this morning:
   - one that **reads** a record from a fake backing store, where the record
     contains personal data you did not choose to be there;
   - one that **sends** a contact detail to a simulated third party.

   Do not reuse this morning's orders/shipping scenario. Pick something else —
   a clinic booking system, a library account, a warranty claim, a tenancy
   application. The data shapes should be yours.

3. **Close the OUT leak.** Whatever reaches your third-party tool must contain
   no personal data beyond what that party genuinely needs to do its job. You
   decide what that is and defend it in `FINDINGS.md`.

4. **Close the STORED leak.** Anything your agent writes down — a log file, or
   AgentCore Memory if you use it — must contain no raw personal data.
   Redaction happens **at the moment of writing**, not as a cleanup pass.

5. **Document the IN leak.** Your read tool must return at least one field
   containing personal data nobody would have put there on purpose (this
   morning's was a card number in a free-text payment reference). You are not
   required to close it. You *are* required to explain in `FINDINGS.md` what
   closing it would cost and what it would break.

### Design constraints — these are what is actually being marked

6. **Name your control functions after the destination, not the data.**
   `for_partner(...)`, `for_storage(...)` — not `redact_email(...)`. If a
   reviewer can tell what a function does to data without knowing where the
   data is going, the design is wrong.

7. **Use an allow-list, not a deny-list**, for at least the outbound control,
   and say why in a comment.

8. **One of your controls must use a decision API** (`ApplyGuardrail`) and one
   must use a **transformation API** (Comprehend's `detect_pii_entities`).
   Choose which goes where and justify it in one sentence each. Getting these
   the wrong way round is a defensible answer if you argue it well; not
   noticing there was a choice is not.

### Tests

9. **At least two `pytest` tests**, and they must be real assertions about
   leaks, not smoke tests:
   - one asserting that the payload handed to your third-party tool contains
     no raw personal data;
   - one asserting that a persisted record contains none.

   Both should be able to fail. Write them so that deleting a control turns
   one red.

### Write-up

10. **`FINDINGS.md`** containing this table, filled in for your agent:

| Leak | Where the data crossed | Where I closed it | What it still misses |
|---|---|---|---|
| OUT | | | |
| IN | | *(not closed)* | |
| STORED | | | |

Plus two short paragraphs:
- **Fail open or fail closed?** If Comprehend or the guardrail is unavailable
  when a record is about to be written, what does your code do — and is that
  what you intended? Say which you chose and why.
- **What you would do with another day.**

---

## Getting started

You are not being marked on setup, so here it is.

```bash
agentcore create --project-name PiiLab --name LabAgent \
  --language Python --framework LangChain_LangGraph \
  --model-provider Bedrock --memory none
cd PiiLab
```

That gives you `app/LabAgent/main.py` (the entrypoint) and
`agentcore/agentcore.json` (the project config). Your work goes in
`app/LabAgent/`:

```
app/LabAgent/
  main.py          <- entrypoint, already scaffolded
  tools.py         <- your two tools + the fake backing store
  controls.py      <- for_partner(), for_storage()
  store.py         <- whatever writes records down
tests/
  test_leaks.py    <- the two tests
```

Run it locally while you iterate — much faster than deploying:

```bash
agentcore dev
```

Deploy when you are happy:

```bash
agentcore deploy --yes
agentcore invoke "your test message with a name, an email and a phone number in it"
```

**Permissions you will need:** `comprehend:DetectPiiEntities`,
`bedrock:ApplyGuardrail`, and a Bedrock Guardrail to point at. You can reuse
the `support-agent-pii` guardrail from this morning — ask for the ID if you
did not note it down.

**If you want to use AgentCore Memory** for the persistence requirement rather
than a log file: fine, and it is the more interesting answer. Be aware a new
memory resource takes **about ten minutes** to go ACTIVE, so create it first
and build everything else while you wait. A log file is a perfectly acceptable
answer and costs you none of that time.

---

## What good looks like

Before you submit, check:

- [ ] `git clone` into a clean directory, `pip install -r requirements.txt`,
      `pytest` from the repo root — all green.
- [ ] Deleting one line from `controls.py` makes a test go red.
- [ ] No function in `controls.py` is named after a data type.
- [ ] `FINDINGS.md` table is filled in, including the "still misses" column —
      that column is where most of the marks are.
- [ ] You can answer, out loud, why each control uses the API it uses.
- [ ] No real personal data anywhere in the repo. Use obviously fabricated
      names, addresses and test card numbers.

---

## Deliverable

**A link to a public GitHub repository**, submitted on Canvas as a URL —
nothing else.

The repository must contain:

- your source, with tests in a separate directory from application code;
- a dependency file (`requirements.txt` or `pyproject.toml`);
- a short `README.md` with setup and run instructions, and one line saying
  whether you ran it deployed or under `agentcore dev`;
- `FINDINGS.md`;
- a `.gitignore` that excludes your virtual environment — and, today
  especially, any transcript or log file you generated.

It must pass `pytest` when cloned fresh and run from the repo root.

---

## Time expectation

**~1.5 hours.** If you are past two, stop, submit what you have, and put the
rest in the "what you would do with another day" paragraph — that paragraph is
worth marks and an unfinished feature is not.
