# Lumina Google Auth Testing

1. Create a MongoDB user with a custom `user_id` and an unexpired `user_sessions` record.
2. Call `GET /api/auth/me` with `Authorization: Bearer <session_token>` and verify the user is returned without MongoDB `_id`.
3. Open the app with a secure `session_token` cookie and verify the workspace loads.
4. Verify the login button redirects using the current browser origin, never a hardcoded redirect URL.
5. Verify a returned `#session_id=` is exchanged server-side and immediately cleared from the URL.
6. Verify logout clears the cookie and the next visit returns to the login screen.