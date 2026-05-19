from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from decouple import config
from django.conf import settings
from pydantic import BaseModel, ValidationError

from ai_assistant.prompts import SQL_AGENT_SYSTEM_PROMPT, load_openui_prompt


class AssistantConfigurationError(RuntimeError):
    pass


@dataclass
class AssistantChatResponse:
    mode: str
    text: str
    openui_code: str | None
    sql_answer: str


class AssistantResponseSchema(BaseModel):
    mode: str
    text: str
    openui_code: str | None = None
    sql_answer: str


def build_database_uri() -> str:
    database = settings.DATABASES["default"]
    engine = database["ENGINE"]

    if engine == "django.db.backends.sqlite3":
        db_path = Path(database["NAME"]).resolve().as_posix()
        return f"sqlite:///{db_path}"

    if engine == "django.db.backends.postgresql":
        user = quote_plus(str(database["USER"]))
        password = quote_plus(str(database["PASSWORD"]))
        host = database.get("HOST", "localhost")
        port = database.get("PORT", "5432")
        name = database["NAME"]
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}"

    raise AssistantConfigurationError(f"Unsupported database engine: {engine}")


def _import_langchain_dependencies() -> tuple[Any, Any, Any]:
    try:
        from langchain.agents import create_agent
        from langchain_community.agent_toolkits import SQLDatabaseToolkit
        from langchain_community.utilities import SQLDatabase
    except ImportError as exc:
        raise AssistantConfigurationError(
            "LangChain SQL dependencies are not installed. Install langchain, langchain-community, and langgraph."
        ) from exc

    return create_agent, SQLDatabaseToolkit, SQLDatabase


def _import_openrouter_model() -> Any:
    try:
        from langchain_openrouter import ChatOpenRouter
    except ImportError as exc:
        raise AssistantConfigurationError(
            "OpenRouter LangChain integration is not installed. Install langchain-openrouter."
        ) from exc

    api_key = config("OPENROUTER_API_KEY", default="").strip()
    if not api_key:
        raise AssistantConfigurationError("OPENROUTER_API_KEY is not configured.")

    return ChatOpenRouter(
        model=config("OPENROUTER_MODEL", default="openai/gpt-4.1-mini"),
        temperature=0,
        max_tokens=1800,
        api_key=api_key,
    )


