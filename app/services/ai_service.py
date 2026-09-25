import json
import os
import requests
from datetime import date

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"


def _get_settings():
    from app.utils import load_settings
    return load_settings()


def get_provider():
    settings = _get_settings()
    provider = settings.get("ai_provider", "") or os.environ.get("VCMS_AI_PROVIDER", "openrouter")
    provider = provider.strip().lower()
    return "google" if provider == "google" else "openrouter"


def get_api_key():
    return get_google_api_key() if get_provider() == "google" else get_openrouter_api_key()


def get_model():
    return get_google_model() if get_provider() == "google" else get_openrouter_model()


def get_openrouter_api_key():
    settings = _get_settings()
    key = settings.get("openrouter_api_key", "")
    if not key:
        key = os.environ.get("VCMS_OPENROUTER_KEY", "")
    return key


def get_openrouter_model():
    settings = _get_settings()
    model = settings.get("openrouter_model", "")
    if not model:
        model = os.environ.get("VCMS_OPENROUTER_MODEL", "google/gemma-3-1b-it:free")
    return model


def get_google_api_key():
    settings = _get_settings()
    key = settings.get("google_api_key", "")
    if not key:
        key = os.environ.get("VCMS_GOOGLE_KEY", "")
    return key


def get_google_model():
    settings = _get_settings()
    model = settings.get("google_model", "")
    if not model:
        model = os.environ.get("VCMS_GOOGLE_MODEL", DEFAULT_GEMINI_MODEL)
    return model


def get_provider_key(provider):
    return get_google_api_key() if provider == "google" else get_openrouter_api_key()


def get_provider_model(provider):
    return get_google_model() if provider == "google" else get_openrouter_model()


def get_headers(provider=None):
    provider = provider or get_provider()
    if provider == "google":
        return {
            "x-goog-api-key": get_google_api_key(),
            "Content-Type": "application/json",
        }
    return {
        "Authorization": f"Bearer {get_openrouter_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "VCMS Vehicle Compliance",
    }


def check_api_key():
    return bool(get_api_key().strip())


# ---------------------------------------------------------------------------
# Google Gemini request/response helpers
# ---------------------------------------------------------------------------

def _gemini_url(action, model, stream=False):
    url = f"{GEMINI_BASE_URL}/{model}:{action}"
    if stream:
        url += "?alt=sse"
    return url


