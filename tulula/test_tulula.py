import importlib.util, json, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("tulula", Path(__file__).with_name("tulula.py"))
tulula = importlib.util.module_from_spec(spec); spec.loader.exec_module(tulula)


class ParseStream(unittest.TestCase):
    def test_collects_text_call_and_id(self):
        chunks = [{"type": "AssistantPart", "chunkType": "start", "content": "Ear"},
                  {"type": "AssistantPart", "chunkType": "delta", "content": "plugs?"},
                  {"type": "AssistantPart", "chunkType": "final", "content": "Earplugs?"},
                  {"type": "toolCall", "toolCallId": "c1", "toolName": "request_earplugs", "args": {}, "message": "m"},
                  {"type": "addMessage", "id": "msg_1"}]
        r = tulula.parse_stream(chunks)
        self.assertEqual(r["text"], "Earplugs?")
        self.assertEqual(r["id"], "msg_1")
        self.assertEqual([c["name"] for c in r["calls"]], ["request_earplugs"])

    def test_missing_message_id_raises(self):
        with self.assertRaises(tulula.olmo.ApiError):
            tulula.parse_stream([{"type": "AssistantPart", "chunkType": "delta", "content": "x"}])


class ToolFields(unittest.TestCase):
    def test_no_tools_sends_nothing(self):
        self.assertEqual(tulula.tool_fields([]), [])

    def test_result_is_not_sent_to_model(self):
        tools = [{"name": "t", "description": "d", "parameters": {"type": "object"}, "result": "SECRET"}]
        fields = dict(tulula.tool_fields(tools))
        self.assertEqual(fields["enableToolCalling"], "true")
        self.assertNotIn("SECRET", fields["toolDefinitions"])
        self.assertEqual(json.loads(fields["toolDefinitions"])[0]["name"], "t")

    def test_bad_tools_file_names_missing_field(self):
        p = Path(__file__).with_name("_bad_tools.json")
        p.write_text('[{"name": "t"}]')
        try:
            with self.assertRaisesRegex(tulula.olmo.ApiError, "missing"):
                tulula.load_tools(p)
        finally:
            p.unlink()


if __name__ == "__main__":
    unittest.main()
