# QR Code Generator Prototype

## System Requirements

Build a dynamic QR code system where:
- Users submit a long URL and get back a short URL token + QR code image
- The QR code encodes a short URL that redirects (302) to the original URL via your server
- Users can modify the target URL after QR code creation
- Users can delete a QR code (soft delete)
- Users can optionally set an expiration timestamp on create or update
- Deleted or expired links return appropriate HTTP status codes
- URL validation: format check, normalization, malicious URL blocking

## Design Questions

Answer these before you start coding:

1. **Static vs Dynamic QR Code:** Why does this system use dynamic QR codes (encode short URL) instead of static (encode original URL directly)? When would you choose static instead?

> 採用 dynamic 的核心理由是「QR 印出後仍能修改 target URL」。
> - Static 直接把長 URL 編進 QR，印的當下就鎖死，無法改 target、無 analytics、無法 expire / delete。
>   - Static 適合：WiFi 密碼 QR、一次性活動票券、或不需 analytics 且不想依賴第三方服務的場景。
> - Dynamic 多一跳 server redirect 換來四件事：
>   - 可改 target、可記錄 scan、可 soft delete / expire、可 A/B test。
>     代價是依賴 server（QR 圖本身不再自包含，server 掛掉 = QR 失效）與多一次 RTT。

2. **Token Generation:** How will you generate short URL tokens? 
   What happens when two different URLs produce the same token?
   How does collision probability change as the number of tokens grows?

> - 用 `SHA-256(url + nonce)` → Base62 → truncate to 7 chars，
>   搭配 collision retry（最多 10 次，每次換 nonce）。
> - Token space = 62^7 ≈ 3.5 trillion
>   依 [Birthday paradox](https://en.wikipedia.org/wiki/Birthday_problem)，
>   當已用 token 數接近 √(62^7) ≈ 1.87 million 時 collision 機率才會明顯上升
> - retry 失敗則 raise `RuntimeError`，由上層 alert / 換策略。
>   加 nonce 讓同 URL 每次得到不同 token，避免「同 URL 共用 token」破壞 analytics 與 access control。
>   沒選 sequential ID（會洩漏總量、易被 enumerate）也沒選 UUID（22+ chars 太長不適合短網址）。
> - 當資料量級到 10 億時，可加長 token 到 8-9 chars，或換成 sharded counter + Base62（trade-off 是可猜測性）。

3. **Redirect Strategy:** Why 302 (temporary) instead of 301 (permanent)? What are the trade-offs for analytics, URL modification, and latency?

> 必須用 302。
> - **301 兩個致命問題**：
>   - 被 browser、CDN、甚至 DNS resolver 永久 cache
>   - 修改 target URL 後 client 仍會去舊網址 → 直接破壞 dynamic 的核心價值
>   - request 不再 hit server → 無法記錄 scan analytics
> - **302 trade-off**：每次回 server 換得 dynamic update + analytics，代價是每次 RTT + server load。
>   - 對短網址產品而言 dynamic update + analytics 是 must-have，這個 trade-off 是必選的。
> - **Latency 緩解**：
>   - in-memory cache (Redis) + edge CDN with short TTL
>   - 本專案用 `redirect_cache: dict[str, str]` 模擬 Redis
>   - update / delete 時主動 invalidate

4. **URL Normalization:** What normalization rules do you need? Why is `http://Example.com/` and `https://example.com` potentially the same URL?

> - **目前 normalize 規則**：
>   1. host 轉小寫（RFC 3986 §6.2.2.1，DNS case-insensitive）
>   2. path 移除 trailing `/`（§6.2.3，root path 的 `/` 可省略）
>   3. scheme 強制 https
> - **為什麼 `http://Example.com/` ≈ `https://example.com`**：
>   - host 大小寫無關 + root 的 `/` 可省略 + 多數 server 自動 http → https
> - **強制 https 是有爭議的 trade-off**：
>   - 某些 site 的 http 與 https 路徑不等價（例：localhost 開發環境、特定企業內網）
>   - 這個決策犧牲少數正確性換取多數安全性
> - **可再加的規則**：
>   - 移除 default port (`:80`, `:443`)
>   - 排序 query parameters
>   - 移除 fragment（`#section` server 看不到）
>   - 選擇性移除 tracking params (`utm_*`)
> - 本系統不做 dedupe（同 URL 不共用 token），所以 normalize 主要為了驗證一致性，不是去重。

5. **Error Semantics:** What should happen when someone scans a deleted link vs a non-existent link? Should the HTTP status codes be different?

> 必須區分。
> - **語意**：
>   - **404 Not Found** — token 從未存在（可能打錯了）
>   - **410 Gone** — token 曾經存在，但已 deleted / expired，請別再 retry
> - **為什麼要分**：
>   - SEO crawler — 410 立刻從 index 移除
>   - UX — 用戶知道是失效不是打錯
>   - Analytics — 可區分無效掃描 vs 過期掃描
> - **本系統刻意的不對稱**：
>   - `/r/{token}` redirect path → deleted / expired 回 **410**（對掃 QR 的 user 說真話）
>   - `/api/qr/{token}` management path → deleted 回 **404**（避免 enumeration attack，不暴露 token 曾存在）
> - **expire vs delete**：目前共用 410，可在 response body 帶 reason 區分（`"reason": "expired"` vs `"deleted"`）。

## Verification

Your prototype should pass all of these:

```bash
# Create a QR code
curl -X POST http://localhost:8000/api/qr/create \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
# → 200, returns {"token": "...", "short_url": "...", "qr_code_url": "...", "original_url": "..."}

# Redirect
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/{token}
# → 302

# Get info
curl http://localhost:8000/api/qr/{token}
# → 200, returns token metadata

# Update target URL
curl -X PATCH http://localhost:8000/api/qr/{token} \
  -H "Content-Type: application/json" \
  -d '{"url": "https://new-url.com"}'
# → 200

# Redirect now goes to new URL
curl -o /dev/null -w "%{redirect_url}" http://localhost:8000/r/{token}
# → https://new-url.com

# Delete
curl -X DELETE http://localhost:8000/api/qr/{token}
# → 200

# Redirect after delete
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/{token}
# → 410

# Non-existent token
curl -o /dev/null -w "%{http_code}" http://localhost:8000/r/INVALID
# → 404

# QR code image
# (create a new one first, then)
curl -o /dev/null -w "%{http_code} %{content_type}" http://localhost:8000/api/qr/{token}/image
# → 200 image/png

# Analytics
curl http://localhost:8000/api/qr/{token}/analytics
# → 200, returns {"token": "...", "total_scans": N, "scans_by_day": [...]}
```

## Suggested Tech Stack

Python + FastAPI recommended, but you may use any language/framework.
