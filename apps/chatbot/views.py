import json

from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from .engine import answer
from .models import ChatMessage

RATE_LIMIT = 30  # messages per minute per session


@require_POST
def message(request):
    try:
        payload = json.loads(request.body or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)
    text = str(payload.get("message", "")).strip()[:500]
    if not text:
        return JsonResponse({"error": "empty"}, status=400)
    if not request.session.session_key:
        request.session.save()
    sk = request.session.session_key
    key = f"chat-rate:{sk}"
    if cache.get(key, 0) >= RATE_LIMIT:
        return JsonResponse({"reply": "Bạn gửi hơi nhanh, đợi mình một chút nhé!", "products": [], "quick_replies": [], "links": []})
    cache.set(key, cache.get(key, 0) + 1, 60)

    user = request.user if request.user.is_authenticated else None
    result = answer(text, request)
    ChatMessage.objects.create(session_key=sk, user=user, role="user", text=text, intent=result["intent"])
    ChatMessage.objects.create(session_key=sk, user=user, role="bot", text=result["reply"], intent=result["intent"])
    return JsonResponse(result)
