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

from src.openai.azureai_config import DEPLOYMENT, get_azure_client
from src.utils import _string_content, _to_openai_messages, _tool_name, print_message, print_stream, show_graph, to_openai_tool_calls


document_content = ""
client = get_azure_client()

# sequence - To autmatically handle lists of items, we can use Sequence from typing.
# This allows us to specify that a field should be a list of a certain type, 
# and it can be used in our state schema for our agent.
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]  # This field is a sequence of BaseMessage, and we use the add_messages function to handle adding messages to this field in our graph nodes.


@tool
def update(content:str) -> str:
    """This tool takes in a string and returns the updated string."""
    global document_content
    document_content = content
    return f" Document has been updated successfully: The current content is :\n{document_content}"


@tool
def save(filename:str) -> str:
    """This tool takes in a filename and saves the current document content to that text file. and finish the process
     Args:
        filename (str): The name of the file to save the document content to.
    """
    with open(filename, "w") as f:
        f.write(document_content)
    return f" Document has been saved successfully to {filename}"

tools = [update, save]
openai_tools = [convert_to_openai_tool(tool_item) for tool_item in tools]


def agent_node(state: AgentState) -> AgentState:
    system_prompt = f"You are a helpful assistant that helps users update and save a document. " \
    "You can use the 'update' tool to update the content of the document, and the 'save' tool to " \
    "save the document to a text file. Please assist the user with their requests regarding updating " \
    "and saving their document." \
    "The current content of the document is:\n" + document_content

    msgList = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]

    if not state["messages"]:
        msgList.append(
            {
                "role": "user",
                "content": "I'm ready to help you update the document!, What would you like to create",
            }
        )
    else:
        user_input = input("\n What would you like to do with the document? (You can ask me to update the document or save it)?")
        msgList.append(
            {
                "role": "user",
                "content": user_input,
            }
        )
    
    msgList.extend(_to_openai_messages(state["messages"]))
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
    print(f"\n 🤖 AI : {message.content}")
    if hasattr(message, "tool_calls") and message.tool_calls:
        print(f"\n 🛠️ Tool calls: [{', '.join(_tool_name(tc) for tc in message.tool_calls)}]")

    raw_tool_calls = message.tool_calls or []
    langchain_tool_calls = []
    for tool_call in raw_tool_calls:
        arguments = tool_call.function.arguments or "{}"
        try:
            parsed_args = json.loads(arguments)
        except json.JSONDecodeError:
            parsed_args = {}

        langchain_tool_calls.append(
            {
                "id": tool_call.id,
                "name": tool_call.function.name,
                "args": parsed_args,
                "type": "tool_call",
            }
        )

    ai_message = AIMessage(
        content=message.content or "",
        tool_calls=langchain_tool_calls,
        additional_kwargs={
            "tool_calls": [tool_call.model_dump() for tool_call in raw_tool_calls]
        },
    )
    return {"messages": [ai_message]}


def should_continue(state: AgentState) -> str:
    """This function checks if the conversation should continue or if it has reached an end condition."""
    # In this example, we will just check if the last message contains a certain keyword to determine if we should end the conversation.
    messages = state['messages']
    if not messages:
        return "continue"
    
    last_message = state['messages'][-1]
    tool_calls = getattr(last_message, "tool_calls", None) or getattr(last_message, "additional_kwargs", {}).get("tool_calls", [])
    print(f"Tool calls: {tool_calls}")

    # for msg in reversed(messages):
    #     tool_calls = getattr(msg, "tool_calls", None) or msg.additional_kwargs.get("tool_calls", [])
    if tool_calls:
        for tool_call in tool_calls:
            if _tool_name(tool_call) == 'save':
                return "end"
                
    return "continue"

#graph contructuion

graph = StateGraph(AgentState)
graph.add_node('agent',agent_node)
tools_node = ToolNode(tools=tools)
graph.add_node('tools', tools_node)

graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent", 
    should_continue,
    {
        "continue": "tools",
        "end": END
    })
graph.add_edge("tools", "agent")

app = graph.compile()
# show_graph(app, "drafter.png")


def run_doc_agent(state: AgentState) -> dict:
    """This function runs the document agent by taking in the current state and returning the updated state after processing the agent node."""
    print(f"\n ===== DRAFTER =========")

    response = app.stream(state, stream_mode="values")
    print_message(response)

    
    print(f"\n ===== DRAFTER FINISHED =========")


if __name__ == "__main__":
    run_doc_agent({"messages":[]})