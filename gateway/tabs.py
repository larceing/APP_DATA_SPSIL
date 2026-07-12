import time

TAB_TTL_SECONDS = 15  # algo más del doble del latido de base.html (5s), tolera algún corte breve

# {user_id: {'tab_id': str, 'last_seen': float}} — memoria de un solo
# proceso, igual que CONNECTED_NODES/PENDING_REQUESTS (ver README,
# limitaciones conocidas: InMemoryChannelLayer exige un único proceso).
_ACTIVE_TABS = {}


def check_and_register(user_id, tab_id):
    """Registra `tab_id` como la pestaña activa de `user_id` si no hay
    otra viva (latido reciente) con un id distinto. Devuelve True si esta
    pestaña queda como la activa, False si hay otra y por tanto debe
    bloquearse."""
    now = time.monotonic()
    actual = _ACTIVE_TABS.get(user_id)
    if actual and actual['tab_id'] != tab_id and now - actual['last_seen'] < TAB_TTL_SECONDS:
        return False
    _ACTIVE_TABS[user_id] = {'tab_id': tab_id, 'last_seen': now}
    return True
