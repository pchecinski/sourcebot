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

# Local Configuration

Set variables in `config/main.yml`

Required env variables:
```
discord:
  token:
  role_channel:
  logs_channel:
  sauce_channels;
  money_guilds:

mongodb:
  uri: 
  db: 
```

# Docker Instructions

You must configure the following files for Docker:

- `config/main.yml` 
    - Bot configuration
    - See `config/main.yaml.example`
- `user_conf.d/nginx.conf` 
    - NGINX configuration for GIF/Media conversion hosting 
    - See, rename & copy `nginx.conf.example` into the `user_conf.d` folder
    - Change all instances of `STATIC.EXAMPLE.COM` to your desired hostname
- `nginx-certbot.env` 
    - Let's Encrypt configuration
    - See `nginx-certbot.env.example`
- `nginx/nginx_secrets/cloudflare.ini` 
    - Optional for Cloudflare DNS Let's Encrypt challenge
    - This can be subbed for other DNS API challenges
    - Can also be removed if you want to use default web challenge (godspeed)