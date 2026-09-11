# Official-price cost estimates

Copilot shows an **estimated USD model cost**, not token counts and not the router's bill. The built-in price snapshot was verified on **2026-09-07** against [OpenAI's official API pricing](https://developers.openai.com/api/docs/pricing). No credentials or paid requests are needed to calculate it. The price date and source appear on hover.

The reference basis is **Standard API list pricing**. Router markups, provider discounts, Fast/Flex/Batch service tiers, regional uplifts and hosted-tool charges are excluded. QGIS tools run locally. Thinking does not add a guessed multiplier: reported output already includes reasoning. Image/PDF inputs are included when the router accounts for them in model input usage. Separate audio, image-generation and other modality price schemes are not supported by this rate card.

## Verified flagship prices

USD per one million units of the specified category:

| Model | Ordinary input | Cached input | Cache writes | Output |
| --- | ---: | ---: | ---: | ---: |
| gpt-6-astra | 10.00 | 1.00 | 12.50 | 50.00 |
| gpt-5.6-sol | 4.00 | 0.40 | 5.00 | 20.00 |
| gpt-5.6-terra | 2.00 | 0.20 | 2.50 | 12.00 |
| gpt-5.6-luna | 0.20 | 0.02 | 0.25 | 1.20 |

The complete supported exact-ID table is in `qgis_ai_copilot/pricing.py`, taken from the official Standard table (and its Codex row). Unknown providers/models, custom aliases, fine-tunes and separate-modality models show **Cost unavailable**, never a guessed equivalent or $0.

For Astra, GPT-5.6 Sol/Terra/Luna, GPT-5.5/Pro and GPT-5.4/Pro, requests with **more than 272,000 input units** use 2× input/cache rates and 1.5× output rates for the full request. Exactly 272,000 stays in the short-context tier. Sources: [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), [Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol), [Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra), [OpenAI changelog](https://developers.openai.com/api/docs/changelog), and the official pricing table above.

## Calculation and uncertainty

For every completed model call, calculate:

`(ordinary × input rate + cached × cache rate + written × write rate + output × output rate) / 1,000,000`

`ordinary = input − cached − written`. Cached reads and separately billed writes are subsets of input, not extra input to count twice. See [Prompt Caching](https://developers.openai.com/api/docs/guides/prompt-caching) and the accounting method in [OpenAI's spending-controller example](https://developers.openai.com/cookbook/articles/per_run_spending_controller_responses_api). That example's invented prices are **not** used.

- Full usable breakdown: `Est. $0.0139` (rounded to four decimals).
- Missing cache details: a minimum/maximum range using possible official category rates, e.g. `Est. $0.0132–$0.0152`. Missing cache counts are never assumed to be zero. Range endpoints round outward.
- Very small nonzero costs: `Est. <$0.0001`.
- Missing/invalid required usage, unknown prices, or stopped/failed requests: `Cost unavailable`. Upstream billing may continue after Stop.

Calculate each HTTP model response separately, then sum; two short-context calls must not be priced as one long-context call. A successful answer with one missing round's usage remains unavailable. Attempts replaced by Retry are not represented as a complete bill across retries.

New answers store bounded numeric per-call counters and a sanitized decimal-string estimate with model, currency, source and recognized pricing date. No raw layer values or credential data are added. Existing small-usage answers can be evaluated against this dated price snapshot on display; this is not reconstruction of a historic invoice. Old large multi-step aggregates with no per-call breakdown remain unavailable.

## Updating the price snapshot

Re-open the official source, verify exact model IDs, cache semantics and context thresholds, then update rates, `PRICE_DATE`, recognized historic revisions (if retained), documentation and tests together. Do not silently strip router suffixes or map a custom model to a similar official name. This alpha does not scrape prices at runtime.
