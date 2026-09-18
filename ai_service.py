import json
import os
import requests
from datetime import date, timedelta

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _get_settings():
    from utils import load_settings
    return load_settings()


def get_api_key():
    settings = _get_settings()
    key = settings.get("openrouter_api_key", "")
    if not key:
        key = os.environ.get("VCMS_OPENROUTER_KEY", "")
    return key


def get_model():
    settings = _get_settings()
    model = settings.get("openrouter_model", "")
    if not model:
        model = os.environ.get("VCMS_OPENROUTER_MODEL", "google/gemma-3-1b-it:free")
    return model


def get_headers():
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
        "X-Title": "VCMS Vehicle Compliance",
    }


def check_api_key():
    return bool(get_api_key().strip())


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
# API test
# ---------------------------------------------------------------------------

def test_api_connection():
    import time
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "error": "No API key configured"}
    model = get_model()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in 3 words."}],
        "temperature": 0.3,
        "max_tokens": 20,
    }
    start = time.time()
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=get_headers(), timeout=60)
        elapsed = round(time.time() - start, 1)
        if r.status_code == 200:
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            reply = content.strip() if content else str(data)[:200]
            return {"ok": True, "elapsed": elapsed, "model": model, "reply": reply}
        elif r.status_code == 401:
            return {"ok": False, "error": "Invalid API key (401 Unauthorized)", "elapsed": elapsed}
        elif r.status_code == 429:
            return {"ok": False, "error": "Rate limited (429). Try again later.", "elapsed": elapsed}
        else:
            return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": elapsed}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "Cannot connect to OpenRouter. Check your internet."}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "Request timed out (60s)."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def test_api_connection_debug():
    import time
    api_key = get_api_key()
    if not api_key:
        return {"ok": False, "debug": {"error": "No API key configured"}}

    model = get_model()
    headers = get_headers()
    masked_key = api_key[:12] + "..." + api_key[-4:] if len(api_key) > 16 else "****"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in 3 words."}],
        "temperature": 0.3,
        "max_tokens": 20,
    }

    debug = {
        "request": {
            "url": OPENROUTER_URL,
            "method": "POST",
            "auth": f"Bearer {masked_key}",
            "model": model,
            "body": json.dumps(payload, indent=2),
            "headers": {k: (v if k != "Authorization" else f"Bearer {masked_key}") for k, v in headers.items()},
        },
        "response": None,
        "timing": {},
    }

    start = time.time()
    try:
        r = requests.post(OPENROUTER_URL, json=payload, headers=headers, timeout=60)
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
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content")
            reply = content.strip() if content else str(data)[:200]
            return {"ok": True, "debug": debug, "reply": reply, "elapsed": total}
        else:
            return {"ok": False, "debug": debug, "elapsed": total}

    except requests.exceptions.ConnectionError:
        debug["timing"]["total_seconds"] = round(time.time() - start, 2)
        debug["response"] = {"error": "Connection failed — could not reach openrouter.ai"}
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
# Document comparison — field-by-field diff against existing vehicle
# ---------------------------------------------------------------------------

COMPARE_FIELDS = [
    ("engine_number", "Engine Number", "text"),
    ("owner_name", "Owner Name", "text"),
    ("address", "Address", "text"),
    ("mobile_number", "Mobile Number", "text"),
    ("vehicle_type", "Vehicle Type", "text"),
    ("registration_date", "Registration Date", "date"),
    ("puc_expiry", "PUC Expiry", "date"),
    ("fitness_expiry", "Fitness Expiry", "date"),
    ("permit_expiry", "Permit Expiry", "date"),
    ("national_permit_number", "NP Auth No", "text"),
    ("insurance_expiry", "Insurance Expiry", "date"),
    ("insurance_company", "Insurance Company", "text"),
    ("policy_number", "Policy Number", "text"),
]


def compare_vehicle_data(scanned, vehicle):
    """Compare scanned data against an existing vehicle record.

    Returns a list of dicts:
        {field, label, type, existing_value, scanned_value, status}
    status is one of: "empty" (DB is blank, fill from scan),
                       "changed" (both have values that differ),
                       "same" (values match)
    """
    from utils import parse_date

    results = []
    for field, label, ftype in COMPARE_FIELDS:
        scanned_val = scanned.get(field)
        existing_val = getattr(vehicle, field, None)

        # Normalize scanned value
        if ftype == "date":
            if scanned_val:
                from datetime import date as _date
                if isinstance(scanned_val, _date):
                    parsed_scan = scanned_val
                else:
                    parsed_scan = parse_date(str(scanned_val))
            else:
                parsed_scan = None
            db_val = existing_val
        else:
            parsed_scan = str(scanned_val).strip() if scanned_val else ""
            db_val = str(existing_val).strip() if existing_val else ""

        # Determine status
        if not db_val:
            status = "empty"
        elif parsed_scan and str(parsed_scan) != str(db_val):
            status = "changed"
        else:
            status = "same"

        results.append({
            "field": field,
            "label": label,
            "type": ftype,
            "existing_value": db_val if db_val else "—",
            "scanned_value": parsed_scan if parsed_scan else "—",
            "status": status,
        })

    return results


# ---------------------------------------------------------------------------
# Document parser
# ---------------------------------------------------------------------------

PARSE_PROMPT = """Extract vehicle information from the following OCR text of an Indian vehicle document (RC, Insurance, PUC, or Fitness certificate).

Return a JSON object with these fields (use null for missing fields):
{{
    "vehicle_number": "string",
    "chassis_number": "string",
    "engine_number": "string",
    "owner_name": "string",
    "address": "string or null",
    "registration_date": "YYYY-MM-DD or null",
    "puc_expiry": "YYYY-MM-DD or null",
    "fitness_expiry": "YYYY-MM-DD or null",
    "permit_expiry": "YYYY-MM-DD or null",
    "national_permit_number": "string or null (NP Auth No / National Permit Auth Number)",
    "insurance_expiry": "YYYY-MM-DD or null",
    "insurance_company": "string or null",
    "policy_number": "string or null",
    "vehicle_type": "string or null",
    "document_type": "RC/Insurance/PUC/Fitness/Unknown"
}}

Rules:
- Return ONLY the JSON object, no explanation
- Use DD-MM-YYYY or DD/MM/YYYY format dates and convert to YYYY-MM-DD
- Uppercase vehicle and chassis numbers
- If a field is not found, set it to null
- "NP Auth No", "National Permit Auth No", "NP Authorization" all map to national_permit_number
- Address may appear as a block of text with house number, street, city, pin code — combine into one string

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
    return json.loads(response)


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
    return json.loads(response)
