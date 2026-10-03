"""Unit tests for ScheduleParser and calculate_next_run."""
from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

from backend.services.schedule_parser import schedule_parser, calculate_next_run


class TestScheduleParser(unittest.IsolatedAsyncioTestCase):
    def test_parse_reminder_tomorrow(self):
        prompt = "Remind me tomorrow at 6 PM to submit my project."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "reminder")
        self.assertEqual(res.schedule_type, "one_time")
        self.assertIn("submit my project", res.prompt)
        self.assertFalse(res.is_ambiguous)
        self.assertIsNotNone(res.next_run_at)
        self.assertIsNotNone(res.next_run_at.tzinfo)
        self.assertEqual(res.next_run_at.hour, 18)
        self.assertEqual(res.next_run_at.minute, 0)

    def test_parse_automation_daily(self):
        prompt = "Every morning at 9 AM, check my project and tell me if there are any errors."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.schedule_type, "recurring")
        self.assertEqual(res.schedule_definition.get("frequency"), "daily")
        self.assertEqual(res.schedule_definition.get("time"), "09:00")
        self.assertFalse(res.is_ambiguous)
        self.assertIsNotNone(res.next_run_at)
        self.assertEqual(res.next_run_at.hour, 9)
        self.assertEqual(res.next_run_at.minute, 0)

    def test_parse_automation_weekly(self):
        prompt = "Every Monday at 10 AM, generate my weekly report."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.schedule_type, "recurring")
        self.assertEqual(res.schedule_definition.get("frequency"), "weekly")
        self.assertIn("monday", res.schedule_definition.get("days", []))
        self.assertEqual(res.schedule_definition.get("time"), "10:00")
        self.assertFalse(res.is_ambiguous)
        self.assertIsNotNone(res.next_run_at)
        self.assertEqual(res.next_run_at.weekday(), 0)  # Monday
        self.assertEqual(res.next_run_at.hour, 10)
        self.assertEqual(res.next_run_at.minute, 0)

    def test_parse_automation_weekdays(self):
        prompt = "Run this task every weekday at 8:30 AM."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.schedule_type, "recurring")
        self.assertEqual(res.schedule_definition.get("frequency"), "weekdays")
        self.assertEqual(res.schedule_definition.get("time"), "08:30")
        self.assertFalse(res.is_ambiguous)
        self.assertIsNotNone(res.next_run_at)
        self.assertLess(res.next_run_at.weekday(), 5)  # Mon-Fri
        self.assertEqual(res.next_run_at.hour, 8)
        self.assertEqual(res.next_run_at.minute, 30)

    def test_parse_hourly_received_email_brief_as_automation(self):
        res = schedule_parser.parse_quick_rule(
            "Every 1 hour, brief all emails I have received.",
            user_tz="Asia/Kolkata",
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.schedule_type, "recurring")
        self.assertEqual(res.schedule_definition, {"frequency": "interval", "interval_minutes": 60})
        self.assertEqual(res.normalized_intent["action"], "gmail_brief_messages")
        self.assertEqual(res.execution_config["action_type"], "email_brief")
        self.assertEqual(res.execution_config["required_connectors"], ["gmail"])
        self.assertNotIn("every 1 hour", res.prompt.lower())
        self.assertIsNotNone(res.next_run_at)

        shorthand = schedule_parser.parse_quick_rule("Every hour, check my inbox.", user_tz="Asia/Kolkata")
        self.assertIsNotNone(shorthand)
        self.assertEqual(shorthand.schedule_definition, {"frequency": "interval", "interval_minutes": 60})
        self.assertEqual(shorthand.normalized_intent["action"], "gmail_list_messages")

        every_two_days = schedule_parser.parse_quick_rule("Every 2 days, check my inbox.", user_tz="Asia/Kolkata")
        self.assertIsNotNone(every_two_days)
        self.assertEqual(every_two_days.schedule_definition, {"frequency": "interval", "interval_minutes": 2880})

        every_two_weeks = schedule_parser.parse_quick_rule("Every two weeks, brief received emails.", user_tz="Asia/Kolkata")
        self.assertIsNotNone(every_two_weeks)
        self.assertEqual(every_two_weeks.schedule_definition, {"frequency": "interval", "interval_minutes": 20160})

        daily_at_nine = schedule_parser.parse_quick_rule("Every day at 9 AM, check my inbox.", user_tz="Asia/Kolkata")
        self.assertIsNotNone(daily_at_nine)
        self.assertEqual(daily_at_nine.schedule_definition, {"frequency": "daily", "time": "09:00"})

    def test_email_metadata_sends_only_for_explicit_send_action(self):
        task_type, intent, config = schedule_parser._extract_automation_metadata(
            "check my latest emails",
            "check my latest emails",
        )
        self.assertEqual(task_type, "automation")
        self.assertEqual(intent["action"], "gmail_list_messages")
        self.assertEqual(config["action_type"], "email_read")

        task_type, intent, _ = schedule_parser._extract_automation_metadata(
            "send an email to person@example.com",
            "send an email to person@example.com",
        )
        self.assertEqual(task_type, "automation")
        self.assertEqual(intent["action"], "gmail_send_email")

    def test_parse_ambiguous_no_time(self):
        prompt = "Remind me to call John"
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertTrue(res.is_ambiguous)
        self.assertIsNotNone(res.clarification_question)
        self.assertIn("When would you like me to remind you", res.clarification_question)

    def test_parse_ambiguous_tomorrow_no_time(self):
        prompt = "Remind me tomorrow to submit taxes"
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")

        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertTrue(res.is_ambiguous)
        self.assertIsNotNone(res.clarification_question)
        self.assertIn("What time tomorrow", res.clarification_question)

    def test_calculate_next_run_preserves_tz(self):
        tz = "Asia/Kolkata"
        now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=ZoneInfo(tz))
        sched_def = {"frequency": "daily", "time": "15:00"}
        nxt = calculate_next_run("recurring", sched_def, tz, from_time=now)

        self.assertIsNotNone(nxt)
        self.assertEqual(str(nxt.tzinfo), "Asia/Kolkata")
        self.assertEqual(nxt.day, 1)
        self.assertEqual(nxt.hour, 15)
        self.assertEqual(nxt.minute, 0)

        # If time has passed today, next run is tomorrow
        past_def = {"frequency": "daily", "time": "10:00"}
        nxt_past = calculate_next_run("recurring", past_def, tz, from_time=now)
        self.assertIsNotNone(nxt_past)
        self.assertEqual(nxt_past.day, 2)
        self.assertEqual(nxt_past.hour, 10)

    def test_parse_scheduled_birthday_email(self):
        prompt = "Schedule an email to John wishing him happy birthday at 12 AM on October 15."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")
        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.normalized_intent.get("category"), "email")
        self.assertEqual(res.normalized_intent.get("target"), "John")
        self.assertEqual(res.name, "Send birthday email to John")
        self.assertEqual(res.schedule_type, "one_time")
        self.assertEqual(res.schedule_definition.get("frequency"), "once")
        self.assertEqual(res.next_run_at.month, 10)
        self.assertEqual(res.next_run_at.day, 15)
        self.assertEqual(res.next_run_at.hour, 0)
        self.assertEqual(res.next_run_at.minute, 0)

    def test_parse_scheduled_research_report(self):
        prompt = "Schedule a research report on AI agents for tomorrow at 6 PM."
        res = schedule_parser.parse_quick_rule(prompt, user_tz="Asia/Kolkata")
        self.assertIsNotNone(res)
        self.assertTrue(res.is_schedule)
        self.assertEqual(res.task_type, "automation")
        self.assertEqual(res.normalized_intent.get("category"), "research")
        self.assertEqual(res.normalized_intent.get("topic"), "AI agents")
        self.assertEqual(res.name, "Research report on AI agents")
        self.assertEqual(res.schedule_type, "one_time")
        self.assertEqual(res.next_run_at.hour, 18)
        self.assertEqual(res.next_run_at.minute, 0)

    async def test_planner_schedule_fastpath(self):
        from backend.agent.nodes.planner import planner_node
        res = await planner_node({
            "user_input": "Schedule an email to John wishing him happy birthday at 12 AM on October 15.",
            "intent": "schedule"
        })
        self.assertIn("plan", res)
        self.assertEqual(len(res["plan"]), 1)
        step = res["plan"][0]
        self.assertEqual(step["tool"], "schedule_task")
        self.assertEqual(step["args"]["name"], "Send birthday email to John")
        self.assertEqual(step["args"]["schedule_type"], "one_time")


