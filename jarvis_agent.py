import subprocess
import time


# Path to your .bat file
bat_file = r"edgelaunch.bat"

# Run the batch file as administrator
try:
    process = subprocess.run(["powershell", "Start-Process", bat_file, "-Verb", "runAs"], check=True)

    
    print("Batch file executed successfully. Now running Python code...")

    # Wait a few seconds if needed
    time.sleep(3)

    from browser_use import Agent
    from browser_use.browser.browser import Browser, BrowserConfig
    from langchain_openai import ChatOpenAI
    import asyncio
    import os
    from dotenv import load_dotenv

    load_dotenv('.env', override=True)
    os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')

    # Connect to the already running Edge browser
    config = BrowserConfig(
        cdp_url="http://localhost:9223/json/version"  # Use the specific endpoint
    )

    browser = Browser(config=config)

    async def main():
        agent = Agent(
            task="Go to link- 'https://o365exchange.visualstudio.com/Enterprise%20Cloud/_sprints/taskboard/PACE%20Collab%20-%20Anuj%20N%20Crew/Enterprise%20Cloud/Bi-Weekly-IDC/CY25/CY25-H1/CY25-H1-Q1/Week%2011%20-%2012' On the sprint page, there is an option of New Work Item on top right of page. Click and create new user story-'Build Model for Viva Insights' and save it. Click on the user story you created and then assign name 'Divij Bajaj' on the top assign people tab. Give story points as 3. In the description section write- 'Build model for viva insights which is unstructured logs'. In acceptance criteria write-'Successfully building model and validating with SMEs with precision >=80'. Click on save and close button.",
            llm=ChatOpenAI(model="gpt-4o"),
            browser=browser
        )
        result = await agent.run()
        print(result)

    # Run the async function
    asyncio.run(main())

except subprocess.CalledProcessError as e:
    print(f"Error occurred while executing the batch file: {e}")
