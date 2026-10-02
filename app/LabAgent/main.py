import os
from collections import OrderedDict

# Stop tracing from recording message content (a STORED leak into OTEL/CloudWatch).
# Assigned, not setdefault: the ADOT distro has already set it to "true".
os.environ["TRACELOOP_TRACE_CONTENT"] = "false"
os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.prebuilt import create_react_agent
from opentelemetry.instrumentation.langchain import LangchainInstrumentor
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model

import store
from tools import TOOLS

LangchainInstrumentor().instrument()

app = BedrockAgentCoreApp()
log = app.logger

_llm = None

def get_or_create_model():
    global _llm
    if _llm is None:
        _llm = load_model()
    return _llm


DEFAULT_SYSTEM_PROMPT = """
You are a library assistant. Use read_account to answer questions about a
member's loans, due dates, holds and fines. When a reserved item is ready
and the member wants to be told, use send_hold_text with a short message
saying which branch to collect it from and the hold reference.
Never repeat payment card details back to anyone, and never put book titles
or other account details into a text message.
"""


# Scaffold's public web-search MCP client removed: an outbound channel for_partner doesn't cover.
tools = TOOLS

# Module-level checkpointer preserves conversation history across invocations.
# InMemorySaver keeps every thread_id (= session_id) checkpoint in memory
# forever, so we bound it to 128 active threads with LRU eviction (the
# least-recently-used thread is deleted and its history reset) to keep a
# long-running process from growing without limit. For durable history, swap in
# a persistent checkpointer (e.g. SqliteSaver/AsyncSqliteSaver with a file path).
_CHECKPOINT_LIMIT = 128
_checkpointer = InMemorySaver()
_thread_ids = OrderedDict()


def touch_thread(thread_id):
    if thread_id in _thread_ids:
        _thread_ids.move_to_end(thread_id)
        return
    while len(_thread_ids) >= _CHECKPOINT_LIMIT:
        evicted, _ = _thread_ids.popitem(last=False)
        _checkpointer.delete_thread(evicted)
    _thread_ids[thread_id] = True



@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent.....")

    # Define the agent using create_react_agent (checkpointer is shared across invocations)
    graph = create_react_agent(
        get_or_create_model(),
        tools=tools,
        prompt=DEFAULT_SYSTEM_PROMPT,
        checkpointer=_checkpointer,
    )

    # Process the user prompt
    prompt = payload.get("prompt", "What can you help me with?")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    session_id = getattr(context, "session_id", None) or "default-session"
    touch_thread(session_id)
    # Length only; the text itself goes through store.write.
    log.info("Agent input received (%d chars)", len(prompt))

    # Run the agent (checkpointer auto-loads/saves history per session)
    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=prompt)]},
        config={"configurable": {"thread_id": session_id}},
    )

    # Return result
    output = result["messages"][-1].content
    store.write({"event": "turn", "session_id": session_id, "prompt": prompt, "response": output})
    log.info("Agent output returned (%d chars)", len(output))
    return {"result": output}


if __name__ == "__main__":
    app.run()
