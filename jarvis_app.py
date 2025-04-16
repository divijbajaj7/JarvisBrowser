import streamlit as st
import time
import asyncio
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from browser_use import Agent

# Load environment variables
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Ensure API key is set
if not OPENAI_API_KEY:
    st.error("❌ OpenAI API key not found! Please set it in a .env file.")
    st.stop()

# Streamlit Page Config
st.set_page_config(page_title="JARVIS - Browser Navigation Assistant", layout="wide")

# Function to execute the agent
async def execute_agent(task):
    agent = Agent(
        task=task,
        llm=ChatOpenAI(model="gpt-4o", openai_api_key=OPENAI_API_KEY),
    )
    result = await agent.run()
    return result

# Session State for Execution Steps
if "steps" not in st.session_state:
    st.session_state.steps = []
if "result" not in st.session_state:
    st.session_state.result = None

# UI Components
st.title("🤖 JARVIS - Browser Navigation Assistant")
st.subheader("Type your command below and let JARVIS execute it in the browser!")

# User Input
task = st.text_area("Enter Task", placeholder="Find a two-way flight from New Delhi to Hyderabad on Google Flights...")

if st.button("Execute Task"):
    if task.strip() == "":
        st.warning("Please enter a valid task.")
    else:
        st.session_state.steps = []  # Clear previous steps
        st.session_state.result = None

        # Processing Animation
        with st.spinner("JARVIS is thinking and executing your task..."):
            async def run_agent():
                st.session_state.result = await execute_agent(task)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(run_agent())

        # Display Result
        if st.session_state.result:
            st.success("✅ Task Completed!")
            st.subheader("Result:")
            st.write(st.session_state.result)

# Navigation for Logs Page
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Home", "Execution Steps"])

# Execution Steps Page
if page == "Execution Steps":
    st.title("📝 Execution Steps Log")
    st.write("Here you can see each step JARVIS performed during execution.")

    if st.session_state.result:
        steps_markdown = "\n".join(f"- {step}" for step in st.session_state.steps)
        st.markdown(f"### Execution Steps\n{steps_markdown}")
    else:
        st.warning("No execution steps available. Please run a task first.")
