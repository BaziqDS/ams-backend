from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import patch

from ai_assistant.service import AssistantChatResponse
from ai_assistant.service import InventoryAssistantService


class AssistantChatApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="assistant.user", password="pw")

    def test_chat_endpoint_requires_authentication(self):
        response = self.client.post("/api/ai/chat/", {"message": "hello"}, format="json")
        self.assertIn(response.status_code, {401, 403})

    @patch("ai_assistant.views.InventoryAssistantService")
    def test_chat_endpoint_returns_structured_payload(self, service_cls_mock):
        service_cls_mock.return_value.chat.return_value = AssistantChatResponse(
            mode="openui",
            text="Here is the low inventory summary.",
            openui_code='root = Card([CardHeader("Low Inventory", "2 items need attention")])',
            sql_answer="Two items are below their threshold.",
        )

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/ai/chat/",
            {"message": "What are the low inventory assets?"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["mode"], "openui")
        self.assertEqual(response.data["text"], "Here is the low inventory summary.")
        self.assertIn("Low Inventory", response.data["openui_code"])
        self.assertEqual(response.data["sql_answer"], "Two items are below their threshold.")

    @patch("ai_assistant.views.InventoryAssistantService")
    def test_stream_endpoint_returns_server_sent_events(self, service_cls_mock):
        service = service_cls_mock.return_value
        service.stream_chat_events.return_value = [
            {"type": "status", "message": "Querying the AMS database"},
            {"type": "openui_delta", "delta": 'root = Card([])'},
            {"type": "final", "mode": "openui", "text": "Done", "openui_code": "root = Card([])", "sql_answer": "Done"},
        ]
        service.encode_stream_event.side_effect = InventoryAssistantService.encode_stream_event

        self.client.force_authenticate(user=self.user)
        response = self.client.post(
            "/api/ai/chat/stream/",
            {"message": "What are the low inventory assets?"},
            format="json",
        )

        body = b"".join(response.streaming_content).decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/event-stream")
        self.assertIn('"type": "openui_delta"', body)
        self.assertIn("root = Card", body)

    def test_chat_endpoint_rejects_blank_messages(self):
        self.client.force_authenticate(user=self.user)
        response = self.client.post("/api/ai/chat/", {"message": "   "}, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("message", response.data)


class AssistantServiceFormattingTests(TestCase):
    @patch("ai_assistant.service._import_langchain_dependencies")
    @patch("ai_assistant.service._import_openrouter_model")
    def test_chat_handles_missing_formatter_keys_without_crashing(self, model_import_mock, deps_import_mock):
        class FakeStructuredModel:
            def invoke(self, _messages):
                return {"text": "Inventory is currently empty."}

        class FakeModel:
            def with_structured_output(self, _schema):
                return FakeStructuredModel()

        class FakeSqlAgent:
            def invoke(self, _payload):
                class Message:
                    content = "There are no assets in the system."

                return {"messages": [Message()]}

        class FakeToolkit:
            def __init__(self, db, llm):
                self.db = db
                self.llm = llm

            def get_tools(self):
                return []

        class FakeDatabase:
            dialect = "sqlite"

            @classmethod
            def from_uri(cls, _uri):
                return cls()

        def fake_create_agent(_model, _tools, system_prompt):
            self.assertIn("SQL database", system_prompt)
            return FakeSqlAgent()

        model_import_mock.return_value = FakeModel()
        deps_import_mock.return_value = (fake_create_agent, FakeToolkit, FakeDatabase)

        service = InventoryAssistantService()
        response = service.chat(message="Show me inventory health", history=[])

        self.assertEqual(response.mode, "text")
        self.assertEqual(response.text, "Inventory is currently empty.")
        self.assertIsNone(response.openui_code)
        self.assertEqual(response.sql_answer, "There are no assets in the system.")

    @patch("ai_assistant.service._import_langchain_dependencies")
    @patch("ai_assistant.service._import_openrouter_model")
    def test_stream_chat_events_yields_openui_deltas(self, model_import_mock, deps_import_mock):
        class FakeChunk:
            def __init__(self, content):
                self.content = content

        class FakeModel:
            def stream(self, _messages):
                yield FakeChunk("root = ")
                yield FakeChunk('Card([])')

        class FakeSqlAgent:
            def invoke(self, _payload):
                class Message:
                    content = "Two items are below their threshold."

                return {"messages": [Message()]}

        class FakeToolkit:
            def __init__(self, db, llm):
                self.db = db
                self.llm = llm

            def get_tools(self):
                return []

        class FakeDatabase:
            dialect = "sqlite"

            @classmethod
            def from_uri(cls, _uri):
                return cls()

        def fake_create_agent(_model, _tools, system_prompt):
            self.assertIn("SQL database", system_prompt)
            return FakeSqlAgent()

        model_import_mock.return_value = FakeModel()
        deps_import_mock.return_value = (fake_create_agent, FakeToolkit, FakeDatabase)

        service = InventoryAssistantService()
        events = list(service.stream_chat_events(message="Show low inventory", history=[]))

        self.assertEqual(events[0]["type"], "status")
        self.assertEqual(events[1]["type"], "sql_answer")
        self.assertEqual(events[3]["type"], "openui_delta")
        self.assertEqual(events[4]["type"], "openui_delta")
        self.assertEqual(events[-1]["openui_code"], "root = Card([])")
