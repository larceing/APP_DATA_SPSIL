from .consumers import CONNECTED_NODES
from .models import GatewayNode
from .permissions import get_accessible_pages


def gateway_status(request):
    node = GatewayNode.objects.filter(active=True).first()
    online = bool(node and node.slug in CONNECTED_NODES)
    return {
        'gateway_status': 'online' if online else 'offline',
        'gateway_node_name': node.name if node else None,
    }


def accessible_pages(request):
    if not request.user.is_authenticated:
        return {'accessible_pages': [], 'accessible_page_slugs': set()}
    pages = get_accessible_pages(request.user)
    return {'accessible_pages': pages, 'accessible_page_slugs': {page.slug for page in pages}}
