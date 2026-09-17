"""Function declaration schema for Gemini discovery agent.

Defines the discrete, structured tool declarations passed to Gemini.
"""

from __future__ import annotations
from typing import Any
from google.genai import types

# Tool definitions using Google GenAI SDK types
DISCOVERY_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="click",
                description="Click an interactive UI element identified by its accessibility role and accessible name.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "role": types.Schema(
                            type=types.Type.STRING,
                            description="The accessibility role, e.g. 'button', 'link', 'textbox'.",
                        ),
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="The accessible name or visible text of the element, e.g. 'Login', 'Add to cart'.",
                        ),
                    },
                    required=["role", "name"],
                ),
            ),
            types.FunctionDeclaration(
                name="type",
                description="Type text into an input field identified by its accessibility role and accessible name.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "role": types.Schema(
                            type=types.Type.STRING,
                            description="The accessibility role, typically 'textbox'.",
                        ),
                        "name": types.Schema(
                            type=types.Type.STRING,
                            description="The accessible name or placeholder/label of the textbox, e.g. 'Username', 'Password'.",
                        ),
                        "text": types.Schema(
                            type=types.Type.STRING,
                            description="The exact text to type into the field.",
                        ),
                    },
                    required=["role", "name", "text"],
                ),
            ),
            types.FunctionDeclaration(
                name="navigate",
                description="Navigate the browser to an absolute URL.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "url": types.Schema(
                            type=types.Type.STRING,
                            description="The destination URL (must be in the allowlist).",
                        ),
                    },
                    required=["url"],
                ),
            ),
            types.FunctionDeclaration(
                name="finish",
                description="Call this when the goal has been successfully reached or determined impossible.",
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "success": types.Schema(
                            type=types.Type.BOOLEAN,
                            description="True if the goal was accomplished; False if blocked/impossible.",
                        ),
                        "reason": types.Schema(
                            type=types.Type.STRING,
                            description="Detailed explanation of the outcome or checkpoint reached.",
                        ),
                    },
                    required=["success", "reason"],
                ),
            ),
        ]
    )
]
