import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.config import Settings
from app.llm import GroqClient, LLMUnavailable
from app.server import App, seed_dataset

Q = "What was revenue in FY2025 and how much did it grow from FY2024?"


class FakeLLM(GroqClient):
    def __init__(self, reply=None, exc=None):
        self.reply, self.exc = reply, exc

    @property
    def available(self):
        return True

    def complete(self, question, context, calc_block):
        if self.exc:
            raise self.exc
        return self.reply


class LlmPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(Settings(data_dir=Path(tempfile.mkdtemp()), groq_api_key=""))
        seed_dataset(cls.app)

    def ask(self, llm):
        self.app.orch.llm = llm
        return self.app.orch.ask(Q)

    def test_valid_llm_answer_used(self):
        r = self.ask(FakeLLM("Revenue rose from 125.0 to 148.2 [1], about 18.56% growth [1]."))
        self.assertEqual((r.mode, r.grounded), ("llm", True))

    def test_hallucinated_number_rejected_and_replaced(self):
        r = self.ask(FakeLLM("Revenue was 999 crore [1]."))
        self.assertEqual(r.mode, "offline")
        self.assertIn("18.56", r.answer)
        self.assertIn("grounding validation", r.notice)

    def test_fabricated_citation_rejected(self):
        self.assertEqual(self.ask(FakeLLM("Revenue grew 18.56% [9].")).mode, "offline")

    def test_quota_exhaustion_falls_back(self):
        r = self.ask(FakeLLM(exc=LLMUnavailable("Groq quota/rate limit reached")))
        self.assertEqual(r.mode, "offline")
        self.assertIn("quota", r.notice)

    def test_groq_client_http_handling(self):
        c = GroqClient(Settings(groq_api_key="k"))
        resp = mock.Mock(status_code=429)
        with mock.patch("app.llm.requests.post", return_value=resp):
            with self.assertRaises(LLMUnavailable):
                c.complete("q", "ctx", "")
        ok = mock.Mock(status_code=200)
        ok.json.return_value = {"choices": [{"message": {"content": " hi [1] "}}]}
        with mock.patch("app.llm.requests.post", return_value=ok) as p:
            self.assertEqual(c.complete("q", "ctx", ""), "hi [1]")
            self.assertEqual(p.call_args.kwargs["json"]["model"], "openai/gpt-oss-120b")
        with self.assertRaises(LLMUnavailable):
            GroqClient(Settings(groq_api_key="")).complete("q", "c", "")


if __name__ == "__main__":
    unittest.main()
