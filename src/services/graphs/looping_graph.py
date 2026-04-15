from langgraph.graph import StateGraph, START, END
from typing import List, TypedDict, Union
from IPython.display import Image, display
import random

class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed
    name: str
    number: List[int]
    counter: int

def greeting_node(state:AgentState) -> AgentState:
    """This node takes in a name and a number, processes them,
      and updates the state with a greeting message."""
    state['name'] = f"Hi {state['name']}!"
    state['counter'] = 0
    return state

def random_node(state:AgentState) -> AgentState:
    """This node takes in a number and updates the state with a random number."""
    state['number'].append(random.randint(1, 10))
    state['counter'] += 1
    return state

def should_continue(state:AgentState) -> bool:
    """This function checks if the counter is less than 5 to determine if we should continue looping."""
    if state['counter'] < 5:
        print(f"Counter is {state['counter']}, continuing to loop...")
        return "loop"
    else:
        return "exit"
    return state['counter'] < 5

graph = StateGraph(AgentState)
graph.add_node("greeting", greeting_node)
graph.add_node("random", random_node)

graph.add_edge("greeting", "random")
graph.add_conditional_edges("random", should_continue, 
                          {
    "loop": "random",
    "exit": END
})

graph.add_edge(START, "greeting")
# graph.add_edge("random", END)
app = graph.compile()

# Save and open graph image
img_bytes = app.get_graph().draw_mermaid_png()
with open("static/looping_graph.png", "wb") as f:
    f.write(img_bytes)
import subprocess
subprocess.run(["open", "static/looping_graph.png"])  # macOS: opens in Preview

input_state = AgentState(name="Alice", number=[], counter=0)
result = app.invoke(input_state)
print(result)