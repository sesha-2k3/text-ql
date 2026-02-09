"""
PlannerAgent: Analyzes questions and identifies missing information.

Uses Groq's llama-3.3-70b-versatile model to understand user intent,
identify schema gaps, and generate clarifying questions.
"""

import json
import logging
from pathlib import Path
from typing import Any

from groq import Groq

from api.models import PlannerOutput
from config.settings import get_settings
from schema.models import SchemaContext

logger = logging.getLogger(__name__)

# Load system prompt
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "planner.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text() if PROMPT_PATH.exists() else ""


class PlannerAgent:
    """
    Agent responsible for analyzing questions and planning SQL generation.
    
    This agent:
    - Assesses if the schema is sufficient
    - Generates clarifying questions
    - Documents safe assumptions
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """
        Initialize the PlannerAgent.
        
        Args:
            api_key: Groq API key (defaults to settings)
            model: Model name (defaults to settings)
        """
        settings = get_settings()
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.planner_model

        if not self.api_key:
            raise ValueError("Groq API key is required. Set GROQ_API_KEY environment variable.")

        self.client = Groq(api_key=self.api_key)

    def run(
        self,
        question: str,
        schema: SchemaContext | None,
        dialect: str = "postgres",
    ) -> PlannerOutput:
        """
        Analyze the question and schema to produce a plan.
        
        Args:
            question: Natural language question from the user
            schema: Parsed schema context (may be None or empty)
            dialect: SQL dialect (postgres, mysql, sqlite)
            
        Returns:
            PlannerOutput with schema assessment and questions
        """
        # Build the user message
        user_message = self._build_user_message(question, schema, dialect)

        logger.debug(f"PlannerAgent input: {user_message[:500]}...")

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,  # Low temperature for consistent outputs
                max_tokens=1000,
            )

            content = response.choices[0].message.content
            logger.debug(f"PlannerAgent raw response: {content}")

            return self._parse_response(content)

        except Exception as e:
            logger.error(f"PlannerAgent error: {e}")
            # Return a safe default on error
            return PlannerOutput(
                schema_sufficient=False,
                clarifying_questions=["An error occurred during planning. Please try again."],
                assumptions=[],
            )

    def _build_user_message(
        self,
        question: str,
        schema: SchemaContext | None,
        dialect: str,
    ) -> str:
        """Build the user message for the LLM."""
        parts = [
            f"Question: {question}",
            f"Dialect: {dialect}",
            "",
            "Schema:",
        ]

        if schema and not schema.is_empty:
            parts.append(schema.to_prompt_string())
        else:
            parts.append("(No schema provided)")

        return "\n".join(parts)

    def _parse_response(self, content: str | None) -> PlannerOutput:
        """Parse the LLM response into PlannerOutput."""
        if not content:
            return PlannerOutput(
                schema_sufficient=False,
                clarifying_questions=["Failed to get response from planner."],
                assumptions=[],
            )

        # Try to extract JSON from the response
        try:
            # Handle potential markdown code blocks
            cleaned = content.strip()
            if cleaned.startswith("```"):
                # Remove markdown code block
                lines = cleaned.split("\n")
                # Remove first and last lines (``` markers)
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block or not line.startswith("```"):
                        json_lines.append(line)
                cleaned = "\n".join(json_lines)

            data = json.loads(cleaned)

            return PlannerOutput(
                schema_sufficient=data.get("schema_sufficient", False),
                clarifying_questions=data.get("clarifying_questions", []),
                assumptions=data.get("assumptions", []),
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse planner response as JSON: {e}")
            # Try to extract useful information anyway
            return PlannerOutput(
                schema_sufficient=False,
                clarifying_questions=[
                    "Could not parse planning response. Please provide more details."
                ],
                assumptions=[],
            )


def create_planner_agent(
    api_key: str | None = None,
    model: str | None = None,
) -> PlannerAgent:
    """Factory function to create a PlannerAgent."""
    return PlannerAgent(api_key=api_key, model=model)
