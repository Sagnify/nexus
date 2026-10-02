import unittest
from unittest.mock import AsyncMock, patch

from backend.api import nexus


class TestPermissionResume(unittest.IsolatedAsyncioTestCase):
    async def test_approval_updates_graph_checkpoint_before_resuming(self):
        task_id = "task_permission_resume_test"
        step_id = "step-delete-recycle-bin"
        state = {
            "task_id": task_id,
            "permission_required": True,
            "permission_status": "pending",
            "execution_status": "paused",
        }

        class FakeGraph:
            def __init__(self):
                self.update = None

            async def aupdate_state(self, config, values, as_node=None):
                self.update = (config, values, as_node)
                state.update(values)

        graph = FakeGraph()

        with (
            patch.dict(nexus._task_states, {task_id: state}),
            patch.dict(nexus._task_background_jobs, {}),
            patch.object(nexus, "nexus_graph", graph),
            patch.object(nexus, "run_agent_workflow", new_callable=AsyncMock) as workflow,
            patch.object(nexus.permission_engine, "resolve_permission") as resolve_permission,
        ):
            response = await nexus.submit_permission(
                task_id,
                nexus.PermissionDecision(step_id=step_id, approved=True),
            )

            job = nexus._task_background_jobs[task_id]
            await job

            self.assertEqual(response, {"status": "resumed"})
            self.assertEqual(
                graph.update,
                (
                    {"configurable": {"thread_id": task_id}},
                    {
                        "permission_status": "approved",
                        "permission_required": False,
                        "execution_status": "executing",
                    },
                    "permission_gate",
                ),
            )
            resolve_permission.assert_called_once_with(task_id, step_id, True)
            workflow.assert_awaited_once_with(task_id, state, resume=True)


if __name__ == "__main__":
    unittest.main()