# Findings

Scenario: library account `LIB-1234`. The account holds contact details, a sensitive loan history ("Coping With Debt"), and a test card number a volunteer typed into `staff_notes`.

| Leak | Where the data crossed | Where I closed it | What it still misses |
|---|---|---|---|
| OUT | `send_hold_text` → SMS provider: account fields, plus the model-written `message` | `for_partner()`: allow-list (`name`, `phone`), then a Comprehend per-type policy on the message: allow `NAME`/`PHONE`, mask `EMAIL`/`ADDRESS`/unlisted types, block card/bank/PIN/password. Fails closed. | Book titles (not PII to Comprehend); any name passes, not just the member's; spelled-out numbers and non-English text; over-masking of the hold ref or branch; the provider keeps name and phone; the LLM provider and any tool that skips `for_partner` |
| IN | `read_account` returns the whole account, card number included, to the model | *(not closed)* | The model sees the card on every lookup; only the system prompt stops it repeating it. It also sits in the in-memory checkpointer. |
| STORED | (1) turn log; (2) scaffold `log.info` of the raw prompt and reply; (3) OTEL GenAI events in `agentcore/.cli/traces` and CloudWatch | (1) `store.write()` calls `for_storage()`: field allow-list (`prompt`, `response`), then an ApplyGuardrail decision; withheld if it intervenes. (2) Logs lengths only. (3) `main.py` forces `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false`; assigned, not `setdefault`, because the ADOT distro sets it to `true` first. | Only as good as the guardrail: titles get through, and a filter on *Detect* writes everything. Most turns are withheld, so the log has little content. Metadata is unchecked. The checkpointer and Bedrock invocation logging aren't covered. A future `print` bypasses all of it; only the grep would catch that. |

## Why each API

- **`for_partner` → Comprehend (transformation):** a hold text is worth sending even after an email is masked out of it, but not if it contains a card number. Deciding that needs to know *what* each piece of PII is and *where* it sits, which is exactly what Comprehend returns.
- **`for_storage` → ApplyGuardrail (decision):** nobody needs our log to answer a member, so when a turn contains PII it's cheaper to not write it than to try to clean it. A yes/no answer is all that takes. In the live run, Ada's turn was withheld and "When does Central Library open?" was written in full. I only read `action`; using the guardrail's masked output would turn it into a second transformation API.

## Closing the IN leak

That would mean a `for_model()` on `read_account` output, like this morning's guardrail on tool results. The cost:

- an extra AWS call on every lookup;
- the agent couldn't confirm contact details or answer "did my fine payment go through?";
- book titles still wouldn't be caught.

Texts would keep working, because `send_hold_text` reads the account directly. The real fix is upstream: take payments through a payment system, and validate `staff_notes`.

## Fail open or closed?

**Closed, in both controls, on purpose.**

- **Storage:** with no `GUARDRAIL_ID`, or the guardrail unreachable, only metadata is written, marked `withheld`. A lost log line is recoverable; a card number on disk isn't. This morning's `scan()` failed open.
- **Partner:** with Comprehend unreachable, the text isn't sent. A hold notice can wait.

One side effect I didn't intend: a non-AWS error in `for_storage` propagates after the model has answered, so the member gets an error instead of the answer.

## With another day

- Templated SMS: the model supplies only `hold_ref` and `branch`, which removes book titles from the message entirely.
- Redact the log instead of withholding it, so it keeps its value.
- Build `for_model()` for `staff_notes`, and measure what it breaks.
- Add a test that fails if any logger or trace output contains PII.
- Move the log to AgentCore Memory.
- Check Bedrock model-invocation logging on the account.
