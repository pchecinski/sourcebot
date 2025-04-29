#!/var/lib/sourcebot/env/bin/python
# -*- coding: utf-8 -*-
'''
Main source code / entry point for telegram tiktok bot
'''

# Python standard libraries
import logging
import re

# Third-party libraries
from telegram import Update
from telegram.ext import ApplicationBuilder, CallbackContext, MessageHandler, filters

# Local modules
from config import config
from handlers import tiktok

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

TIKTOK_PATTERN = re.compile(r"(https:\/\/(?:(?:v[mt]\.|www\.)tiktok.com(?:\/t)*\/\w+|www.tiktok.com\/@[\w\.]+\/video\/\w+))")

async def tiktok_message(update: Update, context: CallbackContext.DEFAULT_TYPE):
    '''
    tiktok message handler
    '''
    for match in re.finditer(TIKTOK_PATTERN, update.message.text):
        for result in await tiktok(match=match):
            await context.bot.send_message(reply_to_message_id=update.message.message_id, chat_id=update.effective_chat.id, text=result['content'])

if __name__ == '__main__':
    application = ApplicationBuilder().token(config['telegram']['token']).build()
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), tiktok_message))
    application.run_polling()
