import os, sys, unittest, tempfile
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import app as A
class T(unittest.TestCase):
    def setUp(self): self.c = A.app.test_client()
    def cmd(self, t): return self.c.post("/api/ai/command", json={"text": t}).get_json()
    def test_task_and_advance(self):
        self.assertIn("high-priority", self.cmd("Create a high priority task to finish paper tomorrow")["reply"])
        t = self.c.get("/api/tasks").get_json()["data"][0]; self.assertEqual(t["priority"], "HIGH")
        self.assertEqual(self.c.post(f"/api/tasks/{t['id']}/advance").get_json()["status"], "IN_PROGRESS")
    def test_memory(self):
        self.cmd("Remember that I prefer evening workouts"); self.assertEqual(len(self.cmd("search my memory for workouts")["data"]), 1)
        self.assertIn("Forgot 1", self.cmd("Forget that I prefer evening workouts")["reply"])
    def test_approval_workflow_privacy_search(self):
        w = self.c.get("/api/workflows").get_json()["data"][0]; self.assertIn("waiting approval", self.c.post(f"/api/workflows/{w['id']}/run").get_json()["log"][-1])
        a = self.c.get("/api/approvals").get_json()["data"][0]; self.assertEqual(self.c.post(f"/api/approvals/{a['id']}/reject").get_json()["status"], "REJECTED")
        self.assertEqual(self.c.post("/api/settings/privacy", json={"mode": "STRICT"}).get_json()["mode"], "STRICT")
        self.assertEqual(A.redact("a@b.com sk-abcdefghijklmnopqrst"), "[EMAIL] [KEY]"); self.assertTrue(self.c.get("/api/search?q=robotics").get_json()["success"])
    def test_calendar_slots_conflict(self):
        r = self.cmd("Find a free 90 minute slot tomorrow"); self.assertTrue(r["success"] and r["data"])
        e = self.c.get("/api/events").get_json()["data"][0]
        w = self.c.post("/api/events", json={"title": "x", "start": e["start"], "end": e["end"]}).get_json(); self.assertIn("Conflicts", w["warning"])
    def test_llm_provider_and_strict(self):
        os.environ["OPENAI_API_KEY"] = "sk-testtesttesttesttest"; seen = []
        A.post = lambda u, b, h: seen.append(b) or {"choices": [{"message": {"content": "hello from llm"}}]}
        self.c.post("/api/settings/privacy", json={"mode": "GUARDED"}); self.c.post("/api/providers/select", json={"provider": "OpenAI"})
        r = self.cmd("what is robotics? mail me at a@b.com"); self.assertEqual(r["reply"], "hello from llm"); self.assertNotIn("a@b.com", str(seen))
        self.c.post("/api/settings/privacy", json={"mode": "STRICT"}); self.assertIn("No LLM", self.cmd("what is robotics")["reply"])
        self.assertTrue(self.c.post("/api/providers/Claude/test").get_json()["error"].startswith("Claude is not configured"))
        self.assertIn("Liyra", self.c.get("/").get_data(as_text=True)); self.assertEqual(self.c.get("/app").status_code, 200)
if __name__ == "__main__": unittest.main()