def _to_gemini_payload(messages, temperature=0.3, max_tokens=None):
    system_parts = []
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            system_parts.append(content)
        elif role == "assistant":
            contents.append({"role": "model", "parts": [{"text": content}]})
        else:
            contents.append({"role": "user", "parts": [{"text": content}]})

    payload = {"contents": contents, "generationConfig": {"temperature": temperature}}
    if max_tokens:
        payload["generationConfig"]["maxOutputTokens"] = max_tokens
    if system_parts:
        payload["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_parts)}]}
    return payload


def _gemini_extract_text(data):
    candidates = data.get("candidates") or [{}]
    parts = candidates[0].get("content", {}).get("parts", []) or []
    text = "".join(p.get("text", "") for p in parts)
    return text.strip() if text else None


def _gemini_error_message(response):
    try:
        err = response.json().get("error", {})
        return err.get("message") or response.text[:200]
    except Exception:
        return response.text[:200] if response.text else "Unknown Google API error"


# ---------------------------------------------------------------------------
# Fleet context builder — full vehicle list for case-insensitive search
# ---------------------------------------------------------------------------

def build_fleet_context(vehicles, today=None):
    today = today or date.today()
    total = len(vehicles)
    expired, expiring_7, expiring_30, valid = 0, 0, 0, 0
    doc_stats = {"PUC": 0, "Fitness": 0, "Permit": 0, "Tax": 0, "Insurance": 0}
    owner_map = {}
    type_map = {}
    district_map = {}

    all_vehicles = []
    for v in vehicles:
        statuses = v.document_statuses()
        worst = v.overall_status()
        if worst == "status-red":
            expired += 1
        elif worst == "status-orange":
            expiring_7 += 1
        elif worst == "status-yellow":
            expiring_30 += 1
        else:
            valid += 1

        for label, info in statuses.items():
            if info["class"] in ("status-red", "status-orange", "status-yellow"):
                doc_stats[label] = doc_stats.get(label, 0) + 1

        owner_map.setdefault(v.owner_name, []).append(v.vehicle_number)
        type_map.setdefault(v.vehicle_type or "Unspecified", []).append(v.vehicle_number)
        if v.district:
            district_map.setdefault(v.district, []).append(v.vehicle_number)

        doc_list = []
        for label, info in statuses.items():
            days = (info["expiry"] - today).days if info["expiry"] else None
            doc_list.append({
                "document": label,
                "expiry": info["expiry"].isoformat() if info["expiry"] else "Not Set",
                "status": info["status"],
                "days_left": days,
            })

        all_vehicles.append({
            "vehicle_number": v.vehicle_number,
            "chassis_number": v.chassis_number,
            "engine_number": v.engine_number or "",
            "owner_name": v.owner_name,
            "mobile_number": v.mobile_number,
            "vehicle_type": v.vehicle_type or "",
            "district": v.district or "",
            "registration_date": v.registration_date.isoformat() if v.registration_date else "",
            "documents": doc_list,
            "insurance_company": v.insurance_company or "",
            "policy_number": v.policy_number or "",
            "remarks": v.remarks or "",
        })

    return {
        "summary": {
            "total_vehicles": total,
            "expired": expired,
            "expiring_within_7_days": expiring_7,
            "expiring_within_30_days": expiring_30,
            "fully_valid": valid,
            "documents_with_issues": doc_stats,
        },
        "owners": {k: len(v) for k, v in owner_map.items()},
        "vehicle_types": {k: len(v) for k, v in type_map.items()},
        "districts": {k: len(v) for k, v in district_map.items()},
        "vehicles": all_vehicles,
    }


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are VCMS AI Assistant — an expert on Indian vehicle compliance management.

Your Role:
- Help fleet managers track vehicle document expiries (PUC, Fitness, Permit, Tax, Insurance)
- Answer questions about specific vehicles, owners, compliance status
- Provide actionable recommendations for renewals

CRITICAL RULES:
1. Vehicle numbers are CASE-INSENSITIVE. When user types "mh12ab1234", match it against "MH12AB1234" in the data. Always do case-insensitive matching.
2. Search by partial matches too — if user types "MH12", show all vehicles starting with MH12.
3. Owner names are also case-insensitive.
4. Always show the full vehicle number in your response (uppercase as stored in data).
5. Use today's date: {today}

Response Format:
- Use markdown tables for multiple vehicles
- Use bullet points for lists
- Bold key info like vehicle numbers, dates, status
- Be concise but complete
- If no match found, say so clearly and suggest what the user might have meant

Fleet Data:
{fleet_context}
"""


# ---------------------------------------------------------------------------
# Chat assistant
# ---------------------------------------------------------------------------

def ask_assistant(user_question, vehicles, history=None):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    today = date.today().isoformat()
    system_msg = SYSTEM_PROMPT.format(fleet_context=context_str, today=today)

    messages = [{"role": "system", "content": system_msg}]

    if history:
        for msg in history[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_question})

    reply = chat_completion(messages)
    return reply or "I couldn't generate a response. Please try again."


def ask_assistant_stream(user_question, vehicles, history=None):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    today = date.today().isoformat()
    system_msg = SYSTEM_PROMPT.format(fleet_context=context_str, today=today)

    messages = [{"role": "system", "content": system_msg}]

    if history:
        for msg in history[-20:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_question})

    return chat_completion_stream(messages)


# ---------------------------------------------------------------------------
# Chat completion
# ---------------------------------------------------------------------------

def chat_completion(messages, model=None):
    if get_provider() == "google":
        return google_chat_completion(messages, model)
    model = model or get_model()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
    }
    r = requests.post(OPENROUTER_URL, json=payload, headers=get_headers(), timeout=120)
    r.raise_for_status()
    data = r.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    return content.strip() if content else None


def chat_completion_stream(messages, model=None):
    if get_provider() == "google":
        yield from google_chat_completion_stream(messages, model)
        return
    model = model or get_model()
    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    r = requests.post(OPENROUTER_URL, json=payload, headers=get_headers(), stream=True, timeout=120)
    r.raise_for_status()
    for line in r.iter_lines():
        if line:
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                chunk = json.loads(data)
                if "choices" in chunk and chunk["choices"]:
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]


# ---------------------------------------------------------------------------
# Google Gemini chat completion
# ---------------------------------------------------------------------------

def google_chat_completion(messages, model=None):
    model = model or get_google_model()
    url = _gemini_url("generateContent", model)
    payload = _to_gemini_payload(messages, temperature=0.3)
    r = requests.post(url, json=payload, headers=get_headers(), timeout=120)
    r.raise_for_status()
    return _gemini_extract_text(r.json())


def google_chat_completion_stream(messages, model=None):
    model = model or get_google_model()
    url = _gemini_url("generateContent", model, stream=True)
    payload = _to_gemini_payload(messages, temperature=0.3)
    r = requests.post(url, json=payload, headers=get_headers(), stream=True, timeout=120)
    r.raise_for_status()
    for line in r.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8")
        if not line.startswith("data: "):
            continue
        data = line[6:]
        if data.strip() == "[DONE]":
            break
        chunk = json.loads(data)
        for candidate in chunk.get("candidates", []) or []:
            for part in candidate.get("content", {}).get("parts", []) or []:
                if "text" in part:
                    yield part["text"]


# ---------------------------------------------------------------------------
# API test
# ---------------------------------------------------------------------------

def test_api_connection(provider=None):
    import time
    provider = provider or get_provider()
    if provider not in ("openrouter", "google"):
        provider = "openrouter"
    api_key = get_provider_key(provider)
    if not api_key:
        return {"ok": False, "error": f"No API key configured for {'Google Gemini' if provider == 'google' else 'OpenRouter'}"}
    model = get_provider_model(provider)

    if provider == "google":
        url = _gemini_url("generateContent", model)
        payload = _to_gemini_payload(
            [{"role": "user", "content": "Say hi in 3 words."}],
            temperature=0.3, max_tokens=20,
        )
        extract = _gemini_extract_text
        error_label = "Google AI Studio"
    else:
        url = OPENROUTER_URL
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Say hi in 3 words."}],
            "temperature": 0.3,
            "max_tokens": 20,
        }
        extract = lambda d: (d.get("choices", [{}])[0].get("message", {}).get("content") or "").strip() or None
        error_label = "OpenRouter"

    start = time.time()
    try:
        r = requests.post(url, json=payload, headers=get_headers(provider), timeout=60)
        elapsed = round(time.time() - start, 1)
        if r.status_code == 200:
            reply = extract(r.json())
            return {"ok": True, "elapsed": elapsed, "model": model, "provider": provider, "reply": reply or "OK"}
        elif r.status_code in (401, 403):
            return {"ok": False, "error": "Invalid API key (401/403 Unauthorized)", "elapsed": elapsed}
        elif r.status_code == 429:
            return {"ok": False, "error": "Rate limited (429). Try again later.", "elapsed": elapsed}
        else:
            detail = _gemini_error_message(r) if provider == "google" else r.text[:200]
            return {"ok": False, "error": f"HTTP {r.status_code}: {detail}", "elapsed": elapsed}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": f"Cannot connect to {error_label}. Check your internet."}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Request timed out (60s)."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_api_connection_debug(provider=None):
    import time
    provider = provider or get_provider()
    if provider not in ("openrouter", "google"):
        provider = "openrouter"
    api_key = get_provider_key(provider)
    if not api_key:
        return {"ok": False, "debug": {"error": f"No API key configured for {'Google Gemini' if provider == 'google' else 'OpenRouter'}"}}

    model = get_provider_model(provider)
    headers = get_headers(provider)
    masked_key = api_key[:12] + "..." + api_key[-4:] if len(api_key) > 16 else "****"

    if provider == "google":
        url = _gemini_url("generateContent", model)
        payload = _to_gemini_payload(
            [{"role": "user", "content": "Say hi in 3 words."}],
            temperature=0.3, max_tokens=20,
        )
        extract = _gemini_extract_text
    else:
        url = OPENROUTER_URL
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Say hi in 3 words."}],
            "temperature": 0.3,
            "max_tokens": 20,
        }
        extract = lambda d: (d.get("choices", [{}])[0].get("message", {}).get("content") or "").strip() or None

    debug = {
        "request": {
            "url": url,
            "method": "POST",
            "auth": f"Bearer {masked_key}" if provider == "openrouter" else f"x-goog-api-key {masked_key}",
            "model": model,
            "provider": provider,
            "body": json.dumps(payload, indent=2),
            "headers": {k: (v if k not in ("Authorization", "x-goog-api-key") else masked_key)
                        for k, v in headers.items()},
        },
        "response": None,
        "timing": {},
    }

    start = time.time()
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        total = round(time.time() - start, 2)

        resp_body = ""
        try:
            resp_body = json.dumps(r.json(), indent=2)
        except Exception:
            resp_body = r.text[:1000]

        debug["response"] = {
            "status_code": r.status_code,
            "status_text": "OK" if r.status_code == 200 else "Error",
            "headers": dict(r.headers),
            "body": resp_body[:2000],
        }
        debug["timing"] = {"total_seconds": total}

        if r.status_code == 200:
            reply = extract(r.json())
            return {"ok": True, "debug": debug, "reply": reply or "OK", "elapsed": total}
        else:
            return {"ok": False, "debug": debug, "elapsed": total}

    except requests.exceptions.ConnectionError:
        debug["timing"]["total_seconds"] = round(time.time() - start, 2)
        host = "generativelanguage.googleapis.com" if provider == "google" else "openrouter.ai"
        debug["response"] = {"error": f"Connection failed — could not reach {host}"}
        return {"ok": False, "debug": debug}
    except requests.exceptions.Timeout:
        debug["timing"]["total_seconds"] = round(time.time() - start, 2)
        debug["response"] = {"error": "Request timed out after 60 seconds"}
        return {"ok": False, "debug": debug}
    except Exception as e:
        debug["timing"]["total_seconds"] = round(time.time() - start, 2)
        debug["response"] = {"error": str(e)}
        return {"ok": False, "debug": debug}


# ---------------------------------------------------------------------------
# Document parser
# ---------------------------------------------------------------------------

PARSE_PROMPT = """Extract vehicle information from the following OCR text of an Indian vehicle document (RC, Insurance, PUC, Fitness certificate, or Tax receipt).

Return a JSON object with these fields (use null for missing fields):
{{
    "vehicle_number": "string",
    "chassis_number": "string",
    "engine_number": "string",
    "owner_name": "string",
    "registration_date": "YYYY-MM-DD or null",
    "puc_expiry": "YYYY-MM-DD or null",
    "fitness_expiry": "YYYY-MM-DD or null",
    "permit_from": "YYYY-MM-DD or null",
    "permit_expiry": "YYYY-MM-DD or null",
    "permit_auth_no": "string or null",
    "permit_address": "string or null",
    "insurance_expiry": "YYYY-MM-DD or null",
    "insurance_company": "string or null",
    "policy_number": "string or null",
    "vehicle_type": "string or null",
    "tax_from": "YYYY-MM-DD or null",
    "tax_expiry": "YYYY-MM-DD or null",
    "tax_mode": "Monthly (M)/Quarterly (Q)/Half-Yearly (HY)/Yearly (Y)/Lifetime (LTT)/null",
    "tax_amount": number or null,
    "document_type": "RC/Insurance/PUC/Fitness/Tax Receipt/Unknown"
}}

Rules:
- Return ONLY the JSON object, no explanation
- Use DD-MM-YYYY or DD/MM/YYYY format dates and convert to YYYY-MM-DD
- Uppercase vehicle and chassis numbers
- If a field is not found, set it to null
- For a tax receipt: tax_from is the tax period start, tax_expiry is the valid-until date, tax_amount is the paid amount as a number, and tax_mode is the closest match from the list above (lifetime tax -> "Lifetime (LTT)")
- For a permit: permit_from is the validity start date, permit_expiry is the valid-until date, permit_auth_no is the permit/authorisation number, and permit_address is the address printed on the permit (holder or issuing authority)

OCR Text:
{ocr_text}
"""


def parse_document_text(ocr_text):
    messages = [
        {"role": "system", "content": "You are a document parser. Return only valid JSON."},
        {"role": "user", "content": PARSE_PROMPT.format(ocr_text=ocr_text)},
    ]
    response = chat_completion(messages)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
    data = json.loads(response)
    # Validate required fields with defaults
    required_fields = {
        "vehicle_number": str,
        "chassis_number": str,
        "engine_number": str,
        "owner_name": str,
        "registration_date": (str, type(None)),
        "puc_expiry": (str, type(None)),
        "fitness_expiry": (str, type(None)),
        "permit_from": (str, type(None)),
        "permit_expiry": (str, type(None)),
        "permit_auth_no": (str, type(None)),
        "permit_address": (str, type(None)),
        "insurance_expiry": (str, type(None)),
        "insurance_company": (str, type(None)),
        "policy_number": (str, type(None)),
        "vehicle_type": (str, type(None)),
        "tax_from": (str, type(None)),
        "tax_expiry": (str, type(None)),
        "tax_mode": (str, type(None)),
        "tax_amount": (int, float, type(None)),
        "document_type": str,
    }
    validated = {}
    for field, expected_type in required_fields.items():
        value = data.get(field)
        if value is None:
            validated[field] = None
        elif isinstance(expected_type, tuple):
            if not isinstance(value, expected_type):
                validated[field] = None
            else:
                validated[field] = value
        elif not isinstance(value, expected_type):
            # Try to coerce
            try:
                validated[field] = expected_type(value)
            except (ValueError, TypeError):
                validated[field] = None
        else:
            validated[field] = value
    # Ensure document_type has a valid value
    if validated["document_type"] not in ("RC", "Insurance", "PUC", "Fitness", "Tax Receipt", "Unknown"):
        validated["document_type"] = "Unknown"
    return validated


# ---------------------------------------------------------------------------
# AI Insights
# ---------------------------------------------------------------------------

INSIGHTS_PROMPT = """Analyze the following vehicle fleet compliance data and provide actionable insights.

Fleet Summary:
{fleet_context}

Provide your analysis in this exact JSON format:
{{
    "risk_summary": "1-2 sentence overall risk assessment",
    "top_issues": ["issue1", "issue2", "issue3"],
    "recommendations": ["recommendation1", "recommendation2", "recommendation3"],
    "vehicle_risks": [
        {{"vehicle": "number", "owner": "name", "risk_level": "high/medium/low", "reason": "why"}}
    ],
    "monthly_outlook": "what to expect in the coming month"
}}

Rules:
- Focus on the most critical compliance gaps
- Prioritize expired documents first, then expiring soon
- Vehicle risks should cover the top 10 most at-risk vehicles
- Be specific with dates and document names
- Return ONLY the JSON object
"""


def generate_insights(vehicles):
    context = build_fleet_context(vehicles)
    context_str = json.dumps(context, indent=2, default=str)
    messages = [
        {"role": "system", "content": "You are a fleet compliance analyst. Return only valid JSON."},
        {"role": "user", "content": INSIGHTS_PROMPT.format(fleet_context=context_str)},
    ]
    response = chat_completion(messages)
    response = response.strip()
    if response.startswith("```"):
        response = response.split("\n", 1)[1]
        if response.endswith("```"):
            response = response[:-3]
        response = response.strip()
    data = json.loads(response)
    # Validate required structure
    validated = {
        "risk_summary": str(data.get("risk_summary", "No risk summary available.")),
        "top_issues": [str(x) for x in (data.get("top_issues") or []) if isinstance(x, str)][:5],
        "recommendations": [str(x) for x in (data.get("recommendations") or []) if isinstance(x, str)][:5],
        "monthly_outlook": str(data.get("monthly_outlook", "Outlook unavailable.")),
    }
    # Validate vehicle_risks
    vehicle_risks = []
    for vr in (data.get("vehicle_risks") or [])[:10]:
        if isinstance(vr, dict):
            vehicle_risks.append({
                "vehicle": str(vr.get("vehicle", "")),
                "owner": str(vr.get("owner", "")),
                "risk_level": vr.get("risk_level") if vr.get("risk_level") in ("high", "medium", "low") else "medium",
                "reason": str(vr.get("reason", "")),
            })
    validated["vehicle_risks"] = vehicle_risks
    return validated
