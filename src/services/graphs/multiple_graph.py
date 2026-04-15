from typing import List, TypedDict, Union
from langgraph.graph import StateGraph,START,END# framework that allows us to create state graphs for our applications
from IPython.display import Image, display


class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed
    name: str
    values :List[int]
    operation: str
    number1: int
    number2: int
    result:str


def first_node(state:AgentState) -> AgentState:
    """This node takes in a name and a list of values, processes them,
      and updates the state with a result message."""
    state['result'] = f"Hello {state['name']}, the sum of your values is {sum(state['values'])}!"
    return state


def second_node(state:AgentState) -> AgentState:
    """This node takes the result from the first node and appends a message to it."""
    state['result'] += " Keep up the great work!"
    return state


def third_node(state:AgentState) -> AgentState:
    """This node takes the result from the second node and appends a final message to it."""
    state['result'] += " You're doing amazing!"
    return state



graph = StateGraph(AgentState)
graph.add_node("first_node", first_node)
graph.add_node("second_node", second_node)
graph.add_node("third_node", third_node)

graph.add_edge("first_node", "second_node") # connect the first node to the second node
graph.add_edge("second_node", "third_node") # connect the second node to the third node

graph.set_entry_point("first_node")
graph.set_finish_point("third_node")
app = graph.compile()

answer = app.invoke({"name": "Alice", "values": [1, 2, 3, 4, 5]})
print(answer["result"])