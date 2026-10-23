"""Offline tests never load local credentials or write personal application state."""
import os
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
os.environ['ANTHROPIC_API_KEY'] = 'test-only-key'
os.environ['TELEGRAM_BOT_TOKEN'] = ''
os.environ['TELEGRAM_CHAT_ID'] = ''
