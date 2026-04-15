from pathlib import Path
import json
import sys
from typing import Annotated, Sequence, TypedDict
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import tool # This is a decorator that allows us to easily define tools that can be used in our graph. It handles the logic of calling the tool and updating the state with the tool's output.
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.graph.message import add_messages # This is a reduceed function that can be used to add messages to our state in a more streamlined way.
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.utils import print_stream, show_graph, to_openai_tool_calls 
from src.openai.azureai_config import DEPLOYMENT, get_azure_client


# email = Annotated[str, "This has to be valid email address"]
# print(email.__metadata__)

# sequence - To autmatically handle lists of items, we can use Sequence from typing.
# This allows us to specify that a field should be a list of a certain type, 
# and it can be used in our state schema for our agent.
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # This field is a sequence of BaseMessage, and we use the add_messages function to handle adding messages to this field in our graph nodes.


@tool
def add(a: int, b: int) -> int:
    """This tool takes in two integers and returns their sum."""
    return a + b    

@tool
def subtract(a: int, b: int) -> int:
    """This tool takes in two integers and returns their difference."""
    return a - b

tools = [add, subtract]
openai_tools = [convert_to_openai_tool(tool_item) for tool_item in tools]

client = get_azure_client()


def agent_node(state: AgentState) -> AgentState:
    """This node takes in a list of messages, processes them with the LLM,
      and updates the state with a response message."""
    # Convert LangChain messages to OpenAI format
    msgList = [
        {
            "role": "system",
            "content": "You are my AI assistant. Please answer my query to the best of your ability.",
        }
    ]
    for msg in state["messages"]:
        if isinstance(msg, HumanMessage):
            msgList.append({"role": "user", "content": msg.content})
        elif isinstance(msg, ToolMessage):
            msgList.append(
                {
                    "role": "tool",
                    "content": msg.content,
                    "tool_call_id": msg.tool_call_id,
                }
            )
        elif isinstance(msg, AIMessage):
            tool_calls = getattr(msg, "tool_calls", None) or msg.additional_kwargs.get("tool_calls", [])
            assistant_payload = {
                "role": "assistant",
                "content": msg.content or "",
            }
            if tool_calls:
                assistant_payload["tool_calls"] = to_openai_tool_calls(tool_calls)
            msgList.append(assistant_payload)
        else:
            msgList.append({"role": "assistant", "content": msg.content})
    
    # print(msgList)
    response = client.chat.completions.create(
        messages=msgList,
        max_tokens=4096,
        temperature=1.0,
        top_p=1.0,
        model=DEPLOYMENT,
        tools=openai_tools,
        tool_choice="auto",
    )
    message = response.choices[0].message
    ai_message = AIMessage(
        content=message.content or "",
        additional_kwargs={
            "tool_calls": [tool_call.model_dump() for tool_call in (message.tool_calls or [])]
        },
    )
    return {"messages": [ai_message]} # we return the updated state with the new message from the LLM, which will be added to the conversation history in our graph.


def should_continue(state: AgentState) -> bool:
    """This function checks if the conversation should continue based on the messages in the state."""
    # For example, we can check if the last message from the user contains a certain keyword to determine if we should continue the conversation.
    last_message = state['messages'][-1]
    # print(f"Last message: {last_message}")
    tool_calls = getattr(last_message, "tool_calls", None) or last_message.additional_kwargs.get("tool_calls", [])
    # print(f"Tool calls: {tool_calls}")
    if not tool_calls:
        return "end"
    return "continue"
    


#graph construction    
graph = StateGraph(AgentState)
graph.add_node("agent", agent_node)

tools_node = ToolNode(tools=tools) # This node allows us to integrate our tools into the graph, so that the LLM can call these tools when generating responses.
graph.add_node("tools", tools_node)

graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent", 
    should_continue,
    {
        "continue": "tools",
        "end": END
    })
graph.add_edge("tools", "agent") # After the tools are called, we route back to the agent node to continue the conversation.
app = graph.compile()
# show_graph(app, "agent_bot_graph.png")

input_state = {"messages": [HumanMessage(content="What is 2 + 2?, and what us 33+33 ?, what is 10-4? and please tell me the joke")]}
print_stream(app.stream(input_state, stream_mode="values"))