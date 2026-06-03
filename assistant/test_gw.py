import asyncio
from services.llm_gateway import LLMGateway

async def main():
    gw = LLMGateway()
    print("Testing LLMGateway classification...")
    res = await gw.classify_intent("turn on the lights in the bedroom")
    print("RESULT:", res)

if __name__ == "__main__":
    asyncio.run(main())
