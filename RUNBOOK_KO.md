# Horizon 운영 가이드 (한국어 / EXAONE)

이 문서는 이 저장소를 LG EXAONE(`k-exaone_v2.5`)으로 돌리고, GitHub 트렌딩(데일리·위클리·먼슬리)과 허깅페이스 트렌딩 모델 TOP 50을 함께 수집하는 설정을 정리한 것입니다.

## 1. 준비

```bash
cd Horizon
python3 -m venv .venv && source .venv/bin/activate   # 선택
pip install -e .                                     # mcp/playwright/openbb는 선택 의존성
cp .env.example .env                                 # 이미 .env가 있으면 그대로 사용
```

`.env`에 키를 둡니다. `data/config.json`의 `ai.api_key_env`에는 **키 값이 아니라 환경변수 이름**을 넣습니다.

```
EXAONE_API_KEY=sk-...
```

## 2. EXAONE 설정 (`data/config.json`)

EXAONE API는 OpenAI 호환이므로 `provider`는 `openai`로 두고 `base_url`만 바꿉니다.

```json
"ai": {
  "provider": "openai",
  "model": "k-exaone_v2.5",
  "base_url": "https://api.exaone.ai/v1",
  "api_key_env": "EXAONE_API_KEY",
  "temperature": 0.3,
  "max_tokens": 8192,
  "throttle_sec": 1.0,
  "analysis_concurrency": 1,
  "enrichment_concurrency": 1,
  "languages": ["ko"],
  "extra_body": { "reasoning_effort": "low", "top_p": 0.95 }
}
```

알아둘 점:

- **모델은 항상 추론(thinking)을 거칩니다.** 끌 수 없고 `reasoning_effort`(`low`/`high`/`max`)로 강도만 조절합니다. 그래서 `max_tokens`에는 추론 토큰과 답변이 함께 들어갑니다. 작게 잡으면 JSON이 잘리므로 8192 이상을 권합니다.
- **무료 키의 한도는 초당 1회 + 하루 100회입니다.** 동시에 두 건을 보내면 `429 second limit(1)`, 하루 100건을 넘기면 `429 day limit(100), called 100 times today`가 돌아옵니다. 일 한도는 실행 중에 풀리지 않으므로, 그 경우 Horizon이 항목마다 재시도하지 않고 즉시 실행을 멈추고 `AIProviderUnavailableError`로 알립니다. 재시도도 호출 수를 사용하니 한도에 여유를 두세요.
- 그래서 `analysis_concurrency`·`enrichment_concurrency`를 1로, `throttle_sec`를 1.0으로 두었습니다.
- 응답 본문이 `\n\n`으로 시작할 수 있습니다. Horizon의 JSON 파서가 앞뒤 공백을 제거하므로 그대로 동작합니다.
- `extra_body`는 OpenAI SDK의 `extra_body`로 그대로 전달됩니다. `reasoning_effort`를 빼면 기본값 `max`가 적용되어 느려집니다.
- 무료 기간·할당량은 플랫폼 정책에 따라 바뀔 수 있습니다. `GET /v1/models`로 사용 가능한 모델을 확인할 수 있습니다.

## 3. 한국어 출력

- `ai.languages: ["ko"]` — 이 배열의 각 언어마다 요약 아티팩트가 생성됩니다. `["ko", "en"]`처럼 두 개를 두면 두 벌을 만듭니다(호출량 2배).
- 분석 단계의 `reason`/`summary`도 첫 번째 언어로 작성됩니다.
- 데일리 요약 헤더·라벨·날짜 표기는 `src/ai/summarizer.py`의 `LABELS["ko"]`에 있습니다.
- `display.timezone: "Asia/Seoul"` — 요약의 날짜와 각 항목의 시각을 이 시간대로 표시합니다. 수집 시각 자체는 UTC로 저장됩니다.
- 프로필 이름은 각 `profiles/*/profile.json`의 `display_names`에 `"ko"` 값을 두면 한국어로 나옵니다.

## 4. 수집 소스

### GitHub 트렌딩

```json
"github_trending": {
  "enabled": true,
  "periods": ["daily", "weekly", "monthly"],
  "language": null,
  "spoken_language": null,
  "max_items_per_period": 25,
  "category": "github-trending",
  "profile": "trending"
}
```

- 페이지를 직접 파싱합니다(`article.Box-row`). GitHub가 HTML 구조를 바꾸면 `src/scrapers/github_trending.py`의 `parse_page`를 손봐야 합니다.
- 세 기간을 각각 한 번씩 요청하고, 같은 저장소가 여러 기간에 있으면 **한 건으로 합칩니다.** 모든 순위는 `metadata["periods"]`에 남습니다.
- 기간별 실패는 그 기간만 실패로 기록되고 나머지는 정상 수집됩니다.

