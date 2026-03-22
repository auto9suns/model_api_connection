"""
Examples — model_connector.py
Run: python example.py
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))
from model_connector import LLMConnector, chat


def example_basic():
    llm = LLMConnector()

    print("=== SiliconFlow / deepseek-ai/DeepSeek-V3 ===")
    print(llm.chat("用一句话解释什么是大语言模型", provider="siliconflow", model="deepseek-ai/DeepSeek-V3"))

    print("\n=== OpenAI / gpt-4o ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="openai", model="gpt-4o"))

    print("\n=== Anthropic / claude-sonnet-4-6 ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="anthropic", model="claude-sonnet-4-6"))

    print("\n=== Gemini / gemini-2.0-flash ===")
    print(llm.chat("Explain LLMs in one sentence.", provider="gemini", model="gemini-2.0-flash"))


def example_streaming():
    llm = LLMConnector()

    print("=== Streaming: deepseek-ai/DeepSeek-R1 (with reasoning) ===")
    for chunk in llm.chat("9.9和9.11哪个大？请思考后回答。",
                           provider="siliconflow", model="deepseek-ai/DeepSeek-R1", stream=True):
        print(chunk, end="", flush=True)
    print()

    print("\n=== Streaming: claude-sonnet-4-6 ===")
    for chunk in llm.chat("Write a haiku about Python.",
                           provider="anthropic", model="claude-sonnet-4-6", stream=True):
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
    print("\nTo run examples: example_basic(), example_streaming(), example_multiturn()")
