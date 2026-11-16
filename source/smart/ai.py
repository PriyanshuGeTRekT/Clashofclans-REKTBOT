# smart/ai.py - one small helper around the Claude API (official `anthropic` SDK).
#
# Used by the vision fallback, the base reader, self-healing (when OCR fails) and plain-language
# goals. The API key comes from the Smart page (SMART_AI_KEY) or, when that is empty, from the usual
# SDK sources (ANTHROPIC_API_KEY, `ant auth login` profile). Calls are capped per hour.
import base64
import json
import time

MODELS = [('claude-opus-5-5', 'Claude Opus 5.5 (best)'),
          ('claude-sonnet-5-5', 'Claude Sonnet 5.5 (cheaper)'),
          ('claude-haiku-5-5', 'Claude Haiku 5.5 (cheapest)')]
DEFAULT_MODEL = 'claude-opus-5-5'
FALLBACK_BETA = 'server-side-fallback-2026-07-01'
_calls = []


def _log(msg):
    print(f'[SMART AI] {msg}')


def _budget_ok(cfg):
    limit = int(cfg.get('SMART_AI_MAX_CALLS_PER_HOUR', 20) or 20)
    now = time.time()
    _calls[:] = [t for t in _calls if now - t < 3600]
    if len(_calls) >= limit:
        _log(f'hourly limit of {limit} calls reached, skipping')
        return False
    _calls.append(now)
    return True


def _client(cfg):
    import anthropic
    key = str(cfg.get('SMART_AI_KEY', '') or '').strip()
    return anthropic.Anthropic(api_key=key) if key else anthropic.Anthropic()


def _image_block(image_bgr):
    import cv2
    ok, buf = cv2.imencode('.png', image_bgr)
    if not ok:
        raise ValueError('could not encode the screenshot')
    return {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                        'data': base64.standard_b64encode(buf.tobytes()).decode('ascii')}}


def ask_json(cfg, prompt, schema, image_bgr=None, system=None, effort='low'):
    """Ask Claude for a JSON object matching `schema`. Returns the dict, or None on any failure."""
    import anthropic
    if not _budget_ok(cfg):
        return None
    content = []
    if image_bgr is not None:
        content.append(_image_block(image_bgr))
    content.append({'type': 'text', 'text': prompt})
    kwargs = dict(
        model=str(cfg.get('SMART_AI_MODEL') or DEFAULT_MODEL),
        max_tokens=16000,
        messages=[{'role': 'user', 'content': content}],
        output_config={'effort': effort, 'format': {'type': 'json_schema', 'schema': schema}},
    )
    if system:
        kwargs['system'] = system
    try:
        client = _client(cfg)
        try:
            # Safety classifiers can decline a request; let the API fall back to another model.
            response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks='default', **kwargs)
        except anthropic.BadRequestError:
            response = client.messages.create(**kwargs)       # model/platform without fallbacks
    except anthropic.AuthenticationError:
        _log('the API key was rejected - check it on the Smart page')
        return None
    except anthropic.RateLimitError:
        _log('rate limited by the API, skipping this call')
        return None
    except anthropic.APIStatusError as e:
        _log(f'API error {e.status_code}: {e.message}')
        return None
    except anthropic.APIConnectionError:
        _log('could not reach the API (network)')
        return None
    except Exception as e:                       # no credentials at all, bad config, ...
        _log(f'{e.__class__.__name__}: {e}')
        return None
    if response.stop_reason == 'refusal':
        _log('the model declined this request')
        return None
    text = next((b.text for b in response.content if b.type == 'text'), '')
    try:
        return json.loads(text)
    except ValueError:
        _log('the answer was not valid JSON')
        return None
