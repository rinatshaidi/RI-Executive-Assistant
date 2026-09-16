import unittest

from planner import plan_tasks, relocation_options


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.events = [
            {"id": "meeting", "title": "Meeting", "start": "2026-09-17T10:00:00+03:00", "end": "2026-09-17T11:00:00+03:00"},
            {"id": "registry", "title": "Registry", "start": "2026-09-17T15:00:00+03:00", "end": "2026-09-17T15:30:00+03:00"},
        ]

    def test_tasks_fill_only_free_time(self):
        result = plan_tasks({
            "windowStart": "2026-09-17T09:00:00+03:00",
            "windowEnd": "2026-09-17T16:00:00+03:00",
            "calendarEvents": self.events,
            "tasks": [
                {"title": "Call", "durationMinutes": 30},
                {"title": "Documents", "durationMinutes": 60},
            ],
        })
        self.assertEqual([item["title"] for item in result["proposedEvents"]], ["Call", "Documents"])
        self.assertEqual(result["proposedEvents"][0]["start"], "2026-09-17T09:00:00+03:00")
        self.assertEqual(result["proposedEvents"][1]["start"], "2026-09-17T11:00:00+03:00")

    def test_relocation_excludes_target_event(self):
        result = relocation_options({
            "windowStart": "2026-09-17T09:00:00+03:00",
            "windowEnd": "2026-09-17T17:00:00+03:00",
            "travelBufferMinutes": 0,
            "calendarEvents": self.events,
            "targetEvent": {"id": "meeting", "durationMinutes": 60},
        })
        self.assertEqual(result["options"][0]["start"], "2026-09-17T09:00:00+03:00")


if __name__ == "__main__":
    unittest.main()