class InventoryAssistantService:
    def __init__(self) -> None:
        self._model = _import_openrouter_model()
        create_agent, toolkit_cls, sql_database_cls = _import_langchain_dependencies()

        database = sql_database_cls.from_uri(build_database_uri())
        toolkit = toolkit_cls(db=database, llm=self._model)
        system_prompt = SQL_AGENT_SYSTEM_PROMPT.format(dialect=database.dialect, top_k=8)

        self._sql_agent = create_agent(
            self._model,
            toolkit.get_tools(),
            system_prompt=system_prompt,
        )
        self._openui_prompt = load_openui_prompt()

    def chat(self, *, message: str, history: list[dict[str, str]] | None = None) -> AssistantChatResponse:
        sql_answer = self.answer_sql_question(message=message, history=history)

        raw_formatted = self._format_response(message=message, sql_answer=sql_answer)
        formatted = self._coerce_formatted_response(raw_formatted, sql_answer)

        if formatted.mode == "openui" and formatted.openui_code:
            return AssistantChatResponse(
                mode=formatted.mode,
                text=formatted.text,
                openui_code=formatted.openui_code,
                sql_answer=formatted.sql_answer,
            )

        return AssistantChatResponse(
            mode="text",
            text=formatted.text or sql_answer,
            openui_code=None,
            sql_answer=sql_answer,
        )

    def answer_sql_question(self, *, message: str, history: list[dict[str, str]] | None = None) -> str:
        conversation = []
        for item in history or []:
            role = item.get("role", "").strip()
            content = item.get("content", "").strip()
            if role in {"user", "assistant"} and content:
                conversation.append({"role": role, "content": content})
        conversation.append({"role": "user", "content": message})

        sql_result = self._sql_agent.invoke({"messages": conversation})
        return self._extract_text_answer(sql_result)

    def stream_openui_response(self, *, message: str, sql_answer: str):
        prompt = (
            "You are rendering a database-backed AMS assistant answer as OpenUI Lang for a narrow side panel.\n"
            "Output OpenUI Lang only. Do not wrap it in markdown fences. Do not explain the code.\n"
            "Use only values from the SQL-backed answer. Never invent asset names, counts, codes, statuses, or locations.\n"
            "Use compact cards, tags, and small tables. Avoid full-screen dashboards or large multi-region layouts.\n"
            "Always assign one final root expression.\n\n"
            f"{self._openui_prompt}"
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    f"User question:\n{message}\n\n"
                    f"SQL-backed answer:\n{sql_answer}\n\n"
                    "Render this as compact OpenUI Lang now."
                ),
            },
        ]

        for chunk in self._model.stream(messages):
            content = getattr(chunk, "content", "")
            if isinstance(content, str) and content:
                yield content
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        yield item["text"]

    def stream_chat_events(self, *, message: str, history: list[dict[str, str]] | None = None):
        yield {"type": "status", "message": "Querying the AMS database"}
        sql_answer = self.answer_sql_question(message=message, history=history)
        yield {"type": "sql_answer", "text": sql_answer, "sql_answer": sql_answer}
        yield {"type": "status", "message": "Rendering OpenUI"}

        openui_code = ""
        for delta in self.stream_openui_response(message=message, sql_answer=sql_answer):
            openui_code += delta
            yield {"type": "openui_delta", "delta": delta}

        yield {
            "type": "final",
            "mode": "openui" if openui_code.strip() else "text",
            "text": sql_answer,
            "openui_code": openui_code.strip() or None,
            "sql_answer": sql_answer,
        }

    @staticmethod
    def encode_stream_event(event: dict[str, Any]) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def _format_response(self, *, message: str, sql_answer: str) -> Any:
        formatter = self._model.with_structured_output(AssistantResponseSchema)
        return formatter.invoke(
            [
                {
                    "role": "system",
                    "content": (
                        "You are preparing assistant responses for a themed asset-management chat side panel.\n"
                        "Return mode='openui' when a compact visual summary helps, such as grouped counts,\n"
                        "rankings, low-inventory summaries, status rollups, or location breakdowns.\n"
                        "Return mode='text' for direct factual answers that are clearer as prose.\n"
                        "The `text` field should always contain a short assistant response.\n"
                        "The `sql_answer` field must preserve the SQL agent's plain-language answer.\n"
                        "Only set `openui_code` when mode='openui'.\n\n"
                        f"{self._openui_prompt}"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"User question:\n{message}\n\n"
                        f"SQL-backed answer:\n{sql_answer}\n\n"
                        "Produce the response envelope now."
                    ),
                },
            ]
        )

    @staticmethod
    def _extract_text_answer(result: Any) -> str:
        messages = result.get("messages", []) if isinstance(result, dict) else []
        for message in reversed(messages):
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.strip()
        raise AssistantConfigurationError("The SQL agent did not return a final answer.")

    @staticmethod
    def _coerce_formatted_response(raw_formatted: Any, sql_answer: str) -> AssistantResponseSchema:
        if isinstance(raw_formatted, AssistantResponseSchema):
            if not raw_formatted.sql_answer:
                raw_formatted.sql_answer = sql_answer
            return raw_formatted

        if isinstance(raw_formatted, dict):
            payload = dict(raw_formatted)
            payload.setdefault("mode", "text")
            payload.setdefault("text", sql_answer)
            payload.setdefault("sql_answer", sql_answer)
            payload.setdefault("openui_code", None)
            try:
                return AssistantResponseSchema.model_validate(payload)
            except ValidationError:
                pass

        return AssistantResponseSchema(
            mode="text",
            text=sql_answer,
            openui_code=None,
            sql_answer=sql_answer,
        )
