from langgraph.graph import StateGraph, START, END
from typing import List, TypedDict, Union
from IPython.display import Image, display

class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed 
    name: str
    values :List[int]
    operation1: str
    operation2: str
    number1: int
    number2: int
    result:str

def addition_node(state:AgentState) -> AgentState:
    """This node takes in two numbers and an operation, processes them,
      and updates the state with a result message."""
    if state['operation1'] == '+':
        state['result'] = state['number1'] + state['number2']
    return state

def subtraction_node(state:AgentState) -> AgentState:
    """This node takes in two numbers and an operation, processes them,
      and updates the state with a result message."""
    if state['operation2'] == '-':
        state['result'] = state['number1'] - state['number2']
    return state

def router_node(state:AgentState) -> AgentState:
    """This node routes the state to either the addition node or the subtraction node based on the operations specified."""
    if state['operation1'] == '+':
        return 'addition_operation'
    elif state['operation2'] == '-':
        return 'subtraction_operation'
    
graph = StateGraph(AgentState)
graph.add_node("add_node", addition_node)
graph.add_node("subtract_node", subtraction_node)
graph.add_node("router_node", lambda state:state) #passthrough function for routing

graph.add_edge(START, "router_node")

graph.add_conditional_edges("router_node", 
router_node,                            
{
    "addition_operation": "add_node",
    "subtraction_operation": "subtract_node"
})

graph.add_edge("add_node", END)
graph.add_edge("subtract_node", END)

app = graph.compile()

# Save and open graph image
img_bytes = app.get_graph().draw_mermaid_png()
with open("static/cond_graph.png", "wb") as f:
    f.write(img_bytes)
import subprocess
# subprocess.run(["open", "static/cond_graph.png"])  # macOS: opens in Preview

input_state = AgentState(name="Example", values=[1, 2], operation1="-", operation2="-", number1=5, number2=3, result="")
answer = app.invoke(input_state)
print(f"Result of {input_state['number1']} {input_state['operation1']} {input_state['number2']} is: {answer['result']}")