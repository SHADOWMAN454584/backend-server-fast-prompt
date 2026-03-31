# AI Chatbot Endpoint Integration Guide

This file documents the chatbot endpoints and the exact frontend request format needed to connect the Flutter enquiry screen to the backend.

## 1. Backend Base URL

Use the existing app base URL from `AppConstants.apiBaseUrl`.

Current default in the app:

- `https://backend-server-fast-prompt.onrender.com`

You can override it at runtime:

- `flutter run --dart-define=API_BASE_URL=https://your-server-url`

## 2. Primary Chatbot Endpoints

### POST /api/chatbot

Use this endpoint to send user messages to the AI chatbot.

Full URL:

- `{API_BASE_URL}/api/chatbot`

Headers:

- `Content-Type: application/json`

Request body:

```json
{
  "message": "What's the best time to travel to avoid crowds at CSMT?",
  "conversation_history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi! How can I help you with transit?" }
  ]
}
```

Request body notes:

- `message` is required.
- `conversation_history` is optional but recommended for context-aware chat.

Success response (200):

```json
{
  "response": "Based on typical crowd patterns at CSMT Railway Station...",
  "topic_valid": true,
  "suggested_topics": null
}
```

Frontend usage:

- Read AI reply from `response`.
- Optionally handle `topic_valid` and `suggested_topics` for unsupported-topic UX.

### GET /api/chatbot/topics

Use this endpoint to fetch supported topics the chatbot can answer.

Full URL:

- `{API_BASE_URL}/api/chatbot/topics`

Success response (200):

```json
{
  "supported_topics": [
    {
      "category": "Public Transport",
      "description": "Bus schedules, departures, routes, alerts, and service updates",
      "example_questions": [
        "What are the bus routes from downtown to the airport?",
        "Are there any bus service alerts today?"
      ]
    }
  ]
}
```

## 3. Frontend Mapping for Current Screen

Current enquiry screen file:

- `lib/screens/alerts/alerts_screen.dart`

Current placeholder URL:

- `YOUR_BACKEND_ENDPOINT/chat`

Replace with:

- `${AppConstants.apiBaseUrl}/api/chatbot`

Expected request body from that screen:

```json
{
  "message": "<user input>",
  "conversation_history": []
}
```

Expected response handling:

- Use `data['response']` as assistant message text.

## 4. Minimal Flutter Request Example

```dart
final response = await http.post(
  Uri.parse('${AppConstants.apiBaseUrl}/api/chatbot'),
  headers: {'Content-Type': 'application/json'},
  body: jsonEncode({
    'message': message,
    'conversation_history': conversationHistory,
  }),
);

if (response.statusCode == 200) {
  final data = jsonDecode(response.body);
  final botText = data['response'] ?? 'No response';
}
```

## 5. Recommended Error Handling

- 400: Invalid payload (missing/invalid `message`).
- 404: Route not found (wrong base URL or endpoint path).
- 500: Backend/internal AI error.
- 503: Service temporarily unavailable.

Fallback UX suggestion:

- Show user-friendly message such as: `Chat service is temporarily unavailable. Please try again.`

## 6. Quick Connectivity Checklist

- Base URL is correct and reachable.
- Frontend calls `POST /api/chatbot` (not `/chat`).
- `Content-Type` is `application/json`.
- Request includes `message` string.
- Response parser reads `response` field.
- Optional: send and persist `conversation_history` to improve continuity.

## 7. Optional AI Endpoints (Not Chat)

These are AI-related but not primary chatbot routes:

- `POST /ai/insights`
- `POST /ai/route-advice`
- `POST /ai/smart-route`

Use them for route/crowd intelligence features, while `POST /api/chatbot` remains the conversational endpoint.
