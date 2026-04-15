


from typing import Annotated, Sequence, TypedDict
import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage


def show_graph(app,filename:str):
    """Utility function to save and display the graph image."""
    img_bytes = app.get_graph().draw_mermaid_png()
    with open(f'static/{filename}', "wb") as f:
        f.write(img_bytes)
    import subprocess
    subprocess.run(["open", f'static/{filename}'])  # macOS: opens in Preview


def print_stream(stream):
    """Utility function to print streaming responses from the LLM."""
    for s in stream:
        if not isinstance(s, dict) or "messages" not in s or not s["messages"]:
            continue
        message = s["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()


def to_openai_tool_calls(tool_calls: list[dict]) -> list[dict]:
    """Convert LangChain-style tool calls into Azure OpenAI chat payload format."""
    normalized_calls = []
    for tool_call in tool_calls:
        if tool_call.get("function"):
            normalized_calls.append(tool_call)
            continue

        normalized_calls.append(
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": json.dumps(tool_call.get("args", {})),
                },
            }
        )
    return normalized_calls


def print_message(messages):
    """Utility function to print a message in a readable format."""
    if messages is None:
        return

    seen_tool_outputs: set[tuple[str, str]] = set()

    for step in messages:
        step_messages = []
        if isinstance(step, dict):
            step_messages = step.get("messages", [])
        elif isinstance(step, BaseMessage):
            step_messages = [step]

        for message in step_messages:
            if isinstance(message, ToolMessage):
                tool_id = str(getattr(message, "tool_call_id", ""))
                content = str(getattr(message, "content", ""))
                key = (tool_id, content)
                if key in seen_tool_outputs:
                    continue
                seen_tool_outputs.add(key)
                print(f"\nTool Result: {content}")



def _string_content(content) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content)



def _to_openai_messages(messages: Sequence[BaseMessage]) -> list[dict]:
    payload: list[dict] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            payload.append({"role": "user", "content": _string_content(msg.content)})
            continue

        if isinstance(msg, ToolMessage):
            payload.append(
                {
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": _string_content(msg.content),
                }
            )
            continue

        if isinstance(msg, AIMessage):
            tool_calls = to_openai_tool_calls(getattr(msg, "tool_calls", []) or [])
            assistant_msg = {
                "role": "assistant",
                "content": _string_content(msg.content) if msg.content is not None else "",
            }
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            payload.append(assistant_msg)

    return payload


def _tool_name(tool_call) -> str:
    if isinstance(tool_call, dict):
        if "name" in tool_call:
            return tool_call["name"]
        function_obj = tool_call.get("function", {})
        if isinstance(function_obj, dict):
            return function_obj.get("name", "")
        return ""

    function_obj = getattr(tool_call, "function", None)
    if function_obj is not None:
        return getattr(function_obj, "name", "")
    return getattr(tool_call, "name", "")