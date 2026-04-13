from app.settings import settings
print(f"OpenAI Key: {bool(settings.openai_api_key)}")
print(f"DeepSeek Key: {bool(settings.deepseek_api_key)}")
print(f"Zhipu Key: {bool(settings.zhipu_api_key)}")
print(f"Zhipu Model: {settings.zhipu_builder_model}")
print(f"Has Zhipu Trace: {settings.has_zhipu}")
