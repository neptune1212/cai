"""Example script demonstrating usage of the bug bounty agent to analyze website vulnerabilities.

This script shows how to:
- Initialize the CAI client
- Set up messages for vulnerability analysis
- Run the bug bounty agent with target website
"""

from cai.types import Agent
from cai.core import CAI
from cai.agents.bug_bounter import bug_bounter_agent

client = CAI()

# Example messages for bug bounty testing
messages = [{
    "role": "user", 
    "content": """I need you to help me analyze potential vulnerabilities in a target website: https://example.com
                 Focus on:
                 1. Web application security 
                 2. API endpoints
                 3. Common vulnerabilities
                 Please start with reconnaissance and proceed systematically."""
}]

# Run the bug bounty agent to analyze the target website
response = client.run(
    agent=bug_bounter_agent,
    messages=messages
)

print(response)