from .consumers import CONNECTED_NODES
from .models import GatewayNode


def gateway_status(request):
    node = GatewayNode.objects.filter(active=True).first()
    online = bool(node and node.slug in CONNECTED_NODES)
    return {
        'gateway_status': 'online' if online else 'offline',
        'gateway_node_name': node.name if node else None,
    }
