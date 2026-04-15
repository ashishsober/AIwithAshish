import sys

from pathlib import Path
from langgraph.graph import StateGraph, START, END
from typing import List, TypedDict, Union
from IPython.display import Image, display
from langchain_core.messages import HumanMessage, AIMessage
from langchain_openai import ChatOpenAI
from openai import AzureOpenAI
from dotenv import load_dotenv
import os
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from src.openai.azureai_config import DEPLOYMENT, get_azure_client


load_dotenv()

class AgentState(TypedDict): # our state schema for our agent, we can add more fields as needed
    messages: List[HumanMessage]


client = get_azure_client()

def process_node(state: AgentState) -> AgentState:
    """This node takes in a list of messages, processes them with the LLM,
      and updates the state with a response message."""
    # Convert LangChain messages to OpenAI format
    msgList = [
        {"role": "user" if isinstance(msg, HumanMessage) else "assistant", 
         "content": msg.content}
        for msg in state['messages']
    ]
    # print(msgList)
    response = client.chat.completions.create(
                    messages=msgList,
                    max_tokens=4096,
                    temperature=1.0,
                    top_p=1.0,
                    model=DEPLOYMENT,
                )
    state['messages'].append(AIMessage(content=response.choices[0].message.content))
    print(f"AI response: {state['messages'][-1].content}")
    # print(f"CURRENT STATE: {state['messages']}")
    return state



graph = StateGraph(AgentState)
graph.add_node("process", process_node)
graph.add_edge(START, "process")
graph.add_edge("process", END)
app = graph.compile()

# Save and open graph image
# img_bytes = app.get_graph().draw_mermaid_png()
# with open("static/agent_bot_graph.png", "wb") as f:
#     f.write(img_bytes)
# import subprocess
# subprocess.run(["open", "static/agent_bot_graph.png"])  # macO


conversation_history = [] # should be store in database or vector database
user_input = input("Enter a message for the agent: ")
while user_input.lower() != "exit":
    conversation_history.append(HumanMessage(content=user_input))
    result = app.invoke(AgentState(messages=conversation_history))
    conversation_history.append(result['messages'][-1]) #it pints to the last message in the list which is the most recent AI response
    
    user_input = input("Enter a message for the agent (or type 'exit' to quit): ")


with open("logs/logging.txt", "w") as f:
    for msg in conversation_history:
        role = "User" if isinstance(msg, HumanMessage) else "AI"
        f.write(f"{role}: {msg.content}\n")
print("Conversation history saved to logging.txt")