### 허깅페이스

```json
"huggingface": {
  "enabled": true,
  "limit": 50,
  "sort": "trendingScore",
  "pipeline_tag": null,
  "search": null,
  "category": "hf-trending",
  "profile": "trending"
}
```

`https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=50`을 그대로 사용하므로 API 키가 필요 없습니다.

### 트렌딩 전용 프로필

`profiles/trending/`은 순위형 항목(저장소·모델)을 위한 프로필입니다. `processing.profile_settings.trending.threshold`가 3.0이라 대부분의 트렌딩 항목이 요약에 들어가고, `topic_dedup`은 꺼 두어 서로 다른 저장소가 하나로 합쳐지지 않습니다. 뉴스는 기존 `tech-news` 프로필(기준 7.0)을 그대로 씁니다.

## 5. 하루 호출 예산과 설정 두 가지

호출 수는 대략 **수집 항목 수 × 2**(분석 1 + 요약 아티팩트 1)입니다. 트렌딩 프로필은 도구를 쓰지 않으므로 항목당 2회, 뉴스(`tech-news`)는 배경 조사에 `web_search`를 쓰면 1회 더 듭니다.

| 설정 파일 | 수집 | 예상 호출 | 무료 한도(100/일) |
|---|---|---|---|
| `data/config.json` (요청 그대로) | GH 일·주·월 33 + HF 50 = 83건 | 약 170회 | **초과 — 유료 한도 필요** |
| `data/config.quota.json` (무료용) | GH 일·주 16 + HF 16 = 32건 | 약 65회 | 여유 있음 |

무료 키로 매일 돌릴 때는 두 번째 파일을 씁니다:

```bash
python -m src.main --config data/config.quota.json
```

`data/config.json` 자체를 무료용으로 바꾸려면 `github_trending.periods`를 `["daily", "weekly"]`, `max_items_per_period`를 8, `huggingface.limit`을 16으로 낮추면 됩니다. 하루 한도가 리셋되는 시각은 플랫폼 공지에 없어 확인하지 못했습니다.

## 6. 실행

```bash
python -m src.main                                   # data/config.json (요청 범위 전체)
python -m src.main --config data/config.quota.json   # 무료 한도에 맞춘 실행
python -m src.main --hours 24                        # 수집 구간 강제
python -m src.main --config 다른설정.json --data-dir 다른데이터
```

결과물:

- `data/summaries/YYYY-MM-DD-ko.md` — 한국어 데일리 요약
- `docs/_posts/YYYY-MM-DD-summary-ko.md` — GitHub Pages용 사본
- `data/config.json.bak` — 설정을 저장할 때 생기는 백업

## 7. 부분만 확인하기

전체 파이프라인은 무료 API의 초당 1회 제한 때문에 32건 기준 15~20분, 83건 기준 40분 이상 걸립니다. 소스만 확인할 때는:

```bash
# 수집기 단위 테스트 (네트워크 불필요)
python -m pytest tests/test_github_trending.py tests/test_huggingface.py -q

# 실제 수집만 확인
python - <<'PY'
import asyncio, json, httpx
from datetime import datetime, timezone
from src.models import Config
from src.scrapers.github_trending import GitHubTrendingScraper
from src.scrapers.huggingface import HuggingFaceScraper

cfg = Config.model_validate(json.load(open("data/config.json")))
async def main():
    async with httpx.AsyncClient(timeout=45) as c:
        gh = await GitHubTrendingScraper(cfg.sources.github_trending, c).fetch(datetime.now(timezone.utc))
        hf = await HuggingFaceScraper(cfg.sources.huggingface, c).fetch(datetime.now(timezone.utc))
    print(len(gh.items), "repos /", len(hf.items), "models")
    print(gh.items[0].title)
    print(hf.items[0].title)
asyncio.run(main())
PY
```

## 8. 운영 팁

- 매일 같은 시간에 돌리려면 `.github/workflows/daily-summary.yml.disabled`를 참고하거나 cron을 씁니다. `EXAONE_API_KEY`는 저장소 비밀로 넣습니다.
- 수집 항목이 90건을 넘으면 `digest.max_items`로 요약 분량을 자릅니다(현재 50). 자르기 전에 점수순으로 정렬합니다.
- `data/config.json`과 `.env`는 `.gitignore`에 포함되어 있어 커밋되지 않습니다.
