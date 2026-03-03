# Mish Mish

A real-time multiplayer card game built with FastAPI and WebSockets.

## Running locally

```bash
uv run uvicorn main:app --reload
```

## Running tests

```bash
uv run pytest -v
```

## Deployment

```bash
fly deploy --ha=false
```

## Admin API

All admin endpoints require the `x-admin-key` header. The key is stored as the `ADMIN_KEY` fly secret.

### List all active games

```bash
curl https://mishmish-game.fly.dev/admin/games \
  -H "x-admin-key: YOUR_ADMIN_KEY"
```

### Delete a specific game

```bash
curl -X DELETE https://mishmish-game.fly.dev/admin/games/GAME_ID \
  -H "x-admin-key: YOUR_ADMIN_KEY"
```

### Delete all active games

Useful for clearing out test/abandoned games.

```bash
curl -X DELETE https://mishmish-game.fly.dev/admin/games \
  -H "x-admin-key: YOUR_ADMIN_KEY"
```

## Environment variables / secrets

| Variable | Required | Description |
|---|---|---|
| `JWT_SECRET` | Yes | Signs player session tokens |
| `ADMIN_KEY` | Yes | Protects admin API endpoints |
| `TWILIO_ACCOUNT_SID` | No | Enables SMS password reset |
| `TWILIO_AUTH_TOKEN` | No | Enables SMS password reset |
| `TWILIO_FROM_NUMBER` | No | SMS sender number |
| `APP_BASE_URL` | No | Base URL for reset links (e.g. `https://mishmish-game.fly.dev`) |
