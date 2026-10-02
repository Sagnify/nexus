import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.abspath("."))

import pytest
from backend.agent.nodes.planner import _build_active_connector_priority_plan, _compose_smart_email
from backend.core.permissions import permission_engine

@pytest.mark.asyncio
async def test_email_planning():
    test_queries = [
        'send a mail to swagnikganguly2004@gmail.com "Hey bro, Wassup"',
        'send email to alex@company.com subject Project Update body We have completed phase 1 successfully.',
        'email to sarah@nexus.ai regarding weekly sync',
    ]

    for q in test_queries:
        print("=" * 60)
        print("QUERY:", q)
        plan = await _build_active_connector_priority_plan(q, user_name="Swagnik")
        assert len(plan) > 0, "Plan should not be empty"
        step = plan[0]
        assert step.get("risk_level") == "PRIVILEGED", "Risk level should be PRIVILEGED"
        assert "args" in step
        body = step["args"]["body"]
        assert "[Your Name]" not in body, f"Body should never contain [Your Name]: {body}"
        assert "Swagnik" in body, f"Default logged-in user name should be used: {body}"
        
        # Test permission engine gate
        risk, needs_approval = permission_engine.evaluate_step(step["tool"], step["args"])
        assert needs_approval is True, "Must require human approval before sending"
        assert risk.value == "PRIVILEGED", "Risk level in permission engine must be PRIVILEGED"

    print("\nALL EMAIL PLANNING AND PERMISSION CHECKS PASSED!")


@pytest.mark.asyncio
async def test_sender_name_override():
    # When prompt specifies a different sender name, it should override logged-in user
    override_query = "write a mail to client@firm.com from Charlie regarding project timeline"
    plan = await _build_active_connector_priority_plan(override_query, user_name="Swagnik")
    assert len(plan) > 0
    body = plan[0]["args"]["body"]
    print("\nOVERRIDE BODY:\n", body)
    assert "[Your Name]" not in body, f"Body should never contain [Your Name]: {body}"
    assert "Charlie" in body, f"Explicit sender from prompt 'Charlie' should be used: {body}"

    override_query_2 = "send an email to team@nexus.ai sign off as Alice saying great work on the launch"
    plan_2 = await _build_active_connector_priority_plan(override_query_2, user_name="Swagnik")
    assert len(plan_2) > 0
    body_2 = plan_2[0]["args"]["body"]
    print("\nOVERRIDE 2 BODY:\n", body_2)
    assert "[Your Name]" not in body_2
    assert "Alice" in body_2, f"Explicit sender 'Alice' should be used: {body_2}"

if __name__ == "__main__":
    asyncio.run(test_email_planning())
    asyncio.run(test_sender_name_override())

