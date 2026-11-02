import unittest
from unittest import mock

from agentic_sales.models import meta
from agentic_sales.models.anthropic import AnthropicText
from agentic_sales.models.base import Image, Message, ModelError, ModelRequest
from agentic_sales.models.gemini import GeminiText


def req(max_tokens=300, json_mode=False):
    return ModelRequest(system="Be brief.", messages=[Message(role="user", content="hi")], max_tokens=max_tokens, temperature=0.2, json_mode=json_mode)


def answer(text="Hello", finish="stop"):
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}


class MuseSpark(unittest.TestCase):
    def call(self, effort=None, request=None, data=None):
        with mock.patch.object(meta, "post_json", return_value=data or answer()) as post:
            out = meta.MetaText("muse-spark-1.3", api_key="K", effort=effort).complete(request or req())
        return out, post.call_args

    def test_reasoning_effort_is_sent_and_headroom_is_added_to_the_token_limit(self):
        out, call = self.call("low")
        body = call.args[2]
        self.assertEqual((body["reasoning_effort"], body["max_tokens"], body["model"]), ("low", 300 + meta.REASONING_HEADROOM["low"], "muse-spark-1.3"))
        self.assertEqual(call.args[1], {"Authorization": "Bearer K"})
        self.assertEqual((out.text, out.input_tokens, out.output_tokens), ("Hello", 5, 7))

    def test_pictures_travel_with_the_last_user_message_as_data_uris(self):
        request = ModelRequest(system="Describe.", messages=(Message("user", "first"), Message("assistant", "ok"), Message("user", "this one")),
                               images=(Image("image/png", b"\x89PNG-bytes"),), max_tokens=100)
        body = self.call("minimal", request)[1].args[2]
        self.assertEqual(body["messages"][1]["content"], "first")                                   # earlier turns stay plain text
        parts = body["messages"][-1]["content"]
        self.assertEqual(parts[0], {"type": "text", "text": "this one"})
        self.assertEqual(parts[1]["type"], "image_url")
        self.assertEqual(parts[1]["image_url"]["url"], "data:image/png;base64,iVBORy1ieXRlcw==")

    def test_requests_without_pictures_keep_plain_text_content(self):
        self.assertEqual(self.call("low")[1].args[2]["messages"][-1]["content"], "hi")

    def test_providers_that_cannot_read_pictures_refuse_clearly(self):
        request = ModelRequest(system="x", messages=(Message("user", "y"),), images=(Image("image/png", b"p"),))
        for model in (GeminiText(api_key="K"), AnthropicText("claude-x", api_key="K")):
            with self.assertRaisesRegex(ModelError, "not set up to read images"):
                model.complete(request)

    def test_each_effort_level_has_its_own_headroom(self):
        for effort, extra in meta.REASONING_HEADROOM.items():
            self.assertEqual(self.call(effort)[1].args[2]["max_tokens"], 300 + extra)

    def test_json_mode_asks_for_a_json_object(self):
        self.assertEqual(self.call("minimal", req(json_mode=True))[1].args[2]["response_format"], {"type": "json_object"})
        self.assertNotIn("response_format", self.call("minimal")[1].args[2])

    def test_the_effort_defaults_to_low_can_come_from_the_environment_and_must_be_valid(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            self.assertEqual(meta.MetaText(api_key="K").effort, "low")
        with mock.patch.dict("os.environ", {"META_REASONING_EFFORT": "minimal"}):
            self.assertEqual(meta.MetaText(api_key="K").effort, "minimal")
        with self.assertRaises(ModelError):
            meta.MetaText(api_key="K", effort="extreme")

    def test_a_budget_used_up_by_reasoning_gets_one_quick_retry_before_it_is_an_error(self):
        squeezed, fine = answer(text=None, finish="length"), answer("Here is the answer.")
        with mock.patch.object(meta, "post_json", side_effect=[squeezed, fine]) as post:
            out = meta.MetaText("muse-spark-1.3", api_key="K", effort="low").complete(req(max_tokens=300))
        self.assertEqual(out.text, "Here is the answer.")
        first, second = post.call_args_list[0].args[2], post.call_args_list[1].args[2]
        self.assertEqual((first["reasoning_effort"], first["max_tokens"]), ("low", 300 + meta.REASONING_HEADROOM["low"]))
        self.assertEqual((second["reasoning_effort"], second["max_tokens"]), ("minimal", 300 + meta.REASONING_HEADROOM["low"] + meta.RETRY_EXTRA_TOKENS))
        with mock.patch.object(meta, "post_json", side_effect=[squeezed, squeezed]) as post:       # still empty after the retry: a clear error, never an empty reply
            with self.assertRaisesRegex(ModelError, "no content"):
                meta.MetaText("muse-spark-1.3", api_key="K").complete(req())
        self.assertEqual(post.call_count, 2)                                                       # exactly one retry, not a loop

    def test_an_answer_squeezed_out_by_reasoning_is_an_error_not_an_empty_reply(self):
        with self.assertRaisesRegex(ModelError, "no content"):
            self.call("low", data=answer(text=None, finish="length"))
        with self.assertRaisesRegex(ModelError, "no choices"):
            self.call("low", data={"choices": []})


if __name__ == "__main__":
    unittest.main()


class MuseSparkOpen(unittest.TestCase):
    def call(self, **kw):
        with mock.patch.object(meta, "post_json", return_value=answer("Na so")) as post:
            out = meta.OpenWeightsText(api_key="B", **kw).complete(req())
        return out, post.call_args

    def test_it_talks_to_baseten_with_the_hackathon_model_and_sends_no_reasoning_effort(self):
        out, call = self.call()
        self.assertEqual(call.args[0], "https://inference.baseten.co/v1/chat/completions")
        self.assertEqual(call.args[1], {"Authorization": "Bearer B"})
        self.assertEqual(call.args[2]["model"], "meta-models/muse-spark-open-1026")
        self.assertNotIn("reasoning_effort", call.args[2])
        self.assertEqual(out.text, "Na so")

    def test_the_endpoint_can_be_changed_and_a_key_is_required(self):
        self.assertEqual(self.call(base="https://example.test/v1/")[1].args[0], "https://example.test/v1/chat/completions")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ModelError, "BASETEN_API_KEY"):
                meta.OpenWeightsText()

    def test_a_long_input_that_eats_the_budget_is_retried_without_a_reasoning_field(self):
        empty = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
        with mock.patch.object(meta, "post_json", side_effect=[empty, answer("ok")]) as post:
            out = meta.OpenWeightsText(api_key="B").complete(req())
        self.assertEqual(out.text, "ok")
        self.assertNotIn("reasoning_effort", post.call_args.args[2])

    def test_the_runtime_uses_it_only_for_the_tasks_asked_for(self):
        from agentic_sales.server import runtime
        env = {"BASETEN_API_KEY": "B", "META_MODEL_API_KEY": "M", "OPEN_WEIGHTS_TASKS": "conversation, vision"}
        args = ("CONVERSATION_MODEL", "muse-spark-1.3", "CONVERSATION_EFFORT", "low")
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIsInstance(runtime.text_model("conversation", *args), meta.OpenWeightsText)
            self.assertIsInstance(runtime.text_model("vision", "VISION_MODEL", "muse-spark-1.3", "VISION_EFFORT", "minimal"), meta.OpenWeightsText)
            reasoning = runtime.text_model("reasoning", "REASONING_MODEL", "muse-spark-1.3", "REASONING_EFFORT", "low")
            self.assertNotIsInstance(reasoning, meta.OpenWeightsText)
            self.assertEqual(reasoning.name, "muse-spark-1.3")
        with mock.patch.dict("os.environ", {**env, "BASETEN_API_KEY": ""}, clear=True):          # no Baseten key: stay on the Meta Model API
            self.assertNotIsInstance(runtime.text_model("conversation", *args), meta.OpenWeightsText)
