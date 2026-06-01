# Yixin API Key Setup

This skill never ships with API keys.

Create:

```text
~/.config/yixin-api/api-keys.json
```

Recommended permissions:

```bash
mkdir -p ~/.config/yixin-api
chmod 700 ~/.config/yixin-api
chmod 600 ~/.config/yixin-api/api-keys.json
```

JSON shape:

```json
{
  "search": "<search-api-key>",
  "fin_db": "<fin-db-api-key>"
}
```

Environment variable alternative:

```bash
export YIXIN_SEARCH_API_KEY="..."
export YIXIN_FIN_DB_API_KEY="..."
```
