from langgraph.graph import StateGraph, START, END
from typing import List, TypedDict, Union
from IPython.display import Image, display

class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed
    operation1: str
    operation2: str
    number1: int
    number2: int
    number3: int
    number4: int
    finalNumber1: int
    finalNumber2: int


def addition_node(state:AgentState) -> AgentState:
    """This node performs addition on number1 and number2."""
    if state['operation1'] == '+':
        state['finalNumber1'] = state['number1'] + state['number2']
    return state

def subtraction_node(state:AgentState) -> AgentState:
    """This node performs subtraction on number1 and number2."""
    if state['operation1'] == '-':
        state['finalNumber1'] = state['number1'] - state['number2']
    return state

def addition2_node(state:AgentState) -> AgentState:
    """This node performs addition on number3 and number4."""
    if state['operation2'] == '+':
        state['finalNumber2'] = state['number3'] + state['number4']
    return state

def subtraction2_node(state:AgentState) -> AgentState:
    """This node performs subtraction on number3 and number4."""
    if state['operation2'] == '-':
        state['finalNumber2'] = state['number3'] - state['number4']
    return state

def router_node1(state:AgentState) -> str:
    """This router routes based on operation1 for number1 and number2."""
    if state['operation1'] == '+':
        return 'addition_operation'
    else:
        return 'subtraction_operation'

def router_node2(state:AgentState) -> str:
    """This router routes based on operation2 for number3 and number4."""
    if state['operation2'] == '+':
        return 'addition2_operation'
    else:
        return 'subtraction2_operation'
    
graph = StateGraph(AgentState)
graph.add_node("add_node", addition_node)
graph.add_node("subtract_node", subtraction_node)
graph.add_node("add_node2", addition2_node)
graph.add_node("subtract_node2", subtraction2_node)
graph.add_node("router_node1", lambda state: state)  # passthrough for router1
graph.add_node("router_node2", lambda state: state)  # passthrough for router2

# Start -> Router1
graph.add_edge(START, "router_node1")

# Router1 conditional edges to operation nodes
graph.add_conditional_edges("router_node1", 
router_node1,                            
{
    "addition_operation": "add_node",
    "subtraction_operation": "subtract_node"
})

# Operation nodes -> Router2
graph.add_edge("add_node", "router_node2")
graph.add_edge("subtract_node", "router_node2")

# Router2 conditional edges to operation nodes
graph.add_conditional_edges("router_node2", 
router_node2,                            
{
    "addition2_operation": "add_node2",
    "subtraction2_operation": "subtract_node2"
})

# Operation nodes -> END
graph.add_edge("add_node2", END)
graph.add_edge("subtract_node2", END)
app = graph.compile()



# Save and open graph image
img_bytes = app.get_graph().draw_mermaid_png()
with open("static/multi_route_graph.png", "wb") as f:
    f.write(img_bytes)
import subprocess
subprocess.run(["open", "static/multi_route_graph.png"])  # macOS: opens in Preview


input_state = AgentState(
    operation1='+',
    operation2='+',
    number1=10,
    number2=5,
    number3=7,
    number4=3)

answer = app.invoke(input_state)
print(f"Result of {input_state['number1']} {input_state['operation1']} {input_state['number2']} is: {answer['finalNumber1']}")
print(f"Result of {input_state['number3']} {input_state['operation2']} {input_state['number4']} is: {answer['finalNumber2']}")