from typing import TypedDict, Union
from langgraph.graph import StateGraph # framework that allows us to create state graphs for our applications
from IPython.display import Image, display


class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed
    message: str


def greeting_node(state:AgentState) -> AgentState:
    state['message'] = f"{state['message']}, you are doing an amazing job learning langgraph!"
    return state

# print(greeting_node({"message": "Ashish"}))

graph = StateGraph(AgentState)
graph.add_node("greeting", greeting_node)

graph.set_entry_point("greeting")
graph.set_finish_point("greeting")

app = graph.compile()

display(Image(app.get_graph().draw_mermaid_png()))

result = app.invoke({"message": "Bob"})
print(result["message"])


