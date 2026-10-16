import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import openai_service


class OpenAIServiceTests(unittest.TestCase):
    def _client(self, flagged=False, captured=None):
        parsed = openai_service.DesignReview(
            overall_score=80, reliability_score=78, buildability_score=82,
            serviceability_score=76, answer="Test it under load.", summary="Promising.",
            strengths=["Simple"], concerns=["Unknown load"],
            suggestions=["Add a test plan"], missing_information=["Material"],
        )
        return SimpleNamespace(
            moderations=SimpleNamespace(create=lambda **_: SimpleNamespace(
                results=[SimpleNamespace(flagged=flagged)]
            )),
            responses=SimpleNamespace(parse=lambda **kwargs: (
                captured.update(kwargs) if captured is not None else None,
                SimpleNamespace(output_parsed=parsed),
            )[1]),
        )

    def test_returns_validated_structured_review(self):
        with patch.object(openai_service, "_client", return_value=self._client()):
            result = openai_service.review_design(
                title="Intake", description="Roller intake", category="Intake",
                season="Test", team_number="1", focus="Reliability",
                question="What should we test?", safety_identifier="safe-user",
            )
        self.assertEqual(result["overall_score"], 80)

    def test_prompt_defines_anchored_hundred_point_scoring(self):
        captured = {}
        with patch.object(
            openai_service, "_client", return_value=self._client(captured=captured)
        ):
            openai_service.review_design(
                title="Intake", description="Roller intake", category="Intake",
                season="Test", team_number="1", focus="Reliability",
                question="What should we test?",
            )

        prompt = captured["input"][1]["content"][0]["text"]
        self.assertIn("90-100: exceptional", prompt)
        self.assertIn("50-69: plausible but uncertain", prompt)
        self.assertIn("Missing information is uncertainty, not proof of a defect", prompt)
        self.assertIn("overall score to their arithmetic mean", prompt)

    def test_rejects_flagged_input_before_review(self):
        with patch.object(openai_service, "_client", return_value=self._client(True)):
            with self.assertRaises(openai_service.ModerationRejected):
                openai_service.review_design(
                    title="Intake", description="Description", category="Intake",
                    season="Test", team_number="1", focus="Reliability",
                    question="Review it",
                )

    def test_public_content_rejects_common_profanity_without_api_call(self):
        with patch.object(openai_service, "_client") as client:
            with self.assertRaises(openai_service.ModerationRejected):
                openai_service.moderate_public_content(
                    texts=["This is fucking inappropriate."], use_api=True
                )
        client.assert_not_called()

    def test_public_content_sends_text_and_image_to_moderation(self):
        captured = {}
        client = self._client(captured=captured)

        def capture_moderation(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(results=[SimpleNamespace(flagged=False)])

        client.moderations.create = capture_moderation
        with (
            patch.object(openai_service, "is_configured", return_value=True),
            patch.object(openai_service, "_client", return_value=client),
        ):
            openai_service.moderate_public_content(
                texts=["A safe robot"], image_bytes=[b"jpeg"], use_api=True
            )

        self.assertEqual(captured["model"], "omni-moderation-latest")
        self.assertEqual(captured["input"][0]["type"], "text")
        self.assertTrue(
            captured["input"][1]["image_url"]["url"].startswith(
                "data:image/jpeg;base64,"
            )
        )

    def test_public_content_fails_closed_when_moderation_is_unavailable(self):
        with patch.object(openai_service, "_client", side_effect=RuntimeError("offline")):
            with self.assertRaises(openai_service.ModerationUnavailable):
                openai_service.moderate_public_content(
                    texts=["A safe robot"], use_api=True
                )


if __name__ == "__main__":
    unittest.main()
