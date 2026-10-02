# PiiLab

A library-account assistant on AgentCore (LangGraph + Bedrock). It reads a member's account, and can text them through an external SMS provider when a hold is ready.

- **OUT:** `for_partner()` applies an allow-list, then Comprehend masks or blocks per PII type.
- **STORED:** `store.write()` calls `for_storage()`, which applies an allow-list, then an ApplyGuardrail write/withhold decision.

See [FINDINGS.md](FINDINGS.md).

**Ran locally under `agentcore dev`; not deployed.**

## Test (no AWS needed)

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt    # Windows: .venv\Scripts\...
.venv/bin/pytest
```

## Run

You need permission for `bedrock:InvokeModel`, `comprehend:DetectPiiEntities` and `bedrock:ApplyGuardrail`. Set the guardrail's PII filters to Mask or Block for input, not Detect.

```powershell
$env:AWS_PROFILE = "<profile>"; $env:AWS_REGION = "us-east-1"; $env:GUARDRAIL_ID = "<id>"; $env:LAB_MODEL_ID = "amazon.nova-micro-v1:0"
agentcore dev
agentcore dev "Hi, I'm Ada Placeholder (ada.placeholder@example.invalid, +44 7700 900456). Member LIB-1234. Is my book ready? Please text me."
```

Check for leaks. No output means nothing leaked:

```powershell
Select-String -Pattern "ada.placeholder@example.invalid" -Path app\LabAgent\logs\*, agentcore\.cli\traces\otlp\*, agentcore\.cli\logs\dev\*
```

All personal data here is fabricated: an `.invalid` email, a drama-range phone number, and the Visa test card number.
