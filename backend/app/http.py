import httpx

# Shared client; closed in main.py's lifespan
client = httpx.AsyncClient(timeout=10)
