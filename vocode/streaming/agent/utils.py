import re
from typing import Dict, Any, AsyncGenerator, AsyncIterable, Callable, List, Optional, Union

from openai.openai_object import OpenAIObject
from vocode.streaming.models.actions import FunctionCall, FunctionFragment
from vocode.streaming.models.events import Sender
from vocode.streaming.models.transcript import (
    ActionFinish,
    ActionStart,
    Message,
    Transcript,
)

SENTENCE_ENDINGS = [".", "!", "?", "\n"]


async def collate_response_async(
    gen: AsyncIterable[Union[str, FunctionFragment]],
    sentence_endings: List[str] = SENTENCE_ENDINGS,
    get_functions = False
) -> AsyncGenerator:
    sentence_endings_pattern = "|".join(map(re.escape, sentence_endings))
    list_item_ending_pattern = r"\n"
    buffer = ""
    function_buffer = ""
    prev_ends_with_money = False
    async for token in gen:
        if not token:
            continue
        if isinstance(token, str):
            if prev_ends_with_money and token.startswith(" "):
                yield buffer.strip()
                buffer = ""

            buffer += token
            possible_list_item = bool(re.match(r"^\d+[ .]", buffer))
            ends_with_money = bool(re.findall(r"\$\d+.$", buffer))
            if re.findall(
                list_item_ending_pattern
                if possible_list_item
                else sentence_endings_pattern,
                token,
            ):
                if not ends_with_money:
                    to_return = buffer.strip()
                    if to_return:
                        yield to_return
                    buffer = ""
            prev_ends_with_money = ends_with_money
        elif isinstance(token, FunctionFragment):
            function_buffer += token.text
    to_return = buffer.strip()
    if to_return:
        yield to_return
    if function_buffer and get_functions:
        yield FunctionCall(text=function_buffer)


def find_last_punctuation(buffer: str) -> Optional[int]:
    indices = [buffer.rfind(ending) for ending in SENTENCE_ENDINGS]
    if not indices:
        return None
    return max(indices)


def get_sentence_from_buffer(buffer: str):
    last_punctuation = find_last_punctuation(buffer)
    if last_punctuation:
        return buffer[: last_punctuation + 1], buffer[last_punctuation + 1 :]
    else:
        return None, None


def format_openai_chat_messages_from_transcript(
    transcript: Transcript, prompt_preamble: Optional[str] = None
) -> List[dict]:
    chat_messages: List[Dict[str, Optional[Any]]] = (
        [{"role": "system", "content": prompt_preamble}] if prompt_preamble else []
    )
    for event_log in transcript.event_logs:
        if isinstance(event_log, Message):
            chat_messages.append(
                {
                    "role": "assistant" if event_log.sender == Sender.BOT else "user",
                    "content": event_log.text,
                }
            )
        elif isinstance(event_log, ActionStart):
            chat_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": event_log.action_type,
                        "arguments": event_log.action_input.params.json(),
                    },
                }
            )
        elif isinstance(event_log, ActionFinish):
            chat_messages.append(
                {
                    "role": "function",
                    "name": event_log.action_type,
                    "content": event_log.action_output.response.json(),
                }
            )
    return chat_messages
