import os

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
os.environ["OPENAI_API_KEY"] = "sk-1234"
chat = ChatOpenAI(
    openai_api_base="http://0.0.0.0:4000",
    model="qwen-coder"
)

response = chat.invoke([HumanMessage(content="Generate a blog post")])
print(response.content)