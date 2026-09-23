import time
from ollama import chat

rfp_text = """ 
REQUEST FOR PROPOSAL

Project: Smart Campus Management System
Organization: ABC University

Background:
ABC University is seeking a technology partner to develop a Smart Campus
Management System to improve the management of campus facilities and student
services.

Project Objective:
The objective is to build a centralized web-based platform that allows
students, faculty, and administrators to access campus services through a
single system.

Scope of Work:
The selected vendor must design, develop, test, and deploy the platform.
The system should include:
- Student service requests
- Facility booking
- Complaint management
- Notification system
- Administrator dashboard
- User management

Technical Requirements:
- The application must be web-based.
- The backend must expose REST APIs.
- PostgreSQL should be used as the database.
- The system must support role-based access control.
- The application must support at least 5,000 concurrent users.

Deliverables:
1. Requirements specification
2. UI/UX designs
3. Developed web application
4. REST API documentation
5. Testing report
6. Deployment documentation

Timeline:
The project must be completed within 6 months from the date of contract
signing.

Evaluation Criteria:
Proposals will be evaluated based on:
- Technical approach: 40%
- Relevant experience: 25%
- Cost: 20%
- Project timeline: 15%

Budget:
The maximum project budget is INR 40 lakh.

Important Constraint:
The solution must be deployed within the university's infrastructure.
"""

start_time = time.time()  # start timer

response = chat(
    model="qwen3.5:4b",
    think=False,
    messages=[
        {
            "role": "system",
            "content": """
You are an RFP Executive Summary Agent.

Analyze the provided RFP and produce a concise, factual executive summary.

Use ONLY information explicitly present in the RFP.
Do not invent, assume, or add information.

Include:
- RFP Overview
- Organization
- Project Objective
- Scope of Work
- Key Requirements
- Deliverables
- Timeline
- Technical Requirements
- Evaluation Criteria
- Budget
- Important Constraints
""",
        },
        {
            "role": "user",
            "content": rfp_text,
        },
    ],
)

end_time = time.time()  # end timer
elapsed = end_time - start_time

print(response.message.content)
print(f"\nResponse generated in {elapsed:.2f} seconds")
