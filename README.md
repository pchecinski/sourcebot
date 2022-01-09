This is a cool bot, I guess.

Requirements:
- git (obviously...)
- python3-venv
- ffmpeg
- screen
- mongodb 4.4

Installation:
- git clone git@github.com:pchecinski/sourcebot.git
- python3.8 -m venv sourcebot-env

Mongodb:
```
use sourcebot
db.tiktok_db.createIndex( { "tiktok_id": 1 }, { unique: true } )
```