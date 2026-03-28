"""
Examples — model_connector.py (powered by litellm)
Run: python example.py
"""

import json
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from model_connector import LLMConnector, chat, strip_think_stream


def example_basic():
    llm = LLMConnector()

    print("=== SiliconFlow / deepseek-v3 ===")
    print(llm.chat("用一句话解释什么是大语言模型", provider="siliconflow", model="deepseek-v3"))

    print("\n=== OpenAI / gpt-4o ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="openai", model="gpt-4o"))

    print("\n=== Anthropic / sonnet-4.6 ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="anthropic", model="sonnet-4.6"))

    print("\n=== Poe / Claude-Sonnet-4.5 ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="poe", model="Claude-Sonnet-4.5"))


def example_streaming():
    llm = LLMConnector()

    print("=== Streaming: deepseek-r1 (with reasoning, stripped) ===")
    stream = llm.chat("9.9和9.11哪个大？", provider="siliconflow", model="deepseek-r1", stream=True)
    for chunk in strip_think_stream(stream):
        print(chunk, end="", flush=True)
    print()

    print("\n=== Streaming: sonnet-4.6 ===")
    for chunk in llm.chat("Write a haiku about Python.",
                           provider="anthropic", model="sonnet-4.6", stream=True):
        print(chunk, end="", flush=True)
    print()


def example_multiturn():
    llm = LLMConnector()
    messages = [
        {"role": "system", "content": "你是一个简洁的助手，回答不超过两句话。"},
        {"role": "user", "content": "我叫小明，我喜欢编程。"},
        {"role": "assistant", "content": "你好，小明！编程是一项很棒的技能。"},
        {"role": "user", "content": "我叫什么名字？我喜欢什么？"},
    ]
    print("=== Multi-turn: gpt-4o ===")
    print(llm.chat(messages, provider="openai", model="gpt-4o"))


def example_tool_use():
    llm = LLMConnector()

    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气信息",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"},
                    },
                    "required": ["city"],
                },
            },
        }
    ]

    print("=== Tool Use: gpt-4o ===")
    response = llm.chat("北京今天天气怎么样？", provider="openai", tools=tools)
    print(f"Model response: {response}")
    print("(In a real app, you would parse tool_calls from the response object)")


def example_list_models():
    llm = LLMConnector()
    for provider in llm.list_providers():
        default = llm.default_model(provider)
        print(f"\n[{provider}]  default: {default}")
        for m in llm.list_models(provider):
            marker = " *" if m == default else ""
            print(f"  {m}{marker}")


if __name__ == "__main__":
    print("Configured models:\n")
    example_list_models()
    print("\nAvailable examples:")
    print("  example_basic()      — basic chat with multiple providers")
    print("  example_streaming()  — streaming with think-tag stripping")
    print("  example_multiturn()  — multi-turn conversation")
    print("  example_tool_use()   — function calling / tool use")
