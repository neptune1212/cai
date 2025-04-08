"""Example script demonstrating how to create a custom cybersecurity agent.

This script shows how to:
- Initialize the CAI client
- Create a custom agent with specific tools
- Set up messages for vulnerability analysis
- Run the custom agent with target website
"""

import os
from dotenv import load_dotenv
from cai.types import Agent
from cai.core import CAI
from cai.util import load_prompt_template
from cai.tools.reconnaissance.generic_linux_command import generic_linux_command
from cai.tools.web.search_web import make_google_search
from cai.tools.reconnaissance.exec_code import execute_code
from cai.tools.reconnaissance.shodan import shodan_search, shodan_host_info
from cai.tools.misc.reasoning import think

load_dotenv()

custom_system_prompt = """
You are an advanced cybersecurity agent specialized in vulnerability assessment.
Your primary goal is to help security professionals identify potential security 
issues in web applications and systems.

CAPABILITIES:
- Perform reconnaissance on target systems
- Analyze web applications for common vulnerabilities
- Identify misconfigurations and security weaknesses
- Suggest remediation steps for discovered issues

ETHICAL GUIDELINES:
- Only analyze systems you have explicit permission to test
- Do not attempt to exploit vulnerabilities or cause damage
- Maintain confidentiality of all findings
- Focus on providing educational value and security improvements

METHODOLOGY:
1. Gather information about the target system
2. Identify potential attack vectors
3. Analyze for common vulnerabilities (OWASP Top 10, etc.)
4. Document findings with clear explanations
5. Suggest specific remediation steps

Always explain your reasoning and approach clearly.
"""

# Define functions for the agent
functions = [
    generic_linux_command,
    execute_code,
    think,
    shodan_search,
    shodan_host_info
]

if os.getenv('GOOGLE_SEARCH_API_KEY') and os.getenv('GOOGLE_SEARCH_CX'):
    functions.append(make_google_search)

# Create custom cybersecurity agent
custom_agent = Agent(
    name="CyberSecurity Agent",
    instructions=custom_system_prompt,
    description="""Agent for cybersecurity analysis and vulnerability discovery.
                   Specializes in web security testing and reconnaissance.""",
    model=os.getenv('CAI_MODEL', "qwen2.5:14b"),
    functions=functions,
    parallel_tool_calls=False,
)

# Initialize CAI client
client = CAI()

# Example messages for vulnerability analysis
messages = [{
    "role": "user", 
    "content": """Analyze potential vulnerabilities in this target website: https://example.com
                 Please focus on:
                 1. Web application security issues
                 2. API endpoint vulnerabilities
                 3. Common security misconfigurations
                 Start with basic reconnaissance and proceed methodically."""
}]

# Run the custom agent
response = client.run(
    agent=custom_agent,
    messages=messages
)

print(response)
