# SirenBot - Discord music bot

discord.py + yt-dlp + Spotify metadata. Built to actually find the track you asked for.

No Lavalink. The bot's voice client streams Opus directly via ffmpeg, and yt-dlp
handles YouTube extraction (which means we ride the same anti-bot patches that
the wider yt-dlp community lands continuously, instead of waiting on Lavalink
plugin releases).

## Setup

1. **Discord bot**: https://discord.com/developers/applications → New Application → Bot. Copy the token. No privileged gateway intents needed. Under OAuth2 → URL Generator: scopes `bot` + `applications.commands`, permissions `Connect`, `Speak`, `Send Messages`, `Use Slash Commands`. Invite to your server.

2. **Spotify app**: https://developer.spotify.com/dashboard → Create App. Redirect URI doesn't matter (put `http://localhost`). Copy Client ID and Secret.

3. **Get your guild ID**: Discord → User Settings → Advanced → enable Developer Mode. Right-click your server → Copy Server ID. Leave `DISCORD_GUILD_IDS` empty to sync slash commands globally; configured guild IDs sync faster.

4. `cp .env.example .env` and fill it in.

5. `docker compose up -d --build`

6. In Discord: `/play never gonna give you up`

## Logging

Every step prints with a stage tag so you can pinpoint a failure:

    [resolve]            query → Spotify anchor → YT candidates → pick
    [voice guild=N]      gateway connect / move / disconnect
    [stream guild=N]     yt-dlp full extraction → direct stream URL
    [ffmpeg guild=N]     source construction, playback, errors
    [player guild=N]     queue state, now-playing, skip/stop

`LOG_LEVEL=DEBUG docker compose up` for the noisy version.

## YouTube bot wall

If you start seeing "Sign in to confirm you're not a bot" in `[stream]` errors,
export a Netscape `cookies.txt` from a logged-in browser, drop it at
`bot/data/cookies.txt`, and set `YT_COOKIES_FILE=/app/data/cookies.txt` in
`.env`. yt-dlp will use it automatically.

## Steps remaining

- [x] Smart resolver (Spotify-anchored, duration scoring, lyric/sped-up rejection)
- [x] Drop Lavalink - native voice + yt-dlp
- [x] `/queue`, `/pause`, `/resume`
- [x] Auto-leave when channel empty
- [ ] Resolution cache in SQLite
- [x] `/nowplaying` 
- [ ] `/seek` 
- [ ] `/volume`
- [ ] Persistent now-playing embed with buttons
- [ ] Queue persistence across restart
- [ ] Filters: bassboost, nightcore, slowed (ffmpeg `-af`)

## Layout

    bot/                Python bot (Dockerfile, main.py, requirements.txt)
    bot/siren/          SirenBot package (config, resolver, player, commands)
    bot/data/           Mounted into container; drop cookies.txt here if needed
    docker-compose.yml  Orchestration (single service)
    .env.example        Copy to .env and fill in
